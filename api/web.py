"""Static app shell with a server-owned, explicit offline-demo notice."""

import re
from pathlib import Path

from fastapi.responses import FileResponse, HTMLResponse

NOTICE = '<aside class="runtime-notice" aria-label="Chế độ demo"><strong>Demo ngoại tuyến.</strong> Dữ liệu riêng; nhập biển số bằng tay. Ngân hàng tắt, phần cứng mô phỏng.</aside>'


def index_response(directory: Path, *, offline_demo: bool):
    if not offline_demo:
        return FileResponse(directory / "index.html")
    html = (directory / "index.html").read_text(encoding="utf8")
    html = html.replace("<!-- RUNTIME_NOTICE -->", NOTICE)
    html = html.replace("<title>", "<title>Demo ngoại tuyến · ", 1)
    # The fallback demo also works when the conference room has no Internet.
    html = re.sub(r'<link[^>]+href="https://fonts\.googleapis\.com[^>]*>\s*', "", html)
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})
