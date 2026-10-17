"""Check source hashes, recorded JSON-pointer values, trace IDs and generated docs."""
import hashlib
import json
from pathlib import Path
import sys
from collections import Counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from physical_model.snapshot import load_snapshot
from render_assumption_docs import render


def pointer(document, path):
    for part in path.split('/')[1:] if path else []:
        part = part.replace('~1', '/').replace('~0', '~')
        document = document[int(part)] if isinstance(document, list) else document[part]
    return document


def audit():
    register = json.loads((ROOT / 'physical_model/data/assumptions.json').read_text())
    rows = register['assumptions'] + register['source_rules']
    ids = [row['id'] for row in rows]
    errors = []
    if len(set(ids)) != len(ids):
        errors.append('Duplicate assumption/source-rule IDs')
    for source in register['source_files']:
        path = ROOT / source['file']
        if hashlib.sha256(path.read_bytes()).hexdigest() != source['sha256']:
            errors.append('Source bytes changed: ' + source['file'])
    checked_refs = 0
    for row in rows + register['unresolved_inputs']:
        for source in row.get('source_refs', []):
            try:
                actual = pointer(json.loads((ROOT / source['file']).read_text()), source['pointer'])
                if actual != source['value']:
                    errors.append(f"{row['id']}: stale source value {source['file']}#{source['pointer']}")
                checked_refs += 1
            except (KeyError, IndexError, OSError, ValueError) as exc:
                errors.append(f"{row['id']}: cannot resolve source reference: {exc}")
        for target in row.get('implementation_refs', []):
            if not (ROOT / target.split(':')[0]).is_file():
                errors.append('Missing implementation file: ' + target)
    counts = dict(Counter(row['classification'] for row in rows))
    if counts != register['summary']['classification_counts']:
        errors.append('Classification counts are stale')
    for file, expected in render(register).items():
        if not (ROOT / file).exists() or (ROOT / file).read_bytes() != expected.encode('utf-8'):
            errors.append('Generated document is stale: ' + file)
    reports = [load_snapshot()] + [load_snapshot(runtime_path=p) for p in sorted((ROOT / 'scenarios').glob('*.json'))]
    for report in reports:
        missing = set(report['assumption_ids_used']) - set(ids)
        if missing:
            errors.append('Unregistered trace IDs: ' + ', '.join(sorted(missing)))
    if errors:
        raise SystemExit('\n'.join(errors))
    print(f"PASS: {len(register['source_files'])} source hashes, {checked_refs} source pointers, "
          f"{len(rows)} register records, {len(reports)} report traces, and generated docs.")


if __name__ == '__main__':
    audit()
