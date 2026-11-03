"""Link the supplied local MB source; never copy or print banking credentials."""
import argparse
import json
from pathlib import Path
import secrets

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source",type=Path,required=True)
    args=parser.parse_args()
    source=args.source.resolve()
    if not (source/"MBBank/mbbank/main.py").is_file() or not (source/".venv314/Scripts/python.exe").is_file():
        parser.error("Supplied MBBank library or its local Python environment is missing")
    key=ROOT/".mb_bridge_token"
    if not key.exists():
        with key.open("x",encoding="ascii") as stream:stream.write(secrets.token_urlsafe(48))
        key.chmod(0o600)
    if len(key.read_text(encoding="ascii").strip())<40:
        raise SystemExit("Existing bridge key is invalid; inspect before rotating it")
    config=ROOT/".mb_bridge.json"
    payload={"source_dir":str(source),"loopback_port":5051,"login_on_startup":False}
    if config.exists() and json.loads(config.read_text(encoding="utf-8"))!=payload:
        raise SystemExit("A different source is already configured; inspect before changing it")
    config.write_text(json.dumps(payload,indent=2),encoding="utf-8")
    print("MB source linked. Shared key prepared. No credentials copied; bank login remains manual.")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
