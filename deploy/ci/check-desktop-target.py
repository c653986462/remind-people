"""Require the corresponding server run and an immutable, non-decreasing EXE."""
import json
from pathlib import Path
import re
import sys


def check(candidate: dict, active: dict, latest: str):
    source = candidate.get('source_commit', '')
    run_id = str(candidate.get('run_id', ''))
    if not re.fullmatch(r'(?:[a-f0-9]{40}|[a-f0-9]{64})', source) or not run_id.isdigit():
        raise ValueError('Desktop artifact must identify its CI source and run.')
    if active.get('source_commit') != source or str(active.get('run_id', '')) != run_id:
        raise ValueError('The matching server run is not active; refusing a stale or premature desktop publication.')
    match = re.search(r'^version:\s*(\d+\.\d+\.\d+)\s*$', latest, re.M)
    if not match:
        raise ValueError('Cannot read the currently published desktop version.')
    version = candidate.get('version', '')
    if not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise ValueError('Invalid desktop version.')
    if tuple(map(int, version.split('.'))) < tuple(map(int, match[1].split('.'))):
        raise ValueError('Refusing to downgrade the desktop version.')


if __name__ == '__main__':
    root, active, update_dir = map(Path, sys.argv[1:])
    check(json.loads((root / 'release.json').read_text(encoding='utf-8')),
          json.loads((active / 'server-release.json').read_text(encoding='utf-8')),
          (update_dir / 'latest.yml').read_text(encoding='utf-8'))
