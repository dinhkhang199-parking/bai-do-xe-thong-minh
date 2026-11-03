import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys


def test_direct_pytest_config_ignores_inherited_absolute_database_and_provider(tmp_path):
    root=Path(__file__).resolve().parents[1]
    protected=tmp_path/'operational-sentinel.db'
    with sqlite3.connect(protected) as conn:
        conn.execute('CREATE TABLE sentinel(value TEXT)')
        conn.execute("INSERT INTO sentinel VALUES('unchanged')")
    original=protected.read_bytes()
    env={**os.environ,'ITS_DB_NAME':str(protected),'ITS_UPLOAD_DIR':str(tmp_path/'wrong-uploads'),
         'ITS_ENABLE_OPENAI_VISION':'true','ITS_ENABLE_VISION_IN_AUTO':'true',
         'ITS_OPENAI_API_KEY':'fake-must-not-reach-provider','ITS_API_BEARER_ADMIN_TOKEN':'fake-inherited-token'}
    code="""
import json,runpy
scope=runpy.run_path('tests/conftest.py')
scope['pytest_sessionstart'](None)
from backend import config
print(json.dumps({'db':str(config.DB_PATH),'upload':str(config.UPLOAD_DIR),'vision':config.ENABLE_OPENAI_VISION,
                  'key':bool(config.OPENAI_API_KEY),'static_admin':bool(config.API_BEARER_TOKENS['admin'])}))
"""
    result=subprocess.run([sys.executable,'-c',code],cwd=root,env=env,capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stderr
    data=json.loads(result.stdout)
    assert data['db']!=str(protected) and data['upload']!=env['ITS_UPLOAD_DIR']
    assert data['vision'] is data['key'] is data['static_admin'] is False
    assert protected.read_bytes()==original and not (tmp_path/'wrong-uploads').exists()
