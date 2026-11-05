import csv
import math

import pytest
from PIL import Image

from backend.benchmarking import (
    compute_benchmark_metrics,
    load_benchmark_rows,
    run_static_benchmark,
)
from backend.field_evaluation import (
    FIELDS,
    evaluate_predictions,
    load_manifest,
    prediction_from_ocr,
    sha256,
)
from backend.ocr_analysis import analyze_ocr_rows
from scripts.benchmark_common import normalize
from scripts.run_benchmark import write_reports


def test_missing_predictions_cannot_be_copied_from_truth(tmp_path):
    path = tmp_path / "truth.csv"
    path.write_text("expected_plate\n59-B1 123.45\n", encoding="utf8")
    with pytest.raises(ValueError, match="no predictions"):
        load_benchmark_rows(path)


def test_static_metrics_never_invent_timing_or_nan_labels(tmp_path):
    path = tmp_path / "predictions.csv"
    path.write_text(
        "expected_plate,predicted_plate\n,\n59-B1 123.45,59-B1 123.45\n", encoding="utf8"
    )
    metrics = run_static_benchmark(path)
    assert metrics.labeled_samples == 1 and metrics.unlabeled_samples == 1
    assert metrics.normalized_accuracy == 1
    assert metrics.average_latency_ms is None and metrics.latency_samples == 0
    metrics = compute_benchmark_metrics(
        [{"expected_plate": math.nan, "predicted_plate": math.nan, "latency_ms": math.inf}]
    )
    assert metrics.normalized_accuracy is None and metrics.average_latency_ms is None
    _, markdown = write_reports(metrics, tmp_path)
    assert "not measured" in markdown.read_text(encoding="utf8")


@pytest.mark.parametrize("letter,digit", [("B", "8"), ("O", "0"), ("S", "5"), ("I", "1")])
def test_benchmark_never_repairs_identity(letter, digit):
    truth, prediction = f"59-{letter}1 123.45", f"59-{digit}1 123.45"
    assert normalize(truth) != normalize(prediction)
    assert (
        compute_benchmark_metrics(
            [{"expected_plate": truth, "predicted_plate": prediction}]
        ).normalized_matches
        == 0
    )
    assert (
        analyze_ocr_rows(
            [{"expected_plate": truth, "predicted_plate": prediction}]
        ).normalized_accuracy
        == 0
    )


def manifest_fixture(tmp_path, count=2):
    rows = []
    for i in range(count):
        image = tmp_path / f"{i}.png"
        Image.new("RGB", (30, 30), (i * 30, 0, 0)).save(image)
        rows.append(
            dict(
                zip(
                    FIELDS,
                    (
                        f"S{i}",
                        image.name,
                        sha256(image),
                        f"G{i}",
                        "test",
                        "day",
                        "read",
                        f"59-B1 123.4{i}",
                        "human",
                        "labeler-a",
                        "reviewer-b",
                        "2026-11-03",
                    ),
                )
            )
        )
    return rows


def save_manifest(tmp_path, rows):
    path = tmp_path / "manifest.csv"
    with path.open("w", encoding="utf8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return path


@pytest.mark.parametrize(
    "mutation,match",
    [
        ({"label_source": "ocr-prefilled"}, "human"),
        ({"reviewer": "labeler-a"}, "human"),
        ({"expected_plate": ""}, "required"),
        ({"image_sha256": "0" * 64}, "hash mismatch"),
        ({"expected_action": "abstain"}, "blank plate"),
        ({"reviewed_at": ""}, "ISO"),
    ],
)
def test_field_manifest_rejects_unreviewed_or_changed_data(tmp_path, mutation, match):
    rows = manifest_fixture(tmp_path)
    rows[0].update(mutation)
    with pytest.raises(ValueError, match=match):
        load_manifest(save_manifest(tmp_path, rows))


@pytest.mark.parametrize("leak", ["group", "image", "plate"])
def test_field_manifest_prevents_split_leakage_and_duplicate_images(tmp_path, leak):
    rows = manifest_fixture(tmp_path)
    rows[1]["split"] = "development"
    if leak == "group":
        rows[1]["group_id"] = rows[0]["group_id"]
    elif leak == "image":
        rows[1]["image_path"] = rows[0]["image_path"]
        rows[1]["image_sha256"] = rows[0]["image_sha256"]
    else:
        rows[1]["expected_plate"] = rows[0]["expected_plate"]
    with pytest.raises(ValueError):
        load_manifest(save_manifest(tmp_path, rows))


def test_field_counts_wrong_accepts_abstention_errors_and_latency(tmp_path):
    rows = manifest_fixture(tmp_path, 4)
    rows[2].update(expected_action="abstain", expected_plate="", condition="blur")
    rows[3].update(expected_action="abstain", expected_plate="", condition="blur")
    manifest = load_manifest(save_manifest(tmp_path, rows))
    predictions = [
        {"sample_id": "S0", "predicted_plate": "59B112340", "accepted": True, "latency_ms": 10},
        {"sample_id": "S1", "predicted_plate": "59B112399", "accepted": True, "latency_ms": 20},
        {"sample_id": "S2", "predicted_plate": "", "accepted": False, "latency_ms": 30},
        {
            "sample_id": "S3",
            "predicted_plate": "",
            "accepted": False,
            "latency_ms": 40,
            "error": "TimeoutError",
        },
    ]
    result = evaluate_predictions(manifest, predictions)
    summary = result["summary"]
    assert summary["exact_plate_accuracy"] == 0.5
    assert summary["false_accept_rate_all"] == 0.25
    assert summary["false_accept_rate_accepted"] == 0.5
    assert summary["safe_abstention_rate"] == 0.5  # A timeout is never a successful abstention.
    assert summary["errors"] == 1 and summary["correct_decision_rate"] == 0.5
    assert summary["median_latency_ms"] == 25 and summary["p95_latency_ms"] == 40
    assert summary["exact_plate_wilson95"][0] < 0.5 < summary["exact_plate_wilson95"][1]
    with pytest.raises(ValueError, match="every selected sample"):
        evaluate_predictions(manifest, predictions[:-1])
    with pytest.raises(ValueError, match="Duplicate"):
        evaluate_predictions(manifest, predictions + predictions[:1])
    predictions[0]["accepted"] = "false"
    with pytest.raises(ValueError, match="boolean"):
        evaluate_predictions(manifest, predictions)


@pytest.mark.parametrize("engine", [None, "unavailable", "demo-offline"])
def test_missing_engine_cannot_earn_safe_abstention_credit(tmp_path, engine):
    rows = manifest_fixture(tmp_path, 1)
    rows[0].update(expected_action="abstain", expected_plate="")
    manifest = load_manifest(save_manifest(tmp_path, rows))
    prediction = prediction_from_ocr(
        "S0", {"ocr_engine": engine, "text": "", "is_usable": False}, 10
    )
    summary = evaluate_predictions(manifest, [prediction])["summary"]
    assert summary["errors"] == 1
    assert summary["safe_abstention_rate"] == summary["correct_decision_rate"] == 0


def test_provider_outage_is_recorded_even_when_local_fallback_succeeds(tmp_path):
    rows = manifest_fixture(tmp_path, 1)
    manifest = load_manifest(save_manifest(tmp_path, rows))
    prediction = prediction_from_ocr(
        "S0",
        {
            "text": "59-B1 123.40",
            "is_usable": True,
            "ocr_engine": "fast-alpr-easyocr",
            "ai_status": "unavailable",
        },
        10,
    )
    summary = evaluate_predictions(manifest, [prediction])["summary"]
    assert summary["errors"] == 0 and summary["provider_degraded_samples"] == 1
    assert summary["correct_decision_rate"] == 1
