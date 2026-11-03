"""Prepare a BLANK labeling sheet, validate it, or run production-flow inference."""
import argparse
import csv
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.field_evaluation import FIELDS, evaluate_predictions, load_manifest, sha256


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    prepare = commands.add_parser('prepare')
    prepare.add_argument('images', type=Path)
    prepare.add_argument('manifest', type=Path)
    for action in ('validate', 'run'):
        command = commands.add_parser(action)
        command.add_argument('manifest', type=Path)
        if action == 'run':
            command.add_argument('--output', required=True, type=Path)
            command.add_argument('--split', choices=['development', 'test'], default='test')
            command.add_argument('--live', action='store_true', help='Explicit consent to send these images to the configured vision provider')
    args = parser.parse_args()
    try:
        if args.command == 'prepare':
            images = sorted(p for p in args.images.rglob('*') if p.suffix.lower() in {'.png', '.jpg', '.jpeg', '.webp'})
            if not images:
                raise ValueError('No supported images found')
            args.manifest.parent.mkdir(parents=True, exist_ok=True)
            with args.manifest.open('x', encoding='utf-8-sig', newline='') as handle:
                writer = csv.DictWriter(handle, fieldnames=FIELDS)
                writer.writeheader()
                for i, path in enumerate(images, 1):
                    writer.writerow({'sample_id': f'S{i:04d}', 'image_path': os.path.relpath(path.resolve(), args.manifest.parent.resolve()), 'image_sha256': sha256(path)})
            print(f'Prepared {len(images)} BLANK labels. A human must label, group, split and independently review them.')
            return 0
        manifest = load_manifest(args.manifest)
        if args.command == 'validate':
            print(json.dumps({'valid': True, 'samples': len(manifest), 'groups': len({r['group_id'] for r in manifest}),
                              'test_samples': sum(r['split'] == 'test' for r in manifest)}))
            return 0
        if args.output.exists():
            raise ValueError('Output already exists; use a new path to preserve earlier evidence')
        # Isolated runtime for OCR crops/logs: never write to tickets or live uploads.
        with tempfile.TemporaryDirectory(prefix='its-field-', ignore_cleanup_errors=True) as runtime:
            os.environ['ITS_BASE_DIR'] = runtime
            os.environ['ITS_MB_TEST_MODE'] = 'true'
            os.environ['ITS_DEMO_OFFLINE'] = 'false'
            for key in ('ITS_DB_NAME', 'ITS_UPLOAD_DIR', 'ITS_LOG_DIR', 'ITS_REPORT_DIR'):
                os.environ[key] = {'ITS_DB_NAME': 'field.db', 'ITS_UPLOAD_DIR': 'uploads', 'ITS_LOG_DIR': 'logs', 'ITS_REPORT_DIR': 'reports'}[key]
            if not args.live:
                os.environ['ITS_ENABLE_OPENAI_VISION'] = 'false'
                os.environ['ITS_ENABLE_VISION_IN_AUTO'] = 'false'
                os.environ['ITS_OPENAI_API_KEY'] = ''
            from backend.app_service import process_plate_image
            from backend.openai_vision_adapter import vision_configuration_status
            predictions = []
            for row in manifest:
                if row['split'] != args.split:
                    continue
                if sha256(row['_image']) != row['image_sha256']:
                    raise ValueError('Image changed after manifest validation')
                started = time.perf_counter()
                try:
                    result = process_plate_image(row['_image'])
                    ocr = result.ocr
                    predictions.append({'sample_id': row['sample_id'], 'predicted_plate': result.plate_text,
                        'accepted': ocr.get('is_usable') is True and not bool(ocr.get('ambiguous') or ocr.get('ocr_disagreement')),
                        'latency_ms': (time.perf_counter()-started)*1000, 'engine': ocr.get('ocr_engine')})
                except Exception as exc:
                    predictions.append({'sample_id': row['sample_id'], 'predicted_plate': '', 'accepted': False,
                                        'latency_ms': (time.perf_counter()-started)*1000, 'error': type(exc).__name__})
            report = evaluate_predictions(manifest, predictions, split=args.split)
            # Public model name only; never serialize config/provider URLs or keys.
            report['model'] = vision_configuration_status().get('model') if args.live else 'local-configured-pipeline'
        report.update({'created_at': datetime.now(timezone.utc).isoformat(), 'manifest_sha256': sha256(args.manifest),
                       'live_provider_opt_in': args.live, 'pipeline': 'process_plate_image',
                       'source_sha256': {p.relative_to(ROOT).as_posix(): sha256(p) for folder in ('backend', 'integrations') for p in sorted((ROOT/folder).rglob('*.py'))}})
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open('x', encoding='utf8') as handle:
            json.dump(report, handle, ensure_ascii=False, indent=2, allow_nan=False)
        print(json.dumps(report['summary'], indent=2))
        return 0 if report['summary']['errors'] == 0 else 1
    except (OSError, ValueError) as exc:
        print(f'Evaluation not accepted: {exc}')
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
