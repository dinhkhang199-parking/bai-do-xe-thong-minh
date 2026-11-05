from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.benchmarking import run_static_benchmark
from backend.config import BENCHMARK_UPLOADS_DIR, REPORT_DIR


def _default_csv() -> Path:
    candidate = ROOT / "data" / "benchmark" / "datasets" / "benchmark_dataset.csv"
    return candidate if candidate.exists() else BENCHMARK_UPLOADS_DIR / "benchmark_dataset.csv"


def write_reports(metrics, report_dir: Path = REPORT_DIR) -> tuple[Path, Path]:
    report_dir.mkdir(parents=True, exist_ok=True)
    json_path = report_dir / "benchmark_report.json"
    md_path = report_dir / "benchmark_report.md"
    payload = metrics.as_dict()
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(
        "# OCR/CV Benchmark Report\n\n"
        f"- Total samples: **{metrics.total_samples}**\n"
        f"- Labeled / unlabeled: **{metrics.labeled_samples} / {metrics.unlabeled_samples}**\n"
        f"- Exact accuracy: **{display(metrics.exact_accuracy, '.2%')}**\n"
        f"- Separator-only plate accuracy: **{display(metrics.normalized_accuracy, '.2%')}**\n"
        f"- Unreadable rate: **{display(metrics.unreadable_rate, '.2%')}**\n"
        f"- Average recorded latency (ms): **{display(metrics.average_latency_ms)}**\n"
        f"- P95 recorded latency (ms): **{display(metrics.p95_latency_ms)}**\n"
        f"- Average confidence: **{display(metrics.average_confidence)}**\n\n"
        "Recorded predictions only; this script does not run inference or validate label provenance.\n"
        "Unknown metrics are not measured. Blank ground truth is excluded from accuracy.\n",
        encoding="utf-8",
    )
    return json_path, md_path


def display(value, spec=".2f"):
    return "not measured" if value is None else format(value, spec)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Summarize recorded OCR predictions; never generate predictions from labels."
    )
    parser.add_argument("csv", type=Path)
    args = parser.parse_args()
    csv_path = args.csv
    try:
        metrics = run_static_benchmark(csv_path)
    except (OSError, ValueError) as exc:
        print(f"Benchmark not measured: {exc}")
        return 2
    json_path, md_path = write_reports(metrics)
    print("OCR/CV benchmark")
    print("=" * 40)
    print(f"Dataset: {csv_path}")
    print(f"Total samples: {metrics.total_samples}")
    print(f"Exact accuracy: {display(metrics.exact_accuracy, '.2%')}")
    print(f"Separator-only accuracy: {display(metrics.normalized_accuracy, '.2%')}")
    print(f"Unreadable rate: {display(metrics.unreadable_rate, '.2%')}")
    print(f"Average latency (ms): {display(metrics.average_latency_ms)}")
    print(f"Reports: {json_path} | {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
