"""Independent-label evaluation contracts, split integrity, and selective OCR metrics."""
import csv
from datetime import datetime
import hashlib
import math
from pathlib import Path
import statistics

from backend.benchmarking import finite_number, plate_key
from backend.validators import validate_plate_text

FIELDS = ('sample_id', 'image_path', 'image_sha256', 'group_id', 'split', 'condition',
          'expected_action', 'expected_plate', 'label_source', 'labeler', 'reviewer', 'reviewed_at')


def sha256(path):
    with Path(path).open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def load_manifest(path: Path) -> list[dict]:
    path = path.resolve()
    with path.open(encoding='utf-8-sig', newline='') as handle:
        reader = csv.DictReader(handle)
        missing = set(FIELDS) - set(reader.fieldnames or ())
        if missing:
            raise ValueError('Missing manifest columns: ' + ', '.join(sorted(missing)))
        rows = [{k: (v or '').strip() for k, v in row.items() if k} for row in reader]
    if not rows:
        raise ValueError('Manifest is empty; no accuracy can be measured.')
    ids, hashes, groups, plates = set(), set(), {}, {}
    for row in rows:
        ident = row['sample_id']
        if not ident or ident in ids:
            raise ValueError('Missing or duplicate sample_id')
        ids.add(ident)
        image = (path.parent / row['image_path']).resolve()
        if not row['image_path'] or not image.is_file():
            raise ValueError(f'{ident}: missing image file')
        digest = sha256(image)
        if digest != row['image_sha256']:
            raise ValueError(f'{ident}: image hash mismatch; freeze the reviewed image')
        if digest in hashes:
            raise ValueError(f'{ident}: duplicate image would inflate sample count')
        hashes.add(digest)
        group, split = row['group_id'], row['split']
        if not group or split not in {'development', 'test'} or not row['condition']:
            raise ValueError(f'{ident}: group_id, split and condition are required')
        if groups.setdefault(group, split) != split:
            raise ValueError(f'{ident}: group leaks across development/test splits')
        if row['label_source'] != 'human' or not row['labeler'] or not row['reviewer'] or row['labeler'].casefold() == row['reviewer'].casefold():
            raise ValueError(f'{ident}: two distinct human label/review identities are required')
        try:
            datetime.fromisoformat(row['reviewed_at'])
        except ValueError:
            raise ValueError(f'{ident}: reviewed_at must be an ISO date/time') from None
        action, expected = row['expected_action'], row['expected_plate']
        if action == 'read':
            validate_plate_text(expected)
            key = plate_key(expected)
            if plates.setdefault(key, split) != split:
                raise ValueError(f'{ident}: same vehicle plate appears in development and test')
        elif action != 'abstain' or expected:
            raise ValueError(f'{ident}: choose read with a full plate, or abstain with a blank plate')
        row['_image'] = str(image)
    return rows


def wilson(successes, total):
    if not total:
        return None
    z = 1.96
    p = successes / total
    denominator = 1 + z*z/total
    center = (p + z*z/(2*total)) / denominator
    radius = z * math.sqrt(p*(1-p)/total + z*z/(4*total*total)) / denominator
    return [max(0., center-radius), min(1., center+radius)]


def evaluate_predictions(manifest: list[dict], predictions: list[dict], *, split='test') -> dict:
    rows = [row for row in manifest if row['split'] == split]
    if not rows:
        raise ValueError(f'No samples in split {split}')
    mapping = {}
    for prediction in predictions:
        ident = prediction.get('sample_id')
        if ident in mapping:
            raise ValueError('Duplicate prediction id')
        mapping[ident] = prediction
    if set(mapping) != {row['sample_id'] for row in rows}:
        raise ValueError('Predictions must cover every selected sample exactly once, including errors')
    samples = []
    for row in rows:
        prediction = mapping[row['sample_id']]
        latency = finite_number(prediction.get('latency_ms'))
        if latency is None:
            raise ValueError('Every inference attempt needs a finite nonnegative latency')
        if not isinstance(prediction.get('accepted'), bool):
            raise ValueError('accepted must be a boolean, not a truthy string')
        predicted = str(prediction.get('predicted_plate') or '').strip()
        accepted = prediction['accepted']
        if accepted and (not predicted or prediction.get('error')):
            raise ValueError('An empty or failed prediction cannot be accepted')
        readable = row['expected_action'] == 'read'
        match = readable and bool(predicted) and plate_key(row['expected_plate']) == plate_key(predicted)
        samples.append({
            'sample_id': row['sample_id'], 'group_id': row['group_id'], 'condition': row['condition'],
            'expected_action': row['expected_action'], 'expected_plate': row['expected_plate'],
            'predicted_plate': predicted, 'accepted': accepted, 'exact_plate_match': match,
            'false_accept': accepted and not match, 'latency_ms': latency,
            'error': prediction.get('error'), 'engine': prediction.get('engine', 'unknown'),
            'correct_decision': not prediction.get('error') and (match and accepted if readable else not accepted),
        })

    def summarize(items):
        n = len(items)
        readable = sum(x['expected_action'] == 'read' for x in items)
        exact = sum(x['exact_plate_match'] for x in items)
        accepted = sum(x['accepted'] for x in items)
        wrong = sum(x['false_accept'] for x in items)
        negative = n - readable
        safe = sum(x['expected_action'] == 'abstain' and x['correct_decision'] for x in items)
        latency = sorted(x['latency_ms'] for x in items)
        return {
            'samples': n, 'groups': len({x['group_id'] for x in items}), 'readable': readable,
            'expected_abstentions': negative, 'accepted': accepted, 'false_accepts': wrong,
            'errors': sum(bool(x['error']) for x in items),
            'exact_plate_accuracy': exact/readable if readable else None,
            'exact_plate_wilson95': wilson(exact, readable),
            'false_accept_rate_all': wrong/n,
            'false_accept_rate_accepted': wrong/accepted if accepted else None,
            'abstention_rate': (n-accepted)/n, 'safe_abstention_rate': safe/negative if negative else None,
            'correct_decision_rate': sum(x['correct_decision'] for x in items)/n,
            'median_latency_ms': statistics.median(latency),
            'p95_latency_ms': latency[math.ceil(.95*n)-1], 'max_latency_ms': latency[-1],
        }
    return {
        'split': split, 'summary': summarize(samples),
        'conditions': {condition: summarize([s for s in samples if s['condition'] == condition])
                       for condition in sorted({s['condition'] for s in samples})},
        'samples': samples,
        'limitations': 'Human review is declared metadata, not independently verified by software. Wilson intervals assume independent samples; grouped/derived images are correlated. No automatic academic grade.',
    }
