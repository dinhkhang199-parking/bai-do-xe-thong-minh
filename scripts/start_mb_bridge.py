"""Start the optional read-only MB worker hidden, without logging into the bank."""

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    config_path = ROOT / ".mb_bridge.json"
    if not config_path.is_file() or not (ROOT / ".mb_bridge_token").is_file():
        print("MB bridge is not configured; parking remains available.")
        return 0
    sys.path.insert(0, str(ROOT))
    from integrations.mb_bridge_client import MBConnectionError, call_worker

    try:
        call_worker("/status", timeout=2)
        print("MB read-only bridge is already available.")
        return 0
    except MBConnectionError:
        pass
    config = json.loads(config_path.read_text(encoding="utf-8"))
    source = Path(config["source_dir"]).resolve()
    python = source / ".venv314/Scripts/python.exe"
    if not python.is_file() or not (source / "MBBank/mbbank/main.py").is_file():
        print("MB worker dependency folder is missing; check .mb_bridge.json.")
        return 1
    work = ROOT / "runtime_data/mb_worker"
    work.mkdir(parents=True, exist_ok=True)
    for name in ("home", "tmp", "appdata"):
        (work / name).mkdir(exist_ok=True)
    env = {
        "SystemRoot": os.environ.get("SystemRoot", "C:/Windows"),
        "WINDIR": "C:/Windows",
        "PATH": str(python.parent) + ";C:/Windows/System32",
        "TEMP": str(work / "tmp"),
        "TMP": str(work / "tmp"),
        "HOME": str(work / "home"),
        "USERPROFILE": str(work / "home"),
        "APPDATA": str(work / "appdata"),
        "LOCALAPPDATA": str(work / "appdata"),
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
    }
    with (work / "worker.log").open("ab") as log:
        subprocess.Popen(
            [
                str(python),
                str(ROOT / "integrations/mb_readonly_worker.py"),
                "--source",
                str(source),
                "--key-file",
                str(ROOT / ".mb_bridge_token"),
            ],
            cwd=work,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    print("Started MB read-only worker; bank login awaits administrator action.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
