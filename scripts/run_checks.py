"""Run the backend and browser-logic regression suites with saved reports.

Use --live-vision only when provider calls are explicitly wanted.
"""
import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=ROOT / "work" / "test-results")
    parser.add_argument("--live-vision", action="store_true")
    parser.add_argument("--coverage", action="store_true")
    args = parser.parse_args()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    xml_path = output / "backend-junit.xml"
    frontend_tests = sorted(str(path.relative_to(ROOT)) for path in (ROOT / "tests").glob("test_*.cjs"))
    if not frontend_tests:
        raise RuntimeError("No frontend test suites found")
    commands = [
        ("backend", [sys.executable, "-m", "pytest", "-q", "--junitxml", str(xml_path)]),
        ("frontend", [shutil.which("node") or "node", "--test", *frontend_tests]),
    ]
    if args.coverage:
        commands[0] = ('backend', [sys.executable, '-m', 'coverage', 'run', '-m', 'pytest', '-q', '--junitxml', str(xml_path)])
        commands.extend([
            ('coverage-json', [sys.executable, '-m', 'coverage', 'json', '-o', str(output / 'coverage.json')]),
            ('coverage-xml', [sys.executable, '-m', 'coverage', 'xml', '-o', str(output / 'coverage.xml')]),
            ('coverage-report', [sys.executable, '-m', 'coverage', 'report', '--fail-under=75']),
        ])
    if args.live_vision:
        commands.append(("vision", [sys.executable, "scripts/benchmark_vision_cases.py", "--live", "--output-dir", str(output)]))
    results = {}
    for name, command in commands:
        print("Running " + name + " checks...", flush=True)
        if name == 'backend' and xml_path.exists():
            xml_path.unlink()  # Never reuse a report from an interrupted earlier run.
        process = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600)
        transcript = process.stdout + process.stderr
        (output / (name + "-output.txt")).write_text(transcript, encoding="utf-8")
        results[name] = {"passed": process.returncode == 0, "exit_code": process.returncode}
        if name == "backend" and xml_path.exists():
            suites = ET.parse(xml_path).getroot()
            results[name]["tests"] = sum(int(suite.attrib.get("tests", 0)) for suite in suites.iter("testsuite"))
            for field in ('failures', 'errors', 'skipped'):
                results[name][field] = sum(int(suite.attrib.get(field, 0)) for suite in suites.iter('testsuite'))
        if name == "frontend":
            count = re.search(r"(?:tests|test[s]?)\s+(\d+)", transcript)
            results[name]["tests"] = int(count.group(1)) if count else None
        print(json.dumps({name: results[name]}), flush=True)
    (output / "checks-summary.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    return 0 if all(row["passed"] for row in results.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
