"""Unprivileged, bounded artifact pull. The GitHub token never leaves the runner."""
import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import time
from urllib.parse import urlsplit
import urllib.request
import urllib.error
import zipfile

MAX_BYTES = 512 * 1024 * 1024
INCOMING = Path('/var/lib/certificate-manager-ci/incoming')


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def valid_storage_url(url):
    parsed = urlsplit(url)
    if (parsed.scheme != 'https' or not parsed.hostname
            or not parsed.hostname.endswith('.blob.core.windows.net')
            or parsed.username or parsed.password or parsed.port not in (None, 443)):
        raise ValueError('Unexpected artifact storage endpoint.')


def file_digest(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        while chunk := stream.read(1024 * 1024):
            result.update(chunk)
    return result.hexdigest()


def unpack(zip_path, stage, archive_name, expected_digest):
    """Never extract paths supplied by ZIP; accept precisely two regular files."""
    with zipfile.ZipFile(zip_path) as contents:
        entries = contents.infolist()
        expected_names = {archive_name, archive_name + '.sha256'}
        if len(entries) != 2 or {entry.filename for entry in entries} != expected_names:
            raise ValueError('Unexpected artifact ZIP members.')
        for entry in entries:
            mode = entry.external_attr >> 16
            if (entry.is_dir() or entry.flag_bits & 1 or stat.S_ISLNK(mode)
                    or (stat.S_IFMT(mode) and not stat.S_ISREG(mode))):
                raise ValueError('Artifact members must be regular unencrypted files.')
        archive = contents.getinfo(archive_name)
        sidecar = contents.getinfo(archive_name + '.sha256')
        if not 0 < archive.file_size <= MAX_BYTES or sidecar.file_size > 1024:
            raise ValueError('Artifact members exceed bounds.')
        advertised = contents.read(sidecar).decode('ascii').split()[0].lower()
        if advertised != expected_digest:
            raise ValueError('Archive digest sidecar differs from runner digest.')
        target = stage / 'verified.tar.gz'
        with contents.open(archive) as source, target.open('xb') as output:
            shutil.copyfileobj(source, output, 1024 * 1024)
        if file_digest(target) != expected_digest:
            raise ValueError('Archive digest mismatch.')
        return target


def download(payload, stage):
    size = payload['size']
    if type(size) is not int or not 0 < size <= MAX_BYTES:
        raise ValueError('Invalid artifact size.')
    valid_storage_url(payload['url'])
    start = time.monotonic()
    # Open all signed range requests promptly, before the short-lived URL expires.
    workers = 16
    def part(index):
        left, right = size * index // workers, size * (index + 1) // workers - 1
        part_path = stage / str(index)
        if part_path.is_symlink() or (part_path.exists() and not part_path.is_file()):
            raise ValueError('Invalid partial artifact file.')
        previous = part_path.stat().st_size if part_path.exists() else 0
        if previous > right - left + 1:
            raise ValueError('Partial artifact range exceeds size.')
        if previous == right - left + 1:
            return
        request_left = left + previous
        request = urllib.request.Request(payload['url'], headers={'Range': f'bytes={request_left}-{right}'})
        opener = urllib.request.build_opener(NoRedirect)
        count = previous
        with opener.open(request, timeout=30) as response, part_path.open('ab', buffering=0) as output:
            if response.status != 206 or response.headers.get('Content-Range') != f'bytes {request_left}-{right}/{size}':
                raise ValueError('Artifact range response mismatch.')
            while True:
                if time.monotonic() - start > 540:
                    raise TimeoutError('Artifact pull deadline.')
                chunk = response.read(16384)
                if not chunk:
                    break
                count += len(chunk)
                if count > right - left + 1:
                    raise ValueError('Artifact range exceeds size.')
                output.write(chunk)
            if count != right - left + 1:
                raise ValueError('Truncated artifact range.')
    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(part, range(workers)))
    zip_path = stage / 'artifact.zip'
    if zip_path.is_symlink() or (zip_path.exists() and not zip_path.is_file()):
        raise ValueError('Invalid assembled artifact file.')
    with zip_path.open('wb') as output:
        for index in range(workers):
            with (stage / str(index)).open('rb') as source:
                shutil.copyfileobj(source, output, 1024 * 1024)
    if file_digest(zip_path) != payload['zip_digest']:
        raise ValueError('Artifact ZIP digest mismatch.')
    return zip_path


def clear_cache(stage):
    if (stage.parent != INCOMING or not re.fullmatch(r'artifact-pull-release-\d+-2-[a-f0-9]{16}', stage.name)
            or stage.resolve(strict=True) != stage or stage.is_symlink()):
        raise ValueError('Invalid artifact cache directory.')
    allowed = {str(index) for index in range(16)} | {'artifact.zip', 'verified.tar.gz'}
    entries = list(stage.iterdir())
    if any(entry.name not in allowed or entry.is_symlink() or not entry.is_file() for entry in entries):
        raise ValueError('Unexpected artifact cache entry.')
    for entry in entries:
        entry.unlink()
    stage.rmdir()


def remote(payload):
    if os.getuid() == 0:
        raise ValueError('Artifact downloading must not run as root.')
    target = Path(payload['target'])
    if (target.parent != INCOMING or INCOMING.resolve(strict=True) != INCOMING
            or not re.fullmatch(r'release-\d+-2\.tar\.gz', target.name) or target.is_symlink()):
        raise ValueError('Invalid incoming artifact target.')
    if not re.fullmatch(r'certificate-manager-full-[A-Za-z0-9.-]+\.tar\.gz', payload['archive']):
        raise ValueError('Invalid artifact archive name.')
    for key in ('zip_digest', 'archive_digest'):
        if not re.fullmatch(r'[a-f0-9]{64}', payload[key]):
            raise ValueError('Invalid digest.')
    if type(payload['size']) is not int or not 0 < payload['size'] <= MAX_BYTES:
        raise ValueError('Invalid artifact size.')
    if target.is_file() and file_digest(target) == payload['archive_digest']:
        print('Matching complete artifact already staged.', flush=True)
        return
    if shutil.disk_usage(INCOMING).free < 3 * payload['size'] + 64 * 1024 * 1024:
        raise ValueError('Insufficient artifact staging space.')
    stage = INCOMING / ('artifact-pull-' + target.name[:-7] + '-' + payload['zip_digest'][:16])
    if stage.is_symlink():
        raise ValueError('Invalid artifact cache.')
    stage.mkdir(mode=0o700, exist_ok=True)
    if stage.resolve(strict=True) != stage or not stage.is_dir():
        raise ValueError('Invalid artifact cache directory.')
    # No URL/token is saved. Only range bytes remain when the bounded pull times out.
    try:
        zip_path = download(payload, stage)
    except ValueError:
        clear_cache(stage)
        raise
    try:
        partial = stage / 'verified.tar.gz'
        if partial.is_symlink():
            raise ValueError('Invalid staged archive.')
        if partial.is_file():
            partial.unlink()
        verified = unpack(zip_path, stage, payload['archive'], payload['archive_digest'])
        os.replace(verified, target)
    finally:
        clear_cache(stage)
    print('Server pulled and verified the complete artifact.', flush=True)


def api_request(url, token, redirect=False):
    request = urllib.request.Request(url, headers={
        'Authorization': 'Bearer ' + token,
        'Accept': 'application/vnd.github+json',
        'User-Agent': 'certificate-manager-artifact-pull',
    })
    opener = urllib.request.build_opener(NoRedirect)
    if redirect:
        try:
            opener.open(request, timeout=20).close()
        except urllib.error.HTTPError as response:
            if response.code == 302:
                url = response.headers.get('Location', '')
                valid_storage_url(url)
                return url
            raise
        raise ValueError('Missing artifact download redirect.')
    with opener.open(request, timeout=20) as response:
        return json.load(response)


def runner(arguments):
    archive, digest, target, *ssh_command = arguments
    repository = os.environ['GITHUB_REPOSITORY']
    run_id = os.environ['GITHUB_RUN_ID']
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository) or not run_id.isdigit():
        raise ValueError('Invalid GitHub repository/run.')
    token = os.environ['GH_ARTIFACT_TOKEN']
    root = f'https://api.github.com/repos/{repository}/actions'
    listing = api_request(f'{root}/runs/{run_id}/artifacts?per_page=100', token)
    candidates = [item for item in listing['artifacts']
                  if item['name'] == 'desktop-' + run_id and not item['expired']]
    if len(candidates) != 1:
        raise ValueError('Expected one current desktop artifact.')
    artifact = candidates[0]
    zip_digest = artifact.get('digest', '')
    if not re.fullmatch(r'sha256:[a-f0-9]{64}', zip_digest):
        raise ValueError('GitHub artifact digest unavailable.')
    signed_url = api_request(f"{root}/artifacts/{int(artifact['id'])}/zip", token, redirect=True)
    # Only a short-lived artifact-specific URL, never the API token, reaches SSH stdin.
    payload = dict(url=signed_url, size=artifact['size_in_bytes'], zip_digest=zip_digest[7:],
                   archive=archive, archive_digest=digest, target=target)
    code = base64.b64encode(Path(__file__).read_bytes()).decode('ascii')
    command = f"python3 -c \"import base64;exec(compile(base64.b64decode('{code}'),'<artifact-pull>','exec'))\" remote"
    child_environment = {key: value for key, value in os.environ.items() if key != 'GH_ARTIFACT_TOKEN'}
    result = subprocess.run(ssh_command + [command], input=json.dumps(payload), text=True,
                            timeout=590, check=False, env=child_environment)
    if result.returncode:
        raise ValueError('Server artifact pull did not complete.')


if __name__ == '__main__':
    try:
        if len(sys.argv) > 1 and sys.argv[1] == 'remote':
            payload = json.loads(sys.stdin.read(32769))
            remote(payload)
        else:
            runner(sys.argv[1:])
    except Exception as error:
        # Exception text can contain signed URLs; only print the class.
        print('Direct artifact pull unavailable: ' + type(error).__name__, file=sys.stderr)
        sys.exit(1)
