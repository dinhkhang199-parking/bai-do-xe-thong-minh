import base64
import io
import json
import threading
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from PIL import Image

import api.main as api_main
from backend.auth import AuthUser
from integrations import mb_readonly_worker as worker
from integrations.ecaptcha_solver import EcaptchaError, EcaptchaSettings, load_settings, solve

TOKEN = "DUMMY_ECAPTCHA_TEST_TOKEN"
URL = "https://ecaptcha.shopcode.top/api/test-only"
ADMIN = AuthUser(username="fixture-admin", role="admin")
OPERATOR = AuthUser(username="fixture-operator", role="operator")


def png():
    stream = io.BytesIO()
    Image.new("RGB", (48, 24), "white").save(stream, format="PNG")
    return stream.getvalue()


def config(tmp_path):
    (tmp_path / ".env").write_text(
        f"ECAPTCHA_URL={URL}\nECAPTCHA_TOKEN={TOKEN}\nMB_PHONE=dummy-user\nMB_PASSWORD=dummy-bank-password\n",
        encoding="utf-8",
    )


def until(check):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline and not check():
        time.sleep(0.01)
    assert check()


class Response:
    def __init__(self, value=None, status=200, raw=None):
        self.status_code = status
        self.raw = raw if raw is not None else json.dumps(value).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def iter_content(self, chunk_size):
        for offset in range(0, len(self.raw), chunk_size):
            yield self.raw[offset : offset + chunk_size]


def test_settings_read_legacy_literals_without_executing_source(tmp_path):
    (tmp_path / "bridge.py").write_text(
        f"import os\nraise RuntimeError('must not execute')\nECAPTCHA_TOKEN=os.getenv('ECAPTCHA_TOKEN','{TOKEN}').strip()\nECAPTCHA_URL=os.getenv('ECAPTCHA_URL','{URL}').strip()\n",
        encoding="utf-8",
    )
    settings = load_settings(tmp_path)
    assert settings.configured and settings.source == "legacy_bridge"
    assert TOKEN not in repr(settings) and TOKEN not in json.dumps(settings.public())
    (tmp_path / ".env").write_text("ECAPTCHA_TOKEN=\n", encoding="utf-8")
    assert not load_settings(tmp_path).configured


def test_env_overrides_legacy_token(tmp_path):
    (tmp_path / "bridge.py").write_text(
        f"ECAPTCHA_TOKEN='{TOKEN}'\nECAPTCHA_URL='{URL}'\n", encoding="utf-8"
    )
    (tmp_path / ".env").write_text("ECAPTCHA_TOKEN=OTHER_DUMMY_TOKEN\n", encoding="utf-8")
    assert load_settings(tmp_path).token == "OTHER_DUMMY_TOKEN"


@pytest.mark.parametrize(
    "url",
    [
        "http://ecaptcha.shopcode.top/solve",
        "https://evil.example/solve",
        "https://ecaptcha.shopcode.top.evil.example/solve",
        "https://user:pass@ecaptcha.shopcode.top/solve",
        "https://ecaptcha.shopcode.top:444/solve",
        "https://ecaptcha.shopcode.top/solve?token=secret",
        "https://ecaptcha.shopcode.top/solve#x",
        "https://127.0.0.1/solve",
    ],
)
def test_unapproved_endpoint_never_receives_service_token(url):
    called = []
    with pytest.raises(EcaptchaError):
        solve(png(), EcaptchaSettings(url, TOKEN), lambda *a, **kw: called.append(kw))
    assert called == []


def test_only_captcha_pixels_and_request_id_are_sent_once():
    calls = []

    def transport(url, **kwargs):
        calls.append((url, kwargs))
        return Response({"status": "success", "captcha": "AB12"})

    assert solve(png(), EcaptchaSettings(URL, TOKEN), transport) == "AB12"
    assert len(calls) == 1
    url, kwargs = calls[0]
    assert set(kwargs["json"]) == {"base64", "request_id"}
    assert kwargs["headers"]["Authorization"] == "Bearer " + TOKEN
    assert TOKEN not in json.dumps(kwargs["json"])
    assert kwargs["allow_redirects"] is False and kwargs["verify"] is True
    with Image.open(io.BytesIO(base64.b64decode(kwargs["json"]["base64"]))) as image:
        assert image.format == "PNG"


@pytest.mark.parametrize(
    "response",
    [
        Response({"status": "success", "captcha": "ABC"}, status=302),
        Response({"status": "failure", "message": TOKEN}),
        Response({"status": "success", "captcha": "<script>"}),
        Response({"status": "success", "captcha": 1234}),
        Response(raw=b"<html>provider error</html>"),
        Response(raw=b"x" * 65537),
    ],
)
def test_provider_failures_are_bounded_and_do_not_expose_credentials(response):
    calls = []

    def transport(*a, **kw):
        calls.append(1)
        return response

    with pytest.raises(EcaptchaError) as error:
        solve(png(), EcaptchaSettings(URL, TOKEN), transport)
    assert len(calls) == 1 and TOKEN not in str(error.value)


def test_live_service_is_disabled_in_test_mode(monkeypatch):
    monkeypatch.setenv("ITS_MB_TEST_MODE", "true")
    with pytest.raises(EcaptchaError, match="kiểm thử"):
        solve(png(), EcaptchaSettings(URL, TOKEN))


def test_automatic_worker_uses_one_solver_request_without_manual_prompt(tmp_path):
    config(tmp_path)
    calls = []

    class Bank:
        def __init__(self, callback):
            self.callback = callback

        def userinfo(self):
            assert self.callback(png()) == "AUTO"

        def getBalance(self):
            return {"acct_list": [{"acctNo": "000123456789", "acctNm": "DEMO", "ccyCd": "VND"}]}

    def solver(image, settings):
        calls.append(1)
        return "AUTO"

    app = worker.create_app(tmp_path, "x" * 48, Bank, solver)
    app.mb_state.connect("ecaptcha")
    until(lambda: app.mb_state.state == "connected")
    status = app.mb_state.status()
    assert calls == [1] and status["captcha"] is None
    assert status["captcha_mode"] == "ecaptcha"
    assert TOKEN not in json.dumps(status) and "dummy-bank-password" not in json.dumps(status)


def test_service_error_falls_back_to_manual_without_retrying_provider(tmp_path):
    config(tmp_path)
    calls = []

    class Bank:
        def __init__(self, callback):
            self.callback = callback

        def userinfo(self):
            assert self.callback(png()) == "TEST"

        def getBalance(self):
            return {"acct_list": [{"acctNo": "000123456789", "acctNm": "DEMO", "ccyCd": "VND"}]}

    def solver(*args):
        calls.append(1)
        raise EcaptchaError("unavailable")

    state = worker.create_app(tmp_path, "x" * 48, Bank, solver).mb_state
    state.connect("ecaptcha")
    until(lambda: state.state == "captcha_required")
    assert "Ecaptcha" in state.message
    state.solve(state.captcha["id"], "TEST")
    until(lambda: state.state == "connected")
    assert calls == [1]


def test_disconnect_during_solving_cannot_continue_bank_login(tmp_path):
    config(tmp_path)
    entered = threading.Event()
    release = threading.Event()
    bank_reads = []

    class Bank:
        def __init__(self, callback):
            self.callback = callback

        def userinfo(self):
            self.callback(png())

        def getBalance(self):
            bank_reads.append(1)
            return {}

    def solver(*args):
        entered.set()
        release.wait(2)
        return "AUTO"

    state = worker.create_app(tmp_path, "x" * 48, Bank, solver).mb_state
    state.connect("ecaptcha")
    assert entered.wait(2)
    state.disconnect()
    release.set()
    time.sleep(0.05)
    assert state.state == "disconnected" and bank_reads == []


@pytest.mark.parametrize("bank_code,expect_manual", [("GW283", True), ("GW21", False)])
def test_only_rejected_automatic_captcha_gets_one_manual_retry(
    tmp_path, monkeypatch, bank_code, expect_manual
):
    config(tmp_path)
    lib = tmp_path / "MBBank/mbbank"
    lib.mkdir(parents=True)
    (lib / "main.py").write_text("")
    logins = []
    solves = []

    class APIError(Exception):
        def __init__(self, code):
            self.code = code

    class Base:
        def __init__(self, **kwargs):
            pass

        def get_capcha_image(self):
            return png()

        def login(self, text):
            logins.append(text)
            if text == "AUTO":
                raise APIError(bank_code)

        def userinfo(self):
            self._authenticate()

        def getBalance(self):
            return {"acct_list": [{"acctNo": "000123456789", "acctNm": "DEMO", "ccyCd": "VND"}]}

    module = SimpleNamespace(MBBank=Base, MBBankAPIError=APIError)
    captcha = SimpleNamespace(CapchaProcessing=object)
    # Replace this worker's import boundary, not Python's shared importlib module.
    monkeypatch.setattr(
        worker,
        "importlib",
        SimpleNamespace(import_module=lambda name: module if name == "mbbank.main" else captcha),
    )

    def solver(*args):
        solves.append(1)
        return "AUTO"

    state = worker.create_app(tmp_path, "x" * 48, solver=solver).mb_state
    state.connect("ecaptcha")
    until(lambda: state.state in {"captcha_required", "error"})
    if expect_manual:
        assert state.state == "captcha_required"
        state.solve(state.captcha["id"], "TEST")
        until(lambda: state.state == "connected")
        assert logins == ["AUTO", "TEST"]
    else:
        assert state.state == "error" and logins == ["AUTO"]
    assert solves == [1]


def test_api_passes_selected_mode_only_for_admin(monkeypatch):
    calls = []
    monkeypatch.setattr(
        api_main,
        "call_worker",
        lambda path, payload: calls.append((path, payload)) or {"ok": True, "state": "connecting"},
    )
    client = TestClient(api_main.app)
    api_main.app.dependency_overrides[api_main.require_bearer_user] = lambda: OPERATOR
    try:
        assert client.post("/mb/connect", json={"captcha_mode": "ecaptcha"}).status_code == 403
        assert calls == []
        api_main.app.dependency_overrides[api_main.require_bearer_user] = lambda: ADMIN
        assert client.post("/mb/connect", json={"captcha_mode": "ecaptcha"}).status_code == 200
        assert calls == [("/connect", {"captcha_mode": "ecaptcha"})]
        assert client.post("/mb/connect", json={"captcha_mode": "unknown"}).status_code == 422
    finally:
        api_main.app.dependency_overrides.clear()
