"""Loopback-only MB history worker. No transfers, balances or credentials exposed."""

import argparse
import base64
import hashlib
import hmac
import importlib
import io
import re
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import dotenv_values
from flask import Flask, jsonify, request
from PIL import Image

from integrations.ecaptcha_solver import EcaptchaError, load_settings
from integrations.ecaptcha_solver import solve as solve_ecaptcha
from integrations.local_mb_captcha import LocalCaptchaError
from integrations.local_mb_captcha import readiness as local_captcha_readiness
from integrations.local_mb_captcha import solve as solve_local_captcha


class ReconnectRequired(RuntimeError):
    pass


def failure_details(error, stage):
    """Only return allowlisted metadata, never provider messages or payloads."""
    name = type(error).__name__
    code = str(getattr(error, "code", "") or "")
    code = code if re.fullmatch(r"(?:GW|MC)[0-9]{2,6}", code) else ""
    response = getattr(error, "response", None)
    http_status = getattr(response, "status_code", None)
    http_status = http_status if type(http_status) is int and 400 <= http_status <= 599 else None
    category = "internal"
    message = "Dịch vụ MB gặp lỗi xử lý. Quản trị viên cần kiểm tra thành phần kết nối MB."
    if code == "GW283":
        category = "captcha_rejected"
        message = "MB chưa chấp nhận CAPTCHA hoặc mã đã hết hạn. Kết nối lại để nhận mã mới."
    elif code == "GW200":
        category = "session_expired"
        message = "Phiên MB đã hết hạn. Kết nối lại để tiếp tục đối soát."
    elif code:
        category = "bank_rejected"
        message = f"MB từ chối yêu cầu ({code}). Kiểm tra thông tin đăng nhập và thông báo trên kênh chính thức của MB trước khi thử lại."
    elif name == "CryptoVerifyError" or http_status == 428:
        category = "verification_required"
        message = "MB yêu cầu xác minh bổ sung. Đăng nhập trên kênh chính thức của MB để hoàn tất xác minh trước khi thử lại."
    elif name in {"Timeout", "ConnectTimeout", "ReadTimeout", "ConnectionError", "SSLError"}:
        category = "network"
        message = "Chưa liên lạc được với MB. Kiểm tra kết nối mạng rồi thử lại."
    elif http_status:
        category = "http_error"
        message = f"Dịch vụ MB trả về lỗi HTTP {http_status}. Chờ dịch vụ ổn định rồi thử lại."
    elif isinstance(error, (ImportError, FileNotFoundError)):
        category = "dependency"
        message = "Thiếu thành phần kết nối MB trên máy chủ. Quản trị viên cần kiểm tra thư viện và cấu hình."
    elif name in {"ValidationError", "JSONDecodeError", "KeyError"}:
        category = "response_format"
        message = "Phản hồi MB khác định dạng thư viện đang hỗ trợ. Cần cập nhật thành phần kết nối trước khi thử lại."
    elif isinstance(error, ReconnectRequired):
        category = "reconnect_required"
        message = "Phiên xác thực MB đã dừng hoặc hết thời gian chờ. Kết nối lại để nhận phiên mới."
    return {
        "category": category,
        "stage": stage,
        "bank_code": code,
        "http_status": http_status,
    }, message


class MBState:
    def __init__(
        self, source, client_factory=None, solver=solve_ecaptcha, local_solver=solve_local_captcha
    ):
        self.source = Path(source)
        self.client_factory = client_factory
        self.solver = solver
        self.captcha_mode = "manual"
        self.local_solver = local_solver
        self.lock = threading.RLock()
        self.call_lock = threading.Lock()
        self.client = None
        self.state = "disconnected"
        self.accounts = []
        self.message = ""
        self.generation = 0
        self.captcha = None
        self.captcha_event = None
        self.captcha_text = ""
        self.cache = {}
        self.last_connect = 0
        self.failure = None
        self.stage = "idle"

    def status(self):
        with self.lock:
            credentials = dotenv_values(self.source / ".env")
            return {
                "ok": True,
                "state": self.state,
                "message": self.message,
                "accounts": list(self.accounts),
                "credentials_present": bool(
                    credentials.get("MB_PHONE") and credentials.get("MB_PASSWORD")
                ),
                "library_present": (self.source / "MBBank/mbbank/main.py").is_file(),
                "captcha_service": load_settings(self.source).public(),
                "captcha_mode": self.captcha_mode,
                "local_captcha": local_captcha_readiness(),
                "failure": dict(self.failure) if self.failure else None,
                "captcha": dict(self.captcha) if self.captcha else None,
            }

    def resolve_captcha(self, image, generation):
        if generation != self.generation or self.state != "connecting":
            raise ReconnectRequired()
        if self.captcha_mode in {"ecaptcha", "local"}:
            with self.lock:
                self.state = "captcha_solving"
                self.message = (
                    "Đang đọc CAPTCHA trên máy chủ…"
                    if self.captcha_mode == "local"
                    else "Đang giải CAPTCHA bằng Ecaptcha…"
                )
            try:
                text = (
                    self.local_solver(image)
                    if self.captcha_mode == "local"
                    else self.solver(image, load_settings(self.source))
                )
                with self.lock:
                    if generation != self.generation:
                        raise ReconnectRequired()
                    self.state = "connecting"
                    self.message = ""
                return text, True
            except (EcaptchaError, LocalCaptchaError):
                with self.lock:
                    if generation != self.generation:
                        raise ReconnectRequired()
                    self.state = "connecting"
                    self.message = (
                        "Bộ giải cục bộ chưa đọc chắc mã. Bạn nhập CAPTCHA bên dưới để tiếp tục."
                        if self.captcha_mode == "local"
                        else "Ecaptcha chưa giải được mã. Bạn nhập CAPTCHA bên dưới để tiếp tục."
                    )
        return self.manual_captcha(image, generation), False

    def manual_captcha(self, image, generation):
        if generation != self.generation or self.state != "connecting":
            raise ReconnectRequired()
        if len(image) > 512000:
            raise ValueError("captcha too large")
        with Image.open(io.BytesIO(image)) as opened:
            if opened.width * opened.height > 1000000:
                raise ValueError("captcha too large")
            stream = io.BytesIO()
            opened.convert("RGB").save(stream, format="PNG")
        event = threading.Event()
        with self.lock:
            self.captcha = {
                "id": hashlib.sha256(
                    stream.getvalue() + str(time.monotonic()).encode()
                ).hexdigest()[:32],
                "image": "data:image/png;base64," + base64.b64encode(stream.getvalue()).decode(),
            }
            self.captcha_event = event
            self.captcha_text = ""
            self.state = "captcha_required"
        event.wait(180)
        with self.lock:
            if generation != self.generation or self.captcha_event is not event:
                raise ReconnectRequired()
            text = self.captcha_text
            self.captcha = None
            self.captcha_event = None
            self.captcha_text = ""
            if not text:
                raise ReconnectRequired()
            self.state = "connecting"
        return text

    def make_client(self, generation):
        if self.client_factory:
            return self.client_factory(lambda image: self.resolve_captcha(image, generation)[0])
        lib = self.source / "MBBank"
        if not (lib / "mbbank/main.py").is_file():
            raise ImportError("library missing")
        sys.path.insert(0, str(lib))
        module = importlib.import_module("mbbank.main")
        captcha_module = importlib.import_module("mbbank.capcha_ocr")
        import requests

        session = requests.Session()
        session.trust_env = False
        budget = {"remaining": 12}
        owner = self

        class Transport:
            @staticmethod
            def call(method, url, **kwargs):
                budget["remaining"] -= 1
                if budget["remaining"] < 0:
                    raise ReconnectRequired("Bank retry limit reached")
                parsed = urlparse(url)
                if parsed.scheme != "https" or parsed.netloc != "online.mbbank.com.vn":
                    raise ReconnectRequired("Unsupported bank destination")
                # Transfer endpoints are never needed for authentication/history.
                if "/transfer/" in parsed.path or "make-transfer" in parsed.path:
                    raise ReconnectRequired("Transfer operations disabled")
                with owner.lock:
                    if generation != owner.generation:
                        raise ReconnectRequired()
                    owner.stage = {
                        "/assets/wasm/main.wasm": "encryption",
                        "/api/retail-internetbankingms/getCaptchaImage": "captcha",
                        "/api/retail_web/internetbanking/v2.0/doLogin": "login",
                        "/api/retail-go-ekycms/v1.0/verify-biometric-nfc-transaction": "verification",
                        "/api/retail-accountms/accountms/getBalance": "accounts",
                        "/api/retail-transactionms/transactionms/get-account-transaction-history": "history",
                    }.get(parsed.path, "bank_request")
                kwargs["timeout"] = (5, 15)
                kwargs["verify"] = True
                kwargs["allow_redirects"] = False
                response = session.request(method, url, **kwargs)
                if response.is_redirect:
                    response.close()
                    raise ReconnectRequired("Redirect disabled")
                response.raise_for_status()
                return response

            def get(self, url, **kwargs):
                return self.call("GET", url, **kwargs)

            def post(self, url, **kwargs):
                return self.call("POST", url, **kwargs)

        module.requests = Transport()

        class ManualCaptcha(captcha_module.CapchaProcessing):
            def process_image(self, image):
                return owner.resolve_captcha(image, generation)[0]

        manual = ManualCaptcha()
        # The supplied library creates its default OCR before applying ocr_class.
        # Replace the default OCR constructor in this worker process only.
        module.CapchaOCR = lambda: manual

        class ReadOnlyClient(module.MBBank):
            _auth_attempted = False

            def _authenticate(self):
                if self._auth_attempted or owner.state != "connecting":
                    raise ReconnectRequired()
                self._auth_attempted = True
                text, automatic = owner.resolve_captcha(self.get_capcha_image(), generation)
                try:
                    return self.login(text)
                except module.MBBankAPIError as error:
                    # Retry only a rejected automatic CAPTCHA, once, by human entry.
                    if not automatic or error.code != "GW283":
                        raise
                    owner.message = "MB chưa chấp nhận mã tự động. Hãy nhập mã mới bên dưới."
                    return self.login(owner.manual_captcha(self.get_capcha_image(), generation))

        credentials = dotenv_values(self.source / ".env")
        phone = credentials.get("MB_PHONE", "")
        password = credentials.get("MB_PASSWORD", "")
        if not phone or not password:
            raise ValueError("missing credentials")
        client = ReadOnlyClient(
            username=phone, password=password, ocr_class=manual, retry_times=1, timeout=(5, 15)
        )
        client._reset_read_budget = lambda: budget.update(remaining=6)
        return client

    def connect(self, captcha_mode="manual"):
        with self.lock:
            if captcha_mode not in {"manual", "ecaptcha", "local"}:
                raise ValueError("unsupported captcha mode")
            if self.state in {"connected", "connecting", "captcha_required", "captcha_solving"}:
                return
            if captcha_mode == "ecaptcha" and not load_settings(self.source).configured:
                self.state = "error"
                self.message = (
                    "Chưa cấu hình Ecaptcha hợp lệ. Chọn nhập tay hoặc kiểm tra khóa dịch vụ."
                )
                return
            if captcha_mode == "local" and not local_captcha_readiness()["configured"]:
                self.state = "error"
                self.message = (
                    "Bộ giải CAPTCHA cục bộ chưa sẵn sàng. Chọn nhập tay hoặc kiểm tra mô hình."
                )
                return
            if time.monotonic() - self.last_connect < 10:
                return
            self.last_connect = time.monotonic()
            self.generation += 1
            generation = self.generation
            self.state = "connecting"
            self.message = ""
            self.accounts = []
            self.cache = {}
            self.failure = None
            self.stage = "initialization"
            self.captcha_mode = captcha_mode

        def login():
            try:
                # The supplied SDK uses module-level transport/encryption state.
                # Finish obsolete provider calls before creating another client.
                with self.call_lock:
                    with self.lock:
                        if generation != self.generation:
                            return
                    client = self.make_client(generation)
                    client.userinfo()
                    with self.lock:
                        if generation != self.generation:
                            return
                    value = plain(client.getBalance())
                accounts = []
                for item in value.get("acct_list", []):
                    account = str(item.get("acctNo") or "")
                    if re.fullmatch(r"[0-9]{6,24}", account) and item.get("ccyCd") == "VND":
                        accounts.append(
                            {
                                "account": account,
                                "name": str(item.get("acctNm") or "")[:150],
                                "currency": "VND",
                            }
                        )
                if not accounts:
                    raise ValueError("no VND account")
                with self.lock:
                    if generation == self.generation:
                        self.client = client
                        self.accounts = accounts
                        self.state = "connected"
                        self.message = ""
                        self.failure = None
                        self.stage = "ready"
            except Exception as error:
                with self.lock:
                    if generation == self.generation:
                        self.client = None
                        self.state = "error"
                        self.accounts = []
                        self.failure, self.message = failure_details(error, self.stage)
                        self.captcha = None

        threading.Thread(target=login, daemon=True, name="mb-user-login").start()

    def disconnect(self):
        with self.lock:
            self.generation += 1
            self.client = None
            self.state = "disconnected"
            self.accounts = []
            self.cache = {}
            self.failure = None
            self.message = ""
            self.stage = "idle"
            self.captcha_text = ""
            self.captcha = None
            if self.captcha_event:
                self.captcha_event.set()

    def solve(self, identifier, text):
        if not re.fullmatch(r"[A-Za-z0-9]{4,12}", text):
            raise ValueError("invalid captcha")
        with self.lock:
            if (
                not self.captcha
                or self.captcha["id"] != identifier
                or not self.captcha_event
                or self.captcha_event.is_set()
            ):
                raise ValueError("expired captcha")
            self.captcha_text = text
            self.captcha_event.set()

    def transactions(self, account):
        if not self.call_lock.acquire(blocking=False):
            raise ReconnectRequired("busy")
        generation = None
        try:
            with self.lock:
                if (
                    self.state != "connected"
                    or not self.client
                    or not any(a["account"] == account for a in self.accounts)
                ):
                    raise ReconnectRequired()
                cached = self.cache.get(account)
                if cached and time.monotonic() - cached[0] < 10:
                    return cached[1]
                generation = self.generation
                client = self.client
            end = datetime.now()
            reset = getattr(client, "_reset_read_budget", None)
            if reset:
                reset()
            data = plain(
                client.getTransactionAccountHistory(
                    accountNo=account, from_date=end - timedelta(days=1), to_date=end
                )
            )
            rows = data.get("transactionHistoryList")
            if not isinstance(rows, list) or len(rows) > 2000:
                raise ValueError("unexpected history")
            keep = {
                "refNo",
                "docId",
                "accountNo",
                "creditAmount",
                "debitAmount",
                "currency",
                "description",
                "addDescription",
                "transactionDate",
            }
            records = [{key: row.get(key) for key in keep} for row in rows if isinstance(row, dict)]
            with self.lock:
                if generation != self.generation:
                    raise ReconnectRequired()
                self.cache[account] = (time.monotonic(), records)
            return records
        except Exception as error:
            with self.lock:
                if generation is not None and generation == self.generation:
                    self.client = None
                    self.state = "error"
                    self.accounts = []
                    self.cache = {}
                    self.failure, self.message = failure_details(error, "history")
            raise ReconnectRequired() from None
        finally:
            self.call_lock.release()


def plain(value):
    return value.model_dump() if hasattr(value, "model_dump") else value


def create_app(source, token, client_factory=None, solver=solve_ecaptcha):
    if len(token) < 40:
        raise ValueError("Bridge key is too short")
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 4096
    state = MBState(source, client_factory, solver)
    app.mb_state = state

    @app.before_request
    def authenticate():
        supplied = request.headers.get("Authorization", "")
        if not hmac.compare_digest(supplied.encode("utf-8"), ("Bearer " + token).encode("utf-8")):
            return jsonify(ok=False, error="unauthorized"), 401

    @app.get("/status")
    def status():
        return jsonify(state.status())

    @app.post("/connect")
    def connect():
        data = request.get_json(silent=True) or {}
        try:
            state.connect(data.get("captcha_mode", "manual"))
            return jsonify(state.status())
        except ValueError:
            return jsonify(ok=False, error="unsupported_captcha_mode"), 400

    @app.post("/disconnect")
    def disconnect():
        state.disconnect()
        return jsonify(state.status())

    @app.post("/captcha")
    def captcha():
        data = request.get_json(silent=True) or {}
        try:
            state.solve(str(data.get("id", "")), str(data.get("text", "")).strip())
            return jsonify(ok=True)
        except ValueError:
            return jsonify(ok=False, error="invalid_or_expired_captcha"), 400

    @app.post("/transactions")
    def transactions():
        data = request.get_json(silent=True) or {}
        account = str(data.get("account", ""))
        if not re.fullmatch(r"[0-9]{6,24}", account):
            return jsonify(ok=False, error="invalid_account"), 400
        try:
            return jsonify(ok=True, transactions=state.transactions(account))
        except ReconnectRequired:
            return jsonify(ok=False, error="reconnect_required"), 409

    return app


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--key-file", type=Path, required=True)
    args = parser.parse_args()
    app = create_app(args.source, args.key_file.read_text(encoding="ascii").strip())
    # Startup performs no bank login, CAPTCHA solving or history request.
    app.run(host="127.0.0.1", port=5051, debug=False, use_reloader=False, threaded=True)


if __name__ == "__main__":
    main()
