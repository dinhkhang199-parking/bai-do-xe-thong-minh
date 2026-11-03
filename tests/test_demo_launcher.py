import os

import pytest

from scripts.serve import prepare_demo_environment


def test_demo_rejects_existing_non_demo_runtime(tmp_path):
    path = tmp_path / 'parking_system.db'
    path.write_bytes(b'operational-sentinel')
    with pytest.raises(ValueError, match='no demo marker'):
        prepare_demo_environment(tmp_path)
    assert path.read_bytes() == b'operational-sentinel'


def test_demo_removes_inherited_paths_and_credentials(tmp_path, monkeypatch):
    # Restore the entire environment even though the function mutates it directly.
    monkeypatch.setattr(os, 'environ', dict(os.environ))
    os.environ.update({'ITS_DB_NAME': '/live/production.db', 'ITS_OPENAI_API_KEY': 'must-not-survive',
                       'ITS_UPLOAD_DIR': '/live/photos', 'ITS_API_BEARER_ADMIN_TOKEN': 'old-token'})
    prepare_demo_environment(tmp_path)
    assert os.environ['ITS_BASE_DIR'] == str(tmp_path.resolve())
    assert os.environ['ITS_LOAD_ENV'] == 'false'
    assert os.environ['ITS_MB_TEST_MODE'] == 'true'
    assert os.environ['ITS_DEMO_OFFLINE'] == 'true'
    assert len(os.environ['ITS_API_JWT_SECRET']) >= 32
    assert not {'ITS_DB_NAME', 'ITS_UPLOAD_DIR', 'ITS_OPENAI_API_KEY', 'ITS_API_BEARER_ADMIN_TOKEN'} & os.environ.keys()
    prepare_demo_environment(tmp_path)  # Repeat start preserves the marked demo directory.


def test_offline_demo_ocr_never_calls_provider(monkeypatch):
    from backend.app_service import process_plate_image
    monkeypatch.setenv('ITS_DEMO_OFFLINE', 'true')
    def forbidden(*args, **kwargs):
        raise AssertionError('Offline demo attempted OCR')
    result = process_plate_image('any-image.png', alpr_runner=forbidden)
    assert result.plate_text == '' and result.ocr['is_usable'] is False
    assert result.ocr['ocr_engine'] == 'demo-offline'


def test_demo_notice_is_server_owned_and_live_shell_is_unchanged(monkeypatch):
    from fastapi.testclient import TestClient
    from api.main import app
    client = TestClient(app)
    monkeypatch.setenv('ITS_DEMO_OFFLINE', 'true')
    demo = client.get('/')
    assert demo.status_code == 200 and demo.headers['cache-control'] == 'no-store'
    assert demo.text.count('class="runtime-notice"') == 2
    assert 'fonts.googleapis.com' not in demo.text
    monkeypatch.setenv('ITS_DEMO_OFFLINE', 'false')
    live = client.get('/')
    assert live.status_code == 200 and 'class="runtime-notice"' not in live.text
