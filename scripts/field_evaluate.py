"""Prepare a BLANK labeling sheet, validate it, or run production-flow inference."""
import argparse
import csv
from datetime import datetime, timezone
import json
import hashlib
import io
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend.field_evaluation import FIELDS, evaluate_predictions, load_manifest, prediction_from_ocr, sha256


def write_new(path: Path, text: str, *, encoding='utf8'):
    """Publish complete bytes without replacing another run's existing evidence."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', encoding=encoding, newline='', dir=path.parent, delete=False) as file:
        temporary=Path(file.name)
        file.write(text)
    try:
        os.link(temporary,path)  # Atomic create-if-absent on the supported Windows/NTFS environment.
    finally:
        temporary.unlink(missing_ok=True)


def input_fingerprint():
    code={p.relative_to(ROOT).as_posix(): sha256(p) for folder in ('backend','integrations') for p in sorted((ROOT/folder).rglob('*.py'))}
    models={p.relative_to(ROOT).as_posix(): sha256(p) for folder in ('models','integrations/person1')
            for p in sorted((ROOT/folder).rglob('*')) if p.is_file() and p.suffix in {'.pt','.onnx'}}
    return {'source_sha256':code,'repository_model_sha256':models}


def freeze_images(rows, folder):
    folder.mkdir(parents=True,exist_ok=True)
    paths={}
    for index,row in enumerate(rows):
        image=folder/(str(index)+Path(row['_image']).suffix)
        shutil.copyfile(row['_image'],image)
        if sha256(image)!=row['image_sha256']:
            raise ValueError('Image changed before the evaluation snapshot was frozen')
        paths[row['sample_id']]=image
    return paths


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
            images = sorted(p for p in args.images.rglob('*') if p.is_file() and p.suffix.lower() in {'.png', '.jpg', '.jpeg', '.webp'})
            if not images:
                raise ValueError('No supported images found')
            handle=io.StringIO(newline='')
            writer=csv.DictWriter(handle,fieldnames=FIELDS)
            writer.writeheader()
            for i,path in enumerate(images,1):
                try:
                    reference=os.path.relpath(path.resolve(),args.manifest.parent.resolve())
                except ValueError:
                    reference=str(path.resolve())  # Windows inputs and report may be on different drives.
                writer.writerow({'sample_id':f'S{i:04d}','image_path':reference,'image_sha256':sha256(path)})
            write_new(args.manifest,handle.getvalue(),encoding='utf-8-sig')
            print(f'Prepared {len(images)} BLANK labels. A human must label, group, split and independently review them.')
            return 0
        manifest_bytes=args.manifest.read_bytes()
        manifest = load_manifest(args.manifest,content=manifest_bytes)
        if args.command == 'validate':
            print(json.dumps({'valid': True, 'samples': len(manifest), 'groups': len({r['group_id'] for r in manifest}),
                              'test_samples': sum(r['split'] == 'test' for r in manifest)}))
            return 0
        if args.output.exists():
            raise ValueError('Output already exists; use a new path to preserve earlier evidence')
        selected=[row for row in manifest if row['split']==args.split]
        if not selected:
            raise ValueError('Selected split contains no samples')
        fingerprint=input_fingerprint()
        # Isolated runtime for OCR crops/logs: never write to tickets or live uploads.
        with tempfile.TemporaryDirectory(prefix='its-field-', ignore_cleanup_errors=True) as runtime:
            frozen=freeze_images(selected,Path(runtime)/'inputs')
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
            for row in selected:
                started = time.perf_counter()
                try:
                    result = process_plate_image(str(frozen[row['sample_id']]))
                    ocr = result.ocr
                    predictions.append(prediction_from_ocr(row['sample_id'], {**ocr, 'text': result.plate_text},
                                                           (time.perf_counter()-started)*1000))
                except Exception as exc:
                    predictions.append({'sample_id': row['sample_id'], 'predicted_plate': '', 'accepted': False,
                                        'latency_ms': (time.perf_counter()-started)*1000, 'error': type(exc).__name__})
                if sha256(frozen[row['sample_id']])!=row['image_sha256']:
                    raise ValueError('An inference operation changed its frozen input')
            report = evaluate_predictions(manifest, predictions, split=args.split)
            # Public model name only; never serialize config/provider URLs or keys.
            report['model'] = vision_configuration_status().get('model') if args.live else 'local-configured-pipeline'
        if input_fingerprint()!=fingerprint:
            raise ValueError('Source/model files changed during evaluation; result is not publishable')
        report.update({'created_at': datetime.now(timezone.utc).isoformat(), 'manifest_sha256': hashlib.sha256(manifest_bytes).hexdigest(),
                       'live_provider_opt_in': args.live, 'pipeline': 'process_plate_image',
                       'manifest_snapshot': [{key:row[key] for key in FIELDS} for row in manifest], **fingerprint})
        write_new(args.output,json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False))
        print(json.dumps(report['summary'], indent=2))
        return 0 if report['summary']['errors'] == 0 else 1
    except (OSError, ValueError) as exc:
        print(f'Evaluation not accepted: {exc}')
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
