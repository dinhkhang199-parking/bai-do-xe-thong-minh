"""Account lifecycle changes must immediately invalidate prior HTTP sessions."""

import base64
import hashlib
import hmac
import json
import sqlite3
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

import api.main as api_main
from backend import auth, db


pytestmark = pytest.mark.unit

PASSWORD = "FixturePass941!"
NEW_PASSWORD = "ChangedFixture593!"
TEST_SIGNING_KEY = "fixture-only-session-signing-key-not-a-deployment-secret"


@pytest.fixture
def session_client(tmp_path, monkeypatch):
    """Route every DB helper, including imported aliases, to one disposable DB."""
    database = tmp_path / "sessions.sqlite3"
    monkeypatch.setattr(db, "_connect", lambda db_path=None: sqlite3.connect(database))
    monkeypatch.setattr(auth, "API_JWT_SECRET", TEST_SIGNING_KEY)
    monkeypatch.setattr(auth, "API_ALLOW_STATIC_TOKENS", False)
    monkeypatch.setattr(auth, "get_streamlit_users", lambda: [])
    db.init_db(database)
    with TestClient(api_main.app) as client:
        yield client


def create_account(username, role="operator", password=PASSWORD):
    assert db.create_app_user(username, auth._hash_password(password), role)


def login(client, username, password=PASSWORD):
    response = client.post("/auth/login", data={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def assert_session_denied(client, token):
    assert client.get("/auth/me", headers=bearer(token)).status_code == 401
    # Authentication must reject this before any barrier action can execute.
    response = client.post(
        "/devices/barrier/open",
        headers=bearer(token),
        data={"lane_id": "fixture-lane", "reason": "session regression"},
    )
    assert response.status_code == 401


@pytest.mark.parametrize("change", ["disable", "delete", "demote"])
def test_account_admin_changes_revoke_sessions_even_after_restoration(session_client, change):
    client = session_client
    create_account("control01", role="admin")
    create_account("subject01", role="admin")
    control = bearer(login(client, "control01"))
    prior_token = login(client, "subject01")
    assert client.get("/admin/users", headers=bearer(prior_token)).status_code == 200

    if change == "disable":
        changed = client.patch("/admin/users/subject01/active", headers=control, data={"is_active": "false"})
    elif change == "delete":
        changed = client.delete("/admin/users/subject01", headers=control)
    else:
        changed = client.patch("/admin/users/subject01/role", headers=control, data={"role": "viewer"})
    assert changed.status_code == 200
    assert_session_denied(client, prior_token)
    assert client.get("/admin/users", headers=bearer(prior_token)).status_code == 401

    if change == "disable":
        restored = client.patch("/admin/users/subject01/active", headers=control, data={"is_active": "true"})
    elif change == "delete":
        restored = client.post(
            "/admin/users", headers=control,
            data={"username": "subject01", "password": PASSWORD, "role": "admin"},
        )
    else:
        restored = client.patch("/admin/users/subject01/role", headers=control, data={"role": "admin"})
    assert restored.status_code in {200, 201}
    assert_session_denied(client, prior_token)
    fresh_token = login(client, "subject01")
    assert client.get("/admin/users", headers=bearer(fresh_token)).status_code == 200
    assert client.get("/admin/users", headers=control).status_code == 200


def test_password_change_revokes_old_session_and_old_password(session_client):
    client = session_client
    create_account("subject01")
    prior_token = login(client, "subject01")
    success, message = auth.change_streamlit_password("subject01", PASSWORD, NEW_PASSWORD)
    assert success, message
    assert_session_denied(client, prior_token)
    assert client.post(
        "/auth/login", data={"username": "subject01", "password": PASSWORD}
    ).status_code == 401
    fresh_token = login(client, "subject01", NEW_PASSWORD)
    assert client.get("/auth/me", headers=bearer(fresh_token)).status_code == 200


def test_legacy_password_upgrade_can_issue_session_and_later_login_keeps_it_valid(session_client):
    username = "subject01"
    legacy_hash = hashlib.sha256(f"its::{username}::{PASSWORD}".encode()).hexdigest()
    assert db.create_app_user(username, legacy_hash, "operator")
    upgraded_token = login(session_client, username)
    assert session_client.get("/auth/me", headers=bearer(upgraded_token)).status_code == 200
    later_token = login(session_client, username)
    assert session_client.get("/auth/me", headers=bearer(later_token)).status_code == 200
    # Merely signing in again must not revoke another valid session.
    assert session_client.get("/auth/me", headers=bearer(upgraded_token)).status_code == 200


def test_database_password_failure_cannot_fall_back_to_same_name_environment_admin(session_client, monkeypatch):
    client = session_client
    create_account("subject01", role="viewer", password=NEW_PASSWORD)
    monkeypatch.setattr(auth, "get_streamlit_users", lambda: [auth.LoginUser("subject01", PASSWORD, "admin")])
    response = client.post("/auth/login", data={"username": "subject01", "password": PASSWORD})
    assert response.status_code == 401
    current_token = login(client, "subject01", NEW_PASSWORD)
    assert client.get("/auth/me", headers=bearer(current_token)).json()["user"]["role"] == "viewer"
    assert client.get("/admin/users", headers=bearer(current_token)).status_code == 403


@pytest.mark.parametrize("change", ["password", "role", "remove"])
def test_environment_sessions_follow_current_configuration(session_client, monkeypatch, change):
    client = session_client
    configured = [auth.LoginUser("envsubject", PASSWORD, "operator")]
    monkeypatch.setattr(auth, "get_streamlit_users", lambda: configured)
    prior_token = login(client, "envsubject")
    assert client.get("/auth/me", headers=bearer(prior_token)).status_code == 200

    if change == "password":
        configured[:] = [auth.LoginUser("envsubject", NEW_PASSWORD, "operator")]
    elif change == "role":
        configured[:] = [auth.LoginUser("envsubject", PASSWORD, "viewer")]
    else:
        configured.clear()
    assert_session_denied(client, prior_token)

    if change == "remove":
        assert client.post(
            "/auth/login", data={"username": "envsubject", "password": PASSWORD}
        ).status_code == 401
    else:
        fresh_token = login(client, "envsubject", NEW_PASSWORD if change == "password" else PASSWORD)
        current = client.get("/auth/me", headers=bearer(fresh_token))
        assert current.status_code == 200
        assert current.json()["user"]["role"] == ("viewer" if change == "role" else "operator")


def test_database_identity_shadows_existing_environment_session(session_client, monkeypatch):
    client = session_client
    monkeypatch.setattr(auth, "get_streamlit_users", lambda: [auth.LoginUser("subject01", PASSWORD, "admin")])
    environment_token = login(client, "subject01")
    assert client.get("/admin/users", headers=bearer(environment_token)).status_code == 200
    create_account("subject01", role="viewer", password=NEW_PASSWORD)
    assert_session_denied(client, environment_token)
    assert client.post(
        "/auth/login", data={"username": "subject01", "password": PASSWORD}
    ).status_code == 401
    database_token = login(client, "subject01", NEW_PASSWORD)
    assert client.get("/auth/me", headers=bearer(database_token)).json()["user"]["role"] == "viewer"


def test_deleted_database_principal_cannot_be_reissued_as_environment_identity(session_client, monkeypatch):
    create_account("subject01")
    authenticated = auth.authenticate_streamlit_user("subject01", PASSWORD)
    assert authenticated is not None
    assert db.delete_app_user("subject01")
    monkeypatch.setattr(auth, "get_streamlit_users", lambda: [auth.LoginUser("subject01", PASSWORD, "operator")])
    with pytest.raises(ValueError, match="Session identity"):
        auth.create_session_token(authenticated)


def test_arbitrary_unverified_identity_cannot_mint_a_session(session_client):
    create_account("subject01", role="admin")
    with pytest.raises(ValueError, match="Session identity"):
        auth.create_session_token(auth.AuthUser("subject01", "admin"))


def test_legacy_signed_token_without_account_binding_is_rejected(session_client):
    create_account("subject01", role="admin")

    def encode(value):
        return base64.urlsafe_b64encode(json.dumps(value, separators=(",", ":")).encode()).decode().rstrip("=")

    now = int(datetime.now(timezone.utc).timestamp())
    header = encode({"alg": "HS256", "typ": "JWT"})
    payload = encode({"sub": "subject01", "role": "admin", "iat": now, "exp": now + 300})
    body = f"{header}.{payload}"
    signature = base64.urlsafe_b64encode(
        hmac.new(TEST_SIGNING_KEY.encode(), body.encode(), hashlib.sha256).digest()
    ).decode().rstrip("=")
    assert_session_denied(session_client, f"{body}.{signature}")


def test_session_timestamps_use_real_utc_epoch_seconds(session_client):
    create_account("subject01")
    authenticated = auth.authenticate_streamlit_user("subject01", PASSWORD)
    assert authenticated is not None
    before = int(datetime.now(timezone.utc).timestamp())
    token = auth.create_session_token(authenticated, expires_minutes=5)
    after = int(datetime.now(timezone.utc).timestamp())
    encoded = token.split(".")[1]
    payload = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
    assert before <= payload["iat"] <= after
    assert payload["exp"] - payload["iat"] == 300
    assert session_client.get("/auth/me", headers=bearer(token)).status_code == 200


def test_admin_cannot_demote_their_current_account(session_client):
    create_account("control01", role="admin")
    create_account("backup01", role="admin")
    token = login(session_client, "control01")
    response = session_client.patch("/admin/users/control01/role", headers=bearer(token), data={"role": "viewer"})
    assert response.status_code == 400
    assert db.fetch_app_user("control01")["role"] == "admin"
    assert session_client.get("/admin/users", headers=bearer(token)).status_code == 200


@pytest.mark.parametrize("change", ["demote", "disable", "delete"])
def test_last_database_admin_is_preserved_even_for_environment_admin(session_client, monkeypatch, change):
    create_account("lastadmin", role="admin")
    monkeypatch.setattr(auth, "get_streamlit_users", lambda: [auth.LoginUser("envadmin", PASSWORD, "admin")])
    control = bearer(login(session_client, "envadmin"))
    if change == "demote":
        response = session_client.patch("/admin/users/lastadmin/role", headers=control, data={"role": "viewer"})
    elif change == "disable":
        response = session_client.patch("/admin/users/lastadmin/active", headers=control, data={"is_active": "false"})
    else:
        response = session_client.delete("/admin/users/lastadmin", headers=control)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "last_admin"
    account = db.fetch_app_user("lastadmin")
    assert account["role"] == "admin" and account["is_active"] == 1


@pytest.mark.parametrize("change", ["role", "active"])
def test_saving_unchanged_account_settings_does_not_log_user_out(session_client, change):
    create_account("control01", role="admin")
    token = login(session_client, "control01")
    if change == "role":
        response = session_client.patch("/admin/users/control01/role", headers=bearer(token), data={"role": "admin"})
    else:
        response = session_client.patch("/admin/users/control01/active", headers=bearer(token), data={"is_active": "true"})
    assert response.status_code == 200
    assert session_client.get("/admin/users", headers=bearer(token)).status_code == 200


def test_concurrent_admin_removals_keep_one_active_admin(session_client):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    create_account("firstadmin", role="admin")
    create_account("secondadmin", role="admin")
    start = Barrier(2)

    def remove(username):
        start.wait(timeout=5)
        try:
            if username == "firstadmin":
                db.update_app_user_role(username, "viewer")
            else:
                db.delete_app_user(username)
            return "changed"
        except db.LastAdminError:
            return "protected"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(remove, ["firstadmin", "secondadmin"]))
    assert sorted(outcomes) == ["changed", "protected"]
    users = db.list_app_users()
    assert len(users[(users.role == "admin") & (users.is_active == 1)]) == 1
