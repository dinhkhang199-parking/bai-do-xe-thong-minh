import base64
import io
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from PIL import Image

import api.main as api_main
from backend import billing, parking_service
from backend.auth import AuthUser
from backend.db import init_db

ADMIN = AuthUser(username="fixture-admin", role="admin")
OPERATOR = AuthUser(username="fixture-operator", role="operator")
VIEWER = AuthUser(username="fixture-viewer", role="viewer")
BASE = "2026-11-01T08:00:00+07:00"


@pytest.fixture
def store(tmp_path, monkeypatch):
    path = tmp_path / "parking.db"
    init_db(path)
    monkeypatch.setattr(billing, "DB_PATH", path)
    monkeypatch.setattr(parking_service, "DB_PATH", path)
    return path


def enable(vehicle="motorcycle", **changes):
    current = next(item for item in billing.get_tariffs() if item["vehicle_type"] == vehicle)
    values = {key: current[key] for key in billing.SAMPLE_TARIFFS[vehicle]}
    return billing.set_tariff(
        vehicle, {**values, "revision": current["revision"], "enabled": True, **changes}, ADMIN
    )


def ticket(store, plate="59-B1 123.45", complete=True):
    result = parking_service.vehicle_entry(plate, manual_override=True, actor=OPERATOR)
    with sqlite3.connect(store) as conn:
        conn.execute(
            "UPDATE parking_logs SET entry_time=?,exit_time=?,status=? WHERE ticket_id=?",
            (
                BASE,
                "2026-11-01T11:00:00+07:00" if complete else None,
                "COMPLETED" if complete else "IN_PARKING",
                result["ticket_id"],
            ),
        )
    return result["ticket_id"]


def test_default_prices_are_samples_and_not_chargeable(store):
    assert all(not policy["enabled"] for policy in billing.get_tariffs())
    tid = ticket(store)
    assert billing.get_finance(tid)["amount"] is None
    enable()
    assert billing.get_finance(tid)["state"] == "unconfigured"


@pytest.mark.parametrize(
    "minutes,amount",
    [
        (0, 0),
        (10, 0),
        (11, 3000),
        (120, 3000),
        (121, 4000),
        (180, 4000),
        (1440, 20000),
        (1441, 23000),
        (2880, 40000),
    ],
)
def test_hourly_rounding_grace_and_rolling_daily_cap(minutes, amount):
    end = datetime.fromisoformat(BASE) + timedelta(minutes=minutes)
    assert (
        billing.calculate_fee(BASE, end.isoformat(), billing.SAMPLE_TARIFFS["motorcycle"])["amount"]
        == amount
    )


def test_seconds_and_timezones_are_normalized():
    policy = billing.SAMPLE_TARIFFS["motorcycle"]
    assert billing.calculate_fee(BASE, "2026-11-01T03:00:01Z", policy)["amount"] == 4000
    assert (
        billing.calculate_fee("2026-11-01 08:00:00", "2026-11-01T01:10:00Z", policy)["amount"] == 0
    )
    with pytest.raises(billing.BillingError):
        billing.calculate_fee(BASE, "2026-10-31T08:00:00+07:00", policy)


def test_flat_rate_is_per_visit_and_zero_cap_means_uncapped():
    flat = {**billing.SAMPLE_TARIFFS["motorcycle"], "mode": "flat"}
    assert billing.calculate_fee(BASE, "2026-11-05T08:00:00+07:00", flat)["amount"] == 5000
    uncapped = {**flat, "mode": "hourly", "daily_cap": 0}
    assert billing.calculate_fee(BASE, "2026-11-02T08:00:00+07:00", uncapped)["amount"] == 25000


def test_price_snapshot_and_revision_conflict(store):
    policy = enable()
    tid = ticket(store)
    enable(first_amount=9999)
    assert billing.get_finance(tid)["amount"] == 4000
    with pytest.raises(billing.BillingError, match="thay đổi"):
        billing.set_tariff("motorcycle", policy, ADMIN)
    with pytest.raises(billing.BillingError):
        billing.set_tariff("motorcycle", policy, OPERATOR)


def test_qr_roundtrip_stable_and_not_a_ticket_authorization(store):
    tid = ticket(store, complete=False)
    first = billing.ticket_pass(tid)
    second = billing.ticket_pass(tid)
    assert first["qr_payload"] == second["qr_payload"]
    assert tid not in first["qr_payload"] and "59-B1" not in first["qr_payload"]
    assert billing.lookup_qr(first["qr_payload"])["ticket_id"] == tid
    with Image.open(io.BytesIO(base64.b64decode(first["qr_image"].split(",")[1]))) as image:
        assert image.format == "PNG" and image.width > 200
    with pytest.raises(billing.BillingError):
        billing.lookup_qr("https://example.com/" + tid)
    assert billing.lookup_qr(first["qr_payload"])["status"] == "IN_PARKING"


@pytest.mark.parametrize("status", ["IN_PARKING", "NEEDS_REVIEW", "CANCELLED"])
def test_payments_require_completed_tickets(store, status):
    enable()
    tid = ticket(store)
    with sqlite3.connect(store) as conn:
        conn.execute("UPDATE parking_logs SET status=? WHERE ticket_id=?", (status, tid))
    with pytest.raises(billing.BillingError):
        billing.record_payment(tid, 4000, "0" * 64, "cash", 5000, OPERATOR)


def test_atomic_idempotent_payment_and_audit(store):
    enable()
    tid = ticket(store)
    quote = billing.get_finance(tid)

    def pay():
        return billing.record_payment(
            tid, quote["amount"], quote["quote_id"], "cash", 5000, OPERATOR
        )

    with ThreadPoolExecutor(max_workers=4) as pool:
        receipts = list(pool.map(lambda _: pay(), range(4)))
    assert len({row["receipt"]["receipt_id"] for row in receipts}) == 1
    assert sum(not row["already_paid"] for row in receipts) == 1
    assert receipts[0]["receipt"]["change_amount"] == 1000
    with sqlite3.connect(store) as conn:
        assert conn.execute("SELECT count(*) FROM parking_payments").fetchone()[0] == 1
        assert (
            conn.execute(
                "SELECT count(*) FROM audit_logs WHERE action='payment.record'"
            ).fetchone()[0]
            == 1
        )
    assert billing.get_finance(tid)["state"] == "paid"


def test_payment_rejects_stale_quotes_underpayment_and_viewers(store):
    enable()
    tid = ticket(store)
    quote = billing.get_finance(tid)
    for amount, token, received, actor in [
        (1, quote["quote_id"], 5000, OPERATOR),
        (4000, "0" * 64, 5000, OPERATOR),
        (4000, quote["quote_id"], 3000, OPERATOR),
        (4000, quote["quote_id"], 5000, VIEWER),
    ]:
        with pytest.raises(billing.BillingError):
            billing.record_payment(tid, amount, token, "cash", received, actor)


def test_migration_preserves_old_tickets_and_does_not_apply_current_prices(store):
    with sqlite3.connect(store) as conn:
        conn.execute(
            "INSERT INTO parking_logs(ticket_id,plate_entry,entry_time,status) VALUES('OLD','59-B1 123.45',?,'IN_PARKING')",
            (BASE,),
        )
    init_db(store)
    first = billing.ticket_pass("OLD")
    init_db(store)
    assert billing.ticket_pass("OLD")["qr_payload"] == first["qr_payload"]
    assert first["finance"]["amount"] is None


def test_api_permissions_payload_validation_and_lookup(store):
    enable()
    tid = ticket(store)
    client = TestClient(api_main.app)
    assert client.get(f"/tickets/{tid}/pass").status_code == 401
    api_main.app.dependency_overrides[api_main.require_bearer_user] = lambda: VIEWER
    try:
        result = client.get(f"/tickets/{tid}/pass")
        assert result.status_code == 200 and result.headers["cache-control"] == "private, no-store"
        assert (
            client.post("/tickets/lookup-qr", data={"payload": result.json()["qr_payload"]}).json()[
                "ticket"
            ]["ticket_id"]
            == tid
        )
        assert client.get("/pricing").status_code == 403
        quote = billing.get_finance(tid)
        payload = {
            "amount": quote["amount"],
            "quote_id": quote["quote_id"],
            "method": "cash",
            "received_amount": 5000,
        }
        assert client.post(f"/tickets/{tid}/payment", json=payload).status_code == 403
        api_main.app.dependency_overrides[api_main.require_bearer_user] = lambda: OPERATOR
        assert (
            client.post(f"/tickets/{tid}/payment", json={**payload, "amount": 1.2}).status_code
            == 422
        )
        assert client.post(f"/tickets/{tid}/payment", json=payload).status_code == 200
    finally:
        api_main.app.dependency_overrides.clear()
