import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Establish isolation before any application module binds default DB/log paths.
# Domain audit/event functions otherwise use the user's normal runtime database.
_test_runtime = tempfile.TemporaryDirectory(prefix="its-pytest-", ignore_cleanup_errors=True)
os.environ["ITS_BASE_DIR"] = _test_runtime.name
os.environ["ITS_LOAD_ENV"] = "false"
for _key in tuple(os.environ):
    if _key.upper().startswith("ITS_"):
        del os.environ[_key]
os.environ.update(
    {
        "ITS_BASE_DIR": _test_runtime.name,
        "ITS_LOAD_ENV": "false",
        "ITS_DB_NAME": "parking_system.db",
        "ITS_UPLOAD_DIR": "uploads",
        "ITS_LOG_DIR": "logs",
        "ITS_REPORT_DIR": "reports",
        "ITS_FAST_MODE": "true",
        "ITS_ENABLE_PADDLE_OCR": "false",
        "ITS_ENABLE_HARDCASE_OCR": "false",
        "ITS_ENABLE_OPENAI_VISION": "false",
        "ITS_ENABLE_VISION_IN_AUTO": "false",
        "ITS_OPENAI_API_KEY": "",
        "ITS_OPENAI_BASE_URL": "http://127.0.0.1:1/v1",
        "ITS_MB_TEST_MODE": "true",
        "ITS_API_JWT_SECRET": "isolated-pytest-only-signing-fixture-2026",
        "ITS_API_ALLOW_STATIC_TOKENS": "false",
    }
)


def pytest_sessionstart(session):
    from backend.db import init_db

    init_db()


@pytest.fixture
def log_rows(tmp_path, monkeypatch):
    """Exercise web filters against a real isolated database rather than a mocked frame."""
    import sqlite3

    from backend import read_queries
    from backend.db import init_db

    path = tmp_path / "read-fixture.db"
    init_db(path)
    monkeypatch.setattr(read_queries, "DB_PATH", path)

    def seed(rows):
        with sqlite3.connect(path) as conn:
            for source in rows:
                row = {"status": "IN_PARKING", **source}
                columns = list(row)
                conn.execute(
                    "INSERT INTO parking_logs("
                    + ",".join(columns)
                    + ") VALUES("
                    + ",".join("?" for _ in columns)
                    + ")",
                    [row[key] for key in columns],
                )
        return path

    return seed
