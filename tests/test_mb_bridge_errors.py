import io
import json
from urllib.error import HTTPError
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
import api.main as api_main
from backend.auth import AuthUser
from integrations import mb_bridge_client as bridge


@pytest.mark.parametrize('kind,status,phrase',[
    ('invalid_or_expired_captcha',400,'CAPTCHA'),('reconnect_required',409,'Phiên MB'),
    ('invalid_account',400,'Tài khoản'),('unknown',503,'Dịch vụ MB'),
])
def test_bridge_returns_actionable_safe_errors(tmp_path,monkeypatch,kind,status,phrase):
    (tmp_path/'.mb_bridge_token').write_text('x'*48)
    monkeypatch.setattr(bridge,'PROJECT',tmp_path);monkeypatch.setenv('ITS_MB_TEST_MODE','false')
    body=json.dumps({'ok':False,'error':kind,'private':'SECRET'}).encode()
    def open_request(*args,**kwargs):raise HTTPError('http://127.0.0.1:5051/captcha',400,'SECRET',{},io.BytesIO(body))
    monkeypatch.setattr(bridge.request,'build_opener',lambda *args:SimpleNamespace(open=open_request))
    with pytest.raises(bridge.MBConnectionError) as caught:bridge.call_worker('/captcha',{})
    assert caught.value.status==status and phrase in str(caught.value)
    assert 'SECRET' not in str(caught.value)


def test_api_preserves_expired_captcha_error_status(monkeypatch):
    def expired(*args,**kwargs):raise bridge.MBConnectionError('CAPTCHA đã hết hạn.',400)
    monkeypatch.setattr(api_main,'call_worker',expired)
    api_main.app.dependency_overrides[api_main.require_bearer_user]=lambda:AuthUser(username='fixture-admin',role='admin')
    try:
        response=TestClient(api_main.app).post('/mb/captcha',json={'id':'a'*32,'text':'TEST'})
        assert response.status_code==400 and 'CAPTCHA' in response.text
    finally:api_main.app.dependency_overrides.clear()
