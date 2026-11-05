import csv
import hashlib
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.field_evaluation import FIELDS, load_manifest, sha256
from scripts import field_evaluate as field


def create_manifest(tmp_path):
    image = tmp_path / "sample.png"
    image.write_bytes(b"frozen-image-bytes")  # Fake pipeline below never decodes it.
    path = tmp_path / "labels.csv"
    row = dict(
        zip(
            FIELDS,
            (
                "S1",
                image.name,
                sha256(image),
                "G1",
                "test",
                "day",
                "read",
                "59-B1 123.45",
                "human",
                "person-a",
                "person-b",
                "2026-11-03",
            ),
        )
    )
    with path.open("w", encoding="utf8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerow(row)
    return path, image


@pytest.mark.parametrize("change", ["manifest_and_original", "frozen_image", "source"])
def test_cli_uses_frozen_labels_images_and_code(tmp_path, monkeypatch, change):
    from backend import app_service, openai_vision_adapter

    manifest, image = create_manifest(tmp_path)
    initial = manifest.read_bytes()
    source = tmp_path / "source/backend"
    source.mkdir(parents=True)
    code = source / "pipeline.py"
    code.write_text("original", encoding="utf8")
    monkeypatch.setattr(field, "ROOT", tmp_path / "source")
    monkeypatch.setattr(os, "environ", dict(os.environ))
    monkeypatch.setattr(
        openai_vision_adapter, "vision_configuration_status", lambda: {"model": "fixture"}
    )

    def process(frozen):
        assert Path(frozen) != image and Path(frozen).read_bytes() == b"frozen-image-bytes"
        if change == "manifest_and_original":
            image.write_bytes(b"changed original after snapshot")
            manifest.write_text("changed manifest after snapshot", encoding="utf8")
        elif change == "source":
            code.write_text("changed", encoding="utf8")
        else:
            Path(frozen).write_bytes(b"changed frozen input")
        return SimpleNamespace(
            plate_text="59-B1 123.45",
            ocr={"text": "59-B1 123.45", "is_usable": True, "ocr_engine": "fixture"},
        )

    monkeypatch.setattr(app_service, "process_plate_image", process)
    output = tmp_path / "report.json"
    monkeypatch.setattr(
        sys, "argv", ["field_evaluate", "run", str(manifest), "--output", str(output)]
    )
    status = field.main()
    if change == "manifest_and_original":
        assert status == 0
        report = json.loads(output.read_text(encoding="utf8"))
        assert report["manifest_sha256"] == hashlib.sha256(initial).hexdigest()
        assert report["manifest_snapshot"][0]["expected_plate"] == "59-B1 123.45"
        assert report["summary"]["correct_decision_rate"] == 1
    else:
        assert status == 2 and not output.exists()


def test_prepare_ignores_image_named_directory_and_cannot_replace_evidence(tmp_path, monkeypatch):
    images = tmp_path / "images"
    images.mkdir()
    (images / "folder.jpg").mkdir()
    (images / "photo.png").write_bytes(b"placeholder")
    output = tmp_path / "labels.csv"
    monkeypatch.setattr(sys, "argv", ["field_evaluate", "prepare", str(images), str(output)])
    assert field.main() == 0
    before = output.read_bytes()
    assert "folder.jpg" not in before.decode("utf-8-sig")
    assert field.main() == 2 and output.read_bytes() == before


def test_duplicate_csv_headers_are_rejected_before_using_labels(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text("sample_id,sample_id\na,b\n", encoding="utf8")
    with pytest.raises(ValueError, match="Duplicate manifest columns"):
        load_manifest(path)
