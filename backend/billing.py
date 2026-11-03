"""Ticket QR lookup, frozen tariffs and atomic records of manually received payments."""
from __future__ import annotations

import base64
from contextlib import contextmanager, closing
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
import math
import re
import secrets
import sqlite3
from uuid import uuid4

from backend.config import DB_PATH

LOCAL_TZ = timezone(timedelta(hours=7))
VEHICLE_TYPES = {"motorcycle": "Xe máy", "car": "Ô tô"}
SAMPLE_TARIFFS = {
    "motorcycle": {"mode":"hourly","flat_amount":5000,"first_minutes":120,"first_amount":3000,"next_minutes":60,"next_amount":1000,"daily_cap":20000,"grace_minutes":10},
    "car": {"mode":"hourly","flat_amount":30000,"first_minutes":60,"first_amount":10000,"next_minutes":60,"next_amount":5000,"daily_cap":100000,"grace_minutes":10},
}


class BillingError(ValueError):
    def __init__(self, message, status=409):
        super().__init__(message)
        self.status = status


def now():
    return datetime.now(LOCAL_TZ)


def init_billing_schema(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS parking_tariffs (
        vehicle_type TEXT PRIMARY KEY, enabled INTEGER NOT NULL DEFAULT 0,
        revision INTEGER NOT NULL, policy_json TEXT NOT NULL, updated_at TEXT, updated_by TEXT)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS ticket_billing (
        ticket_id TEXT PRIMARY KEY, qr_token TEXT NOT NULL UNIQUE, vehicle_type TEXT NOT NULL,
        policy_json TEXT, created_at TEXT NOT NULL)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS parking_payments (
        ticket_id TEXT PRIMARY KEY, receipt_id TEXT NOT NULL UNIQUE,
        amount INTEGER NOT NULL CHECK(amount >= 0), method TEXT NOT NULL,
        received_amount INTEGER NOT NULL, change_amount INTEGER NOT NULL,
        billed_until TEXT NOT NULL, policy_json TEXT NOT NULL,
        paid_at TEXT NOT NULL, paid_by TEXT NOT NULL)""")
    for vehicle_type, policy in SAMPLE_TARIFFS.items():
        conn.execute("INSERT OR IGNORE INTO parking_tariffs VALUES (?,0,1,?,?,NULL)",
                     (vehicle_type,json.dumps(policy),now().isoformat()))
    # Existing tickets get QR identifiers, but no retroactive or guessed charges.
    conn.execute("""INSERT OR IGNORE INTO ticket_billing
        SELECT ticket_id, lower(hex(randomblob(24))), 'unknown', NULL, ?
        FROM parking_logs""",(now().isoformat(),))
    from backend.mb_payments import init_schema
    init_schema(conn)


@contextmanager
def transaction(db_path=None):
    conn=sqlite3.connect(db_path or DB_PATH,timeout=15,isolation_level=None)
    conn.row_factory=sqlite3.Row
    try:
        conn.execute("BEGIN IMMEDIATE")
        yield conn
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


def register_ticket(conn, ticket_id, vehicle_type, created_at):
    if vehicle_type not in VEHICLE_TYPES:
        raise BillingError("Loại xe không hợp lệ.",400)
    row=conn.execute("SELECT enabled,revision,policy_json FROM parking_tariffs WHERE vehicle_type=?",(vehicle_type,)).fetchone()
    policy=None
    if row and row[0]:
        policy={**json.loads(row[2]),"revision":row[1],"vehicle_type":vehicle_type}
    conn.execute("INSERT INTO ticket_billing VALUES (?,?,?,?,?)",
        (ticket_id,secrets.token_hex(24),vehicle_type,json.dumps(policy) if policy else None,created_at))


def _audit(conn, actor, action, target, details):
    conn.execute("""INSERT INTO audit_logs(actor_username,actor_role,action,target_type,target_id,details_json)
        VALUES (?,?,?,?,?,?)""",(actor.username,actor.role,action,"billing",target,json.dumps(details,ensure_ascii=False)))


def get_tariffs(db_path=None):
    with transaction(db_path) as conn:
        return [{**json.loads(row["policy_json"]),"vehicle_type":row["vehicle_type"],
                 "enabled":bool(row["enabled"]),"revision":row["revision"],
                 "updated_at":row["updated_at"]} for row in conn.execute("SELECT * FROM parking_tariffs ORDER BY vehicle_type")]


def set_tariff(vehicle_type, payload, actor, db_path=None):
    if actor.role != "admin":
        raise BillingError("Chỉ quản trị viên được đổi biểu phí.",403)
    if vehicle_type not in VEHICLE_TYPES:
        raise BillingError("Loại xe không hợp lệ.",400)
    policy={key:payload[key] for key in SAMPLE_TARIFFS[vehicle_type]}
    validate_policy(policy)
    with transaction(db_path) as conn:
        row=conn.execute("SELECT revision FROM parking_tariffs WHERE vehicle_type=?",(vehicle_type,)).fetchone()
        if not row or row[0] != payload["revision"]:
            raise BillingError("Biểu phí đã thay đổi. Tải lại trang trước khi lưu.")
        revision=row[0]+1
        conn.execute("""UPDATE parking_tariffs SET enabled=?,revision=?,policy_json=?,updated_at=?,updated_by=?
            WHERE vehicle_type=?""",(int(payload["enabled"]),revision,json.dumps(policy),now().isoformat(),actor.username,vehicle_type))
        _audit(conn,actor,"tariff.update",vehicle_type,{"revision":revision,"enabled":payload["enabled"],"policy":policy})
    return {**policy,"vehicle_type":vehicle_type,"enabled":payload["enabled"],"revision":revision}


def validate_policy(policy):
    if policy.get("mode") not in {"hourly","flat"}:
        raise BillingError("Cách tính phí không hợp lệ.",400)
    for name in ("flat_amount","first_amount","next_amount","daily_cap"):
        if type(policy.get(name)) is not int or not 0 <= policy[name] <= 10000000:
            raise BillingError("Mức tiền phải là số nguyên từ 0 đến 10.000.000 đồng.",400)
    for name in ("first_minutes","next_minutes"):
        if type(policy.get(name)) is not int or not 1 <= policy[name] <= 1440:
            raise BillingError("Mỗi khoảng tính phí phải từ 1 đến 1.440 phút.",400)
    if type(policy.get("grace_minutes")) is not int or not 0 <= policy["grace_minutes"] <= 1440:
        raise BillingError("Thời gian miễn phí không hợp lệ.",400)


def timestamp(value):
    try:
        parsed=datetime.fromisoformat(str(value).replace("Z","+00:00"))
        return parsed.replace(tzinfo=LOCAL_TZ) if parsed.tzinfo is None else parsed.astimezone(LOCAL_TZ)
    except (TypeError,ValueError):
        raise BillingError("Thời gian của vé không hợp lệ; cần kiểm tra trước khi thu tiền.") from None


def calculate_fee(entry_time, end_time, policy):
    validate_policy(policy)
    seconds=(timestamp(end_time)-timestamp(entry_time)).total_seconds()
    if seconds < 0:
        raise BillingError("Giờ ra sớm hơn giờ vào; cần kiểm tra vé.")
    minutes=math.ceil(seconds/60)
    if minutes <= policy["grace_minutes"]:
        amount=0
    elif policy["mode"]=="flat":
        amount=policy["flat_amount"]
    else:
        def segment_amount(length):
            if length<=0:
                return 0
            value=policy["first_amount"]+max(0,math.ceil((length-policy["first_minutes"])/policy["next_minutes"]))*policy["next_amount"]
            return min(value,policy["daily_cap"]) if policy["daily_cap"] else value
        if policy["daily_cap"]:
            days,remainder=divmod(minutes,1440)
            amount=days*segment_amount(1440)+segment_amount(remainder)
        else:
            amount=segment_amount(minutes)
    return {"amount":int(amount),"duration_minutes":minutes,"billed_until":timestamp(end_time).isoformat()}


def _ticket(conn,ticket_id):
    row=conn.execute("""SELECT p.ticket_id,p.plate_entry,p.plate_exit,p.entry_time,p.exit_time,p.status,
        b.qr_token,b.vehicle_type,b.policy_json
        FROM parking_logs p LEFT JOIN ticket_billing b ON b.ticket_id=p.ticket_id WHERE p.ticket_id=?""",(ticket_id,)).fetchone()
    if not row:
        raise BillingError("Không tìm thấy vé.",404)
    result=dict(row)
    if not result["qr_token"]:
        token=secrets.token_hex(24)
        conn.execute("INSERT INTO ticket_billing VALUES (?,?,'unknown',NULL,?)",(ticket_id,token,now().isoformat()))
        result.update(qr_token=token,vehicle_type="unknown")
    return result


_PAYMENT_NOT_LOADED=object()


def _finance(conn,ticket,payment=_PAYMENT_NOT_LOADED):
    if payment is _PAYMENT_NOT_LOADED:
        payment=conn.execute("SELECT * FROM parking_payments WHERE ticket_id=?",(ticket["ticket_id"],)).fetchone()
    if payment:
        receipt=dict(payment); receipt.pop("policy_json",None)
        return {"state":"paid","payable":False,"amount":receipt["amount"],"receipt":receipt}
    if ticket["status"]=="CANCELLED":
        return {"state":"cancelled","payable":False,"amount":None,"message":"Vé đã hủy, không thu tiền."}
    if not ticket["policy_json"]:
        return {"state":"unconfigured","payable":False,"amount":None,
                "message":"Vé này không có biểu phí đã kích hoạt lúc xe vào; không tính phí tự động."}
    policy=json.loads(ticket["policy_json"])
    if ticket["status"]=="COMPLETED" and not ticket["exit_time"]:
        raise BillingError("Vé đã hoàn tất nhưng thiếu giờ ra; cần kiểm tra trước khi thu tiền.")
    end=ticket["exit_time"] or now().isoformat()
    result=calculate_fee(ticket["entry_time"],end,policy)
    payable=ticket["status"]=="COMPLETED"
    digest=hashlib.sha256(json.dumps({"ticket":ticket["ticket_id"],"policy":policy,**result},sort_keys=True).encode()).hexdigest()
    return {**result,"state":"unpaid" if payable else "estimate","payable":payable,
            "policy":policy,"quote_id":digest,
            "message":"Chờ đối chiếu và duyệt xe ra trước khi thu tiền." if not payable else "Chưa ghi nhận thu tiền."}


def get_finance(ticket_id,db_path=None):
    with transaction(db_path) as conn:
        return _finance(conn,_ticket(conn,ticket_id))


def payment_overview(query="",payment_state="",limit=50,offset=0,db_path=None):
    """Read-only payment list; configuration status never exposes bank account data."""
    if payment_state not in {"","paid","unpaid","unconfigured"} or not 1<=limit<=100 or offset<0:
        raise BillingError("Bộ lọc thanh toán không hợp lệ.",400)
    state_sql="CASE WHEN r.ticket_id IS NOT NULL THEN 'paid' WHEN b.policy_json IS NOT NULL THEN 'unpaid' ELSE 'unconfigured' END"
    join_sql="FROM parking_logs p LEFT JOIN ticket_billing b ON p.ticket_id=b.ticket_id LEFT JOIN parking_payments r ON p.ticket_id=r.ticket_id"
    where=["p.status='COMPLETED'"]; params=[]
    if query.strip():
        where.append("instr(upper(coalesce(p.ticket_id,'') || ' ' || coalesce(p.plate_entry,'') || ' ' || coalesce(p.plate_exit,'')),upper(?))>0")
        params.append(query.strip())
    if payment_state:
        where.append("("+state_sql+")=?");params.append(payment_state)
    condition=" WHERE "+" AND ".join(where)
    with closing(sqlite3.connect(db_path or DB_PATH,timeout=10)) as conn:
        conn.row_factory=sqlite3.Row
        conn.execute("BEGIN")
        total=conn.execute("SELECT count(*) "+join_sql+condition,params).fetchone()[0]
        rows=conn.execute("""SELECT p.ticket_id,p.plate_entry,p.entry_time,p.exit_time,p.status,
            b.vehicle_type,b.policy_json,r.receipt_id,r.method,r.paid_at,r.amount AS paid_amount,"""+state_sql+" AS payment_state "+
            join_sql+condition+" ORDER BY coalesce(p.exit_time,p.entry_time) DESC,p.ticket_id DESC LIMIT ? OFFSET ?",(*params,limit,offset)).fetchall()
        items=[]
        for row in rows:
            ticket=dict(row)
            try:
                finance=({'state':'paid','amount':ticket['paid_amount']} if ticket['payment_state']=='paid' else _finance(conn,ticket,None))
                state=finance["state"];amount=finance["amount"];message=finance.get("message","")
            except (BillingError,ValueError,TypeError,KeyError):
                state="needs_review";amount=None;message="Thông tin tính phí cần kiểm tra trước khi thu."
            items.append({key:ticket[key] for key in ("ticket_id","plate_entry","exit_time","vehicle_type","receipt_id","method","paid_at")} |
                         {"payment_state":state,"amount":amount,"message":message})
        tariffs=[{"vehicle_type":row[0],"enabled":bool(row[1])} for row in conn.execute("SELECT vehicle_type,enabled FROM parking_tariffs ORDER BY vehicle_type")]
        bank=conn.execute("SELECT enabled,account_no FROM mb_settings WHERE id=1").fetchone()
        configuration={"tariffs":tariffs,"mb_enabled":bool(bank and bank[0]),"receiver_saved":bool(bank and bank[1])}
    return {"items":items,"count":len(items),"total":total,"limit":limit,"offset":offset,"configuration":configuration}


def ticket_pass(ticket_id,db_path=None):
    import qrcode
    with transaction(db_path) as conn:
        ticket=_ticket(conn,ticket_id)
        finance=_finance(conn,ticket)
        automatic_mb=bool(conn.execute("SELECT enabled FROM mb_settings WHERE id=1").fetchone()[0])
    payload="ITS1:"+ticket.pop("qr_token")
    ticket.pop("policy_json",None)
    image=qrcode.make(payload,box_size=8,border=4)
    stream=io.BytesIO(); image.save(stream,format="PNG")
    return {"ticket":ticket,"finance":finance,"qr_payload":payload,"mb_auto_enabled":automatic_mb,
            "qr_image":"data:image/png;base64,"+base64.b64encode(stream.getvalue()).decode()}


def lookup_qr(payload,db_path=None):
    match=re.fullmatch(r"ITS1:([0-9a-f]{48})",payload.strip())
    if not match:
        raise BillingError("Mã QR không phải vé ITS Parking hợp lệ.",400)
    with transaction(db_path) as conn:
        row=conn.execute("""SELECT p.ticket_id,p.plate_entry,p.status FROM ticket_billing b
            JOIN parking_logs p ON p.ticket_id=b.ticket_id WHERE b.qr_token=?""",(match[1],)).fetchone()
        if not row:
            raise BillingError("Không tìm thấy vé tương ứng mã QR.",404)
        return dict(row)


def _save_receipt(conn,ticket_id,quote,method,received,actor,verification="manual",bank_reference=None,bank_order_code=None):
    amount=quote["amount"]
    receipt={"ticket_id":ticket_id,"receipt_id":"R"+uuid4().hex[:16].upper(),
        "amount":amount,"method":method,"received_amount":received,"change_amount":received-amount,
        "billed_until":quote["billed_until"],"paid_at":now().isoformat(),"paid_by":actor.username,
        "verification":verification,"bank_reference":bank_reference,"bank_order_code":bank_order_code}
    conn.execute("""INSERT INTO parking_payments
        (ticket_id,receipt_id,amount,method,received_amount,change_amount,billed_until,policy_json,paid_at,paid_by,verification,bank_reference,bank_order_code)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (ticket_id,receipt["receipt_id"],amount,method,received,received-amount,quote["billed_until"],
         json.dumps(quote["policy"]),receipt["paid_at"],actor.username,verification,bank_reference,bank_order_code))
    _audit(conn,actor,"payment.record",ticket_id,receipt)
    conn.execute("""INSERT INTO parking_events(ticket_id,event_type,actor_username,actor_role,details_json)
        VALUES (?,'PAYMENT_RECORDED',?,?,?)""",(ticket_id,actor.username,actor.role,json.dumps(receipt)))
    return receipt


def record_payment(ticket_id,amount,quote_id,method,received_amount,actor,db_path=None):
    if actor.role not in {"admin","operator"}:
        raise BillingError("Tài khoản không có quyền ghi nhận thu tiền.",403)
    if method not in {"cash","transfer"} or type(amount) is not int or type(received_amount) is not int or amount<0:
        raise BillingError("Thông tin thu tiền không hợp lệ.",400)
    with transaction(db_path) as conn:
        ticket=_ticket(conn,ticket_id); quote=_finance(conn,ticket)
        if quote["state"]=="paid":
            return {"receipt":quote["receipt"],"already_paid":True}
        if not quote["payable"]:
            raise BillingError("Vé chưa đủ điều kiện thu tiền. Đối chiếu xe ra và kiểm tra biểu phí trước.")
        if quote_id!=quote["quote_id"] or amount!=quote["amount"]:
            raise BillingError("Số tiền hoặc thông tin vé đã thay đổi. Mở lại vé để kiểm tra.")
        received=amount if method=="transfer" else received_amount
        if received<amount or received>1000000000:
            raise BillingError("Tiền khách đưa phải đủ số tiền cần thu và không vượt 1 tỷ đồng.",400)
        receipt=_save_receipt(conn,ticket_id,quote,method,received,actor)
        conn.execute("UPDATE mb_orders SET status='cancelled' WHERE ticket_id=? AND status='pending'",(ticket_id,))
        return {"receipt":receipt,"already_paid":False}
