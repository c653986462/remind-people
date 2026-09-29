"""Verify a full release without dependencies, SMTP credentials, or network calls."""
import base64
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sys


def verify(root: Path) -> dict:
    root = root.resolve()
    manifest = json.loads((root / 'release.json').read_text(encoding='utf-8'))
    version = manifest['version']
    if not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise ValueError('Invalid release version')
    installer = manifest['installer']
    if installer != f'证事 Setup {version}.exe':
        raise ValueError('Installer/version mismatch')
    required = {
        'app/main.py', 'app/email_service.py', 'requirements.txt',
        'frontend/dist/index.html', 'frontend/dist/download/index.html',
        'deploy/setup-full-update.sh', 'deploy/setup-email-reminders-update.sh',
        'deploy/verify-full-release.py', 'desktop-updates/latest.yml',
        f'desktop-updates/{installer}', f'desktop-updates/{installer}.blockmap',
    }
    hashes = manifest['files']
    if not required.issubset(hashes):
        raise ValueError('Incomplete release: backend, website, and desktop are all required')
    actual = {path.relative_to(root).as_posix() for path in root.rglob('*') if path.is_file()}
    if actual != set(hashes) | {'release.json'}:
        raise ValueError('Unexpected or missing files')
    for relative, digest in hashes.items():
        name = PurePosixPath(relative)
        if name.is_absolute() or '..' in name.parts or '\\' in relative:
            raise ValueError('Unsafe release path')
        if name.parts[0] not in {'app', 'frontend', 'deploy', 'desktop-updates', 'requirements.txt'}:
            raise ValueError('Unexpected release directory')
        if any(part == '.env' or part.startswith('.env.') for part in name.parts):
            raise ValueError('Secrets must not be included in releases')
        path = root / relative
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise ValueError('Symlinks are not allowed')
        with path.open('rb') as handle:
            calculated = hashlib.file_digest(handle, 'sha256').hexdigest()
        if calculated != digest:
            raise ValueError(f'Checksum mismatch: {relative}')
    latest = (root / 'desktop-updates/latest.yml').read_text(encoding='utf-8')
    exe = root / 'desktop-updates' / installer
    with exe.open('rb') as handle:
        sha512 = base64.b64encode(hashlib.file_digest(handle, 'sha512').digest()).decode()
    expected = [f'version: {version}', f'path: {installer}', f'sha512: {sha512}', f'    size: {exe.stat().st_size}']
    if not all(line in latest.splitlines() for line in expected):
        raise ValueError('Desktop update manifest is stale or invalid')
    return manifest


if __name__ == '__main__':
    result = verify(Path(sys.argv[1]))
    print(f"Verified full release {result['version']}: backend + web + download site + desktop")
