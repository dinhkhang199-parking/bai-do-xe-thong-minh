from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

import api.main as api_main

pytestmark = pytest.mark.api


@pytest.fixture
def client(monkeypatch):
    # Keep auth overrides local to this test; do not rely on stored JWT accounts.
    monkeypatch.setattr(api_main.app, "dependency_overrides", {})
    return TestClient(api_main.app)


def readiness_payload():
    return {
        "checks": [{"name": "external_models", "status": "pass"}],
        "models": [
            {
                "name": "dummy.pt",
                "path": "C:/dummy/models/dummy.pt",
                "size_mb": 1.0,
                "metadata": {"cache_path": "C:/dummy/cache", "kind": "fixture"},
            }
        ],
        "diagnostics": {
            "path": "C:/dummy",
            "items": [{"image_path": "C:/dummy/image.jpg", "status": "ok"}, "public"],
            "path_count": 2,
        },
        "summary": {"pass": 1, "warn": 0, "fail": 0, "info": 0},
    }


def public_readiness_payload():
    return {
        "checks": [{"name": "external_models", "status": "pass"}],
        "models": [
            {
                "name": "dummy.pt",
                "size_mb": 1.0,
                "metadata": {"kind": "fixture"},
            }
        ],
        "diagnostics": {"items": [{"status": "ok"}, "public"], "path_count": 2},
        "summary": {"pass": 1, "warn": 0, "fail": 0, "info": 0},
    }


@pytest.mark.parametrize("role", sorted(api_main.ALL_ROLES))
@pytest.mark.parametrize("expose_paths", [False, True])
def test_cv_readiness_honors_path_exposure_for_all_roles(client, monkeypatch, role, expose_paths):
    original = readiness_payload()
    before = deepcopy(original)
    monkeypatch.setattr(api_main, "API_EXPOSE_INTERNAL_PATHS", expose_paths)
    monkeypatch.setattr(api_main, "build_cv_readiness", lambda: original)
    api_main.app.dependency_overrides[api_main.require_bearer_user] = lambda: api_main.AuthUser(
        username=f"dummy-{role}", role=role
    )

    response = client.get("/cv/readiness")

    assert response.status_code == 200
    expected = before if expose_paths else public_readiness_payload()
    assert response.json() == {"ok": True, **expected}
    assert original == before


@pytest.mark.parametrize("sanitize", [api_main._sanitize_record, api_main._sanitize_ocr_payload])
def test_shared_sanitizers_strip_nested_path_fields_without_mutation(monkeypatch, sanitize):
    original = readiness_payload()
    before = deepcopy(original)
    monkeypatch.setattr(api_main, "API_EXPOSE_INTERNAL_PATHS", False)

    result = sanitize(original)

    assert result == public_readiness_payload()
    assert original == before
    assert result is not original
    assert result["models"] is not original["models"]
    assert result["models"][0] is not original["models"][0]


def test_cv_readiness_rejects_unauthenticated_requests(client, monkeypatch):
    monkeypatch.setattr(api_main, "verify_session_token", lambda token: None)
    monkeypatch.setattr(api_main, "parse_static_bearer_token", lambda token: None)

    def should_not_build_readiness():
        raise AssertionError("Unauthenticated request reached readiness data")

    monkeypatch.setattr(api_main, "build_cv_readiness", should_not_build_readiness)

    response = client.get("/cv/readiness")

    assert response.status_code == 401
