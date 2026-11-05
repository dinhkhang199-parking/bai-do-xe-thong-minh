"""Copy only source/test assets to a fresh temporary checkout before any app import."""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.run_checks import write_summary

FOLDERS = ("api", "backend", "frontend", "integrations", "models", "scripts", "tests", "docs")


def isolated_environment(runtime: Path) -> dict[str, str]:
    # No inherited ITS_*, proxy, provider, DB/upload paths, or .env settings.
    env = {
        key: value
        for key, value in os.environ.items()
        if key.upper()
        in {
            "PATH",
            "SYSTEMROOT",
            "WINDIR",
            "USERPROFILE",
            "HOME",
            "COMSPEC",
            "PATHEXT",
        }
    }
    for name in ("tmp", "appdata", "data"):
        (runtime / name).mkdir(parents=True, exist_ok=True)
    env.update(
        {
            "TEMP": str(runtime / "tmp"),
            "TMP": str(runtime / "tmp"),
            "APPDATA": str(runtime / "appdata"),
            "LOCALAPPDATA": str(runtime / "appdata"),
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
            "ITS_LOAD_ENV": "false",
            "ITS_BASE_DIR": str(runtime / "data"),
            "ITS_MB_TEST_MODE": "true",
            "ITS_ENABLE_OPENAI_VISION": "false",
            "ITS_ENABLE_VISION_IN_AUTO": "false",
            "ITS_OPENAI_API_KEY": "",
            "ITS_OPENAI_BASE_URL": "http://127.0.0.1:1/v1",
            "ITS_API_JWT_SECRET": "isolated-regression-fixture-not-a-real-key-2026",
            "ITS_API_ALLOW_STATIC_TOKENS": "false",
            "ITS_API_TOKEN": "",
            "ITS_ENABLE_HARDCASE_OCR": "false",
            "ITS_ENABLE_PADDLE_OCR": "false",
            "ITS_FAST_MODE": "true",
            "ITS_STREAMLIT_ADMIN_PASSWORD": "",
            "ITS_STREAMLIT_OPERATOR_PASSWORD": "",
            "ITS_STREAMLIT_VIEWER_PASSWORD": "",
        }
    )
    return env


def copy_source(target: Path) -> dict[str, str]:
    target.mkdir(parents=True, exist_ok=True)
    for folder in FOLDERS:
        shutil.copytree(
            ROOT / folder,
            target / folder,
            ignore=shutil.ignore_patterns(
                "__pycache__",
                "*.pyc",
                ".pytest_cache",
                ".env*",
                ".mb_bridge*",
                "*.db",
                "*.sqlite*",
                "*.log",
            ),
        )
    for name in ("pytest.ini", "pyproject.toml", ".coveragerc", "README.md", "ARCHITECTURE.md"):
        shutil.copy2(ROOT / name, target / name)
    return {
        p.relative_to(target).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(target.rglob("*"))
        if p.is_file()
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "work" / "isolated-results")
    parser.add_argument("--coverage", action="store_true")
    args = parser.parse_args(argv)
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    lock = output / ".checks.lock"
    try:
        with lock.open("x", encoding="ascii") as file:
            file.write(str(os.getpid()))
    except FileExistsError:
        print("Output already locked. Use a new --output-dir for this run.")
        return 2
    summary = output / "checks-summary.json"
    state = {"run": {"passed": False, "state": "preparing", "id": uuid.uuid4().hex}}
    code = 1
    try:
        write_summary(summary, state)
        # Invalidate old evidence before copy/import/subprocess can fail.
        for name in (
            "source-manifest.json",
            "backend-junit.xml",
            ".coverage",
            "coverage.json",
            "coverage.xml",
        ):
            (output / name).unlink(missing_ok=True)
        with tempfile.TemporaryDirectory(
            prefix="its-checks-", ignore_cleanup_errors=True
        ) as folder:
            run = Path(folder)
            manifest = copy_source(run / "source")
            env = isolated_environment(run / "runtime")
            reports = run / "reports"
            command = [sys.executable, "scripts/run_checks.py", "--output-dir", str(reports)]
            if args.coverage:
                command.append("--coverage")
            state["run"]["state"] = "running"
            write_summary(summary, state)
            result = subprocess.run(command, cwd=run / "source", env=env, timeout=900)
            current = json.loads((reports / "checks-summary.json").read_text(encoding="utf8"))
            if result.returncode or not current.get("run", {}).get("passed"):
                current.setdefault("run", {}).update(passed=False, state="failed")
            for name, expected in manifest.items():
                if hashlib.sha256((run / "source" / name).read_bytes()).hexdigest() != expected:
                    current["run"].update(
                        passed=False, state="failed", reason="source_mutated_during_tests"
                    )
                    break
            for path in reports.iterdir():
                if path.is_file() and (
                    path.name.endswith("-output.txt")
                    or path.name
                    in {"backend-junit.xml", ".coverage", "coverage.json", "coverage.xml"}
                ):
                    shutil.copy2(path, output / path.name)
            (output / "source-manifest.json").write_text(
                json.dumps(manifest, indent=2), encoding="utf8"
            )
            state = current
            code = 0 if state["run"]["passed"] else 1
    except (OSError, ValueError, subprocess.TimeoutExpired, KeyboardInterrupt) as exc:
        state["run"].update(
            passed=False,
            state="interrupted" if isinstance(exc, KeyboardInterrupt) else "failed",
            reason=type(exc).__name__,
        )
    finally:
        try:
            write_summary(summary, state)
        finally:
            lock.unlink(missing_ok=True)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
