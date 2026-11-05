"""Short-lived OCR reuse bound to authenticated user and exact image content."""

import copy
import hashlib
import secrets
import threading
import time
from pathlib import Path

TTL_SECONDS = 600
MAX_ITEMS = 256
_items = {}
_lock = threading.Lock()
_clock = time.monotonic


def _digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def remember(path, owner, processed):
    at = _clock()
    token = secrets.token_urlsafe(32)
    try:
        digest = _digest(path)
    except OSError:
        return None
    entry = {
        "owner": owner,
        "digest": digest,
        "expires": at + TTL_SECONDS,
        "ocr": copy.deepcopy(processed.ocr),
        "plate_text": processed.plate_text,
    }
    with _lock:
        for key in list(_items):
            if _items[key]["expires"] <= at:
                _items.pop(key, None)
        while len(_items) >= MAX_ITEMS:
            _items.pop(next(iter(_items)))
        _items[token] = entry
    return token


def reuse(token, path, owner):
    at = _clock()
    with _lock:
        entry = _items.get(token)
        if not entry or entry["expires"] <= at:
            _items.pop(token, None)
            return None
        entry = copy.deepcopy(entry)
    if entry["owner"] != owner or entry["digest"] != _digest(path):
        return None
    from backend.app_service import ProcessedPlate

    return ProcessedPlate(ocr=entry["ocr"], plate_text=entry["plate_text"])
