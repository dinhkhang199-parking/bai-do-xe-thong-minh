import json
from pathlib import Path
import subprocess

import pytest

from scripts import run_checks


@pytest.fixture
def runner(tmp_path, monkeypatch):
    (tmp_path/'tests').mkdir()
    (tmp_path/'tests/test_fixture.cjs').write_text('// test fixture', encoding='utf8')
    monkeypatch.setattr(run_checks, 'ROOT', tmp_path)
    output=tmp_path/'reports'
    output.mkdir()
    (output/'checks-summary.json').write_text('{"backend":{"passed":true,"tests":999}}', encoding='utf8')
    for name in ('backend-junit.xml','coverage.json','coverage.xml'):
        (output/name).write_text('stale evidence', encoding='utf8')
    def success(command, **kwargs):
        current=json.loads((output/'checks-summary.json').read_text(encoding='utf8'))
        assert current['run']['passed'] is False and current['run']['state']=='running'
        if '--junitxml' in command:
            (output/'backend-junit.xml').write_text('<testsuites><testsuite tests="3" failures="0" errors="0" skipped="0"/></testsuites>',encoding='utf8')
            return subprocess.CompletedProcess(command,0,'3 passed','')
        return subprocess.CompletedProcess(command,0,'# tests 4\n# pass 4\n# fail 0\n# cancelled 0\n# skipped 0\n# todo 0\n','')
    return output, success


@pytest.mark.parametrize('failure', ['timeout', 'missing_node', 'invalid_junit', 'interrupted'])
def test_failed_or_interrupted_run_never_keeps_previous_pass(runner, monkeypatch, failure):
    output, success=runner
    def process(command, **kwargs):
        if failure=='timeout':
            raise subprocess.TimeoutExpired(command,600,output=b'partial transcript')
        if failure=='interrupted':
            raise KeyboardInterrupt()
        if failure=='missing_node' and '--test' in command:
            raise FileNotFoundError('node missing')
        result=success(command,**kwargs)
        if failure=='invalid_junit' and '--junitxml' in command:
            (output/'backend-junit.xml').write_text('bad xml',encoding='utf8')
        return result
    monkeypatch.setattr(run_checks.subprocess,'run',process)
    assert run_checks.main(['--output-dir',str(output)])==1
    report=json.loads((output/'checks-summary.json').read_text(encoding='utf8'))
    assert report['run']['passed'] is False and report['run']['state'] in {'failed','interrupted'}
    assert not (output/'coverage.json').exists() and not (output/'coverage.xml').exists()
    assert not (output/'.checks.lock').exists()


def test_zero_or_skipped_tests_are_not_a_success():
    assert run_checks.frontend_result('# tests 0\n# pass 0\n# fail 0\n# cancelled 0\n# skipped 0\n# todo 0')['passed'] is False
    assert run_checks.frontend_result('# tests 2\n# pass 1\n# fail 0\n# cancelled 0\n# skipped 1\n# todo 0')['passed'] is False


def test_passing_run_reports_only_current_results(runner,monkeypatch):
    output,success=runner
    monkeypatch.setattr(run_checks.subprocess,'run',success)
    assert run_checks.main(['--output-dir',str(output)])==0
    result=json.loads((output/'checks-summary.json').read_text(encoding='utf8'))
    assert result['run']['state']=='completed' and result['run']['passed']
    assert result['backend']['tests']==3 and result['frontend']['tests']==4


def test_existing_run_lock_leaves_other_run_untouched(runner):
    output,_=runner
    (output/'.checks.lock').write_text('fixture',encoding='ascii')
    before=(output/'checks-summary.json').read_bytes()
    assert run_checks.main(['--output-dir',str(output)])==2
    assert (output/'checks-summary.json').read_bytes()==before


def test_isolated_copy_failure_invalidates_old_summary_and_manifest(runner,monkeypatch):
    from scripts import isolated_checks
    output,_=runner
    (output/'source-manifest.json').write_text('{"old":"hash"}',encoding='utf8')
    def unavailable(*args):
        raise OSError('fixture copy failure')
    monkeypatch.setattr(isolated_checks,'copy_source',unavailable)
    assert isolated_checks.main(['--output-dir',str(output)])==1
    result=json.loads((output/'checks-summary.json').read_text(encoding='utf8'))
    assert result['run']['passed'] is False and result['run']['state']=='failed'
    assert not (output/'source-manifest.json').exists()
    assert not (output/'.checks.lock').exists()
