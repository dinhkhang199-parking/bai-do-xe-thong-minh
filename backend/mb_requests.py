"""Durable amount-entered QR requests, automatically settled from verified MB credits."""
from datetime import timedelta
import re
import secrets
from uuid import uuid4

from backend import billing,mb_payments as mb
from integrations.mb_bridge_client import call_worker,MBConnectionError


def expire(conn):
    conn.execute("UPDATE mb_qr_requests SET status='expired' WHERE status='pending' AND expires_at<?",(billing.now().isoformat(),))


def view(row):
    result=dict(row)
    result.pop("idempotency_key",None)
    result["automatic_reconciliation"]=True
    result["reference"]=result["code"]
    result["ticket_id"]=None
    if result["status"]=="pending":
        result["qr_payload"],result["qr_image"]=mb.transfer_qr(result["account_no"],result["amount"],result["code"])
    if result["status"]=="paid":
        result["receipt"]={"receipt_id":result["receipt_id"],"amount":result["amount"],
            "paid_at":result["paid_at"],"bank_reference":result["bank_reference"],
            "method":"mb_transfer","verification":"mb_verified"}
    return result


def create_request(amount,idempotency_key,actor,worker=None):
    worker=worker or call_worker
    if actor.role not in {"admin","operator"}:
        raise billing.BillingError("Không có quyền tạo QR thanh toán.",403)
    if type(amount) is not int or not 1<=amount<=1000000000 or not re.fullmatch(r"[A-Za-z0-9_-]{16,80}",idempotency_key):
        raise billing.BillingError("Số tiền hoặc mã yêu cầu không hợp lệ.",400)
    config=mb.settings()
    if not config["enabled"]:
        raise billing.BillingError("MB tự động chưa bật. Quản trị viên cần kích hoạt tài khoản MB mặc định.")
    remote=worker("/status")
    if remote.get("state")!="connected" or not any(a.get("account")==config["account_no"] and a.get("currency")=="VND" for a in remote.get("accounts",[])):
        raise billing.BillingError("Phiên MB chưa sẵn sàng. Kết nối lại MB trước khi tạo mã.")
    with billing.transaction() as conn:
        expire(conn)
        current=conn.execute("SELECT enabled,revision FROM mb_settings WHERE id=1").fetchone()
        if not current[0] or current[1]!=config["revision"]:
            raise billing.BillingError("Cấu hình MB vừa thay đổi. Hãy thử lại.")
        existing=conn.execute("SELECT * FROM mb_qr_requests WHERE created_by=? AND idempotency_key=?",(actor.username,idempotency_key)).fetchone()
        if existing:
            if existing["amount"]!=amount:
                raise billing.BillingError("Mã yêu cầu đã được dùng cho số tiền khác.")
            return view(existing)
        created=billing.now().replace(microsecond=0)
        code="PAY"+secrets.token_hex(8).upper()
        conn.execute("""INSERT INTO mb_qr_requests
            (code,created_by,idempotency_key,amount,account_no,account_name,status,created_at,expires_at)
            VALUES (?,?,?,?,?,?,'pending',?,?)""",
            (code,actor.username,idempotency_key,amount,config["account_no"],config["account_name"],
             created.isoformat(),(created+timedelta(minutes=15)).isoformat()))
        billing._audit(conn,actor,"mb.quick.create",code,{"amount":amount})
        return view(conn.execute("SELECT * FROM mb_qr_requests WHERE code=?",(code,)).fetchone())


def get_request(code):
    with billing.transaction() as conn:
        expire(conn)
        row=conn.execute("SELECT * FROM mb_qr_requests WHERE code=?",(code,)).fetchone()
        if not row:raise billing.BillingError("Không tìm thấy yêu cầu QR.",404)
        return view(row)


def list_requests(limit=25,offset=0,query="",status=""):
    clauses=[];params=[]
    if status:
        clauses.append("status=?");params.append(status)
    if query.strip():
        # instr treats %, _ and SQL syntax as literal text.
        clauses.append("(instr(lower(code),lower(?))>0 OR instr(lower(coalesce(receipt_id,'')),lower(?))>0)")
        params.extend([query.strip()]*2)
    where=" WHERE "+" AND ".join(clauses) if clauses else ""
    with billing.transaction() as conn:
        expire(conn)
        total=conn.execute("SELECT count(*) FROM mb_qr_requests"+where,params).fetchone()[0]
        rows=conn.execute("SELECT * FROM mb_qr_requests"+where+" ORDER BY created_at DESC,rowid DESC LIMIT ? OFFSET ?",[*params,limit,offset]).fetchall()
        # The list needs status, not repeated PNG generation or receiver details.
        return {"items":[{key:row[key] for key in ("code","amount","status","created_at","paid_at","receipt_id")} for row in rows],
                "total":total,"limit":limit,"offset":offset}


def cancel_request(code,actor):
    if actor.role not in {"admin","operator"}:raise billing.BillingError("Không có quyền dừng mã.",403)
    with billing.transaction() as conn:
        if not conn.execute("SELECT 1 FROM mb_qr_requests WHERE code=?",(code,)).fetchone():
            raise billing.BillingError("Không tìm thấy yêu cầu QR.",404)
        conn.execute("UPDATE mb_qr_requests SET status='cancelled' WHERE code=? AND status='pending'",(code,))
        billing._audit(conn,actor,"mb.quick.cancel",code,{})
    return get_request(code)


def reconcile_request(code,actor,worker=None):
    worker=worker or call_worker
    if actor.role not in {"admin","operator"}:raise billing.BillingError("Không có quyền đối soát.",403)
    request=get_request(code)
    if request["status"] not in {"pending","expired"}:
        return {"request":request,"matched":request["status"]=="paid"}
    config=mb.settings()
    if not config["enabled"] or config["account_no"]!=request["account_no"]:
        return {"request":request,"matched":False}
    response=worker("/transactions",{"account":request["account_no"]})
    rows=response.get("transactions")
    if not isinstance(rows,list) or len(rows)>2000:raise MBConnectionError("Dữ liệu giao dịch MB chưa hợp lệ.")
    matches=list(dict.fromkeys(match for row in rows if isinstance(row,dict) and
                              (match:=mb.matching_transaction(row,request,billing.now()))))
    if len(matches)!=1:return {"request":get_request(code),"matched":False}
    ref,transaction_at=matches[0]
    with billing.transaction() as conn:
        expire(conn)
        locked=conn.execute("SELECT * FROM mb_qr_requests WHERE code=?",(code,)).fetchone()
        current=conn.execute("SELECT enabled,account_no FROM mb_settings WHERE id=1").fetchone()
        if locked["status"]=="paid":return {"request":view(locked),"matched":True}
        if locked["status"] not in {"pending","expired"} or not current[0] or current[1]!=request["account_no"]:
            return {"request":view(locked),"matched":False}
        if conn.execute("SELECT 1 FROM mb_matches WHERE account_no=? AND bank_reference=?",(request["account_no"],ref)).fetchone():
            return {"request":view(locked),"matched":False}
        paid_at=billing.now().isoformat();receipt_id="R"+uuid4().hex[:16].upper()
        conn.execute("INSERT INTO mb_matches VALUES(?,?,?,?,?,?)",(request["account_no"],ref,code,request["amount"],transaction_at,paid_at))
        conn.execute("UPDATE mb_qr_requests SET status='paid',bank_reference=?,receipt_id=?,paid_at=? WHERE code=?",(ref,receipt_id,paid_at,code))
        billing._audit(conn,actor,"payment.quick.received",code,{"receipt_id":receipt_id,"amount":request["amount"],"bank_reference":ref})
        conn.execute("""INSERT INTO parking_events(ticket_id,event_type,actor_username,actor_role,source,details_json)
            VALUES (NULL,'QUICK_PAYMENT_RECEIVED',?,?,'MB',?)""",
            (actor.username,actor.role,__import__("json").dumps({"code":code,"amount":request["amount"],"receipt_id":receipt_id})))
        return {"request":view(conn.execute("SELECT * FROM mb_qr_requests WHERE code=?",(code,)).fetchone()),"matched":True}
