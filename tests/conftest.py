import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Establish isolation before any application module binds default DB/log paths.
# Domain audit/event functions otherwise use the user's normal runtime database.
_test_runtime = tempfile.TemporaryDirectory(prefix="its-pytest-", ignore_cleanup_errors=True)
os.environ["ITS_BASE_DIR"] = _test_runtime.name
os.environ["ITS_LOAD_ENV"] = "false"
os.environ.setdefault("ITS_FAST_MODE", "true")
os.environ.setdefault("ITS_ENABLE_PADDLE_OCR", "false")
os.environ.setdefault("ITS_ENABLE_HARDCASE_OCR", "false")
os.environ.setdefault("ITS_ENABLE_OPENAI_VISION", "false")
os.environ.setdefault("ITS_OPENAI_API_KEY", "")
os.environ["ITS_MB_TEST_MODE"] = "true"


def pytest_sessionstart(session):
    from backend.db import init_db
    init_db()


import pytest


@pytest.fixture
def log_rows(tmp_path,monkeypatch):
    """Exercise web filters against a real isolated database rather than a mocked frame."""
    import sqlite3
    from backend.db import init_db
    from backend import read_queries
    path=tmp_path/'read-fixture.db';init_db(path)
    monkeypatch.setattr(read_queries,'DB_PATH',path)
    def seed(rows):
        with sqlite3.connect(path) as conn:
            for source in rows:
                row={'status':'IN_PARKING',**source}
                columns=list(row)
                conn.execute('INSERT INTO parking_logs('+','.join(columns)+') VALUES('+','.join('?' for _ in columns)+')',[row[key] for key in columns])
        return path
    return seed
