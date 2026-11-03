"""Identity, ambiguity and failure regressions for the entry/exit OCR boundary."""
import json
from types import SimpleNamespace

import numpy as np
import pytest

from backend import alpr_service as alpr, app_service, parking_service, storage
from backend.ocr_quality import clamp_confidence, assess_ocr_quality
from backend.openai_vision_adapter import parse_plate_analysis
from backend.plate_format import normalize_generic_plate_text
from backend.validators import ValidationError, validate_plate_text


def analysis(text):
    return json.dumps(dict(plate_visible=True, plate_count=1, plate_text=text, readable=True,
        layout="two_line", vehicle_type="motorcycle", image_issues=[], uncertain_characters=[], notes=""))


@pytest.mark.parametrize("text", ["66B1069G9", "66-B1 069.99 EXTRA", "ABC12345", "66B1069?99", "６６B106999"])
def test_confirmation_never_repairs_or_discards_identity(text):
    with pytest.raises(ValidationError):
        validate_plate_text(text)


@pytest.mark.parametrize("text", ["66B1069G9", "ABC12345", "66B1069?99", "６６B106999"])
def test_structured_ai_never_repairs_or_discards_identity(text):
    result = parse_plate_analysis(analysis(text))
    assert not result["is_usable"]
    assert result["text"] == ""
    assert result["raw_text"] == text


@pytest.mark.parametrize("text", ["65X17953", "94E105025", "66B106999", "66FH9296", "30AB12345", "30-A8 123.45", "51-A 123.45", "66B1\n069.99"])
def test_valid_confirmation_preserves_every_identity_character(text):
    assert normalize_generic_plate_text(validate_plate_text(text)) == normalize_generic_plate_text(text)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf"), "invalid"])
def test_invalid_confidence_is_never_strong(value):
    assert clamp_confidence(value) == 0
    assert not assess_ocr_quality("66-B1 069.99", value).is_usable
    assert parking_service._safe_confidence(value) == 0


def test_none_confidence_remains_available_for_human_review():
    assert parking_service._safe_confidence(None) is None


def test_unusable_local_result_always_requires_confirmation():
    payload = dict(text="66-B1 069.99", confidence=.9, is_usable=False)
    processed = app_service.process_plate_image("photo.jpg", use_hardcase=False, alpr_runner=lambda *a, **kw: payload)
    assert processed.ocr["review_required"]


def test_internal_typeerror_does_not_repeat_ocr():
    calls = []
    def broken(path, detector_model=None, ocr_engine="auto"):
        calls.append(path)
        raise TypeError("internal OCR defect")
    with pytest.raises(TypeError, match="internal OCR defect"):
        app_service.process_plate_image("photo.jpg", alpr_runner=broken)
    assert calls == ["photo.jpg"]


def test_fusion_preserves_b_8_disagreement():
    result = alpr._fuse_ocr_candidates([
        dict(text="30-AB 123.45", confidence=.99, ocr_engine="fast-alpr-easyocr"),
        dict(text="30-A8 123.45", confidence=.98, ocr_engine="openai-vision"),
    ], "test", "photo.jpg")
    assert result["vision_disagreement"]
    assert result["review_required"]
    assert result["ocr_disagreement"]
    assert not result["is_usable"]


def test_local_multi_plate_abstains_even_if_only_one_has_ocr(monkeypatch):
    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    results = [SimpleNamespace(ocr=SimpleNamespace(text="66B106999", confidence=.99), detection=None),
               SimpleNamespace(ocr=None, detection=None)]
    monkeypatch.setattr(alpr, "_vision_enabled", lambda **kw: False)
    monkeypatch.setattr(alpr, "_load_runtime_frame", lambda path: frame)
    monkeypatch.setattr(alpr, "load_fast_alpr", lambda *a: SimpleNamespace(draw_predictions=lambda f: SimpleNamespace(image=f, results=results)))
    monkeypatch.setattr(alpr, "save_annotated_image", lambda *a: "photo.jpg")
    result = alpr.run_alpr("photo.jpg", ocr_engine="easyocr")
    assert result["text"] == ""
    assert not result["is_usable"]
    assert result["plate_count"] == 2
    assert result["review_required"]


def test_hardcase_cannot_override_local_ambiguity(monkeypatch):
    from backend import hardcase_ocr
    monkeypatch.setattr(hardcase_ocr, "run_hardcase_alpr", lambda *a: pytest.fail("Must retain ambiguity"))
    payload = dict(text="", is_usable=False, ambiguous=True, review_required=True)
    result = app_service.process_plate_image("photo.jpg", use_hardcase=True, alpr_runner=lambda *a, **kw: payload)
    assert result.plate_text == ""


def test_ticket_ids_keep_more_than_sixteen_random_bits(monkeypatch):
    from uuid import UUID
    monkeypatch.setattr(parking_service, "uuid4", lambda: UUID("12345678-1234-4234-8234-123456789abc"))
    assert parking_service.create_ticket_id().endswith("1234567812344234")


def test_corrupt_photo_is_rejected_before_writing(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "UPLOAD_DIR", tmp_path)
    upload = SimpleNamespace(name="photo.jpg", getbuffer=lambda: b"not an image")
    with pytest.raises(ValidationError, match="[Ii]mage|[Ảả]nh"):
        storage.save_uploaded_file(upload, "entry")
    assert not list(tmp_path.iterdir())


def test_fusion_cannot_discard_multi_plate_abstention():
    result = alpr._fuse_ocr_candidates([
        dict(text="66-B1 069.99", confidence=.99, is_usable=True),
        dict(text="", is_usable=False, ambiguous=True, review_required=True),
    ], "test", "photo.jpg")
    assert result["text"] == ""
    assert result["ambiguous"]


def test_pixel_limit_is_checked_before_decoding(tmp_path, monkeypatch):
    from io import BytesIO
    from PIL import Image
    monkeypatch.setattr(storage, "UPLOAD_DIR", tmp_path)
    monkeypatch.setattr(storage, "MAX_UPLOAD_PIXELS", 100)
    stream = BytesIO()
    Image.new("RGB", (11, 10)).save(stream, format="PNG")
    with pytest.raises(ValidationError, match="pixels"):
        storage.save_uploaded_file(SimpleNamespace(name="photo.png", getbuffer=stream.getvalue), "entry")
    assert not list(tmp_path.iterdir())


def test_truncated_photo_is_not_retained_as_evidence(tmp_path, monkeypatch):
    from io import BytesIO
    from PIL import Image
    monkeypatch.setattr(storage, "UPLOAD_DIR", tmp_path)
    stream = BytesIO()
    Image.new("RGB", (90, 60)).save(stream, format="JPEG")
    with pytest.raises(ValidationError):
        storage.save_uploaded_file(SimpleNamespace(name="photo.jpg", getbuffer=lambda: stream.getvalue()[:-100]), "entry")
    assert not list(tmp_path.iterdir())
