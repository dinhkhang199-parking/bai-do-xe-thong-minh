from io import BytesIO
from pathlib import Path
import sys
from PIL import Image

import pytest

pytestmark = pytest.mark.integration


from backend import storage
from backend.validators import MAX_UPLOAD_SIZE_BYTES, ValidationError


def real_image(format="JPEG"):
    stream = BytesIO()
    Image.new("RGB", (90, 60), "white").save(stream, format=format)
    return stream.getvalue()


class DummyUpload:
    def __init__(self, name: str, data: bytes):
        self.name = name
        self._data = data

    def getbuffer(self):
        return self._data


class DummyFastAPIUpload:
    def __init__(self, filename: str, data: bytes):
        self.filename = filename
        self.file = BytesIO(data)


def test_save_uploaded_file_accepts_fastapi_upload(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "UPLOAD_DIR", tmp_path)

    data = real_image()
    saved_path = Path(storage.save_uploaded_file(DummyFastAPIUpload("plate.JPG", data), "api entry"))

    assert saved_path.exists()
    assert saved_path.suffix == ".jpg"
    assert saved_path.read_bytes() == data
    assert saved_path.name.startswith("api_entry_")


@pytest.mark.parametrize("filename", ["plate.exe", "plate", ""])
def test_save_uploaded_file_rejects_invalid_extension(tmp_path, monkeypatch, filename):
    monkeypatch.setattr(storage, "UPLOAD_DIR", tmp_path)

    with pytest.raises(ValidationError, match="Unsupported image format"):
        storage.save_uploaded_file(DummyUpload(filename, b"fake-image"), "entry")


def test_save_uploaded_file_rejects_empty_file(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "UPLOAD_DIR", tmp_path)

    with pytest.raises(ValidationError, match="Empty upload"):
        storage.save_uploaded_file(DummyUpload("plate.jpg", b""), "entry")


def test_save_uploaded_file_rejects_oversized_file(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "UPLOAD_DIR", tmp_path)

    with pytest.raises(ValidationError, match="too large"):
        storage.save_uploaded_file(DummyUpload("plate.jpg", b"x" * (MAX_UPLOAD_SIZE_BYTES + 1)), "entry")


def test_save_uploaded_file_sanitizes_prefix_path_separators(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "UPLOAD_DIR", tmp_path)

    saved_path = Path(storage.save_uploaded_file(DummyUpload("plate.jpg", real_image()), "../evil/path"))

    assert saved_path.exists()
    assert saved_path.resolve().is_relative_to(tmp_path.resolve())
    assert ".." not in saved_path.name
    assert "/" not in saved_path.name
    assert "\\" not in saved_path.name


def test_save_uploaded_file_preserves_png_suffix(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "UPLOAD_DIR", tmp_path)

    data = real_image("PNG")
    saved_path = Path(storage.save_uploaded_file(DummyUpload("plate.PNG", data), "entry"))

    assert saved_path.suffix == ".png"
    assert saved_path.read_bytes() == data


def test_save_uploaded_file_validates_even_when_cv2_unavailable(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "UPLOAD_DIR", tmp_path)
    monkeypatch.setattr(storage, "cv2", None)

    with pytest.raises(ValidationError):
        storage.save_uploaded_file(DummyUpload("plate.jpg", b"not-really-an-image"), "entry")
    data = real_image()
    saved_path = Path(storage.save_uploaded_file(DummyUpload("plate.jpg", data), "entry"))
    assert saved_path.read_bytes() == data


def test_save_uploaded_file_preserves_large_image_detail_for_roi_crop(tmp_path, monkeypatch):
    import numpy as np
    import cv2

    monkeypatch.setattr(storage, "UPLOAD_DIR", tmp_path)

    image = np.full((2200, 3200, 3), 255, dtype=np.uint8)
    ok, encoded = cv2.imencode('.jpg', image)
    assert ok

    saved_path = Path(storage.save_uploaded_file(DummyUpload('large.jpg', encoded.tobytes()), 'entry'))
    saved = cv2.imread(str(saved_path))

    assert saved is not None
    assert saved.shape[:2] == (2200, 3200)
    assert saved_path.read_bytes() == encoded.tobytes()


def test_save_uploaded_file_keeps_small_image_size(tmp_path, monkeypatch):
    import numpy as np
    import cv2

    monkeypatch.setattr(storage, "UPLOAD_DIR", tmp_path)

    image = np.full((600, 900, 3), 255, dtype=np.uint8)
    ok, encoded = cv2.imencode('.jpg', image)
    assert ok

    saved_path = Path(storage.save_uploaded_file(DummyUpload('small.jpg', encoded.tobytes()), 'entry'))
    saved = cv2.imread(str(saved_path))

    assert saved is not None
    assert saved.shape[0] == 600
    assert saved.shape[1] == 900
