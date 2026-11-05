"""Authenticated loopback client for the read-only MB worker."""

import json
import os
from pathlib import Path
from urllib import error, request

PROJECT = Path(__file__).resolve().parents[1]


class MBConnectionError(RuntimeError):
    def __init__(self, message, status=503):
        super().__init__(message)
        self.status = status


class NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise MBConnectionError("MB bridge không được chuyển hướng kết nối.")


def call_worker(path, payload=None, timeout=20):
    if os.getenv("ITS_MB_TEST_MODE") == "true":
        raise MBConnectionError("MB thật bị tắt trong môi trường kiểm thử.")
    if path not in {"/status", "/connect", "/disconnect", "/captcha", "/transactions"}:
        raise MBConnectionError("Thao tác MB không được hỗ trợ.")
    key_path = PROJECT / ".mb_bridge_token"
    try:
        key = key_path.read_text(encoding="ascii").strip()
    except OSError:
        raise MBConnectionError("Chưa cấu hình dịch vụ MB trên máy chủ.") from None
    if len(key) < 40:
        raise MBConnectionError("Khóa kết nối MB chưa hợp lệ.")
    body = json.dumps(payload).encode() if payload is not None else None
    req = request.Request(
        "http://127.0.0.1:5051" + path,
        data=body,
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
        method="POST" if body is not None else "GET",
    )
    opener = request.build_opener(request.ProxyHandler({}), NoRedirect())
    try:
        with opener.open(req, timeout=timeout) as response:
            raw = response.read(2 * 1024 * 1024 + 1)
            if len(raw) > 2 * 1024 * 1024:
                raise MBConnectionError("Dữ liệu MB vượt giới hạn xử lý.")
            result = json.loads(raw)
        if not isinstance(result, dict) or not result.get("ok"):
            raise MBConnectionError("Dịch vụ MB chưa trả về dữ liệu hợp lệ.")
        return result
    except MBConnectionError:
        raise
    except error.HTTPError as exc:
        try:
            raw = exc.read(4097)
            data = json.loads(raw) if len(raw) <= 4096 else {}
            kind = data.get("error") if isinstance(data, dict) else None
        except (OSError, ValueError):
            kind = None
        finally:
            exc.close()
        messages = {
            "invalid_or_expired_captcha": (
                "CAPTCHA đã hết hạn hoặc đã gửi. Cập nhật trạng thái để lấy mã đang chờ.",
                400,
            ),
            "reconnect_required": (
                "Phiên MB chưa sẵn sàng. Mở Kết nối MB để kiểm tra và đăng nhập lại.",
                409,
            ),
            "invalid_account": ("Tài khoản MB chưa hợp lệ.", 400),
            "unsupported_captcha_mode": ("Chế độ CAPTCHA chưa hợp lệ.", 400),
        }
        if kind in messages:
            message, status = messages[kind]
            raise MBConnectionError(message, status) from None
        raise MBConnectionError(
            "Dịch vụ MB chưa xử lý được yêu cầu. Kiểm tra kết nối MB."
        ) from None
    except (error.URLError, TimeoutError, OSError, ValueError):
        raise MBConnectionError(
            "Chưa kết nối được MB. Kiểm tra dịch vụ và đăng nhập lại ở mục Kết nối MB."
        ) from None
