from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.config import REPORT_DIR


def generate_report(report_dir: Path = REPORT_DIR) -> Path:
    report_dir.mkdir(parents=True, exist_ok=True)
    path = report_dir / "evaluation_report.md"
    benchmark_path = report_dir / "benchmark_report.md"
    benchmark_note = (
        "File present (review provenance and source hash before relying on it)"
        if benchmark_path.exists()
        else "Not measured; use scripts/field_evaluate.py with reviewed labels"
    )
    path.write_text(
        "# ITS Parking Technical Evaluation Report\n\n"
        "## Architecture\n\n"
        "- Domain: Smart Parking in Intelligent Transportation Systems.\n"
        "- Sensing: camera/upload snapshot abstraction.\n"
        "- Processing: plate detector/OCR pipeline and Vietnamese plate normalization.\n"
        "- Decision support: ticket lifecycle and review queue.\n"
        "- Control interface: barrier/MQTT/camera simulator contracts.\n"
        "- Observability: audit logs, parking events, runtime DB validation, operation KPIs.\n\n"
        "## FR Checklist\n\n"
        "- Vehicle entry: implemented.\n"
        "- Vehicle exit: implemented.\n"
        "- Plate mismatch review: implemented.\n"
        "- Manual override: implemented.\n"
        "- Admin user management: implemented.\n"
        "- API parity: implemented.\n\n"
        "## NFR Checklist\n\n"
        "- Security: PBKDF2, lockout, RBAC, JWT-compatible sessions.\n"
        "- Auditability: persistent audit and event streams.\n"
        "- Reliability: migrations, runtime validator, tests.\n"
        "- Maintainability: separated backend/API/frontend/integrations/tests.\n"
        "- Extensibility: device simulators ready for real hardware adapters.\n\n"
        "## Benchmark Evidence\n\n"
        f"- Benchmark report: {benchmark_note}.\n"
        "- Field protocol: `docs/FIELD_BENCHMARK_PROTOCOL.md`.\n"
        "- Field manifest template: `data/benchmark/field_manifest_template.csv`.\n\n"
        "## CV/OCR Evidence\n\n"
        "- Run `python scripts/cv_doctor.py` to generate model/engine inventory.\n"
        "- Run `python scripts/benchmark_inference.py` to execute real image inference if field images exist.\n"
        "- Reports: `cv_readiness_report.md` and `inference_benchmark.md`.\n"
        "- The report separates pipeline readiness from field-proven accuracy.\n\n"
        "## Production Readiness Evidence\n\n"
        "- Run `python scripts/production_check.py --demo-ok`.\n"
        "- Validates JWT secret state, static-token mode, directories, DB writability, reports, and hardware mode.\n\n"
        "## Performance Evidence\n\n"
        "- Run `python scripts/performance_smoke.py`.\n"
        "- Generates `performance_smoke.json` and `performance_smoke.md`.\n\n"
        "## Evidence Status (no automatic academic grade)\n\n"
        "| Criterion | Current evidence and required verification |\n"
        "|---|---|\n"
        "| Business rules | See docs/REQUIREMENTS_TRACEABILITY.md; rerun isolated_checks.py |\n"
        "| Tests and coverage | Use checks-summary.json and coverage.json from the same source manifest |\n"
        "| OCR accuracy | Requires independently reviewed labels and frozen field evaluation |\n"
        "| Hardware | Simulator is in scope for the software assignment; no physical validation claimed |\n"
        "| Banking | Fake-provider regressions; a live transaction is a separate acceptance test |\n"
        "| Academic grade | Not measured; determined by the instructor and oral defense |\n",
        encoding="utf-8",
    )
    return path


def main() -> int:
    path = generate_report()
    print(f"Generated evaluation report: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
