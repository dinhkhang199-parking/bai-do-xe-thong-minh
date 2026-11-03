"""Metrics for recorded predictions; this module never invents predictions or timing."""
from __future__ import annotations

import csv
import math
import statistics
from dataclasses import dataclass
from pathlib import Path

from backend.plate_format import normalize_generic_plate_text


def clean_text(value) -> str:
    # pandas and spreadsheet exports can contain NaN instead of an empty cell.
    if value is None or isinstance(value, float) and not math.isfinite(value):
        return ""
    return str(value).strip()


def finite_number(value, *, maximum=None):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number >= 0 and (maximum is None or number <= maximum) else None


def plate_key(value) -> str:
    """Ignore display separators/case, never substitute identity characters B/8 etc."""
    return normalize_generic_plate_text(clean_text(value))


def first_text(row, *keys):
    return next((clean_text(row.get(key)) for key in keys if clean_text(row.get(key))), "")


@dataclass(frozen=True)
class BenchmarkMetrics:
    total_samples: int
    labeled_samples: int
    unlabeled_samples: int
    exact_matches: int
    normalized_matches: int
    unreadable: int
    exact_accuracy: float | None
    normalized_accuracy: float | None
    unreadable_rate: float | None
    average_latency_ms: float | None
    p95_latency_ms: float | None
    average_confidence: float | None
    latency_samples: int

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def compute_benchmark_metrics(rows: list[dict]) -> BenchmarkMetrics:
    exact = normalized = unreadable = labeled = 0
    latencies, confidences = [], []
    for row in rows:
        expected = first_text(row, "expected_plate", "plate", "ground_truth")
        predicted = first_text(row, "predicted_plate", "prediction", "ocr_text")
        if expected:
            labeled += 1
            exact += bool(predicted and expected == predicted)
            normalized += bool(predicted and plate_key(expected) == plate_key(predicted))
        unreadable += not bool(predicted)
        latency = finite_number(row.get("latency_ms"))
        confidence = finite_number(row.get("confidence"), maximum=1)
        if latency is not None:
            latencies.append(latency)
        if confidence is not None:
            confidences.append(confidence)
    return BenchmarkMetrics(
        len(rows), labeled, len(rows) - labeled, exact, normalized, unreadable,
        exact / labeled if labeled else None,
        normalized / labeled if labeled else None,
        unreadable / len(rows) if rows else None,
        statistics.mean(latencies) if latencies else None,
        sorted(latencies)[math.ceil(.95 * len(latencies)) - 1] if latencies else None,
        statistics.mean(confidences) if confidences else None, len(latencies),
    )


def load_benchmark_rows(csv_path: Path) -> list[dict]:
    with csv_path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not set(reader.fieldnames or ()) & {"predicted_plate", "prediction", "ocr_text"}:
            raise ValueError("CSV contains no predictions. Run inference first; ground truth is never a prediction.")
        return list(reader)


def run_static_benchmark(csv_path: Path) -> BenchmarkMetrics:
    return compute_benchmark_metrics(load_benchmark_rows(csv_path))
