import io
import json
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from PIL import Image

import api.main as api_main
from backend import billing, mb_requests, parking_service
from backend import mb_payments as mb
from backend.auth import AuthUser
from backend.db import init_db
from backend.mb_monitor import MBMonitor
from integrations.mb_bridge_client import MBConnectionError
from integrations.mb_readonly_worker import create_app

ADMIN = AuthUser(username="fixture-admin", role="admin")
OPERATOR = AuthUser(username="fixture-operator", role="operator")
VIEWER = AuthUser(username="fixture-viewer", role="viewer")
ACCOUNT = "000123456789"


@pytest.fixture
def context(tmp_path, monkeypatch):
    path = tmp_path / "mb.db"
    init_db(path)
    monkeypatch.setattr(billing, "DB_PATH", path)
    monkeypatch.setattr(parking_service, "DB_PATH", path)
    clock = [datetime(2026, 11, 1, 12, 0, 0, tzinfo=billing.LOCAL_TZ)]
    monkeypatch.setattr(billing, "now", lambda: clock[0])
    rows = []

    def worker(route, payload=None, **kwargs):
        if route == "/status":
            return {
                "ok": True,
                "state": "connected",
                "accounts": [{"account": ACCOUNT, "name": "BAI XE DEMO", "currency": "VND"}],
            }
        return {"ok": True, "transactions": list(rows)}

    monkeypatch.setattr(mb, "call_worker", worker)
    monkeypatch.setattr(api_main, "call_worker", worker)
    policy = next(p for p in billing.get_tariffs() if p["vehicle_type"] == "motorcycle")
    billing.set_tariff("motorcycle", {**policy, "enabled": True}, ADMIN)
    mb.save_settings(ACCOUNT, True, 1, ADMIN)
    return path, clock, rows, worker


def order(context, plate="59-B1 123.45"):
    path, clock, rows, worker = context
    tid = parking_service.vehicle_entry(plate, manual_override=True, actor=OPERATOR)["ticket_id"]
    with sqlite3.connect(path) as conn:
        conn.execute(
            "UPDATE parking_logs SET entry_time=?,exit_time=?,status='COMPLETED' WHERE ticket_id=?",
            ("2026-11-01T08:00:00+07:00", "2026-11-01T11:00:00+07:00", tid),
        )
    result = mb.create_order(tid, OPERATOR)
    return tid, result


def tx(request, **changes):
    return {
        "refNo": "MB-FIXTURE-001",
        "docId": "DUMMY",
        "accountNo": ACCOUNT,
        "creditAmount": str(request["amount"]),
        "debitAmount": "0",
        "currency": "VND",
        "description": "Thanh toan " + request["code"],
        "addDescription": "",
        "transactionDate": "01/11/2026 12:00:01",
        **changes,
    }


def test_monitor_uses_fast_pending_checks_and_backs_off_on_bank_errors(context):
    monitor = MBMonitor(worker=context[3])
    assert monitor.run_once()["state"] == "idle"
    assert monitor.status()["poll_interval_seconds"] == 15
    quick = mb_requests.create_request(5000, "fixture-fast-poll-request", OPERATOR, context[3])
    assert monitor.run_once()["checked"] == 1
    assert monitor.status()["poll_interval_seconds"] == 5

    def failed(*args):
        raise MBConnectionError("fixture unavailable")

    monitor.worker = failed
    for expected in (15, 30, 60, 60):
        assert monitor.run_once()["state"] == "unavailable"
        assert monitor.status()["poll_interval_seconds"] == expected
    assert mb_requests.get_request(quick["code"])["status"] == "pending"
    monitor.worker = context[3]
    assert monitor.run_once()["state"] == "ready"
    assert monitor.status()["poll_interval_seconds"] == 5
    assert monitor.status()["last_check_duration_ms"] >= 0


def test_fast_polls_do_not_alias_the_workers_ten_second_history_cache(context, monkeypatch):
    mb_requests.create_request(5000, "fixture-cache-cadence-request", OPERATOR, context[3])
    clock = [0.0]
    fresh = []
    cached_at = [None]
    passes = [0]
    monkeypatch.setattr("backend.mb_monitor.time", SimpleNamespace(monotonic=lambda: clock[0]))

    def worker(route, *args):
        if route == "/status":
            return context[3](route)
        if cached_at[0] is None or clock[0] - cached_at[0] >= 10:
            fresh.append(clock[0])
            clock[0] += 0.2
            cached_at[0] = clock[0]
        return {"ok": True, "transactions": []}

    monitor = MBMonitor(worker=worker)

    class Wake:
        def wait(self, delay):
            clock[0] += delay
            return False

    monitor.wake_event = Wake()
    original = monitor.run_once

    def run():
        original()
        passes[0] += 1
        if passes[0] == 4:
            monitor.stop_event.set()

    monkeypatch.setattr(monitor, "run_once", run)
    monitor._run_loop()
    assert len(fresh) == 2 and 10 <= fresh[1] - fresh[0] < 11


@pytest.mark.parametrize("state,minimum", [("idle", 5), ("unavailable", 15)])
def test_new_request_wakes_idle_monitor_without_bursts_or_skipping_backoff(
    monkeypatch, state, minimum
):
    clock = [0.0]
    starts = []
    wakes = [1, 2, 3]
    monitor = MBMonitor()
    monitor.info.update(state=state, poll_interval_seconds=15)
    monkeypatch.setattr("backend.mb_monitor.time", SimpleNamespace(monotonic=lambda: clock[0]))

    class Wake:
        def wait(self, delay):
            if wakes and wakes[0] <= clock[0] + delay:
                clock[0] = wakes.pop(0)
                return True
            clock[0] += delay
            return False

        def clear(self):
            pass

    monitor.wake_event = Wake()

    def run():
        starts.append(clock[0])
        if len(starts) == 2:
            monitor.stop_event.set()

    monkeypatch.setattr(monitor, "run_once", run)
    monitor._run_loop()
    assert starts == [0, minimum]


def test_pending_qr_status_reuses_png_but_different_requests_have_distinct_qrs(monkeypatch):
    original = mb.qrcode.make
    rendered = []

    def make(payload, **kwargs):
        rendered.append(payload)
        return original(payload, **kwargs)

    monkeypatch.setattr(mb.qrcode, "make", make)
    mb._qr_image.cache_clear()
    try:
        first = mb.transfer_qr(ACCOUNT, 5000, "PAY" + "A" * 16)
        assert mb.transfer_qr(ACCOUNT, 5000, "PAY" + "A" * 16) == first
        second = mb.transfer_qr(ACCOUNT, 5000, "PAY" + "B" * 16)
        assert second != first and len(rendered) == 2
    finally:
        mb._qr_image.cache_clear()


def test_qr_creation_wakes_after_commit_and_ticket_status_cannot_be_cached(context, monkeypatch):
    tid, invoice = order(context)
    wakes = []
    monkeypatch.setattr(mb_requests, "call_worker", context[3])

    def wake():
        with sqlite3.connect(context[0]) as conn:
            wakes.append(conn.execute("SELECT count(*) FROM mb_qr_requests").fetchone()[0])

    monkeypatch.setattr(api_main.mb_monitor.monitor, "wake", wake)
    client = TestClient(api_main.app)
    api_main.app.dependency_overrides[api_main.require_bearer_user] = lambda: OPERATOR
    try:
        response = client.post(
            "/payments/qr-requests",
            json={"amount": 5000, "idempotency_key": "fixture-wake-after-commit"},
        )
        assert response.status_code == 200 and wakes == [1]
        assert client.post(f"/tickets/{tid}/mb-order").status_code == 200 and wakes == [1, 1]
        response = client.get(f"/tickets/{tid}/mb-order")
        assert (
            response.status_code == 200 and response.headers["cache-control"] == "private, no-store"
        )
        assert wakes == [1, 1]
    finally:
        api_main.app.dependency_overrides.clear()


def test_create_reuses_pending_order_and_does_not_mark_paid(context):
    tid, request = order(context)
    assert mb.create_order(tid, OPERATOR)["code"] == request["code"]
    assert request["qr_image"].startswith("data:image/png;base64,")
    assert billing.get_finance(tid)["state"] == "unpaid"
    assert mb.get_order(tid)["status"] == "pending"


def test_server_monitor_settles_ticket_and_amount_qr_without_browser_actions(context):
    tid, invoice = order(context)
    quick = mb_requests.create_request(5000, "fixture-quick-request-0001", OPERATOR, context[3])
    context[2].extend([tx(invoice), tx(quick, refNo="MB-FIXTURE-QUICK")])
    monitor = MBMonitor(worker=context[3])
    result = monitor.run_once()
    assert result["matched"] == 2 and result["checked"] == 2
    assert billing.get_finance(tid)["receipt"]["paid_by"] == "mb-auto"
    receipt = mb_requests.get_request(quick["code"])
    assert receipt["status"] == "paid" and receipt["receipt"]["verification"] == "mb_verified"
    assert receipt["bank_reference"] == "MB-FIXTURE-QUICK"
    before = receipt["receipt_id"]
    assert MBMonitor(worker=context[3]).run_once()["checked"] == 0
    assert mb_requests.get_request(quick["code"])["receipt_id"] == before


@pytest.mark.parametrize(
    "remote",
    [
        {"state": "disconnected", "accounts": []},
        {"state": "error", "accounts": []},
        {"state": "connected", "accounts": []},
        {"state": "connected", "accounts": [{"account": "other", "currency": "VND"}]},
        {"state": "connected", "accounts": [{"account": ACCOUNT, "currency": "USD"}]},
    ],
)
def test_monitor_checks_connection_even_without_pending_requests(context, remote):
    calls = []

    def worker(route, *args):
        calls.append(route)
        return remote

    monitor = MBMonitor(worker=worker)
    assert monitor.run_once()["state"] == "unavailable"
    assert calls == ["/status"]
    assert monitor.status()["last_error"]


def test_monitor_recovers_and_only_reads_transactions_when_needed(context):
    remote = [{"state": "error", "accounts": []}]
    calls = []

    def worker(route, *args):
        calls.append(route)
        return remote[0]

    monitor = MBMonitor(worker=worker)
    assert monitor.status()["state"] == "starting"
    assert not monitor.status()["running"]
    assert monitor.run_once()["state"] == "unavailable"
    remote[0] = context[3]("/status")
    assert monitor.run_once()["state"] == "idle"
    assert not monitor.status()["last_error"]
    assert calls == ["/status", "/status"]


def test_disconnected_monitor_preserves_pending_requests_and_skips_transactions(context):
    quick = mb_requests.create_request(5000, "fixture-disconnected-0001", OPERATOR, context[3])
    calls = []

    def worker(route, *args):
        calls.append(route)
        return {"state": "disconnected", "accounts": []}

    assert MBMonitor(worker=worker).run_once()["state"] == "unavailable"
    assert calls == ["/status"]
    assert mb_requests.get_request(quick["code"])["status"] == "pending"


def test_quick_history_filters_before_paging_and_searches_literal_receipt_codes(context):
    with sqlite3.connect(context[0]) as conn:
        for i in range(56):
            conn.execute(
                """INSERT INTO mb_qr_requests(code,created_by,idempotency_key,amount,account_no,account_name,status,created_at,expires_at,receipt_id)
                VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (
                    f"PAY{i:016d}",
                    "fixture",
                    f"fixture-{i}",
                    5000,
                    ACCOUNT,
                    "DEMO",
                    "paid" if i % 2 else "pending",
                    context[1][0].isoformat(),
                    (context[1][0] + timedelta(minutes=15)).isoformat(),
                    f"R_{i}%" if i % 2 else None,
                ),
            )
    first = mb_requests.list_requests(status="paid")
    second = mb_requests.list_requests(offset=25, status="paid")
    assert first["total"] == second["total"] == 28
    assert len(first["items"]) == 25 and len(second["items"]) == 3
    assert not {r["code"] for r in first["items"]} & {r["code"] for r in second["items"]}
    assert mb_requests.list_requests(query="r_1%", status="paid")["total"] == 1
    assert mb_requests.list_requests(query="pay0000000000000001")["total"] == 1
    assert mb_requests.list_requests(query="' OR 1=1 --")["total"] == 0
    assert mb_requests.list_requests(query="%_")["total"] == 0
    assert all("account_no" not in item for item in first["items"])


def test_quick_history_api_bounds_filters_and_disallows_caching(context):
    client = TestClient(api_main.app)
    assert client.get("/payments/qr-requests").status_code == 401
    api_main.app.dependency_overrides[api_main.require_bearer_user] = lambda: VIEWER
    try:
        response = client.get("/payments/qr-requests?status=paid&q=missing")
        assert response.status_code == 200 and response.json()["total"] == 0
        assert response.headers["cache-control"] == "private, no-store"
        for params in ("limit=101", "offset=-1", "status=invalid", "q=" + "x" * 101):
            assert client.get("/payments/qr-requests?" + params).status_code == 422
    finally:
        api_main.app.dependency_overrides.clear()


def test_quick_creation_is_idempotent_and_bank_failure_keeps_pending(context):
    first = mb_requests.create_request(5000, "fixture-quick-request-0002", OPERATOR, context[3])
    assert (
        mb_requests.create_request(5000, "fixture-quick-request-0002", OPERATOR, context[3])["code"]
        == first["code"]
    )
    with pytest.raises(billing.BillingError):
        mb_requests.create_request(7000, "fixture-quick-request-0002", OPERATOR, context[3])

    def failure(*args):
        raise MBConnectionError("fixture unavailable")

    monitor = MBMonitor(worker=failure)
    assert monitor.run_once()["state"] == "unavailable"
    assert mb_requests.get_request(first["code"])["status"] == "pending"
    assert monitor.status()["last_error"]


def test_quick_receipt_is_atomic_across_concurrent_watchers(context):
    quick = mb_requests.create_request(4000, "fixture-quick-request-0003", OPERATOR, context[3])
    context[2].append(tx(quick))
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(
            pool.map(
                lambda _: mb_requests.reconcile_request(quick["code"], OPERATOR, context[3]),
                range(4),
            )
        )
    with sqlite3.connect(context[0]) as conn:
        assert conn.execute("SELECT count(*) FROM mb_matches").fetchone()[0] == 1
        assert (
            conn.execute(
                "SELECT count(*) FROM audit_logs WHERE action='payment.quick.received'"
            ).fetchone()[0]
            == 1
        )
    assert mb_requests.get_request(quick["code"])["status"] == "paid"


def test_same_bank_reference_cannot_pay_a_ticket_and_an_amount_request(context):
    tid, invoice = order(context)
    context[2].append(tx(invoice))
    assert mb.reconcile(tid, OPERATOR)["matched"]
    quick = mb_requests.create_request(4000, "fixture-quick-request-0004", OPERATOR, context[3])
    context[2][:] = [tx(quick)]
    assert not mb_requests.reconcile_request(quick["code"], OPERATOR, context[3])["matched"]
    assert mb_requests.get_request(quick["code"])["status"] == "pending"


def test_disabling_bank_cancels_pending_requests_and_monitor_does_not_read_bank(context):
    quick = mb_requests.create_request(5000, "fixture-quick-request-0005", OPERATOR, context[3])
    mb.save_settings(ACCOUNT, False, mb.settings()["revision"], ADMIN)

    def no_bank(*args):
        raise AssertionError("disabled integration must not read")

    assert MBMonitor(worker=no_bank).run_once()["state"] == "disabled"
    assert mb_requests.get_request(quick["code"])["status"] == "cancelled"


def test_saving_unchanged_receiver_does_not_cancel_active_requests(context):
    tid, invoice = order(context)
    quick = mb_requests.create_request(5000, "fixture-quick-request-0006", OPERATOR, context[3])
    mb.save_settings(ACCOUNT, True, mb.settings()["revision"], ADMIN)
    assert mb.get_order(tid)["status"] == "pending"
    assert mb_requests.get_request(quick["code"])["status"] == "pending"


def test_expired_older_ticket_order_can_be_reconciled_after_a_new_code_exists(context):
    tid, old = order(context)
    context[1][0] += timedelta(minutes=16)
    newer = mb.create_order(tid, OPERATOR)
    context[2].append(tx(old))
    assert mb.reconcile(tid, OPERATOR, context[3], order_code=old["code"])["matched"]
    assert mb.get_order(tid)["code"] == old["code"]
    assert mb.get_order(tid, order_code=newer["code"])["status"] == "cancelled"


def test_manual_qr_works_with_saved_receiver_while_auto_integration_is_off(context, monkeypatch):
    mb.save_settings(ACCOUNT, False, mb.settings()["revision"], ADMIN)

    def no_bank(*args, **kwargs):
        raise AssertionError("Manual QR must not contact the bank")

    monkeypatch.setattr(mb, "call_worker", no_bank)
    result = mb.manual_qr_preview(5000, OPERATOR)
    assert result["amount"] == 5000 and result["account_no"] == ACCOUNT
    assert result["reference"].startswith("QR") and result["automatic_reconciliation"] is False
    assert result["ticket_id"] is None and result["qr_image"].startswith("data:image/png;base64,")
    with sqlite3.connect(context[0]) as conn:
        assert conn.execute("SELECT count(*) FROM mb_orders").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM parking_payments").fetchone()[0] == 0
    assert not mb.settings()["enabled"]


def test_manual_qr_cannot_be_mistaken_for_a_ticket_order(context):
    tid, request = order(context)
    preview = mb.manual_qr_preview(request["amount"], OPERATOR)
    context[2].append(tx(request, description=preview["reference"]))
    assert not mb.reconcile(tid, OPERATOR)["matched"]


@pytest.mark.parametrize("amount", [0, -1, True, 1.5, 1000000001])
def test_manual_qr_rejects_invalid_money(context, amount):
    with pytest.raises(billing.BillingError):
        mb.manual_qr_preview(amount, OPERATOR)


def test_manual_qr_api_requires_writer_and_does_not_accept_another_receiver(context):
    client = TestClient(api_main.app)
    assert client.post("/payments/qr-preview", json={"amount": 5000}).status_code == 401
    api_main.app.dependency_overrides[api_main.require_bearer_user] = lambda: VIEWER
    try:
        assert client.post("/payments/qr-preview", json={"amount": 5000}).status_code == 403
        api_main.app.dependency_overrides[api_main.require_bearer_user] = lambda: OPERATOR
        result = client.post("/payments/qr-preview", json={"amount": 5000})
        assert result.status_code == 200 and not result.json()["qr"]["automatic_reconciliation"]
        assert (
            client.post(
                "/payments/qr-preview", json={"amount": 5000, "account_no": "999999999"}
            ).status_code
            == 422
        )
    finally:
        api_main.app.dependency_overrides.clear()


@pytest.mark.parametrize(
    "changes",
    [
        {"creditAmount": "3999"},
        {"creditAmount": "4001"},
        {"debitAmount": "1"},
        {"creditAmount": "-4000"},
        {"accountNo": "999999999"},
        {"currency": "USD"},
        {"currency": None},
        {"refNo": "", "docId": ""},
        {"transactionDate": "01/11/2026 11:59:59"},
        {"transactionDate": "01/11/2026 12:16:00"},
        {"transactionDate": "invalid"},
        {"creditAmount": "NaN"},
        {"creditAmount": "4000.5"},
    ],
)
def test_wrong_or_ambiguous_transaction_never_creates_receipt(context, changes):
    tid, request = order(context)
    context[2].append(tx(request, **changes))
    assert not mb.reconcile(tid, OPERATOR)["matched"]
    assert billing.get_finance(tid)["state"] == "unpaid"


def test_substring_and_multiple_order_codes_do_not_match(context):
    tid, request = order(context)
    for description in [
        "X" + request["code"],
        request["code"] + "Z",
        request["code"] + " ITS" + "A" * 16,
    ]:
        context[2][:] = [tx(request, description=description)]
        assert not mb.reconcile(tid, OPERATOR)["matched"]


def test_matching_transfer_is_atomic_verified_and_idempotent(context):
    tid, request = order(context)
    context[2].extend([tx(request), tx(request)])
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda _: mb.reconcile(tid, OPERATOR), range(4)))
    receipt = billing.get_finance(tid)["receipt"]
    assert receipt["verification"] == "mb_verified" and receipt["method"] == "mb_transfer"
    assert receipt["bank_reference"] == "MB-FIXTURE-001"
    with sqlite3.connect(context[0]) as conn:
        assert conn.execute("SELECT count(*) FROM parking_payments").fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM mb_matches").fetchone()[0] == 1
        assert (
            conn.execute(
                "SELECT count(*) FROM audit_logs WHERE action='payment.record'"
            ).fetchone()[0]
            == 1
        )


def test_bank_reference_cannot_be_reused_for_another_ticket(context):
    first, first_order = order(context)
    context[2][:] = [tx(first_order)]
    assert mb.reconcile(first, OPERATOR)["matched"]
    second, second_order = order(context, "59-C1 777.88")
    context[2][:] = [tx(second_order)]
    assert not mb.reconcile(second, OPERATOR)["matched"]
    assert billing.get_finance(second)["state"] == "unpaid"


def test_two_separate_matching_transfers_require_review(context):
    tid, request = order(context)
    context[2].extend([tx(request), tx(request, refNo="MB-FIXTURE-002")])
    assert not mb.reconcile(tid, OPERATOR)["matched"]


def test_manual_payment_wins_a_race_without_fake_mb_verification(context):
    tid, request = order(context)

    def worker(*args, **kwargs):
        quote = billing.get_finance(tid)
        billing.record_payment(tid, quote["amount"], quote["quote_id"], "cash", 5000, OPERATOR)
        return {"ok": True, "transactions": [tx(request)]}

    assert not mb.reconcile(tid, OPERATOR, worker)["matched"]
    assert billing.get_finance(tid)["receipt"]["verification"] == "manual"
    assert mb.get_order(tid)["status"] == "cancelled"


def test_expired_code_can_confirm_a_transfer_made_before_its_deadline(context):
    tid, request = order(context)
    context[2].append(tx(request))
    context[1][0] += timedelta(minutes=16)
    assert mb.get_order(tid)["status"] == "expired"
    assert mb.reconcile(tid, OPERATOR)["matched"]


def test_config_change_cancels_pending_codes_and_keeps_receipts(context):
    tid, request = order(context)
    mb.save_settings(ACCOUNT, False, mb.settings()["revision"], ADMIN)
    assert mb.get_order(tid)["status"] == "cancelled"
    with pytest.raises(billing.BillingError):
        mb.create_order(tid, OPERATOR)


@pytest.mark.parametrize("enabled", [True, False])
def test_unknown_receiver_or_non_admin_cannot_enable_bank(context, enabled):
    with pytest.raises(billing.BillingError):
        mb.save_settings("999999999", enabled, mb.settings()["revision"], ADMIN)
    with pytest.raises(billing.BillingError):
        mb.save_settings(ACCOUNT, True, mb.settings()["revision"], OPERATOR)
    tid, _ = order(context)
    with pytest.raises(billing.BillingError):
        mb.create_order(tid, VIEWER)


def test_verified_default_can_be_saved_without_enabling_payments(context):
    with sqlite3.connect(context[0]) as conn:
        conn.execute("UPDATE mb_settings SET account_no='',account_name='',enabled=0 WHERE id=1")
    prices = billing.get_tariffs()
    result = mb.save_settings(ACCOUNT, False, mb.settings()["revision"], ADMIN)
    assert result["account_no"] == ACCOUNT
    assert result["account_name"] == "BAI XE DEMO"
    assert result["enabled"] is False
    assert billing.get_tariffs() == prices
    with sqlite3.connect(context[0]) as conn:
        assert conn.execute("SELECT count(*) FROM parking_payments").fetchone()[0] == 0


def test_disconnected_worker_cannot_save_a_new_disabled_receiver(context):
    with sqlite3.connect(context[0]) as conn:
        conn.execute("UPDATE mb_settings SET account_no='',account_name='',enabled=0 WHERE id=1")

    def disconnected(*args, **kwargs):
        return {
            "state": "disconnected",
            "accounts": [{"account": ACCOUNT, "name": "DEMO", "currency": "VND"}],
        }

    with pytest.raises(billing.BillingError):
        mb.save_settings(ACCOUNT, False, mb.settings()["revision"], ADMIN, worker=disconnected)
    assert mb.settings()["account_no"] == ""


def test_worker_failure_does_not_mark_paid(context):
    tid, _ = order(context)

    def failing(*args):
        raise MBConnectionError("unavailable")

    with pytest.raises(MBConnectionError):
        mb.reconcile(tid, OPERATOR, failing)
    assert billing.get_finance(tid)["state"] == "unpaid"


def test_local_qr_has_mb_account_currency_amount_reference_and_valid_crc():
    payload, image = mb.transfer_qr(ACCOUNT, 4000, "ITS" + "A" * 16)

    def parse(text):
        result = {}
        position = 0
        while position < len(text):
            tag = text[position : position + 2]
            length = int(text[position + 2 : position + 4])
            result[tag] = text[position + 4 : position + 4 + length]
            position += 4 + length
        assert position == len(text)
        return result

    root = parse(payload)
    merchant = parse(root["38"])
    account = parse(merchant["01"])
    assert merchant["00"] == "A000000727" and merchant["02"] == "QRIBFTTA"
    assert account == {"00": "970422", "01": ACCOUNT}
    assert root["53"] == "704" and root["54"] == "4000" and root["58"] == "VN"
    assert parse(root["62"])["08"] == "ITS" + "A" * 16
    assert mb.crc16("123456789") == "29B1"
    assert payload[-4:] == mb.crc16(payload[:-4])
    assert image.startswith("data:image/png;base64,")


def test_api_admin_and_operator_boundaries(context):
    client = TestClient(api_main.app)
    assert client.get("/mb/status").status_code == 401
    api_main.app.dependency_overrides[api_main.require_bearer_user] = lambda: VIEWER
    try:
        assert client.get("/mb/status").status_code == 403
        assert client.post("/mb/connect").status_code == 403
        tid, _ = order(context)
        assert client.post(f"/tickets/{tid}/mb-order/check").status_code == 403
        api_main.app.dependency_overrides[api_main.require_bearer_user] = lambda: ADMIN
        response = client.get("/mb/status")
        assert response.status_code == 200 and "password" not in response.text.lower()
    finally:
        api_main.app.dependency_overrides.clear()


def test_worker_idle_start_and_authentication_do_not_login(tmp_path):
    calls = []
    app = create_app(tmp_path, "x" * 48, lambda captcha: calls.append(1))
    client = app.test_client()
    assert client.get("/status").status_code == 401
    assert client.get("/status", headers={"Authorization": "not-secret"}).status_code == 401
    result = client.get("/status", headers={"Authorization": "Bearer " + "x" * 48})
    assert result.json["state"] == "disconnected" and calls == []
    assert (
        client.post("/transfer", headers={"Authorization": "Bearer " + "x" * 48}).status_code == 404
    )


def test_worker_requires_manual_captcha_and_returns_only_owned_vnd_accounts(tmp_path):
    png = io.BytesIO()
    Image.new("RGB", (40, 20), "white").save(png, format="PNG")

    class FakeBank:
        def __init__(self, captcha):
            self.captcha = captcha

        def userinfo(self):
            assert self.captcha(png.getvalue()) == "TEST"

        def getBalance(self):
            return {
                "acct_list": [
                    {
                        "acctNo": ACCOUNT,
                        "acctNm": "DEMO",
                        "ccyCd": "VND",
                        "currentBalance": "do-not-expose",
                    }
                ]
            }

    app = create_app(tmp_path, "x" * 48, FakeBank)
    client = app.test_client()
    headers = {"Authorization": "Bearer " + "x" * 48}
    client.post("/connect", headers=headers)
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline and app.mb_state.state != "captcha_required":
        time.sleep(0.01)
    status = client.get("/status", headers=headers).json
    assert status["state"] == "captcha_required"
    assert (
        client.post("/captcha", headers=headers, json={"id": "wrong", "text": "TEST"}).status_code
        == 400
    )
    assert (
        client.post(
            "/captcha", headers=headers, json={"id": status["captcha"]["id"], "text": "TEST"}
        ).status_code
        == 200
    )
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline and app.mb_state.state != "connected":
        time.sleep(0.01)
    status = client.get("/status", headers=headers).json
    assert status["state"] == "connected" and status["captcha"] is None
    assert "currentBalance" not in json.dumps(status)
    assert (
        client.post("/transactions", headers=headers, json={"account": "999999999"}).status_code
        == 409
    )
