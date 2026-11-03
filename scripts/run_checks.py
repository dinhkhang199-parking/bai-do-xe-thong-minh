"""Run regressions and write evidence that cannot reuse an earlier successful run."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]


def write_summary(path, results):
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf8', dir=path.parent, suffix='.tmp', delete=False) as file:
        json.dump(results, file, indent=2)
        temp = Path(file.name)
    try:
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def _text(value):
    return value.decode('utf8', errors='replace') if isinstance(value, bytes) else (value or '')


def backend_result(path):
    root = ET.parse(path).getroot()
    suites = [suite for suite in root.iter('testsuite') if not suite.findall('testsuite')]
    result = {key: sum(int(suite.attrib.get(key, 0)) for suite in suites)
              for key in ('tests', 'failures', 'errors', 'skipped')}
    result['passed'] = result['tests'] > 0 and not any(result[key] for key in ('failures', 'errors', 'skipped'))
    return result


def frontend_result(transcript):
    counts = {name: int(value) for name, value in re.findall(
        r'^(?:#|ℹ)\s+(tests|pass|fail|cancelled|skipped|todo)\s+(\d+)\s*$', transcript, re.MULTILINE)}
    passed = (all(key in counts for key in ('tests','pass','fail','cancelled','skipped','todo'))
              and counts['tests'] > 0 and counts['pass'] == counts['tests']
              and not any(counts[key] for key in ('fail','cancelled','skipped','todo')))
    return {**counts, 'passed': passed}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'work/test-results')
    parser.add_argument('--live-vision', action='store_true')
    parser.add_argument('--coverage', action='store_true')
    args = parser.parse_args(argv)
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    lock = output / '.checks.lock'
    try:
        with lock.open('x', encoding='ascii') as file:
            file.write(str(os.getpid()))
    except FileExistsError:
        print('Output is locked by another/interrupted run. Use a new --output-dir; no prior evidence was changed.')
        return 2
    summary = output / 'checks-summary.json'
    results = {'run': {'passed': False, 'state': 'running', 'id': uuid.uuid4().hex,
                       'started_at': datetime.now(timezone.utc).isoformat()}}
    try:
        write_summary(summary, results)
        # Only known generated files in this output directory, never user source/DBs.
        for name in ('backend-junit.xml', '.coverage', 'coverage.json', 'coverage.xml',
                     'backend-output.txt', 'frontend-output.txt', 'coverage-json-output.txt',
                     'coverage-xml-output.txt', 'coverage-report-output.txt', 'vision-output.txt'):
            (output / name).unlink(missing_ok=True)
        xml = output / 'backend-junit.xml'
        frontend_tests = sorted(str(p.relative_to(ROOT)) for p in (ROOT / 'tests').glob('test_*.cjs'))
        if not frontend_tests:
            raise RuntimeError('No frontend test suites found')
        backend = [sys.executable, '-m', 'pytest', '-q', '--junitxml', str(xml)]
        if args.coverage:
            backend = [sys.executable, '-m', 'coverage', 'run', '-m', 'pytest', '-q', '--junitxml', str(xml)]
        commands = [('backend', backend), ('frontend', [shutil.which('node') or 'node', '--test', *frontend_tests])]
        if args.coverage:
            commands.extend([
                ('coverage-json', [sys.executable, '-m', 'coverage', 'json', '-o', str(output/'coverage.json')]),
                ('coverage-xml', [sys.executable, '-m', 'coverage', 'xml', '-o', str(output/'coverage.xml')]),
                ('coverage-report', [sys.executable, '-m', 'coverage', 'report', '--fail-under=75']),
            ])
        if args.live_vision:
            commands.append(('vision', [sys.executable, 'scripts/benchmark_vision_cases.py', '--live', '--output-dir', str(output)]))
        env = {**os.environ, 'COVERAGE_FILE': str(output / '.coverage'), 'PYTEST_DISABLE_PLUGIN_AUTOLOAD': '1'}
        for name, command in commands:
            print('Running ' + name + ' checks...', flush=True)
            try:
                process = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True,
                                         encoding='utf8', errors='replace', timeout=600)
                transcript = process.stdout + process.stderr
                result = {'passed': process.returncode == 0, 'exit_code': process.returncode}
                if name in {'backend', 'frontend'}:
                    counts = backend_result(xml) if name == 'backend' else frontend_result(transcript)
                    result = {**result, **counts, 'passed': result['passed'] and counts['passed']}
            except subprocess.TimeoutExpired as exc:
                transcript = _text(exc.stdout) + _text(exc.stderr) + '\nCheck timed out.\n'
                result = {'passed': False, 'exit_code': 124, 'reason': 'timeout'}
            except (OSError, ValueError, ET.ParseError) as exc:
                transcript = 'Could not execute check or read its current report: ' + type(exc).__name__ + '\n'
                result = {'passed': False, 'exit_code': 2, 'reason': type(exc).__name__}
            (output / (name + '-output.txt')).write_text(transcript, encoding='utf8')
            results[name] = result
            write_summary(summary, results)
            print(json.dumps({name: result}), flush=True)
        passed = all(value['passed'] for key, value in results.items() if key != 'run')
        results['run'].update(passed=passed, state='completed' if passed else 'failed')
    except (OSError, RuntimeError, KeyboardInterrupt) as exc:
        results['run'].update(passed=False, state='interrupted' if isinstance(exc, KeyboardInterrupt) else 'failed', reason=type(exc).__name__)
    finally:
        results['run']['finished_at'] = datetime.now(timezone.utc).isoformat()
        try:
            write_summary(summary, results)
        finally:
            lock.unlink(missing_ok=True)
    return 0 if results['run']['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
