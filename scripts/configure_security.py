"""Create a strong local signing key without printing it or importing the app."""
from pathlib import Path
import os
import secrets
import tempfile


def ensure_signing_key(path: Path) -> bool:
    path = Path(path)
    lines = path.read_text(encoding='utf-8-sig').splitlines() if path.exists() else []
    values = [line.split('=',1)[1].strip().strip("\"'") for line in lines
              if line.split('=',1)[0].strip() == 'ITS_API_JWT_SECRET' and '=' in line]
    if values and len(values[0]) >= 32 and values[0] != 'dev-only-change-me' and not values[0].startswith('replace-with-') and len(values) == 1:
        return False
    retained = [line for line in lines if line.split('=',1)[0].strip() != 'ITS_API_JWT_SECRET']
    retained.append('ITS_API_JWT_SECRET=' + secrets.token_urlsafe(48))
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=path.parent,
                                         prefix='.signing-key-',suffix='.tmp',delete=False) as handle:
            temp_path = Path(handle.name)
            handle.write('\n'.join(retained)+'\n')
        os.replace(temp_path,path)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()
    return True


if __name__ == '__main__':
    changed = ensure_signing_key(Path(__file__).resolve().parents[1]/'.env')
    print('Local signing key updated; prior sessions require sign-in.' if changed else 'Local signing key already configured.')
