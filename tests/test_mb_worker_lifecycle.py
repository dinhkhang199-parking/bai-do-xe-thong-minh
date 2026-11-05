"""Regression coverage for diagnostics and cancelled MB sessions; no live bank calls."""

import io
import json
import threading
import time
from types import SimpleNamespace

import pytest
from PIL import Image

from integrations.mb_readonly_worker import MBState, ReconnectRequired, failure_details


def until(condition):
    deadline = time.monotonic() + 2
    while not condition() and time.monotonic() < deadline:
        time.sleep(0.005)
    assert condition()


def png():
    stream = io.BytesIO()
    Image.new("RGB", (32, 16), "white").save(stream, format="PNG")
    return stream.getvalue()


@pytest.mark.parametrize(
    "code,category",
    [("GW283", "captcha_rejected"), ("GW200", "session_expired"), ("GW21", "bank_rejected")],
)
def test_diagnostics_classify_bank_codes_without_exposing_provider_messages(code, category):
    error = RuntimeError("PRIVATE PASSWORD AND ACCOUNT")
    error.code = code
    details, message = failure_details(error, "login")
    assert details["category"] == category and details["bank_code"] == code
    assert "PRIVATE" not in json.dumps([details, message])


def test_diagnostics_reject_arbitrary_error_codes_and_redact_http_bodies():
    error = RuntimeError("PRIVATE TOKEN")
    error.code = "PRIVATE TOKEN"
    error.response = SimpleNamespace(status_code=428, text="PRIVATE RESPONSE")
    details, message = failure_details(error, "login")
    assert details["category"] == "verification_required" and details["bank_code"] == ""
    assert details["http_status"] == 428
    assert "PRIVATE" not in json.dumps([details, message])


def test_login_error_exposes_safe_diagnostic_and_disconnect_clears_it(tmp_path):
    class Client:
        def userinfo(self):
            error = RuntimeError("secret")
            error.code = "GW283"
            raise error

    state = MBState(tmp_path, lambda _: Client())
    state.connect()
    until(lambda: state.state == "error")
    assert state.status()["failure"]["category"] == "captcha_rejected"
    state.disconnect()
    assert state.status()["failure"] is None and not state.message


def test_invalid_account_does_not_destroy_an_authenticated_session(tmp_path):
    state = MBState(tmp_path)
    client = object()
    state.state = "connected"
    state.client = client
    state.accounts = [{"account": "000123456789"}]
    with pytest.raises(ReconnectRequired):
        state.transactions("999999999")
    assert state.state == "connected" and state.client is client


def test_old_history_failure_cannot_destroy_a_new_session(tmp_path):
    entered = threading.Event()
    release = threading.Event()
    errors = []

    class Client:
        def getTransactionAccountHistory(self, **kwargs):
            entered.set()
            release.wait(2)
            raise RuntimeError("old session failure")

    state = MBState(tmp_path)
    state.state = "connected"
    state.client = Client()
    state.accounts = [{"account": "000123456789"}]

    def read():
        try:
            state.transactions("000123456789")
        except ReconnectRequired:
            errors.append(1)

    thread = threading.Thread(target=read)
    thread.start()
    assert entered.wait(2)
    state.disconnect()
    replacement = object()
    with state.lock:
        state.state = "connected"
        state.client = replacement
        state.accounts = [{"account": "000123456789"}]
    release.set()
    thread.join(2)
    assert errors == [1] and state.state == "connected" and state.client is replacement


def test_cancelled_captcha_does_not_clear_the_next_challenge(tmp_path):
    state = MBState(tmp_path)
    state.state = "connecting"
    errors = []

    def challenge():
        try:
            state.manual_captcha(png(), 0)
        except ReconnectRequired:
            errors.append(1)

    thread = threading.Thread(target=challenge)
    thread.start()
    until(lambda: state.captcha_event is not None)
    with state.lock:
        old_event = state.captcha_event
        state.disconnect()
        state.captcha = {"id": "new-challenge"}
        state.captcha_event = threading.Event()
        state.captcha_text = "NEW"
        state.state = "captcha_required"
    old_event.set()
    thread.join(2)
    assert errors == [1] and state.captcha["id"] == "new-challenge" and state.captcha_text == "NEW"


def test_captcha_submission_is_single_use(tmp_path):
    state = MBState(tmp_path)
    state.captcha = {"id": "challenge"}
    state.captcha_event = threading.Event()
    state.solve("challenge", "TEST")
    with pytest.raises(ValueError):
        state.solve("challenge", "OTHR")
    assert state.captcha_text == "TEST"


def test_old_login_finishes_before_new_client_creation(tmp_path):
    entered = threading.Event()
    release = threading.Event()
    created = []

    class Client:
        def __init__(self, index):
            self.index = index

        def userinfo(self):
            if self.index == 0:
                entered.set()
                release.wait(2)

        def getBalance(self):
            return {"acct_list": [{"acctNo": "000123456789", "acctNm": "DEMO", "ccyCd": "VND"}]}

    def factory(_):
        client = Client(len(created))
        created.append(client)
        return client

    state = MBState(tmp_path, factory)
    state.connect()
    assert entered.wait(2)
    state.disconnect()
    state.last_connect = 0
    state.connect()
    assert len(created) == 1
    release.set()
    until(lambda: state.state == "connected")
    assert len(created) == 2 and state.client is created[1]
