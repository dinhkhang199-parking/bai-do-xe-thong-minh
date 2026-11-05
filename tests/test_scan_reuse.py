import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image

import api.main as api_main
from backend import parking_service, scan_cache
from backend.app_service import ProcessedPlate
from backend.auth import AuthUser
from backend.db import init_db

ACTOR = AuthUser(username="fixture-operator", role="operator")


def image_bytes(color="white"):
    file = io.BytesIO()
    Image.new("RGB", (100, 70), color).save(file, format="PNG")
    return file.getvalue()


@pytest.fixture
def context(tmp_path, monkeypatch):
    db = tmp_path / "scan.db"
    init_db(db)
    monkeypatch.setattr(parking_service, "DB_PATH", db)
    calls = []

    def process(path, *args, **kwargs):
        calls.append(path)
        return ProcessedPlate(
            ocr={
                "text": "59-B1 123.45",
                "ocr_engine": "fixture",
                "confidence": None,
                "review_required": True,
            },
            plate_text="59-B1 123.45",
        )

    monkeypatch.setattr(api_main, "process_plate_image", process)
    api_main.app.dependency_overrides[api_main.require_bearer_user] = lambda: ACTOR
    api_main.app.dependency_overrides[api_main.require_read_access] = lambda: ACTOR
    api_main._WRITE_BUCKETS.clear()
    scan_cache._items.clear()
    try:
        yield TestClient(api_main.app), calls, tmp_path
    finally:
        api_main.app.dependency_overrides.clear()
        scan_cache._items.clear()


def test_confirm_reuses_exact_scan_without_a_second_ocr_call(context):
    client, calls, _ = context
    photo = image_bytes()
    scan = client.post("/ocr", files={"file": ("plate.png", photo, "image/png")})
    assert scan.status_code == 200
    token = scan.json()["scan_token"]
    entered = client.post(
        "/vehicle/entry",
        data={"plate_text": "59-B1 123.45", "scan_token": token, "ai_review_confirmed": "true"},
        files={"file": ("renamed.png", photo, "image/png")},
    )
    assert entered.status_code == 201
    assert len(calls) == 1


def test_scan_token_is_bound_to_user_and_file(context):
    client, calls, _ = context
    token = client.post("/ocr", files={"file": ("plate.png", image_bytes(), "image/png")}).json()[
        "scan_token"
    ]
    result = client.post(
        "/vehicle/entry",
        data={"plate_text": "59-B1 123.45", "scan_token": token, "ai_review_confirmed": "true"},
        files={"file": ("plate.png", image_bytes("black"), "image/png")},
    )
    assert result.status_code == 409 and len(calls) == 1
    api_main.app.dependency_overrides[api_main.require_bearer_user] = lambda: AuthUser(
        username="other-operator", role="operator"
    )
    result = client.post(
        "/vehicle/entry",
        data={"plate_text": "59-B1 123.45", "scan_token": token, "ai_review_confirmed": "true"},
        files={"file": ("plate.png", image_bytes(), "image/png")},
    )
    assert result.status_code == 409


def test_expired_scan_cannot_be_used(context, monkeypatch):
    client, calls, _ = context
    clock = [100.0]
    monkeypatch.setattr(scan_cache, "_clock", lambda: clock[0])
    token = client.post("/ocr", files={"file": ("plate.png", image_bytes(), "image/png")}).json()[
        "scan_token"
    ]
    clock[0] += scan_cache.TTL_SECONDS + 1
    result = client.post(
        "/vehicle/entry",
        data={"plate_text": "59-B1 123.45", "scan_token": token, "ai_review_confirmed": "true"},
        files={"file": ("plate.png", image_bytes(), "image/png")},
    )
    assert result.status_code == 409 and len(calls) == 1


def test_manual_photo_confirmation_skips_ai_but_requires_review(context):
    client, calls, _ = context
    blocked = client.post(
        "/vehicle/entry",
        data={"plate_text": "59-B1 123.45", "manual_only": "true"},
        files={"file": ("plate.png", image_bytes(), "image/png")},
    )
    assert blocked.status_code == 400 and not calls
    accepted = client.post(
        "/vehicle/entry",
        data={"plate_text": "59-B1 123.45", "manual_only": "true", "ai_review_confirmed": "true"},
        files={"file": ("plate.png", image_bytes(), "image/png")},
    )
    assert accepted.status_code == 201 and not calls


def test_cache_is_bounded_and_returns_copies(context):
    _, _, tmp = context
    image = tmp / "cache.png"
    image.write_bytes(image_bytes())
    processed = ProcessedPlate(
        ocr={"text": "59-B1 123.45", "nested": {"x": 1}}, plate_text="59-B1 123.45"
    )
    token = scan_cache.remember(image, ACTOR.username, processed)
    copy = scan_cache.reuse(token, image, ACTOR.username)
    copy.ocr["nested"]["x"] = 99
    assert scan_cache.reuse(token, image, ACTOR.username).ocr["nested"]["x"] == 1
    for _ in range(scan_cache.MAX_ITEMS + 2):
        scan_cache.remember(image, ACTOR.username, processed)
    assert len(scan_cache._items) <= scan_cache.MAX_ITEMS
