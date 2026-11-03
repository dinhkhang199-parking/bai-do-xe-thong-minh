"""Ecaptcha adapter: image-only payload, bounded calls and no credential disclosure."""
from __future__ import annotations

import ast
import base64
from dataclasses import dataclass,field
import io
import json
import os
from pathlib import Path
import re
from urllib.parse import urlsplit
from uuid import uuid4

from dotenv import dotenv_values
from PIL import Image

HOST="ecaptcha.shopcode.top"


class EcaptchaError(RuntimeError):
    pass


@dataclass(frozen=True)
class EcaptchaSettings:
    url: str
    token: str = field(repr=False)
    source: str = "none"

    @property
    def configured(self):
        try:
            endpoint=urlsplit(self.url)
            return bool(8<=len(self.token)<=4096 and not any(c in self.token for c in "\r\n") and
                endpoint.scheme=="https" and endpoint.hostname==HOST and endpoint.port in (None,443) and
                not endpoint.username and not endpoint.password and not endpoint.query and not endpoint.fragment and
                endpoint.path.startswith("/") and not any(ord(c)<32 for c in self.url))
        except ValueError:
            return False

    def public(self):
        return {"provider":"Ecaptcha","host":HOST,"configured":self.configured,"source":self.source}


def load_settings(source: Path):
    """Read .env first, then literal defaults from the supplied bridge, without importing it."""
    source=Path(source)
    values=dotenv_values(source/".env")
    defaults={}
    try:
        path=source/"bridge.py"
        if path.stat().st_size<=128000:
            tree=ast.parse(path.read_text(encoding="utf-8-sig"))
            for node in tree.body:
                if not isinstance(node,ast.Assign):
                    continue
                names={target.id for target in node.targets if isinstance(target,ast.Name)}
                for name in names & {"ECAPTCHA_TOKEN","ECAPTCHA_URL"}:
                    if isinstance(node.value,ast.Constant) and isinstance(node.value.value,str):
                        defaults[name]=node.value.value
                    for call in ast.walk(node.value):
                        if (isinstance(call,ast.Call) and isinstance(call.func,ast.Attribute) and
                            isinstance(call.func.value,ast.Name) and call.func.value.id=="os" and call.func.attr=="getenv" and
                            len(call.args)>=2 and isinstance(call.args[0],ast.Constant) and call.args[0].value==name and
                            isinstance(call.args[1],ast.Constant) and isinstance(call.args[1].value,str)):
                            defaults[name]=call.args[1].value
    except (OSError,SyntaxError,UnicodeError):
        pass
    def value(key):
        # An explicitly empty .env value disables the legacy fallback.
        return str(values[key] or "").strip() if key in values else str(defaults.get(key,"")).strip()
    origin="env" if "ECAPTCHA_TOKEN" in values else "legacy_bridge" if defaults.get("ECAPTCHA_TOKEN") else "none"
    return EcaptchaSettings(value("ECAPTCHA_URL"),value("ECAPTCHA_TOKEN"),origin)


def clean_image(image: bytes):
    if not isinstance(image,bytes) or not image or len(image)>512000:
        raise EcaptchaError("Ảnh CAPTCHA không hợp lệ.")
    try:
        with Image.open(io.BytesIO(image)) as original:
            if original.width*original.height>1000000:
                raise EcaptchaError("Ảnh CAPTCHA vượt giới hạn.")
            output=io.BytesIO();original.convert("RGB").save(output,format="PNG")
        result=output.getvalue()
        if len(result)>512000:
            raise EcaptchaError("Ảnh CAPTCHA vượt giới hạn.")
        return result
    except (OSError,ValueError):
        raise EcaptchaError("Không đọc được ảnh CAPTCHA.") from None


def solve(image: bytes, settings: EcaptchaSettings, transport=None):
    if not settings.configured:
        raise EcaptchaError("Chưa có cấu hình Ecaptcha hợp lệ.")
    normalized=clean_image(image)
    body={"base64":base64.b64encode(normalized).decode(),"request_id":uuid4().hex}
    headers={"Authorization":"Bearer "+settings.token,"Content-Type":"application/json"}
    session=None
    if transport is None:
        if os.getenv("ITS_MB_TEST_MODE")=="true":
            raise EcaptchaError("Dịch vụ CAPTCHA thật bị tắt trong môi trường kiểm thử.")
        import requests
        session=requests.Session();session.trust_env=False
        transport=session.post
    try:
        # One request, no automatic retry, no redirects carrying the service token.
        with transport(settings.url,json=body,headers=headers,timeout=(5,20),
                       allow_redirects=False,verify=True,stream=True) as response:
            if not 200<=response.status_code<300:
                raise EcaptchaError("Ecaptcha chưa trả về kết quả thành công.")
            data=bytearray()
            for chunk in response.iter_content(chunk_size=4096):
                data.extend(chunk)
                if len(data)>65536:
                    raise EcaptchaError("Phản hồi Ecaptcha vượt giới hạn.")
            result=json.loads(data)
        text=result.get("captcha") if isinstance(result,dict) and result.get("status")=="success" else None
        if not isinstance(text,str) or not re.fullmatch(r"[A-Za-z0-9]{4,12}",text.strip()):
            raise EcaptchaError("Ecaptcha chưa trả về mã hợp lệ.")
        return text.strip()
    except EcaptchaError:
        raise
    except Exception:
        # Provider responses/exceptions can echo credentials; never expose them.
        raise EcaptchaError("Không gọi được Ecaptcha. Bạn có thể nhập CAPTCHA trực tiếp.") from None
    finally:
        if session is not None:
            session.close()
