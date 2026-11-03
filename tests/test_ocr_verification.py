"""Two image readings cannot silently accept disagreement, truncation or timeout."""
import json
from types import SimpleNamespace

from PIL import Image
import pytest

from backend import openai_vision_adapter as adapter, plate_views


def analysis(text='30AB12345', **updates):
    data = dict(plate_visible=True, plate_count=1, plate_text=text,
        readable=True, layout='one_line', vehicle_type='car', image_issues=[],
        uncertain_characters=[], notes='')
    data.update(updates)
    return json.dumps(data)


def setup_reader(monkeypatch, tmp_path, responses, mode='responses'):
    path = tmp_path / 'plate.png'
    Image.new('RGB', (100, 80), 'white').save(path)
    monkeypatch.setattr(adapter, 'active_ai_settings', lambda: SimpleNamespace(
        enabled=True, api_key='fixture-key', base_url='', model='fixture-model', api_mode=mode, timeout=45,
        verify_readings=True))
    monkeypatch.setattr(plate_views, 'encode_crop_views', lambda _, **kw: [])
    pending = iter(responses)
    calls, closed = [], []

    def create(**kwargs):
        calls.append(kwargs)
        result = next(pending)
        if callable(result):
            result = result()
        if isinstance(result, Exception):
            raise result
        if mode == 'chat':
            return SimpleNamespace(choices=[SimpleNamespace(finish_reason='stop', message=SimpleNamespace(content=result, refusal=None))])
        return SimpleNamespace(status='completed', output_text=result)

    client = SimpleNamespace(responses=SimpleNamespace(create=create),
        chat=SimpleNamespace(completions=SimpleNamespace(create=create)), close=lambda: closed.append(True))
    monkeypatch.setattr(adapter, '_build_client', lambda settings: client)
    return path, calls, closed


@pytest.mark.parametrize('mode', ['responses', 'chat'])
def test_agreement_requires_two_fresh_image_requests_without_candidate_hint(monkeypatch, tmp_path, mode):
    path, calls, closed = setup_reader(monkeypatch, tmp_path, [analysis(), analysis()], mode)
    result = adapter.run_openai_vision(str(path))
    assert result['is_usable'] and result['review_required'] and result['confidence'] is None
    assert result['normalized_text'] == '30AB12345'  # Never normalize B to 8.
    assert result['verification']['status'] == 'agreed'
    assert len(calls) == 2 and closed == [True]
    messages = calls[1]['messages' if mode == 'chat' else 'input']
    assert len(messages) == 1 and messages[0]['role'] == 'user'
    assert '30AB12345' not in json.dumps(messages)
    assert adapter.VERIFY_PROMPT == messages[0]['content'][0]['text']


@pytest.mark.parametrize('second', [analysis('30A812345'), analysis('30AB12346'),
    json.dumps(dict(plate_visible=False, plate_count=0, plate_text='', readable=False)),
    '30AB12345', '{}', RuntimeError('private-fixture-key'),
    analysis('30AB12345', uncertain_characters=['B/8']), '[]'])
def test_failed_or_conflicting_verification_never_autofills(monkeypatch, tmp_path, second):
    path, calls, closed = setup_reader(monkeypatch, tmp_path, [analysis(), second])
    result = adapter.run_openai_vision(str(path))
    assert len(calls) == 2 and closed == [True]
    assert not result['is_usable'] and result['review_required']
    assert result['text'] == result['formatted_text'] == result['normalized_text'] == ''
    assert result['raw_text'] == '30AB12345'
    assert 'private' not in json.dumps(result)
    assert result['verification']['status'] in {'disagreed', 'unavailable'}


def test_initial_abstention_is_final_without_another_guess(monkeypatch, tmp_path):
    data = json.loads(analysis()); data.update(plate_count=2)
    path, calls, _ = setup_reader(monkeypatch, tmp_path, [json.dumps(data)])
    result = adapter.run_openai_vision(str(path))
    assert not result['is_usable'] and len(calls) == 1
    assert result['verification']['status'] == 'not_attempted'


@pytest.mark.parametrize('second_elapsed, accepted', [(20, True), (30, False)])
def test_verification_shares_budget_and_rejects_late_results(monkeypatch, tmp_path, second_elapsed, accepted):
    now = [0.0]
    monkeypatch.setattr(adapter.time, 'monotonic', lambda: now[0])
    def first():
        now[0] += 50
        return analysis()
    def second():
        now[0] += second_elapsed
        return analysis()
    path, calls, _ = setup_reader(monkeypatch, tmp_path, [first, second])
    result = adapter.run_openai_vision(str(path))
    assert calls[0]['timeout'] == 45 and calls[1]['timeout'] == 25
    assert result['is_usable'] is accepted
    if not accepted:
        assert result['verification']['status'] == 'timeout'


def test_exhausted_budget_does_not_start_second_request(monkeypatch, tmp_path):
    now = [0.0]
    monkeypatch.setattr(adapter.time, 'monotonic', lambda: now[0])
    def first():
        now[0] = 76
        return analysis()
    path, calls, _ = setup_reader(monkeypatch, tmp_path, [first])
    result = adapter.run_openai_vision(str(path))
    assert not result['is_usable'] and len(calls) == 1


@pytest.mark.parametrize('second, accepted', [(analysis(), True), (analysis('30A812345'), False)])
def test_api_upload_scan_cache_and_confirmation_keep_verification(monkeypatch, tmp_path, second, accepted):
    from fastapi.testclient import TestClient
    import api.main as api_main
    from backend import alpr_service, parking_service, scan_cache, storage
    from backend.auth import AuthUser
    from backend.db import init_db

    path, calls, _ = setup_reader(monkeypatch, tmp_path, [analysis(), second])
    actor = AuthUser(username='verification-fixture', role='operator')
    database = tmp_path / 'parking.db'
    init_db(database)
    monkeypatch.setattr(parking_service, 'DB_PATH', database)
    monkeypatch.setattr(storage, 'UPLOAD_DIR', tmp_path)
    monkeypatch.setattr(alpr_service, '_vision_enabled', lambda **kw: True)
    api_main.app.dependency_overrides[api_main.require_bearer_user] = lambda: actor
    api_main.app.dependency_overrides[api_main.require_read_access] = lambda: actor
    api_main._WRITE_BUCKETS.clear()
    scan_cache._items.clear()
    try:
        with TestClient(api_main.app) as client:
            files = {'file': ('plate.png', path.read_bytes(), 'image/png')}
            scanned = client.post('/ocr', files=files)
            assert scanned.status_code == 200
            payload = scanned.json()
            assert payload['ocr']['is_usable'] is accepted
            assert payload['ocr']['verification']['status'] == ('agreed' if accepted else 'disagreed')
            entered = client.post('/vehicle/entry', files=files, data={
                'scan_token': payload['scan_token'], 'ai_review_confirmed': 'true', 'vehicle_type': 'car'})
            assert entered.status_code == (201 if accepted else 400)
            assert len(calls) == 2  # Confirmation reuses the image-bound scan.
    finally:
        api_main.app.dependency_overrides.clear()
        scan_cache._items.clear()
