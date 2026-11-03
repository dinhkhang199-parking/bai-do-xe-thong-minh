"""Server-side polling survives closed QR dialogs; all settlement still uses bank evidence."""
from datetime import timedelta
import os
import threading
import time

from backend import billing,mb_payments as mb,mb_requests
from backend.auth import AuthUser
from integrations.mb_bridge_client import call_worker,MBConnectionError


class MBMonitor:
    def __init__(self,worker=None,interval=5,allow_in_test=False):
        self.worker=worker or call_worker;self.interval=interval;self.allow_in_test=allow_in_test
        self.stop_event=threading.Event();self.thread=None;self.lock=threading.Lock()
        self.wake_event=threading.Event();self.failures=0
        self.info={"state":"starting","last_checked_at":None,"last_error":"",
                   "poll_interval_seconds":interval,"last_check_duration_ms":None}

    def status(self):
        with self.lock:return {**self.info,"running":bool(self.thread and self.thread.is_alive())}

    def wake(self):
        """New durable requests interrupt idle waits; the loop still limits read frequency."""
        self.wake_event.set()

    def run_once(self):
        started=time.monotonic()
        state="disabled";error="";checked=0;matched=0;pending=0
        try:
            config=mb.settings()
            if config["enabled"]:
                at=billing.now();cutoff=(at-timedelta(days=1)).isoformat()
                recheck=(at-timedelta(seconds=60)).isoformat()
                with billing.transaction() as conn:
                    mb._expire(conn);mb_requests.expire(conn)
                    candidates=[]
                    for table,kind in [("mb_orders","ticket"),("mb_qr_requests","quick")]:
                        rows=conn.execute(f"""SELECT * FROM {table} WHERE account_no=? AND
                            (status='pending' OR (status='expired' AND expires_at>=? AND
                            (last_checked_at IS NULL OR last_checked_at<=?)))
                            ORDER BY coalesce(last_checked_at,''),created_at LIMIT 50""",
                            (config["account_no"],cutoff,recheck)).fetchall()
                        candidates.extend((kind,dict(row)) for row in rows)
                    pending=sum(item["status"]=="pending" for _,item in candidates)
                remote=self.worker("/status")
                if remote.get("state")!="connected" or not any(
                    a.get("account")==config["account_no"] and a.get("currency")=="VND"
                    for a in remote.get("accounts",[])):
                    raise MBConnectionError("Phiên MB chưa sẵn sàng.")
                if not candidates:state="idle"
                else:
                    state="checking"
                    response=self.worker("/transactions",{"account":config["account_no"]})
                    if not isinstance(response.get("transactions"),list) or len(response["transactions"])>2000:
                        raise MBConnectionError("Dữ liệu giao dịch chưa hợp lệ.")
                    def cached(*args,**kwargs):return response
                    actor=AuthUser(username="mb-auto",role="operator")
                    for kind,item in candidates:
                        try:
                            result=(mb.reconcile(item["ticket_id"],actor,cached,order_code=item["code"]) if kind=="ticket"
                                    else mb_requests.reconcile_request(item["code"],actor,cached))
                            matched+=int(bool(result.get("matched")));checked+=1
                        except billing.BillingError:
                            error="Có yêu cầu cần kiểm tra thông tin trước khi ghi nhận."
                        finally:
                            table="mb_orders" if kind=="ticket" else "mb_qr_requests"
                            with billing.transaction() as conn:
                                conn.execute(f"UPDATE {table} SET last_checked_at=? WHERE code=?",(at.isoformat(),item["code"]))
                    state="ready"
        except Exception:
            # No provider payload, balances or credential values are exposed.
            state="unavailable";error="Chưa đọc được tiền vào MB. Kiểm tra kết nối MB; các mã đang chờ được giữ lại."
        with self.lock:
            self.failures=self.failures+1 if state=="unavailable" else 0
            delay=(min(60,max(15,self.interval)*2**min(self.failures-1,2)) if self.failures
                   else self.interval if pending else max(15,self.interval))
            self.info={"state":state,"last_checked_at":billing.now().isoformat(),"last_error":error,
                       "poll_interval_seconds":delay,
                       "last_check_duration_ms":round((time.monotonic()-started)*1000,2)}
        return {"state":state,"checked":checked,"matched":matched}

    def _run_loop(self):
        delay=0;last_started=None
        while not self.stop_event.is_set():
            if self.wake_event.wait(delay):
                self.wake_event.clear()
                if self.stop_event.is_set():break
                # Repeated create clicks cannot produce a burst of bank reads.
                if last_started is not None:
                    status=self.status()
                    minimum=status["poll_interval_seconds"] if status["state"]=="unavailable" else self.interval
                    remaining=minimum-(time.monotonic()-last_started)
                    if remaining>0:
                        delay=remaining;continue
            if self.stop_event.is_set():break
            started=time.monotonic()
            self.run_once()
            last_started=started
            # The worker's 10-second cache starts when a bank read finishes.
            # Wait after completion so polls at 5/10s do not repeatedly land
            # just before cache expiry and defer fresh data until the 15s poll.
            delay=self.status()["poll_interval_seconds"]

    def start(self):
        if os.getenv("ITS_MB_TEST_MODE")=="true" and not self.allow_in_test:return
        if self.thread and self.thread.is_alive():return
        self.stop_event.clear()
        self.thread=threading.Thread(target=self._run_loop,daemon=True,name="mb-auto-reconcile");self.thread.start()

    def stop(self):
        self.stop_event.set();self.wake_event.set()
        if self.thread:self.thread.join(timeout=2)


monitor=MBMonitor()
