"""Validate and extract a deployment archive into a new private directory."""
from pathlib import Path, PurePosixPath
import tarfile
import sys

ALLOWED_ROOTS = {'app', 'frontend', 'deploy', 'desktop-updates', 'release.json', 'server-release.json', 'requirements.txt'}


def safe_extract(archive: Path, destination: Path):
    if destination.exists():
        raise ValueError('Extraction destination must not already exist')
    with tarfile.open(archive, 'r:gz') as source:
        members = source.getmembers()
        if len(members) > 20000 or sum(item.size for item in members) > 1024 * 1024 * 1024:
            raise ValueError('Release archive is too large')
        names = set()
        for member in members:
            name = PurePosixPath(member.name)
            if not name.parts or name.is_absolute() or '..' in name.parts or '\\' in member.name:
                raise ValueError('Unsafe archive path')
            if name.parts[0] not in ALLOWED_ROOTS or name.as_posix() in names:
                raise ValueError('Unexpected or duplicate archive path')
            if any(part == '.env' or part.startswith('.env.') for part in name.parts):
                raise ValueError('Secrets cannot be deployed in an archive')
            if not (member.isdir() or member.isfile()) or member.issym() or member.islnk():
                raise ValueError('Archive links and special files are forbidden')
            names.add(name.as_posix())
        destination.mkdir(mode=0o700)
        source.extractall(destination, members=members, filter='data')


if __name__ == '__main__':
    safe_extract(Path(sys.argv[1]), Path(sys.argv[2]))
