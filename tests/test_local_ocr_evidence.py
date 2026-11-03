from types import SimpleNamespace

import numpy as np
import pytest

from backend import alpr_service as alpr, ocr_quality, plate_views


def helper():
    return object.__new__(alpr.EasyOCRVNOCR)


def test_dedup_keeps_b_8_as_different_identities(monkeypatch):
    ocr = helper()
    image = np.zeros((20, 60, 3), dtype=np.uint8)
    responses = iter([[([], '30AB12345', .95)], [([], '30A812345', .94)]])
    ocr.reader = SimpleNamespace(readtext=lambda *a, **kw: next(responses))
    monkeypatch.setattr(ocr, '_enhance', lambda *a, **kw: [('raw', image), ('contrast', image)])
    readings = ocr._ocr_candidates(image)
    assert {text for text, _ in readings} == {'30AB12345', '30A812345'}
    with pytest.raises(alpr._ConflictingReadings):
        alpr._select_local_reading(readings)


def test_weak_bottom_row_cannot_receive_a_format_confidence_bonus():
    text, confidence = helper()._combine_from_candidates([('66-B1', .99)], [('069.99', .54)])
    assert text == '66-B1 069.99' and confidence == .54
    assert not ocr_quality.assess_ocr_quality(text, confidence).is_usable


@pytest.mark.parametrize('top,bottom', [('6681', '06999'), ('66B1', 'O6999'), ('66B1', '069?99'), ('66?B1', '06999')])
def test_combining_rows_never_repairs_or_discards_uncertain_characters(top, bottom):
    assert helper()._combine_from_candidates([(top, .99)], [(bottom, .99)]) == ('', 0.0)


def test_multiple_complete_row_combinations_require_review():
    with pytest.raises(alpr._ConflictingReadings):
        helper()._combine_from_candidates([('30AB', .95), ('30A8', .96)], [('12345', .99)])


@pytest.mark.parametrize('first', ['65-D1 123.45', '65-D1'])
def test_deep_read_cannot_override_different_identity_or_prefix(monkeypatch, first):
    ocr = helper()
    monkeypatch.setattr(alpr, 'FAST_MODE', True)
    monkeypatch.setattr(alpr, 'ENABLE_DEEP_OCR_RETRY', True)
    monkeypatch.setattr(ocr, '_predict_core', lambda image, force_full=False:
        alpr.OcrResult(text='66-D1 123.45' if force_full else first, confidence=.99 if force_full else .7))
    result = ocr.predict(np.zeros((100, 100, 3)))
    assert result.ocr_disagreement and result.text == ''
    payload = alpr._build_candidate_payload(SimpleNamespace(ocr=result, detection=None))
    assert payload['ocr_disagreement'] and not payload['is_usable']


def test_wide_plate_keeps_raw_invalid_character_for_review(monkeypatch):
    ocr = helper()
    monkeypatch.setattr(ocr, '_ocr_best', lambda *a, **kw: ('668106999', .99))
    result = ocr._predict_core(np.zeros((40, 200, 3)))
    assert result.text == '668106999'
    payload = alpr._build_candidate_payload(SimpleNamespace(ocr=result, detection=None))
    assert payload['raw_text'] == payload['text'] == '668106999'
    assert not payload['is_usable']


def test_paddle_cannot_repair_invalid_identity_before_validation(monkeypatch):
    monkeypatch.setattr(alpr, '_get_paddle_reader', lambda: SimpleNamespace(
        ocr=lambda *a, **kw: [{'rec_texts': ['668106999'], 'rec_scores': [.99]}]))
    payload = alpr._run_paddle_ocr('fixture.png', 'fixture', 'fixture.png')
    assert payload['raw_text'] == payload['text'] == '668106999'
    assert not payload['is_usable']


def test_local_conflict_cannot_disappear_during_fusion():
    conflict = dict(text='', is_usable=False, ocr_disagreement=True, review_required=True)
    result = alpr._fuse_ocr_candidates([conflict, dict(text='66B106999', confidence=.99)], 'fixture', 'fixture.png')
    assert result == conflict


def test_local_conflict_blocks_other_fallback_engines(monkeypatch):
    conflict = alpr._LocalOcrConflict(candidates=(('30AB12345', .9), ('30A812345', .9)))
    monkeypatch.setattr(alpr, '_vision_enabled', lambda **kw: False)
    monkeypatch.setattr(alpr, '_load_runtime_frame', lambda _: np.zeros((60, 100, 3)))
    monkeypatch.setattr(alpr, 'save_annotated_image', lambda *a: 'fixture.png')
    monkeypatch.setattr(alpr, 'load_fast_alpr', lambda *a: SimpleNamespace(draw_predictions=lambda frame:
        SimpleNamespace(image=frame, results=[SimpleNamespace(ocr=conflict, detection=None)])))
    monkeypatch.setattr(alpr, '_run_paddle_ocr', lambda *a: pytest.fail('Do not hide local disagreement'))
    result = alpr.run_alpr('fixture.png')
    assert result['ocr_disagreement'] and not result['is_usable']


def test_quality_identity_preserves_letters_and_invalid_raw_text():
    assert ocr_quality.assess_ocr_quality('30-AB 123.45', .99).normalized_text == '30AB12345'
    assert ocr_quality.assess_ocr_quality('66-B1 069.G9', .99).formatted_text == '66-B1 069.G9'


def test_tile_duplicates_are_merged_but_neighbor_plates_remain():
    assert plate_views._merge_duplicate_boxes([(10, 10, 90, 60), (12, 12, 88, 58), (105, 10, 185, 60)]) == [
        (10, 10, 90, 60), (105, 10, 185, 60)]


def test_large_image_uses_bounded_overlapping_tiles_and_global_coordinates(monkeypatch):
    from PIL import Image
    calls = []
    def predict(frame):
        calls.append(frame.shape[:2])
        if len(calls) == 5:
            return [SimpleNamespace(confidence=.95, bounding_box=SimpleNamespace(clamp=lambda w, h: (20, 30, 180, 100)))]
        return []
    monkeypatch.setattr(plate_views, '_detector', lambda: SimpleNamespace(predict=predict))
    boxes = plate_views._find_boxes(Image.new('RGB', (1920, 1080)))
    assert len(calls) == 5
    assert calls == [(1080, 1920)] + [(648, 1152)] * 4
    assert boxes == [(788, 462, 948, 532)]
