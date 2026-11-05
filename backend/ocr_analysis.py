from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from backend.benchmarking import finite_number, first_text
from backend.benchmarking import plate_key as normalize_plate_text


@dataclass(frozen=True)
class OcrAnalysis:
    total: int
    exact_accuracy: float | None
    normalized_accuracy: float | None
    character_accuracy: float | None
    unreadable_rate: float | None
    confusion_pairs: dict[str, int]
    low_confidence_count: int

    def as_dict(self) -> dict:
        return {
            "total": self.total,
            "exact_accuracy": self.exact_accuracy,
            "normalized_accuracy": self.normalized_accuracy,
            "character_accuracy": self.character_accuracy,
            "unreadable_rate": self.unreadable_rate,
            "confusion_pairs": self.confusion_pairs,
            "low_confidence_count": self.low_confidence_count,
        }


def _char_accuracy(expected: str, predicted: str) -> tuple[int, int, Counter]:
    exp = normalize_plate_text(expected)
    pred = normalize_plate_text(predicted)
    max_len = max(len(exp), len(pred), 1)
    correct = 0
    pairs: Counter = Counter()
    for idx in range(max_len):
        e = exp[idx] if idx < len(exp) else "∅"
        p = pred[idx] if idx < len(pred) else "∅"
        if e == p:
            correct += 1
        else:
            pairs[f"{e}->{p}"] += 1
    return correct, max_len, pairs


def analyze_ocr_rows(rows: list[dict], low_confidence_threshold: float = 0.75) -> OcrAnalysis:
    rows = [row for row in rows if first_text(row, "expected_plate", "plate", "ground_truth")]
    total = len(rows)
    if total == 0:
        return OcrAnalysis(0, None, None, None, None, {}, 0)
    exact = 0
    normalized = 0
    unreadable = 0
    char_correct = 0
    char_total = 0
    confusion: Counter = Counter()
    low_conf = 0
    for row in rows:
        expected = first_text(row, "expected_plate", "plate", "ground_truth")
        predicted = first_text(row, "predicted_plate", "prediction", "ocr_text")
        confidence = finite_number(row.get("confidence"), maximum=1)
        if not predicted:
            unreadable += 1
        if expected and predicted and expected == predicted:
            exact += 1
        if (
            expected
            and predicted
            and normalize_plate_text(expected) == normalize_plate_text(predicted)
        ):
            normalized += 1
        c_ok, c_total, pairs = _char_accuracy(expected, predicted)
        char_correct += c_ok
        char_total += c_total
        confusion.update(pairs)
        if confidence is None or confidence < low_confidence_threshold:
            low_conf += 1
    return OcrAnalysis(
        total=total,
        exact_accuracy=exact / total,
        normalized_accuracy=normalized / total,
        character_accuracy=char_correct / max(1, char_total),
        unreadable_rate=unreadable / total,
        confusion_pairs=dict(confusion.most_common(20)),
        low_confidence_count=low_conf,
    )
