"""Speed mode uses one provider call while preserving image/identity safeguards."""

import json
from types import SimpleNamespace

import pytest
from PIL import Image

from backend import alpr_service, config, plate_views
from backend import openai_vision_adapter as adapter


def response(**updates):
    data = dict(
        plate_visible=True,
        plate_count=1,
        plate_text="30AB12345",
        readable=True,
        layout="one_line",
        vehicle_type="car",
        image_issues=[],
        uncertain_characters=[],
        notes="",
    )
    data.update(updates)
    return json.dumps(data)


def configured(monkeypatch, tmp_path, raw, mode="responses"):
    path = tmp_path / "fixture.png"
    Image.new("RGB", (90, 60), "white").save(path)
    settings = SimpleNamespace(
        enabled=True,
        in_auto=True,
        api_key="fixture-only",
        base_url="",
        model="cx/gpt-6.1-sol",
        api_mode=mode,
        timeout=45,
    )
    monkeypatch.setattr(adapter, "OPENAI_VISION_VERIFY", False)
    monkeypatch.setattr(adapter, "active_ai_settings", lambda: settings)
    monkeypatch.setattr(alpr_service, "active_ai_settings", lambda: settings)
    views, calls, closed = [], [], []

    def crops(path, **kwargs):
        views.append(kwargs)
        return [("raw crop", "fixture-image")]

    monkeypatch.setattr(plate_views, "encode_crop_views", crops)

    def create(**kwargs):
        calls.append(kwargs)
        if len(calls) > 1:
            raise AssertionError("Fast mode must not make a second provider call")
        content = raw() if callable(raw) else raw
        if mode == "responses":
            return SimpleNamespace(status="completed", output_text=content)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    finish_reason="stop", message=SimpleNamespace(content=content, refusal=None)
                )
            ]
        )

    client = SimpleNamespace(
        responses=SimpleNamespace(create=create),
        chat=SimpleNamespace(completions=SimpleNamespace(create=create)),
        close=lambda: closed.append(True),
    )
    monkeypatch.setattr(adapter, "_build_client", lambda _: client)
    return path, calls, views, closed


def test_speed_profile_is_default():
    assert config.OPENAI_VISION_VERIFY is False


@pytest.mark.parametrize("mode", ["responses", "chat"])
def test_one_request_low_reasoning_and_two_high_detail_views(monkeypatch, tmp_path, mode):
    path, calls, views, closed = configured(monkeypatch, tmp_path, response(), mode)
    payload = adapter.run_openai_vision(str(path))
    assert payload["is_usable"] and payload["review_required"] and payload["confidence"] is None
    assert payload["normalized_text"] == "30AB12345"
    assert payload["verification"] == {"status": "single_pass", "readings": 1}
    assert payload["ocr_mode"] == "fast" and payload["image_view_count"] == 2
    assert views == [{"include_enhanced": False}] and closed == [True] and len(calls) == 1
    request = calls[0]
    assert request["model"] == "cx/gpt-6.1-sol"
    if mode == "responses":
        assert request["reasoning"] == {"effort": "low"} and request["max_output_tokens"] == 2048
        images = [part for part in request["input"][0]["content"] if part["type"] == "input_image"]
        assert len(images) == 2 and all(part["detail"] == "high" for part in images)
    else:
        assert request["reasoning_effort"] == "low" and request["max_completion_tokens"] == 2048
        images = [part for part in request["messages"][0]["content"] if part["type"] == "image_url"]
        assert len(images) == 2 and all(part["image_url"]["detail"] == "high" for part in images)


@pytest.mark.parametrize(
    "updates",
    [
        dict(plate_count=2),
        dict(readable=False),
        dict(uncertain_characters=["B/8"]),
        dict(plate_text="30AB1234?"),
        dict(plate_visible=False, plate_count=0, plate_text=""),
    ],
)
def test_fast_mode_keeps_abstention_and_never_retries_a_guess(monkeypatch, tmp_path, updates):
    path, calls, _, _ = configured(monkeypatch, tmp_path, response(**updates))
    payload = adapter.run_openai_vision(str(path))
    assert not payload["is_usable"] and payload["review_required"] and payload["text"] == ""
    assert len(calls) == 1


def test_auto_prefers_router_without_waiting_for_other_ocr_engines(monkeypatch, tmp_path):
    path, calls, _, _ = configured(monkeypatch, tmp_path, response())
    monkeypatch.setattr(
        alpr_service,
        "load_fast_alpr",
        lambda *a: pytest.fail("Local OCR must not delay primary vision"),
    )
    monkeypatch.setattr(
        alpr_service, "_run_paddle_ocr", lambda *a: pytest.fail("No fallback after usable vision")
    )
    payload = alpr_service.run_alpr(str(path))
    assert payload["ocr_engine"] == "openai-vision" and payload["ocr_mode"] == "fast"
    assert len(calls) == 1


def test_fast_mode_rejects_result_that_exceeds_its_single_request_budget(monkeypatch, tmp_path):
    now = [0.0]
    monkeypatch.setattr(adapter.time, "monotonic", lambda: now[0])

    def late():
        now[0] = 46
        return response()

    path, calls, _, _ = configured(monkeypatch, tmp_path, late)
    payload = adapter.run_openai_vision(str(path))
    assert calls[0]["timeout"] == 45 and len(calls) == 1
    assert not payload["is_usable"] and payload["verification"]["status"] == "timeout"


def test_raw_only_crop_does_not_generate_a_discarded_contrast_image(monkeypatch, tmp_path):
    path = tmp_path / "plate.png"
    Image.new("RGB", (240, 150), "white").save(path)
    monkeypatch.setattr(
        plate_views.ImageEnhance, "Contrast", lambda *a: pytest.fail("Unused contrast work")
    )
    views = plate_views.crop_views(
        path, finder=lambda _: [(20, 30, 180, 100)], include_enhanced=False
    )
    assert len(views) == 1
