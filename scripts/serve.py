"""Start the existing app, or an explicitly isolated offline academic demo."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import secrets
import socket
import sys
import threading
import time
from urllib.request import build_opener, ProxyHandler
import webbrowser

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def prepare_demo_environment(folder: Path):
    folder = folder.resolve()
    marker = folder / '.its-offline-demo'
    if folder.exists() and any(folder.iterdir()) and not marker.is_file():
        raise ValueError('Demo directory is not empty and has no demo marker. Choose a new directory.')
    folder.mkdir(parents=True, exist_ok=True)
    marker.write_text('ITS isolated offline demo v1\n', encoding='utf8')
    for key in tuple(os.environ):
        if key.upper().startswith('ITS_'):
            del os.environ[key]
    os.environ.update({
        'ITS_LOAD_ENV': 'false', 'ITS_BASE_DIR': str(folder),
        'ITS_DEMO_OFFLINE': 'true', 'ITS_APP_TITLE': 'ITS Parking - demo ngoai tuyen',
        'ITS_MB_TEST_MODE': 'true', 'ITS_ENABLE_OPENAI_VISION': 'false',
        'ITS_ENABLE_VISION_IN_AUTO': 'false', 'ITS_ENABLE_HARDCASE_OCR': 'false',
        'ITS_ENABLE_PADDLE_OCR': 'false', 'ITS_API_ALLOW_STATIC_TOKENS': 'false',
        'ITS_API_JWT_SECRET': secrets.token_urlsafe(48),
    })


def port_available(port):
    with socket.socket() as sock:
        try:
            sock.bind(('127.0.0.1', port))
        except OSError:
            return False
    return True


def open_when_ready(url, timeout=30):
    opener = build_opener(ProxyHandler({}))
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with opener.open(url + '/readiness', timeout=1) as response:
                if response.status == 200 and json.load(response).get('status') == 'ready':
                    webbrowser.open(url)
                    return
        except (OSError, ValueError):
            pass
        time.sleep(.25)
    print('Browser not opened: readiness did not pass. Check the server log.', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--demo', action='store_true', help='Separate DB, public demo accounts, no bank/provider calls')
    parser.add_argument('--demo-dir', type=Path, help='New empty folder, or a folder previously created by --demo')
    parser.add_argument('--port', type=int)
    parser.add_argument('--open-browser', action='store_true')
    parser.add_argument('--check', action='store_true', help='Validate prerequisites without starting a server or seeding users')
    args = parser.parse_args()
    if args.demo_dir and not args.demo:
        parser.error('--demo-dir requires --demo')
    port = args.port if args.port is not None else (8001 if args.demo else 8000)
    if not 1024 <= port <= 65535:
        parser.error('Port must be between 1024 and 65535')
    required = ('fastapi', 'uvicorn', 'pandas', 'numpy', 'PIL', 'multipart', 'dotenv', 'qrcode')
    missing = [name for name in required if importlib.util.find_spec(name) is None]
    if missing:
        print('Missing dependencies: ' + ', '.join(missing) + '. Install requirements_web.txt first.')
        return 2
    if not port_available(port):
        print(f'Port {port} is already in use. Open the existing app or choose --port; no process was stopped.')
        return 2
    if args.check and args.demo:
        print(f'Demo prerequisites ready on 127.0.0.1:{port}. No data was created.')
        return 0
    if args.demo:
        try:
            prepare_demo_environment(args.demo_dir or ROOT / 'work' / 'offline-demo')
        except ValueError as exc:
            print(str(exc))
            return 2
    from backend.config import API_JWT_SECRET
    if len(API_JWT_SECRET) < 32 or API_JWT_SECRET == 'dev-only-change-me' or API_JWT_SECRET.startswith('replace-with-'):
        print('Signing key is missing/placeholder. Run python scripts/configure_security.py, then retry.')
        return 2
    if args.check:
        print(f'App prerequisites ready on 127.0.0.1:{port}. No account or bank session was changed.')
        return 0
    if args.demo:
        from scripts.seed_demo_users import seed_demo_users
        messages = seed_demo_users()
        if any(line.startswith('FAIL') for line in messages):
            print('Unable to create isolated demo accounts.')
            return 2
        print('OFFLINE DEMO: admin / ItsDemo@2026A; operator / ItsDemo@2026O; viewer / ItsDemo@2026V', flush=True)
        print('OCR: manual entry with real validation. Bank disabled. Hardware simulated. Separate demo database.', flush=True)
    url = f'http://127.0.0.1:{port}'
    print(f'ITS: {url}', flush=True)
    if args.open_browser:
        threading.Thread(target=open_when_ready, args=(url,), daemon=True).start()
    import uvicorn
    uvicorn.run('api.main:app', host='127.0.0.1', port=port)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
