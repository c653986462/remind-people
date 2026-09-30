"""Reject an older CI server run before staging it over a newer release."""
import json
from pathlib import Path
import sys


def check(candidate: dict, current: dict):
    old = current.get('run_number')
    new = candidate.get('run_number')
    if new is not None and (not str(new).isdigit() or int(new) < 1):
        raise ValueError('Invalid candidate CI run number.')
    if old is None:
        return  # Bootstrap and administrator-approved manual releases have no CI number.
    if new is None or not str(old).isdigit() or not str(new).isdigit():
        raise ValueError('CI run number is missing or invalid; refusing an unordered publication.')
    if int(new) < int(old):
        raise ValueError('A newer CI server release is already active; refusing stale deployment.')
    if int(new) == int(old) and (candidate.get('run_id'), candidate.get('source_commit')) != (current.get('run_id'), current.get('source_commit')):
        raise ValueError('The same CI run number belongs to a different source or run.')


if __name__ == '__main__':
    current = Path(sys.argv[2])
    check(json.loads(Path(sys.argv[1]).read_text(encoding='utf-8')),
          json.loads(current.read_text(encoding='utf-8')) if current.exists() else {})
