from dataclasses import dataclass
from pathlib import Path
import sqlite3
from contextlib import closing

from backend.config import API_ALLOW_STATIC_TOKENS, API_JWT_SECRET, BASE_DIR, DB_PATH, LOG_DIR, REPORT_DIR, UPLOAD_DIR
from integrations.device_config import load_device_config


@dataclass(frozen=True)
class ReadinessFinding:
    name: str
    status: str
    detail: str


def check_production_readiness(*, demo_ok: bool = False) -> list[ReadinessFinding]:
    findings: list[ReadinessFinding] = []
    default_secret = API_JWT_SECRET == "dev-only-change-me"
    secret_too_short = len(API_JWT_SECRET) < 32
    secret_weak = default_secret or secret_too_short
    findings.append(ReadinessFinding(
        "jwt_secret",
        "warn" if secret_weak and demo_ok else ("fail" if secret_weak else "pass"),
        "JWT secret is default or too short (< 32 chars); set a strong ITS_API_JWT_SECRET" if secret_weak else "JWT secret configured",
    ))
    findings.append(ReadinessFinding(
        "static_tokens",
        "warn" if API_ALLOW_STATIC_TOKENS else "pass",
        "Static tokens enabled for backward-compatible demo mode" if API_ALLOW_STATIC_TOKENS else "Static tokens disabled",
    ))
    for name, path in [("base_dir", BASE_DIR), ("upload_dir", UPLOAD_DIR), ("log_dir", LOG_DIR), ("report_dir", REPORT_DIR)]:
        findings.append(ReadinessFinding(name, "pass" if Path(path).exists() else "fail", f"{path}"))
    try:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("SELECT 1")
        findings.append(ReadinessFinding("database_writable", "pass", str(DB_PATH)))
    except Exception as exc:
        findings.append(ReadinessFinding("database_writable", "fail", str(exc)))
    for report_name in ["benchmark_report.md", "evaluation_report.md", "performance_smoke.md"]:
        report_path = REPORT_DIR / report_name
        findings.append(ReadinessFinding(report_name, "pass" if report_path.exists() else "warn", str(report_path)))
    config = load_device_config()
    findings.append(ReadinessFinding(
        'hardware_mode', 'warn' if demo_ok else 'fail',
        'Simulator adapters active; configuration does not verify a real connection. Missing: ' + (', '.join(config.missing) or 'none'),
    ))
    return findings


def runtime_readiness() -> list[dict]:
    """Read-only probes; never create a database to make a readiness check pass."""
    database_ok = False
    try:
        with closing(sqlite3.connect(Path(DB_PATH).resolve().as_uri() + '?mode=ro', uri=True)) as conn:
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            database_ok = {'parking_logs', 'app_users', 'audit_logs', 'parking_events'}.issubset(tables)
    except (OSError, sqlite3.Error):
        pass
    auth_ok = API_JWT_SECRET != 'dev-only-change-me' and len(API_JWT_SECRET) >= 32
    return [
        {'name':'database', 'status':'ok' if database_ok else 'fail', 'detail':'Required runtime tables available' if database_ok else 'Runtime database unavailable or schema incomplete'},
        {'name':'auth', 'status':'ok' if auth_ok else 'fail', 'detail':'Signing key configured' if auth_ok else 'Signing key missing or weak'},
        {'name':'devices', 'status':'simulated', 'detail':'Simulator adapters active; no real device connection verified'},
        {'name':'api_parity', 'status':'implemented', 'detail':'Application routes implemented; functional verification is separate'},
    ]


def summarize_findings(findings: list[ReadinessFinding]) -> dict[str, int]:
    return {
        "pass": sum(1 for item in findings if item.status == "pass"),
        "warn": sum(1 for item in findings if item.status == "warn"),
        "fail": sum(1 for item in findings if item.status == "fail"),
    }
