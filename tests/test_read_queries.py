import sqlite3
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

import api.main as api
from backend import read_queries as read
from backend.db import fetch_logs
from backend.parking_metrics import build_parking_kpis


def test_query_filters_literal_text_and_timezone_before_paging(log_rows):
    path = log_rows(
        [
            {
                "ticket_id": "T%_1",
                "plate_entry": "59-B1 123.45",
                "entry_time": "2026-11-01 00:00:00",
            },
            {"ticket_id": "T2", "plate_exit": "59-B1 123.45", "entry_time": "2026-10-31T17:00:00Z"},
            {"ticket_id": "T3", "entry_time": "bad-time"},
            {"ticket_id": "T4", "entry_time": "2026-10-31T16:59:59Z"},
        ]
    )
    at = datetime(2026, 10, 31, 17, tzinfo=timezone.utc)
    result = read.logs_page(limit=1, query="59-B1", from_time=at, to_time=at, db_path=path)
    assert result["total"] == 2 and result["count"] == 1
    second = read.logs_page(
        limit=1, offset=1, query="59-B1", from_time=at, to_time=at, db_path=path
    )
    assert result["items"][0]["ticket_id"] != second["items"][0]["ticket_id"]
    assert read.logs_page(ticket_id="%_", db_path=path)["total"] == 1
    assert read.logs_page(query="' OR 1=1 --", db_path=path)["total"] == 0


def test_sql_kpis_match_existing_semantics_with_legacy_confidence(log_rows):
    path = log_rows(
        [
            {
                "ticket_id": "T1",
                "status": "COMPLETED",
                "entry_ocr_confidence": 0.8,
                "exit_ocr_confidence": 0.9,
                "entry_manual_override": 1,
            },
            {
                "ticket_id": "T2",
                "status": "NEEDS_REVIEW",
                "match_result": "MISMATCH",
                "entry_ocr_confidence": "invalid",
            },
            {"ticket_id": "T3", "status": "CANCELLED", "exit_manual_override": 1},
            {"ticket_id": "T4", "status": "IN_PARKING"},
        ]
    )
    with sqlite3.connect(path) as conn:
        conn.execute("ALTER TABLE parking_logs ADD COLUMN ocr_confidence REAL")
        conn.execute("UPDATE parking_logs SET ocr_confidence=.5 WHERE ticket_id='T2'")
    expected = build_parking_kpis(fetch_logs(path)).__dict__
    actual = read.parking_kpis(path).__dict__
    for key in expected:
        assert actual[key] == pytest.approx(expected[key])


def test_active_and_event_lists_are_bounded_and_stable(log_rows):
    path = log_rows(
        [{"ticket_id": f"T{i:04d}", "entry_time": "2026-11-01 08:00:00"} for i in range(210)]
    )
    result = read.active_page(6, 0, path)
    assert result["total"] == 210 and result["count"] == 6
    assert read.active_page(None, 205, path)["count"] == 5
    with sqlite3.connect(path) as conn:
        for i in range(70):
            conn.execute("INSERT INTO parking_events(ticket_id,event_type) VALUES('T0001','TEST')")
            conn.execute("INSERT INTO audit_logs(action) VALUES('TEST')")
    first = read.events_page("T0001", 25, 0, path)
    second = read.events_page("T0001", 25, 25, path)
    assert first["total"] == 70 and not {row["id"] for row in first["items"]} & {
        row["id"] for row in second["items"]
    }
    assert read.audit_page(25, 50, path)["count"] == 20


def test_static_assets_are_compressed_and_keep_contents():
    client = TestClient(api.app)
    plain = client.get("/static/app.js", headers={"Accept-Encoding": "identity"})
    compressed = client.get("/static/app.js", headers={"Accept-Encoding": "gzip"})
    assert plain.status_code == compressed.status_code == 200
    assert compressed.headers["content-encoding"] == "gzip" and compressed.content == plain.content
    assert "Accept-Encoding" in compressed.headers["vary"]
