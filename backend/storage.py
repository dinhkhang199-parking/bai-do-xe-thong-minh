import base64
import re
from datetime import datetime
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from PIL import Image

from backend.config import UPLOAD_DIR
from backend.validators import (
    MAX_UPLOAD_SIZE_BYTES,
    ValidationError,
    validate_image_extension,
    validate_upload_size,
)

try:
    import cv2
except Exception:
    cv2 = None

MAX_UPLOAD_PIXELS = 20_000_000


def _timestamped_path(prefix: str, suffix: str) -> Path:
    safe_prefix = re.sub(r"[^A-Za-z0-9_-]+", "_", (prefix or "file").strip())
    safe_prefix = safe_prefix[:20].strip("_") or "file"
    return (
        UPLOAD_DIR
        / f"{safe_prefix}_{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid4().hex[:16]}{suffix}"
    )


def _maybe_resize_for_ocr(buffer: bytes, suffix: str) -> bytes:
    """Validate pixels but preserve original evidence and small-plate detail.

    OCR adapters size their own views; shrinking evidence here destroys detail
    before the detector can crop a small plate from a large camera frame.
    """
    try:
        with Image.open(BytesIO(buffer)) as image:
            if image.format not in {"JPEG", "PNG", "WEBP"}:
                raise ValidationError("Unsupported image format")
            if image.width * image.height > MAX_UPLOAD_PIXELS:
                raise ValidationError("Image exceeds 20 million pixels")
            if getattr(image, "n_frames", 1) != 1:
                raise ValidationError("Animated images are not supported")
            image.verify()
        with Image.open(BytesIO(buffer)) as image:
            image.load()
    except ValidationError:
        raise
    except Exception as exc:
        raise ValidationError("Invalid image: cannot decode complete pixels") from exc
    return buffer


def save_uploaded_file(uploaded_file, prefix: str):
    # Streamlit UploadedFile uses .name; FastAPI UploadFile uses .filename
    filename = getattr(uploaded_file, "name", None) or getattr(uploaded_file, "filename", "") or ""
    suffix = validate_image_extension(filename)
    # Streamlit UploadedFile has .getbuffer(); FastAPI UploadFile uses .file.read()
    if hasattr(uploaded_file, "getbuffer"):
        buffer = bytes(uploaded_file.getbuffer())
    else:
        file_obj = getattr(uploaded_file, "file", uploaded_file)
        buffer = file_obj.read(MAX_UPLOAD_SIZE_BYTES + 1)
    validate_upload_size(len(buffer))
    output_path = _timestamped_path(prefix, suffix)
    optimized_buffer = _maybe_resize_for_ocr(buffer, suffix)
    output_path.write_bytes(optimized_buffer)
    return str(output_path)


def save_annotated_image(cv2_module, image, prefix: str):
    output_path = _timestamped_path(prefix, ".jpg")
    if not cv2_module.imwrite(str(output_path), image):
        raise OSError("Cannot save annotated image")
    return str(output_path)


def image_to_base64(path: Path):
    if not path.exists():
        return ""
    return base64.b64encode(path.read_bytes()).decode("utf-8")
