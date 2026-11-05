from fastapi.testclient import TestClient

from api.main import app


def test_readiness_and_scorecard_endpoints(monkeypatch):
    import api.main as api

    monkeypatch.setattr(
        api,
        "runtime_readiness",
        lambda: [
            {"name": "database", "status": "ok", "detail": "Fixture database"},
            {"name": "api_parity", "status": "implemented", "detail": "Fixture routes"},
        ],
    )
    client = TestClient(app)

    readiness = client.get("/readiness")
    assert readiness.status_code == 200
    assert readiness.json()["status"] == "ready"
    assert any(check["name"] == "api_parity" for check in readiness.json()["checks"])

    scorecard = client.get("/system/scorecard")
    assert scorecard.status_code == 200
    payload = scorecard.json()
    assert payload["overall_score"] is None
    assert any(
        item["criterion"] == "Testing" and item["status"] == "not_measured"
        for item in payload["items"]
    )


def test_openapi_contains_response_models():
    client = TestClient(app)
    schema = client.get("/openapi.json").json()

    assert "HealthResponse" in schema["components"]["schemas"]
    assert "ReadinessResponse" in schema["components"]["schemas"]
    assert "ScorecardResponse" in schema["components"]["schemas"]
