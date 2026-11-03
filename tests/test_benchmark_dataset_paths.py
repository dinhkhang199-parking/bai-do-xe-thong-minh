from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('script', ['benchmark_bike_back_ctu.py', 'make_bike_back_ctu_ground_truth_template.py', 'prefill_bike_back_ctu_ground_truth.py'])
def test_ctu_helpers_accept_dataset_location_without_inference(script):
    result = subprocess.run([sys.executable, str(ROOT / 'scripts' / script), '--help'], cwd=ROOT,
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0
    assert '--dataset-dir' in result.stdout


def test_ctu_blank_template_creates_output_directory(tmp_path, monkeypatch):
    from scripts import make_bike_back_ctu_ground_truth_template as template
    images = tmp_path / 'images'
    images.mkdir()
    (images / 'one.jpg').write_bytes(b'placeholder-only-not-inferenced')
    output = tmp_path / 'new-output' / 'labels.csv'
    monkeypatch.setattr(template, 'OUT_CSV', output)
    monkeypatch.setattr(sys, 'argv', ['make_template', '--dataset-dir', str(images)])
    template.main()
    assert 'one.jpg,,todo,fill manually' in output.read_text(encoding='utf-8-sig')
