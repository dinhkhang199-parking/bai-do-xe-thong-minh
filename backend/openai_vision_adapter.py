import base64
import io
import json
import re
import time
from pathlib import Path

from PIL import Image, ImageOps

from backend.config import (
    ENABLE_OPENAI_VISION,
    OPENAI_API_KEY,
    OPENAI_API_MODE,
    OPENAI_BASE_URL,
    OPENAI_TIMEOUT_SECONDS,
    OPENAI_VISION_MODEL,
)
from backend.logging_config import get_logger
from backend.plate_format import (
    classify_plate_type,
    format_confirmed_plate,
    normalize_generic_plate_text,
)

logger = get_logger(__name__)

try:
    from openai import OpenAI
except Exception:
    OpenAI = None

MAX_IMAGE_BYTES = 12 * 1024 * 1024
MAX_IMAGE_PIXELS = 20_000_000
MAX_IMAGE_DIMENSION = 2560
MAX_READING_BUDGET_SECONDS = 75.0

PLATE_ANALYSIS_SCHEMA = {
    "type": "object",
    "properties": {
        "plate_visible": {"type": "boolean"},
        "plate_count": {"type": "integer"},
        "plate_text": {"type": "string"},
        "readable": {"type": "boolean"},
        "layout": {"type": "string"},
        "vehicle_type": {"type": "string"},
        "image_issues": {"type": "array", "items": {"type": "string"}},
        "uncertain_characters": {"type": "array", "items": {"type": "string"}},
        "notes": {"type": "string"},
    },
    "required": [
        "plate_visible",
        "plate_count",
        "plate_text",
        "readable",
        "layout",
        "vehicle_type",
        "image_issues",
        "uncertain_characters",
        "notes",
    ],
    "additionalProperties": False,
}

PLATE_PROMPT = (
    "Đọc biển số xe trong ảnh. Trả về đúng một đối tượng JSON với các trường: "
    "plate_visible (boolean), plate_count (số nguyên, số lượng biển nhìn thấy), "
    "plate_text (chuỗi chỉ chứa ký tự biển số, ví dụ 66B106999; để rỗng nếu không đọc được), "
    "readable (boolean), layout (chuỗi 'one_line' hoặc 'two_line'), "
    "vehicle_type (chuỗi 'motorcycle', 'car' hoặc 'unknown'), "
    "image_issues (mảng chuỗi, ví dụ multiple_plates, blurry, glare), "
    "uncertain_characters (mảng chuỗi mô tả ký tự không chắc chắn), notes (chuỗi). "
    "Ảnh đầu tiên là toàn cảnh; các ảnh sau (nếu có) chỉ là những góc nhìn cắt/phóng to từ cùng ảnh đó. "
    "Đếm số biển số vật lý trong ảnh gốc, không đếm các ảnh cắt như xe khác. "
    "Đối chiếu từng hàng và từng ký tự giữa ảnh gốc và ảnh cắt; chú ý B/8, O/0, I/1, S/5, Z/2. "
    "Giữ nguyên chữ và số thực sự nhìn thấy; không tự đổi để ép khớp định dạng, không tự thêm số sê-ri. "
    "Ảnh mờ, nghiêng, lóa hoặc thiếu sáng: dùng các góc nhìn để kiểm tra, ghi rõ vị trí ký tự còn nghi ngờ. "
    "Nếu vẫn không xác định được một ký tự, đặt readable=false và liệt kê uncertain_characters, không đoán. "
    "Chỉ trả JSON theo các trường yêu cầu, không giải thích ngoài JSON."
)

# A fresh request receives images only, never the first reading or a ticket list.
# Agreement is additional evidence, not a calibrated probability of correctness.
VERIFY_PROMPT = PLATE_PROMPT + (
    " Đây là lượt kiểm tra từng ký tự: đọc riêng hàng trên và hàng dưới từ ảnh, "
    "rồi ghép theo thứ tự trái sang phải, trên xuống dưới. Kiểm tra cả ký tự đầu/cuối "
    "và số ký tự mỗi hàng. Không suy ra ký tự bị che từ mẫu biển thường gặp. "
    "Đặc biệt kiểm tra xem ảnh toàn cảnh có biển thứ hai dù nhỏ hoặc mờ không."
)


def _redact_secrets(message) -> str:
    text = str(message)
    settings = active_ai_settings()
    for secret in (OPENAI_API_KEY, OPENAI_BASE_URL,
                   getattr(settings, "api_key", ""), getattr(settings, "base_url", "")):
        if secret:
            text = text.replace(secret, "[redacted]")
    text = re.sub(r"https?://[^\s\"']+", "[redacted-url]", text)
    return text


def _looks_like_plate_text(text: str) -> bool:
    normalized = normalize_generic_plate_text(text)
    if len(normalized) < 6:
        return False
    if not any(ch.isdigit() for ch in normalized):
        return False
    if not any(ch.isalpha() for ch in normalized):
        return False
    return True


def _format_ai_plate(plate_text: str, vehicle_type: str, layout: str) -> str:
    return format_confirmed_plate(plate_text, vehicle_type=vehicle_type)


def _is_full_ai_plate(formatted: str) -> bool:
    if not formatted:
        return False
    return bool(format_confirmed_plate(formatted))


def _ai_payload(*, text: str, raw_text: str, is_usable: bool, review_required: bool, ai_status: str, ai_analysis: dict | None, quality_note: str | None = None) -> dict:
    normalized = normalize_generic_plate_text(text or raw_text)
    return {
        "text": text,
        "raw_text": raw_text,
        "confidence": None,
        "is_usable": is_usable,
        "review_required": review_required,
        "ai_status": ai_status,
        "ai_analysis": ai_analysis,
        "normalized_text": normalized,
        "formatted_text": text,
        "plate_type": classify_plate_type(text) if text else "unknown",
        "quality_note": quality_note,
    }


def _payload_from_structured(data: dict) -> dict:
    for key in ("plate_visible", "readable"):
        if key not in data or not isinstance(data[key], bool):
            raise ValueError("AI output has invalid boolean field")
    if "plate_count" not in data or not isinstance(data["plate_count"], int) or isinstance(data["plate_count"], bool):
        raise ValueError("AI output has invalid plate_count")
    if not isinstance(data.get("plate_text"), str):
        raise ValueError("AI output has invalid plate_text")
    if not isinstance(data.get("layout", ""), str) or not isinstance(data.get("vehicle_type", ""), str) or not isinstance(data.get("notes", ""), str):
        raise ValueError("AI output has invalid string field")
    if not isinstance(data.get("image_issues", []), list) or not all(isinstance(i, str) for i in data.get("image_issues", [])):
        raise ValueError("AI output has invalid image_issues")
    if not isinstance(data.get("uncertain_characters", []), list) or not all(isinstance(i, str) for i in data.get("uncertain_characters", [])):
        raise ValueError("AI output has invalid uncertain_characters")

    ai_analysis = {
        "plate_visible": data.get("plate_visible"),
        "plate_count": data.get("plate_count"),
        "plate_text": data.get("plate_text", ""),
        "readable": data.get("readable", True),
        "layout": data.get("layout", ""),
        "vehicle_type": data.get("vehicle_type", ""),
        "image_issues": data.get("image_issues", []),
        "uncertain_characters": data.get("uncertain_characters", []),
        "notes": data.get("notes", ""),
    }

    plate_text = data.get("plate_text", "").strip()
    plate_visible = data["plate_visible"]
    plate_count = data["plate_count"]
    readable = data["readable"]

    if not plate_visible or plate_count != 1 or "multiple_plates" in ai_analysis["image_issues"]:
        return _ai_payload(text="", raw_text=plate_text, is_usable=False, review_required=True, ai_status="analyzed", ai_analysis=ai_analysis, quality_note="Không xác định được đúng một biển số")
    if not readable or "?" in plate_text or ai_analysis["uncertain_characters"]:
        return _ai_payload(text="", raw_text=plate_text, is_usable=False, review_required=True, ai_status="analyzed", ai_analysis=ai_analysis, quality_note="Ký tự biển số chưa đủ rõ, cần đối chiếu ảnh")

    formatted = _format_ai_plate(plate_text, ai_analysis["vehicle_type"], ai_analysis["layout"])
    is_usable = _is_full_ai_plate(formatted)
    return _ai_payload(
        text=formatted if is_usable else "",
        raw_text=plate_text,
        is_usable=is_usable,
        review_required=True,
        ai_status="analyzed",
        ai_analysis=ai_analysis,
        quality_note="Biển số hợp lệ, cần đối chiếu ảnh" if is_usable else "Kết quả AI chưa đủ tin cậy",
    )


def _payload_from_legacy(text: str) -> dict:
    formatted = format_confirmed_plate(text)
    return _ai_payload(
        text=formatted,
        raw_text=text,
        is_usable=False,
        review_required=True,
        ai_status="legacy_response",
        ai_analysis=None,
        quality_note="Model trả về chuỗi cũ, cần xác nhận thủ công",
    )


def parse_plate_analysis(raw) -> dict:
    text = (raw or "").strip()
    if text.startswith("{") or text.startswith("["):
        try:
            parsed = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            raise ValueError("AI output is not valid JSON") from None
        if not isinstance(parsed, dict):
            raise ValueError("AI output must be a JSON object")
        return _payload_from_structured(parsed)
    if not _looks_like_plate_text(text):
        raise ValueError("AI did not return a valid plate")
    return _payload_from_legacy(text)


def _encode_image_jpeg(image_path: str) -> str:
    path = Path(image_path)
    if not path.exists():
        raise ValueError("Image file not found")
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise ValueError("Image unreadable") from exc
    if size == 0 or size > MAX_IMAGE_BYTES:
        raise ValueError("Image size invalid")
    try:
        with Image.open(path) as image:
            image = ImageOps.exif_transpose(image)
            width, height = image.size
            if width * height > MAX_IMAGE_PIXELS:
                raise ValueError("Image too large")
            longest = max(width, height)
            if longest > MAX_IMAGE_DIMENSION:
                scale = MAX_IMAGE_DIMENSION / float(longest)
                image = image.resize((max(1, int(width * scale)), max(1, int(height * scale))), Image.LANCZOS)
            if image.mode not in ("RGB", "L"):
                image = image.convert("RGB")
            buffer = io.BytesIO()
            image.save(buffer, format="JPEG", quality=90)
            return base64.b64encode(buffer.getvalue()).decode("ascii")
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("Invalid image") from exc


def _build_client(settings=None):
    kwargs = {"api_key": getattr(settings, "api_key", OPENAI_API_KEY), "max_retries": 0}
    base_url = getattr(settings, "base_url", OPENAI_BASE_URL)
    if base_url:
        kwargs["base_url"] = base_url
    return OpenAI(**kwargs)


def _vision_content(image_b64,chat=False, prompt=PLATE_PROMPT):
    views=image_b64 if isinstance(image_b64,list) else [("Ảnh gốc toàn cảnh",image_b64)]
    content=[{"type":"text" if chat else "input_text","text":prompt}]
    for index,(label,encoded) in enumerate(views[:3]):
        if index:
            content.append({"type":"text" if chat else "input_text","text":label})
        if chat:
            content.append({"type":"image_url","image_url":{"url":f"data:image/jpeg;base64,{encoded}","detail":"high"}})
        else:
            content.append({"type":"input_image","image_url":f"data:image/jpeg;base64,{encoded}","detail":"high"})
    return content


def _responses_request(client, image_b64, settings=None, *, prompt=PLATE_PROMPT, timeout=None) -> str:
    model=getattr(settings,"model",OPENAI_VISION_MODEL)
    options={"reasoning":{"effort":"high"},"max_output_tokens":6144} if model.rsplit("/",1)[-1]=="gpt-6.1-sol" else {}
    response = client.responses.create(
        model=model,
        store=False,
        text={
            "format": {
                "type": "json_schema",
                "name": "plate_analysis",
                "strict": True,
                "schema": PLATE_ANALYSIS_SCHEMA,
            }
        },
        input=[
            {
                "role": "user",
                "content": _vision_content(image_b64, prompt=prompt),
            }
        ],
        timeout=timeout if timeout is not None else getattr(settings, "timeout", OPENAI_TIMEOUT_SECONDS),
        **options,
    )
    status = getattr(response, "status", None)
    if status is not None and status != "completed":
        raise RuntimeError("AI response incomplete")
    raw_text = (getattr(response, "output_text", "") or "").strip()
    if not raw_text:
        raise RuntimeError("AI response empty")
    return raw_text


def _chat_request(client, image_b64: str, settings=None, *, prompt=PLATE_PROMPT, timeout=None) -> str:
    model=getattr(settings,"model",OPENAI_VISION_MODEL)
    options={"reasoning_effort":"high","max_completion_tokens":6144} if model.rsplit("/",1)[-1]=="gpt-6.1-sol" else {}
    response = client.chat.completions.create(
        model=model,
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "plate_analysis",
                "strict": True,
                "schema": PLATE_ANALYSIS_SCHEMA,
            },
        },
        messages=[
            {
                "role": "user",
                "content": _vision_content(image_b64,chat=True, prompt=prompt),
            }
        ],
        timeout=timeout if timeout is not None else getattr(settings, "timeout", OPENAI_TIMEOUT_SECONDS),
        **options,
    )
    choices = getattr(response, "choices", None) or []
    if not choices:
        raise RuntimeError("AI response empty")
    choice = choices[0]
    message = getattr(choice, "message", None)
    if message is None or getattr(message, "refusal", None):
        raise RuntimeError("AI response refused")
    if getattr(choice, "finish_reason", None) != "stop":
        raise RuntimeError("AI response incomplete")
    raw_text = (getattr(message, "content", "") or "").strip()
    if not raw_text:
        raise RuntimeError("AI response empty")
    return raw_text


def run_openai_vision(image_path: str) -> dict:
    settings = active_ai_settings()
    if not getattr(settings, "enabled", ENABLE_OPENAI_VISION):
        raise RuntimeError("OpenAI vision is disabled")
    if OpenAI is None:
        raise RuntimeError("openai sdk is not installed")
    if not getattr(settings, "api_key", OPENAI_API_KEY):
        raise RuntimeError("OPENAI_API_KEY is not configured")

    started = time.monotonic()
    request_timeout = max(0.1, min(float(getattr(settings, "timeout", OPENAI_TIMEOUT_SECONDS)), MAX_READING_BUDGET_SECONDS))
    deadline = started + min(request_timeout * 2, MAX_READING_BUDGET_SECONDS)
    image_b64 = _encode_image_jpeg(image_path)
    from backend.plate_views import encode_crop_views
    crops=encode_crop_views(image_path)
    views=[("Ảnh gốc toàn cảnh",image_b64),*crops] if crops else image_b64

    client = _build_client(settings)
    try:
        request = _chat_request if getattr(settings, "api_mode", OPENAI_API_MODE) == "chat" else _responses_request
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RuntimeError("OCR image preparation timed out")
        raw_text = request(client, views, settings, timeout=min(request_timeout, remaining))
        payload = parse_plate_analysis(raw_text)
        payload["verification"] = {"status": "not_attempted", "readings": 1}
        # An abstention is final. Never repeatedly prompt an unreadable image
        # until the model eventually invents an acceptable answer.
        if payload["is_usable"]:
            remaining = deadline - time.monotonic()
            readings = 1
            try:
                if remaining <= 0:
                    raise TimeoutError("No verification budget remains")
                readings = 2
                check = parse_plate_analysis(request(client, views, settings,
                    prompt=VERIFY_PROMPT, timeout=min(request_timeout, remaining)))
                first_identity = normalize_generic_plate_text(payload["text"])
                second_identity = normalize_generic_plate_text(check["text"])
                agreed = bool(check["is_usable"] and first_identity == second_identity)
                payload["verification"] = {"status": "agreed" if agreed else "disagreed",
                    "readings": 2, "analysis": check["ai_analysis"]}
                if not agreed:
                    payload.update(text="", formatted_text="", normalized_text="", is_usable=False,
                        ocr_disagreement=True, quality_note="Hai lượt đọc không thống nhất; cần đối chiếu ảnh hoặc chụp lại.")
            except Exception:
                # Verification failures cannot turn a single reading into an
                # accepted result or trigger a local fallback that hides doubt.
                payload["verification"] = {"status": "unavailable", "readings": readings}
                payload.update(text="", formatted_text="", normalized_text="", is_usable=False,
                    quality_note="Chưa kiểm chứng được kết quả OCR; cần đối chiếu ảnh hoặc quét lại.")
            if time.monotonic() > deadline:
                payload["verification"]["status"] = "timeout"
                payload.update(text="", formatted_text="", normalized_text="", is_usable=False,
                    quality_note="OCR quá thời gian kiểm chứng; cần đối chiếu ảnh hoặc quét lại.")
            if not payload["is_usable"] and payload.get("ai_analysis"):
                payload["ai_analysis"] = dict(payload["ai_analysis"], notes=payload["quality_note"])
    except Exception as exc:
        raise RuntimeError(_redact_secrets(exc)) from None
    finally:
        try:
            client.close()
        except Exception:
            pass

    payload["ocr_engine"] = "openai-vision"
    payload["engine"] = "openai-vision"
    payload["model"] = getattr(settings,"model",OPENAI_VISION_MODEL)
    payload["image_view_count"] = 1+len(crops)
    return payload


def active_ai_settings():
    from backend import ai_settings

    return ai_settings.runtime_ai_settings()


def vision_configuration_status() -> dict:
    settings = active_ai_settings()
    if settings is not None:
        enabled = settings.enabled
        api_key = settings.api_key
        model = settings.model
        api_mode = settings.api_mode
    else:
        enabled = ENABLE_OPENAI_VISION
        api_key = OPENAI_API_KEY
        model = OPENAI_VISION_MODEL
        api_mode = OPENAI_API_MODE

    missing = []
    if not enabled:
        missing.append("ITS_ENABLE_OPENAI_VISION")
    if not api_key:
        missing.append("ITS_OPENAI_API_KEY")
    if not model:
        missing.append("ITS_OPENAI_VISION_MODEL")

    return {
        "configured": bool(enabled and api_key and model),
        "connection_verified": False,
        "api_mode": api_mode,
        "model": model,
        "missing": missing,
        "sdk_available": OpenAI is not None,
    }


def probe_vision_connection() -> dict:
    settings = active_ai_settings()
    if OpenAI is None:
        return {"connected": False, "model_listed": False, "analysis_verified": False, "message": "openai sdk is not installed"}
    if not getattr(settings, "api_key", OPENAI_API_KEY):
        return {"connected": False, "model_listed": False, "analysis_verified": False, "message": "OPENAI_API_KEY is not configured"}

    client = None
    try:
        client = _build_client(settings)
        model_list = client.models.list()
        model_ids = {getattr(item, "id", "") for item in getattr(model_list, "data", [])}
        return {"connected": True, "model_listed": getattr(settings, "model", OPENAI_VISION_MODEL) in model_ids, "analysis_verified": False}
    except Exception:
        return {"connected": False, "model_listed": False, "analysis_verified": False, "message": "Không thể kết nối provider AI"}
    finally:
        if client is not None:
            try:
                client.close()
            except Exception:
                pass
