"""Private certificate attachment storage shared by uploads and backups."""
from contextlib import contextmanager
import os
from pathlib import Path
import re
import time


MAX_ATTACHMENT_BYTES = 15 * 1024 * 1024
MAX_ATTACHMENTS_PER_KIND = 9
CHUNK_SIZE = 1024 * 1024
_STORAGE_KEY = re.compile(r"^[0-9a-f]{32}\.(?:pdf|png|jpg|webp)$")


@contextmanager
def attachment_storage_lock(data_dir: Path = Path("data")):
    """Coordinate attachment mutations with the online database backup process."""
    data_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    lock_file = data_dir / ".attachment-storage.lock"
    flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(lock_file, flags, 0o600)
    try:
        if os.name == "nt":
            import msvcrt
            if os.fstat(descriptor).st_size == 0:
                os.write(descriptor, b"0")
            os.lseek(descriptor, 0, os.SEEK_SET)
            while True:
                try:
                    msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    time.sleep(0.05)
        else:
            import fcntl
            fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        os.close(descriptor)


def attachment_root(data_dir: Path = Path("data")) -> Path:
    root = data_dir / "attachments"
    if root.is_symlink():
        raise ValueError("附件目录不能是符号链接")
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if os.name != "nt":
        root.chmod(0o700)
    return root.resolve()


def storage_path(root: Path, record_id: int, kind: str, storage_key: str) -> Path:
    if kind not in {"pdf", "image"} or not _STORAGE_KEY.fullmatch(storage_key):
        raise ValueError("附件存储信息无效")
    record_dir = root / str(record_id)
    if record_dir.is_symlink():
        raise ValueError("附件记录目录不能是符号链接")
    kind_dir = record_dir / kind
    if kind_dir.is_symlink():
        raise ValueError("附件分类目录不能是符号链接")
    path = kind_dir / storage_key
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("附件路径无效")
    return path


def remove_storage_file(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    parent = path.parent
    if parent.is_dir() and not parent.is_symlink():
        try:
            parent.rmdir()
        except OSError:
            pass
        record_dir = parent.parent
        if record_dir.is_dir() and not record_dir.is_symlink():
            try:
                record_dir.rmdir()
            except OSError:
                pass
