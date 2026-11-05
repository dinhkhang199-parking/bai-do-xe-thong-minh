"""Reconcile incoming MB transfers without sending or refunding funds."""

import base64
import io
import re
import secrets
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from functools import lru_cache

import qrcode

from backend import billing
from integrations.mb_bridge_client import MBConnectionError, call_worker

BIN_MB = "970422"


def init_schema(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS mb_settings (
        id INTEGER PRIMARY KEY CHECK(id=1), enabled INTEGER NOT NULL DEFAULT 0,
        account_no TEXT NOT NULL DEFAULT '', account_name TEXT NOT NULL DEFAULT '', revision INTEGER NOT NULL DEFAULT 1)""")
    conn.execute("INSERT OR IGNORE INTO mb_settings(id) VALUES(1)")
    conn.execute("""CREATE TABLE IF NOT EXISTS mb_orders (
        code TEXT PRIMARY KEY,ticket_id TEXT NOT NULL,amount INTEGER NOT NULL CHECK(amount>0),
        account_no TEXT NOT NULL,account_name TEXT NOT NULL,quote_id TEXT NOT NULL,
        status TEXT NOT NULL,created_at TEXT NOT NULL,expires_at TEXT NOT NULL,
        bank_reference TEXT,receipt_id TEXT)""")
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_mb_pending_ticket ON mb_orders(ticket_id) WHERE status='pending'"
    )
    if "last_checked_at" not in {row[1] for row in conn.execute("PRAGMA table_info(mb_orders)")}:
        conn.execute("ALTER TABLE mb_orders ADD COLUMN last_checked_at TEXT")
    conn.execute("""CREATE TABLE IF NOT EXISTS mb_qr_requests (
        code TEXT PRIMARY KEY,created_by TEXT NOT NULL,idempotency_key TEXT NOT NULL,
        amount INTEGER NOT NULL CHECK(amount>0),account_no TEXT NOT NULL,account_name TEXT NOT NULL,
        status TEXT NOT NULL,created_at TEXT NOT NULL,expires_at TEXT NOT NULL,
        bank_reference TEXT,receipt_id TEXT UNIQUE,paid_at TEXT,last_checked_at TEXT,
        UNIQUE(created_by,idempotency_key))""")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_mb_qr_pending ON mb_qr_requests(status,last_checked_at)"
    )
    conn.execute("""CREATE TABLE IF NOT EXISTS mb_matches (
        account_no TEXT NOT NULL,bank_reference TEXT NOT NULL,order_code TEXT NOT NULL UNIQUE,
        amount INTEGER NOT NULL,transaction_at TEXT NOT NULL,verified_at TEXT NOT NULL,
        PRIMARY KEY(account_no,bank_reference))""")
    columns = {r[1] for r in conn.execute("PRAGMA table_info(parking_payments)")}
    for name, sql_type in {
        "verification": "TEXT NOT NULL DEFAULT 'manual'",
        "bank_reference": "TEXT",
        "bank_order_code": "TEXT",
    }.items():
        if name not in columns:
            conn.execute(f"ALTER TABLE parking_payments ADD COLUMN {name} {sql_type}")


def settings():
    with billing.transaction() as conn:
        value = dict(conn.execute("SELECT * FROM mb_settings WHERE id=1").fetchone())
    value["enabled"] = bool(value["enabled"])
    value.pop("id", None)
    return value


def save_settings(account_no, enabled, revision, actor, worker=None):
    worker = worker or call_worker
    if actor.role != "admin":
        raise billing.BillingError("Chỉ quản trị viên được cấu hình MB.", 403)
    name = ""
    previous = settings()
    # A verified receiver can be saved before payments are enabled.
    if enabled or (account_no and account_no != previous["account_no"]):
        status = worker("/status")
        owned = [
            a
            for a in status.get("accounts", [])
            if a.get("account") == account_no and a.get("currency") == "VND"
        ]
        if status.get("state") != "connected" or len(owned) != 1:
            raise billing.BillingError(
                "Kết nối MB và chọn tài khoản VND thuộc phiên đăng nhập trước khi lưu tài khoản mới hoặc kích hoạt."
            )
        name = str(owned[0].get("name") or "")[:150]
    elif account_no:
        name = previous["account_name"]
    if account_no and not re.fullmatch(r"[0-9]{6,24}", account_no):
        raise billing.BillingError("Số tài khoản nhận không hợp lệ.", 400)
    with billing.transaction() as conn:
        current = conn.execute(
            "SELECT revision,enabled,account_no FROM mb_settings WHERE id=1"
        ).fetchone()
        if current[0] != revision:
            raise billing.BillingError("Cấu hình MB đã đổi. Tải lại trang trước khi lưu.")
        conn.execute(
            "UPDATE mb_settings SET enabled=?,account_no=?,account_name=?,revision=revision+1 WHERE id=1",
            (int(enabled), account_no, name),
        )
        # Receiver changes or disabling invalidate pending requests, never old receipts.
        if current[2] != account_no or (current[1] and not enabled):
            conn.execute("UPDATE mb_orders SET status='cancelled' WHERE status='pending'")
            conn.execute("UPDATE mb_qr_requests SET status='cancelled' WHERE status='pending'")
        billing._audit(
            conn,
            actor,
            "mb.configure",
            "MB",
            {"enabled": enabled, "account_last4": account_no[-4:]},
        )
    return settings()


def tlv(tag, value):
    value = str(value)
    if len(value.encode("utf-8")) > 99:
        raise ValueError("QR field too long")
    return tag + f"{len(value.encode('utf-8')):02}" + value


def crc16(text):
    crc = 0xFFFF
    for byte in text.encode("utf-8"):
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return f"{crc:04X}"


@lru_cache(maxsize=128)
def _qr_image(payload):
    stream = io.BytesIO()
    qrcode.make(payload, box_size=7, border=4).save(stream, format="PNG")
    return "data:image/png;base64," + base64.b64encode(stream.getvalue()).decode()


def transfer_qr(account, amount, reference):
    if (
        not re.fullmatch(r"[0-9]{6,24}", account)
        or type(amount) is not int
        or amount <= 0
        or not re.fullmatch(r"(?:ITS|QR|PAY)[A-F0-9]{16}", reference)
    ):
        raise ValueError("Invalid transfer QR values")
    beneficiary = tlv("00", BIN_MB) + tlv("01", account)
    merchant = tlv("00", "A000000727") + tlv("01", beneficiary) + tlv("02", "QRIBFTTA")
    payload = (
        tlv("00", "01")
        + tlv("01", "12")
        + tlv("38", merchant)
        + tlv("53", "704")
        + tlv("54", amount)
        + tlv("58", "VN")
        + tlv("62", tlv("08", reference))
        + "6304"
    )
    payload += crc16(payload)
    return payload, _qr_image(payload)


def manual_qr_preview(amount, actor):
    if actor.role not in {"admin", "operator"}:
        raise billing.BillingError("Không có quyền tạo QR thanh toán.", 403)
    if type(amount) is not int or not 1 <= amount <= 1000000000:
        raise billing.BillingError("Nhập số tiền nguyên từ 1 đến 1 tỷ đồng.", 400)
    config = settings()
    if not re.fullmatch(r"[0-9]{6,24}", config["account_no"]):
        raise billing.BillingError(
            "Chưa lưu tài khoản MB nhận mặc định. Mở Kết nối MB để chọn tài khoản."
        )
    reference = "QR" + secrets.token_hex(8).upper()
    payload, image = transfer_qr(config["account_no"], amount, reference)
    return {
        "amount": amount,
        "account_no": config["account_no"],
        "account_name": config["account_name"],
        "bank": "MB",
        "reference": reference,
        "qr_payload": payload,
        "qr_image": image,
        "automatic_reconciliation": False,
        "ticket_id": None,
        "message": "QR chuyển khoản thủ công, không tự xác nhận vé đã thanh toán.",
    }


def _expire(conn):
    conn.execute(
        "UPDATE mb_orders SET status='expired' WHERE status='pending' AND expires_at<?",
        (billing.now().isoformat(),),
    )


def _view(order):
    result = dict(order)
    if result["status"] == "pending":
        result["qr_payload"], result["qr_image"] = transfer_qr(
            result["account_no"], result["amount"], result["code"]
        )
    return result


def create_order(ticket_id, actor, worker=None):
    worker = worker or call_worker
    if actor.role not in {"admin", "operator"}:
        raise billing.BillingError("Không có quyền tạo mã chuyển khoản.", 403)
    config = settings()
    if not config["enabled"]:
        raise billing.BillingError(
            "MB chưa kích hoạt. Quản trị viên cần kết nối và chọn tài khoản nhận."
        )
    remote = worker("/status")
    if remote.get("state") != "connected" or not any(
        a.get("account") == config["account_no"] and a.get("currency") == "VND"
        for a in remote.get("accounts", [])
    ):
        raise billing.BillingError("Phiên MB chưa sẵn sàng. Nhờ quản trị viên kết nối lại.")
    with billing.transaction() as conn:
        _expire(conn)
        current = dict(conn.execute("SELECT * FROM mb_settings WHERE id=1").fetchone())
        if current["revision"] != config["revision"] or not current["enabled"]:
            raise billing.BillingError("Cấu hình MB vừa thay đổi. Hãy thử lại.")
        quote = billing._finance(conn, billing._ticket(conn, ticket_id))
        if not quote["payable"] or not quote.get("amount"):
            raise billing.BillingError(
                "Chỉ tạo mã chuyển khoản cho vé đã duyệt ra, chưa thu và có phí lớn hơn 0."
            )
        existing = conn.execute(
            "SELECT * FROM mb_orders WHERE ticket_id=? AND status='pending'", (ticket_id,)
        ).fetchone()
        if existing:
            return _view(existing)
        code = "ITS" + secrets.token_hex(8).upper()
        created = billing.now().replace(microsecond=0)
        conn.execute(
            "INSERT INTO mb_orders(code,ticket_id,amount,account_no,account_name,quote_id,status,created_at,expires_at) VALUES(?,?,?,?,?,?,'pending',?,?)",
            (
                code,
                ticket_id,
                quote["amount"],
                config["account_no"],
                config["account_name"],
                quote["quote_id"],
                created.isoformat(),
                (created + timedelta(minutes=15)).isoformat(),
            ),
        )
        billing._audit(
            conn, actor, "mb.order.create", ticket_id, {"code": code, "amount": quote["amount"]}
        )
        return _view(conn.execute("SELECT * FROM mb_orders WHERE code=?", (code,)).fetchone())


def get_order(ticket_id, order_code=None):
    with billing.transaction() as conn:
        _expire(conn)
        if order_code:
            row = conn.execute(
                "SELECT * FROM mb_orders WHERE ticket_id=? AND code=?", (ticket_id, order_code)
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM mb_orders WHERE ticket_id=? ORDER BY CASE WHEN status='paid' THEN 0 ELSE 1 END,created_at DESC,rowid DESC LIMIT 1",
                (ticket_id,),
            ).fetchone()
        return _view(row) if row else None


def cancel_order(ticket_id, actor):
    if actor.role not in {"admin", "operator"}:
        raise billing.BillingError("Không có quyền dừng mã chuyển khoản.", 403)
    with billing.transaction() as conn:
        conn.execute(
            "UPDATE mb_orders SET status='cancelled' WHERE ticket_id=? AND status='pending'",
            (ticket_id,),
        )
        billing._audit(conn, actor, "mb.order.cancel", ticket_id, {})
    return get_order(ticket_id)


def integer_amount(value):
    try:
        number = Decimal(str(value))
        if not number.is_finite() or number != number.to_integral_value():
            return None
        return int(number)
    except (InvalidOperation, ValueError, TypeError):
        return None


def transaction_time(value):
    try:
        return datetime.strptime(value, "%d/%m/%Y %H:%M:%S").replace(tzinfo=billing.LOCAL_TZ)
    except (TypeError, ValueError):
        try:
            return billing.timestamp(value)
        except billing.BillingError:
            return None


def matching_transaction(row, order, at):
    ref = str(row.get("refNo") or row.get("docId") or "").strip()
    date = transaction_time(row.get("transactionDate"))
    description = " ".join(str(row.get(k) or "") for k in ("description", "addDescription")).upper()
    codes = set(re.findall(r"(?<![A-Z0-9])(?:ITS|PAY)[A-F0-9]{16}(?![A-Z0-9])", description))
    if not ref or len(ref) > 120 or not date:
        return None
    if (
        str(row.get("accountNo") or "").strip() != order["account_no"]
        or row.get("currency") != "VND"
    ):
        return None
    if (
        integer_amount(row.get("creditAmount")) != order["amount"]
        or integer_amount(row.get("debitAmount")) != 0
    ):
        return None
    if codes != {order["code"]}:
        return None
    if not (
        billing.timestamp(order["created_at"]) <= date <= billing.timestamp(order["expires_at"])
    ) or date > at + timedelta(seconds=5):
        return None
    return ref, date.isoformat()


def reconcile(ticket_id, actor, worker=None, order_code=None):
    worker = worker or call_worker
    if actor.role not in {"admin", "operator"}:
        raise billing.BillingError("Không có quyền đối soát.", 403)
    order = get_order(ticket_id, order_code)
    if not order or order["status"] not in {"pending", "expired"}:
        return {"order": order, "matched": False}
    config = settings()
    if not config["enabled"] or config["account_no"] != order["account_no"]:
        raise billing.BillingError("Tài khoản nhận đã thay đổi. Cần kiểm tra lại mã chuyển khoản.")
    response = worker("/transactions", {"account": order["account_no"]})
    rows = response.get("transactions")
    if not isinstance(rows, list) or len(rows) > 2000:
        raise MBConnectionError("Dữ liệu giao dịch MB chưa hợp lệ.")
    at = billing.now()
    matches = [
        match
        for row in rows
        if isinstance(row, dict) and (match := matching_transaction(row, order, at))
    ]
    # A duplicated provider row is one transfer, not two.
    matches = list(dict.fromkeys(matches))
    if len(matches) != 1:
        return {
            "order": get_order(ticket_id),
            "matched": False,
            "message": "Chưa có một giao dịch duy nhất khớp tài khoản, số tiền, nội dung và thời hạn.",
        }
    ref, transaction_at = matches[0]
    with billing.transaction() as conn:
        _expire(conn)
        locked = conn.execute("SELECT * FROM mb_orders WHERE code=?", (order["code"],)).fetchone()
        settings_row = conn.execute(
            "SELECT enabled,account_no FROM mb_settings WHERE id=1"
        ).fetchone()
        if (
            not settings_row[0]
            or settings_row[1] != order["account_no"]
            or locked["status"] not in {"pending", "expired"}
        ):
            return {"order": _view(locked), "matched": locked["status"] == "paid"}
        quote = billing._finance(conn, billing._ticket(conn, ticket_id))
        if (
            not quote["payable"]
            or quote.get("quote_id") != order["quote_id"]
            or quote.get("amount") != order["amount"]
        ):
            conn.execute("UPDATE mb_orders SET status='cancelled' WHERE code=?", (order["code"],))
            return {
                "order": _view(
                    conn.execute(
                        "SELECT * FROM mb_orders WHERE code=?", (order["code"],)
                    ).fetchone()
                ),
                "matched": False,
            }
        if conn.execute(
            "SELECT 1 FROM mb_matches WHERE account_no=? AND bank_reference=?",
            (order["account_no"], ref),
        ).fetchone():
            return {
                "order": _view(locked),
                "matched": False,
                "message": "Giao dịch này đã được dùng cho một vé khác.",
            }
        receipt = billing._save_receipt(
            conn,
            ticket_id,
            quote,
            "mb_transfer",
            order["amount"],
            actor,
            verification="mb_verified",
            bank_reference=ref,
            bank_order_code=order["code"],
        )
        conn.execute(
            "INSERT INTO mb_matches VALUES(?,?,?,?,?,?)",
            (
                order["account_no"],
                ref,
                order["code"],
                order["amount"],
                transaction_at,
                at.isoformat(),
            ),
        )
        conn.execute(
            "UPDATE mb_orders SET status='paid',bank_reference=?,receipt_id=? WHERE code=?",
            (ref, receipt["receipt_id"], order["code"]),
        )
        conn.execute(
            "UPDATE mb_orders SET status='cancelled' WHERE ticket_id=? AND status='pending' AND code<>?",
            (ticket_id, order["code"]),
        )
        return {
            "order": _view(
                conn.execute("SELECT * FROM mb_orders WHERE code=?", (order["code"],)).fetchone()
            ),
            "matched": True,
            "receipt": receipt,
        }
