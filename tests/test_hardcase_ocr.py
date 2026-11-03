import pytest

pytestmark = pytest.mark.ocr


from backend import hardcase_ocr


def test_external_detector_candidate_can_upgrade_partial_baseline():
    baseline = {"text": "66-B1", "confidence": 0.72, "is_usable": False}
    candidate = {
        "text": "66-B1 069.99",
        "confidence": 0.83,
        "is_usable": True,
        "variant": "detector:model.pt",
    }

    assert hardcase_ocr._candidate_is_safe_upgrade(baseline, candidate) is True


def test_non_upgrade_variant_is_rejected():
    baseline = {"text": "66-B1", "confidence": 0.72, "is_usable": False}
    candidate = {
        "text": "66-B1 069.99",
        "confidence": 0.99,
        "is_usable": True,
        "variant": "raw",
    }

    assert hardcase_ocr._candidate_is_safe_upgrade(baseline, candidate) is False


def test_candidate_cannot_change_the_already_read_province_or_series():
    baseline = dict(text="66-B1", confidence=.72, is_usable=False)
    candidate = dict(text="67-B1 069.99", confidence=.99, is_usable=True, variant="detector:model.pt")
    assert not hardcase_ocr._candidate_is_safe_upgrade(baseline, candidate)


def test_hardcase_reuses_baseline_and_abstains_on_conflicting_variants(monkeypatch,tmp_path):
    baseline = dict(text="66-B1", confidence=.72, is_usable=False)
    monkeypatch.setattr(hardcase_ocr,"_load_image",lambda p:None)
    monkeypatch.setattr(hardcase_ocr,"_rotations",lambda im:[])
    monkeypatch.setattr(hardcase_ocr,"_external_detector_paths",lambda p:["one.pt","two.pt"])
    calls=[]
    def run(path,detector_model=None):
        calls.append(detector_model)
        return dict(text="66-B1 069.9"+("9" if detector_model=="one.pt" else "8"),confidence=.99,is_usable=True)
    monkeypatch.setattr(hardcase_ocr,"run_alpr",run)
    result=hardcase_ocr.run_hardcase_alpr("photo.jpg",tmp_path,baseline=baseline)
    assert calls==["one.pt","two.pt"]
    assert result["ocr_disagreement"]
    assert not result["is_usable"]
