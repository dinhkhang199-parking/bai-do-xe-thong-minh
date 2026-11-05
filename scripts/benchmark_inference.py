from __future__ import annotations

import json
import math
import statistics
import sys
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.alpr_service import run_alpr
from backend.benchmarking import plate_key as normalize_plate_text
from backend.config import REPORT_DIR
from backend.ocr_analysis import analyze_ocr_rows
from scripts.run_benchmark import display


def _default_csv() -> Path:
    return ROOT / "data" / "benchmark" / "field_manifest_template.csv"


def _resolve_image_path(raw_path: str, csv_path: Path) -> Path:
    candidate = Path(str(raw_path or ""))
    if candidate.is_absolute():
        return candidate
    return (csv_path.parent / candidate).resolve()


def run_inference_benchmark(
    csv_path: Path | None = None, detector_model: str | None = None, ocr_engine: str = "auto"
) -> dict:
    csv_path = csv_path or _default_csv()
    if not csv_path.exists():
        return {
            "field_images_available": False,
            "reason": f"CSV not found: {csv_path}",
            "samples": [],
        }
    df = pd.read_csv(csv_path, dtype=str, keep_default_na=False)
    samples = []
    latencies = []
    runnable = 0
    for row in df.to_dict(orient="records"):
        image_path = _resolve_image_path(str(row.get("image_path") or ""), csv_path)
        expected = str(row.get("expected_plate") or "").strip()
        sample = {
            "image_path": str(image_path),
            "expected_plate": expected,
            "exists": image_path.is_file(),
        }
        if image_path.is_file():
            runnable += 1
            start = time.perf_counter()
            result = run_alpr(str(image_path), detector_model=detector_model, ocr_engine=ocr_engine)
            elapsed = (time.perf_counter() - start) * 1000
            latencies.append(elapsed)
            predicted = str(result.get("text") or "")
            sample.update(
                {
                    "predicted_plate": predicted,
                    "confidence": float(result.get("confidence") or 0.0),
                    "latency_ms": elapsed,
                    "ocr_engine": result.get("ocr_engine", "unknown"),
                    "quality_note": result.get("quality_note", ""),
                    "normalized_match": bool(
                        expected
                        and predicted
                        and normalize_plate_text(expected) == normalize_plate_text(predicted)
                    ),
                }
            )
        samples.append(sample)
    analysis_rows = [sample for sample in samples if sample.get("exists")]
    analysis = analyze_ocr_rows(analysis_rows).as_dict()
    p95 = None
    if latencies:
        ordered = sorted(latencies)
        p95 = ordered[math.ceil(0.95 * len(ordered)) - 1]
    return {
        "csv_path": str(csv_path),
        "field_images_available": runnable > 0,
        "total_rows": len(samples),
        "runnable_images": runnable,
        "labeled_images": analysis["total"],
        "accuracy_measured": analysis["total"] > 0,
        "average_latency_ms": statistics.mean(latencies) if latencies else None,
        "p95_latency_ms": p95,
        "analysis": analysis,
        "samples": samples,
    }


def write_inference_reports(payload: dict, report_dir: Path = REPORT_DIR) -> tuple[Path, Path]:
    report_dir.mkdir(parents=True, exist_ok=True)
    json_path = report_dir / "inference_benchmark.json"
    md_path = report_dir / "inference_benchmark.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    analysis = payload.get("analysis", {})
    md_path.write_text(
        "# Real Inference Benchmark Report\n\n"
        f"- CSV: `{payload.get('csv_path', '')}`\n"
        f"- Field images available: **{payload.get('field_images_available')}**\n"
        f"- Total rows: **{payload.get('total_rows', 0)}**\n"
        f"- Runnable images: **{payload.get('runnable_images', 0)}**\n"
        f"- Labeled images: **{payload.get('labeled_images', 0)}**\n"
        f"- Separator-only accuracy: **{display(analysis.get('normalized_accuracy'), '.2%')}**\n"
        f"- Positional character accuracy (not CER): **{display(analysis.get('character_accuracy'), '.2%')}**\n"
        f"- Unreadable rate: **{display(analysis.get('unreadable_rate'), '.2%')}**\n"
        f"- Average latency (ms): **{display(payload.get('average_latency_ms'))}**\n"
        f"- P95 latency (ms): **{display(payload.get('p95_latency_ms'))}**\n\n"
        "> If runnable images is 0, this report proves benchmark plumbing only; add real images to prove field accuracy.\n",
        encoding="utf-8",
    )
    return json_path, md_path


def main() -> int:
    payload = run_inference_benchmark()
    json_path, md_path = write_inference_reports(payload)
    print("Real inference benchmark")
    print("=" * 40)
    print(f"Field images available: {payload.get('field_images_available')}")
    print(f"Runnable images: {payload.get('runnable_images', 0)} / {payload.get('total_rows', 0)}")
    print(f"Reports: {json_path} | {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
