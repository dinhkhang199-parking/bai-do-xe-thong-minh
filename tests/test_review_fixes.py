"""Regression cases for the 2026-11-01 source review, using only dummy data."""

import sqlite3
from pathlib import Path
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient
from PIL import Image

import api.main as api
from backend import alpr_service, db, parking_service, production_readiness
from integrations.device_config import DeviceConfig
from scripts.restore_runtime import restore_runtime_backup


def test_signing_key_configuration_preserves_unrelated_values_and_is_idempotent(tmp_path):
    from scripts.configure_security import ensure_signing_key

    path = tmp_path / ".env"
    original = "ITS_OPENAI_API_KEY=fixture-provider-value\nOTHER=value\n"
    path.write_text(original + "ITS_API_JWT_SECRET=weak\n", encoding="utf-8")
    assert ensure_signing_key(path) is True
    content = path.read_text(encoding="utf-8")
    assert content.startswith(original)
    key = next(
        line.split("=", 1)[1]
        for line in content.splitlines()
        if line.startswith("ITS_API_JWT_SECRET=")
    )
    assert len(key) >= 64 and key != "weak"
    assert ensure_signing_key(path) is False and path.read_text(encoding="utf-8") == content


def test_signing_key_configuration_creates_missing_file_without_exposing_key(tmp_path, capsys):
    from scripts.configure_security import ensure_signing_key

    path = tmp_path / ".env"
    assert ensure_signing_key(path) is True
    assert capsys.readouterr().out == ""


def test_distinct_serial_letters_and_digits_do_not_share_ticket_identity(tmp_path, monkeypatch):
    path = tmp_path / "parking.db"
    db.init_db(path)
    monkeypatch.setattr(parking_service, "DB_PATH", path)
    one = parking_service.vehicle_entry("30-AB 123.45", ocr_confidence=0.99)
    two = parking_service.vehicle_entry("30-A8 123.45", ocr_confidence=0.99)
    assert one["success"] and two["success"]
    result = parking_service.vehicle_exit(one["ticket_id"], "30-A8 123.45", ocr_confidence=0.99)
    assert result["match_result"] == "MISMATCH"
    assert result["status"] == "NEEDS_REVIEW"
    result = parking_service.vehicle_exit(two["ticket_id"], "30a8 12345", ocr_confidence=0.99)
    assert result["status"] == "COMPLETED"


@pytest.mark.parametrize(
    "member",
    [
        "runtime/uploads/../outside.txt",
        "runtime/uploads/C:/outside.txt",
        "runtime/uploads/..\\outside.txt",
        "runtime/uploads/CON.jpg",
    ],
)
def test_unsafe_restore_preserves_existing_data(tmp_path, member):
    target = tmp_path / "live"
    target.mkdir()
    db_path = target / "parking.db"
    db_path.write_bytes(b"original")
    archive = tmp_path / "bad.zip"
    with ZipFile(archive, "w") as z:
        z.writestr("manifest.json", "{}")
        z.writestr(member, b"bad")
    with pytest.raises(ValueError):
        restore_runtime_backup(
            archive, db_path=db_path, uploads_dir=target / "uploads", base_dir=target
        )
    assert db_path.read_bytes() == b"original"
    assert not (target / "outside.txt").exists()


def test_corrupt_restore_does_not_replace_database_or_uploads(tmp_path):
    db_path = tmp_path / "live.db"
    db_path.write_bytes(b"original database")
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    (uploads / "old.jpg").write_bytes(b"original photo")
    archive = tmp_path / "bad.zip"
    with ZipFile(archive, "w") as z:
        z.writestr("manifest.json", "{}")
        z.writestr("runtime/live.db", b"not sqlite")
        z.writestr("runtime/uploads/old.jpg", b"changed photo")
    with pytest.raises((ValueError, sqlite3.Error)):
        restore_runtime_backup(archive, db_path=db_path, uploads_dir=uploads, base_dir=tmp_path)
    assert db_path.read_bytes() == b"original database"
    assert (uploads / "old.jpg").read_bytes() == b"original photo"


def test_restore_dry_run_does_not_create_destinations(tmp_path):
    archive = tmp_path / "backup.zip"
    with ZipFile(archive, "w") as z:
        z.writestr("manifest.json", "{}")
        z.writestr("runtime/live.db", b"preview only")
    destination = tmp_path / "not-created"
    result = restore_runtime_backup(
        archive, db_path=destination / "live.db", uploads_dir=destination / "uploads", dry_run=True
    )
    assert result["dry_run"] is True and not destination.exists()


def test_restore_rejects_case_collisions_before_writing(tmp_path):
    archive = tmp_path / "backup.zip"
    with ZipFile(archive, "w") as z:
        z.writestr("manifest.json", "{}")
        z.writestr("runtime/uploads/a.jpg", b"a")
        z.writestr("runtime/uploads/A.jpg", b"b")
    with pytest.raises(ValueError, match="Duplicate"):
        restore_runtime_backup(
            archive, db_path=tmp_path / "live.db", uploads_dir=tmp_path / "uploads"
        )
    assert not (tmp_path / "uploads").exists()


def test_restore_keeps_recovery_copies_after_success(tmp_path):
    source = tmp_path / "source.db"
    with sqlite3.connect(source) as conn:
        conn.execute("CREATE TABLE restored(id INTEGER)")
    conn.close()
    archive = tmp_path / "backup.zip"
    with ZipFile(archive, "w") as z:
        z.writestr("manifest.json", "{}")
        z.write(source, "runtime/live.db")
    target = tmp_path / "live.db"
    target.write_bytes(b"previous data")
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    (uploads / "old.jpg").write_bytes(b"old")
    result = restore_runtime_backup(archive, db_path=target, uploads_dir=uploads)
    assert Path(result["recovery_db"]).read_bytes() == b"previous data"
    assert (Path(result["recovery_uploads"]) / "old.jpg").read_bytes() == b"old"


def test_restore_install_error_rolls_back_both_destinations(tmp_path, monkeypatch):
    import scripts.restore_runtime as restore

    db_path = tmp_path / "live.db"
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    (uploads / "old.jpg").write_bytes(b"old")
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE old_data(id INTEGER)")
    conn.close()
    good = tmp_path / "good.db"
    with sqlite3.connect(good) as conn:
        conn.execute("CREATE TABLE new_data(id INTEGER)")
    conn.close()
    archive = tmp_path / "backup.zip"
    with ZipFile(archive, "w") as z:
        z.writestr("manifest.json", "{}")
        z.write(good, "runtime/live.db")
        z.writestr("runtime/uploads/old.jpg", b"new")
    replace = restore.os.replace

    def fail_install(src, dst):
        if Path(dst) == uploads and Path(src).name == "uploads":
            raise OSError("fixture install failure")
        return replace(src, dst)

    monkeypatch.setattr(restore.os, "replace", fail_install)
    with pytest.raises(OSError):
        restore_runtime_backup(archive, db_path=db_path, uploads_dir=uploads)
    assert (uploads / "old.jpg").read_bytes() == b"old"
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT name FROM sqlite_master WHERE name='old_data'").fetchone()


def test_ai_outage_is_preserved_when_local_fallback_succeeds(monkeypatch):
    monkeypatch.setattr(alpr_service, "_vision_enabled", lambda **kw: True)
    monkeypatch.setattr(
        alpr_service,
        "run_openai_vision",
        lambda path: (_ for _ in ()).throw(RuntimeError("private key")),
    )
    monkeypatch.setattr(alpr_service, "cv2", object())
    monkeypatch.setattr(alpr_service, "_load_runtime_frame", lambda path: object())
    monkeypatch.setattr(alpr_service, "load_fast_alpr", lambda *args: None)
    monkeypatch.setattr(alpr_service, "ENABLE_PADDLE_FALLBACK", False)
    monkeypatch.setattr(alpr_service, "ENABLE_PADDLE_OCR", False)
    monkeypatch.setattr(
        alpr_service,
        "_fuse_ocr_candidates",
        lambda *args: {"text": "66-B1 069.99", "confidence": 0.99, "ocr_engine": "local"},
    )
    result = alpr_service.run_alpr("fixture.jpg")
    assert result["text"] == "66-B1 069.99" and result["review_required"] is True
    assert result["ai_status"] == "unavailable" and "private key" not in str(result)


@pytest.fixture
def client(monkeypatch):
    api.app.dependency_overrides[api.require_bearer_user] = lambda: api.AuthUser(
        "fixture-viewer", "viewer"
    )
    monkeypatch.setattr(api, "API_TOKEN", "fixture-token")
    with TestClient(api.app) as c:
        yield c
    api.app.dependency_overrides.clear()


def test_logs_searches_all_pages_and_matches_both_timestamp_formats(client, monkeypatch, log_rows):
    rows = [
        {
            "ticket_id": f"T{i}",
            "plate_entry": "66-B1 111.11",
            "entry_time": "2026-01-01 08:00:00",
            "status": "COMPLETED",
        }
        for i in range(501)
    ]
    rows[-1].update(
        ticket_id="OLD-TICKET", plate_exit="30-AB 123.45", entry_time="2026-01-01T00:00:00"
    )
    log_rows(rows)
    response = client.get(
        "/logs",
        params={"q": "30-AB", "to_time": "2026-01-01"},
        headers={"x-api-token": "fixture-token"},
    )
    assert response.status_code == 200 and response.json()["total"] == 1
    assert response.json()["items"][0]["ticket_id"] == "OLD-TICKET"
    assert (
        client.get("/logs?offset=500&limit=500", headers={"x-api-token": "fixture-token"}).json()[
            "count"
        ]
        == 1
    )
    assert (
        client.get("/logs?to_time=invalid", headers={"x-api-token": "fixture-token"}).status_code
        == 400
    )


def test_hardware_urls_are_configuration_not_connected_state(monkeypatch):
    config = DeviceConfig(" rtsp://fixture ", "mqtt://fixture", "http://fixture")
    assert config.mode == "CONFIGURED"
    assert DeviceConfig("  ", "mqtt://fixture", "http://fixture").mode == "SIMULATED"
    monkeypatch.setattr(production_readiness, "load_device_config", lambda: config)
    assert (
        next(
            f
            for f in production_readiness.check_production_readiness()
            if f.name == "hardware_mode"
        ).status
        == "fail"
    )


def test_readiness_does_not_create_missing_database(tmp_path, monkeypatch, client):
    path = tmp_path / "missing.db"
    monkeypatch.setattr(production_readiness, "DB_PATH", path)
    response = client.get("/readiness")
    assert response.status_code == 503 and response.json()["status"] == "not_ready"
    assert not path.exists()


def test_ticket_photos_require_auth_and_stay_within_uploads(client, tmp_path, monkeypatch):
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    image = uploads / "entry.png"
    Image.new("RGB", (16, 16), "blue").save(image)
    monkeypatch.setattr(api, "UPLOAD_DIR", uploads)
    monkeypatch.setattr(
        api,
        "fetch_ticket_detail",
        lambda tid: {"entry_image_path": str(image)} if tid == "T1" else None,
    )
    response = client.get("/tickets/T1/images/entry")
    assert response.status_code == 200 and response.headers["content-type"] == "image/png"
    assert response.headers["cache-control"] == "private, no-store"
    assert client.get("/tickets/T1/images/exit").status_code == 404
    outside = tmp_path / "outside.png"
    Image.new("RGB", (16, 16), "red").save(outside)
    monkeypatch.setattr(api, "fetch_ticket_detail", lambda tid: {"entry_image_path": str(outside)})
    assert client.get("/tickets/T1/images/entry").status_code == 404
    api.app.dependency_overrides.clear()
    assert client.get("/tickets/T1/images/entry").status_code == 401
