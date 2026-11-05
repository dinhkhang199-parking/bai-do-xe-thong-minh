import hashlib
import json
import secrets
import sqlite3

import pytest
from fastapi.testclient import TestClient

import api.main as api_main
from backend import billing
from backend.auth import AuthUser
from backend.db import init_db


@pytest.fixture
def store(tmp_path, monkeypatch):
    path = tmp_path / "overview.db"
    init_db(path)
    monkeypatch.setattr(billing, "DB_PATH", path)
    policy = json.dumps(
        {**billing.SAMPLE_TARIFFS["motorcycle"], "revision": 1, "vehicle_type": "motorcycle"}
    )
    with sqlite3.connect(path) as conn:
        for tid, status, price in [
            ("OLD", "COMPLETED", None),
            ("DUE", "COMPLETED", policy),
            ("PAID", "COMPLETED", policy),
            ("ACTIVE", "IN_PARKING", policy),
            ("VOID", "CANCELLED", policy),
        ]:
            conn.execute(
                "INSERT INTO parking_logs(ticket_id,plate_entry,entry_time,exit_time,status) VALUES(?,?,?,?,?)",
                (
                    tid,
                    "59-B1 123.45",
                    "2026-11-01T08:00:00+07:00",
                    "2026-11-01T11:00:00+07:00",
                    status,
                ),
            )
            conn.execute(
                "INSERT INTO ticket_billing VALUES(?,?,?,?,?)",
                (tid, secrets.token_hex(24), "motorcycle", price, "2026-11-01T08:00:00+07:00"),
            )
        conn.execute("UPDATE mb_settings SET account_no='112233445566' WHERE id=1")
    quote = billing.get_finance("PAID")
    billing.record_payment(
        "PAID",
        quote["amount"],
        quote["quote_id"],
        "cash",
        5000,
        AuthUser(username="fixture-cashier", role="operator"),
    )
    return path


def test_overview_separates_paid_due_and_legacy_without_applying_prices(store):
    before = hashlib.sha256(store.read_bytes()).digest()
    result = billing.payment_overview()
    items = {item["ticket_id"]: item for item in result["items"]}
    assert result["total"] == 3
    assert items["OLD"]["payment_state"] == "unconfigured" and items["OLD"]["amount"] is None
    assert items["DUE"]["payment_state"] == "unpaid" and items["DUE"]["amount"] == 4000
    assert items["PAID"]["payment_state"] == "paid" and items["PAID"]["amount"] == 4000
    assert items["PAID"]["method"] == "cash"
    assert all(not row["enabled"] for row in result["configuration"]["tariffs"])
    assert result["configuration"]["receiver_saved"] and not result["configuration"]["mb_enabled"]
    assert hashlib.sha256(store.read_bytes()).digest() == before
    assert "112233445566" not in json.dumps(result)
    assert all("policy_json" not in row and "qr_token" not in row for row in items.values())


@pytest.mark.parametrize(
    "state,tid", [("paid", "PAID"), ("unpaid", "DUE"), ("unconfigured", "OLD")]
)
def test_overview_filters_payment_state_before_paging(store, state, tid):
    result = billing.payment_overview(payment_state=state, limit=1)
    assert result["total"] == 1 and result["items"][0]["ticket_id"] == tid


def test_overview_search_is_literal_and_pagination_is_stable(store):
    assert billing.payment_overview(query="old")["items"][0]["ticket_id"] == "OLD"
    assert billing.payment_overview(query="' OR 1=1 --")["total"] == 0
    full = billing.payment_overview()["items"]
    second = billing.payment_overview(limit=1, offset=1)
    assert second["total"] == 3 and second["items"][0]["ticket_id"] == full[1]["ticket_id"]


def test_bad_ticket_time_is_flagged_without_hiding_other_payments(store):
    with sqlite3.connect(store) as conn:
        conn.execute("UPDATE parking_logs SET exit_time=NULL WHERE ticket_id='DUE'")
    rows = {item["ticket_id"]: item for item in billing.payment_overview()["items"]}
    assert rows["DUE"]["payment_state"] == "needs_review" and rows["DUE"]["amount"] is None
    assert rows["PAID"]["payment_state"] == "paid"


def test_api_requires_login_and_bounds_inputs(store):
    client = TestClient(api_main.app)
    assert client.get("/payments").status_code == 401
    api_main.app.dependency_overrides[api_main.require_bearer_user] = lambda: AuthUser(
        username="fixture-viewer", role="viewer"
    )
    try:
        response = client.get("/payments?payment_state=unconfigured")
        assert response.status_code == 200 and response.json()["total"] == 1
        assert response.headers["cache-control"] == "private, no-store"
        assert client.get("/payments?limit=101").status_code == 422
        assert client.get("/payments?payment_state=invalid").status_code == 422
    finally:
        api_main.app.dependency_overrides.clear()
