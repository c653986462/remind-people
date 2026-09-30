"""Validate a backend and web-only update before the trusted installer touches production."""
import hashlib
import json
from pathlib import Path, PurePosixPath
import sys


def verify(root: Path) -> dict:
    root = root.resolve()
    manifest = json.loads((root / 'server-release.json').read_text(encoding='utf-8'))
    if not str(manifest.get('run_id', '')).isdigit():
        raise ValueError('Invalid server release run id')
    hashes = manifest['files']
    required = {
        'app/main.py', 'app/models.py', 'app/services.py', 'requirements.txt',
        'frontend/dist/index.html', 'frontend/dist/download/index.html',
        'deploy/setup-email-reminders-update.sh',
    }
    if not required.issubset(hashes):
        raise ValueError('Incomplete server release')
    actual = {path.relative_to(root).as_posix() for path in root.rglob('*') if path.is_file()}
    if actual != set(hashes) | {'server-release.json'}:
        raise ValueError('Unexpected or missing files')
    for relative, digest in hashes.items():
        name = PurePosixPath(relative)
        if name.is_absolute() or '..' in name.parts or '\\' in relative or name.parts[0] not in {'app', 'frontend', 'deploy', 'requirements.txt'}:
            raise ValueError('Unsafe server release path')
        if any(part == '.env' or part.startswith('.env.') for part in name.parts):
            raise ValueError('Secrets must not be included in server releases')
        path = root / relative
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise ValueError('Symlinks are not allowed')
        with path.open('rb') as handle:
            calculated = hashlib.file_digest(handle, 'sha256').hexdigest()
        if calculated != digest:
            raise ValueError(f'Checksum mismatch: {relative}')
    return manifest


if __name__ == '__main__':
    result = verify(Path(sys.argv[1]))
    print(f"Verified server release run {result['run_id']}: backend + web")
