#!/usr/bin/env python3
# Managed SQLite backups for certificate-manager.
"""Online SQLite snapshots; never imports the application or modifies its rows."""
from __future__ import annotations

import argparse
from contextlib import closing, contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import sqlite3
import sys
import tarfile
import tempfile
import time
import uuid

from dotenv import dotenv_values
from sqlalchemy.engine import make_url

LOG = logging.getLogger("certificate-database-backup")
NAME = re.compile(r"^certificates-(\d{8}T\d{12}Z)-[0-9a-f]{12}\.sqlite3$")
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def database_path(app_dir: Path) -> Path:
    """Match the deployed environment without logging secrets or creating a DB."""
    app_dir = app_dir.resolve(strict=True)
    config_file = app_dir / ".env"
    if not config_file.is_file():
        raise ValueError("Application .env is missing")
    value = os.environ.get("DATABASE_URL") or dotenv_values(config_file).get("DATABASE_URL")
    url = make_url(value or "sqlite:///./data/certificates.db")
    if url.get_backend_name() != "sqlite" or url.query or not url.database or url.database == ":memory:":
        raise ValueError("Backup requires a file-backed SQLite URL without query parameters")
    raw_path = Path(url.database)
    path = raw_path if raw_path.is_absolute() else app_dir / raw_path
    path = path.resolve(strict=True)
    # The supplied systemd sandbox permits only this deployed data directory.
    if not path.is_relative_to((app_dir / "data").resolve(strict=True)) or not path.is_file():
        raise ValueError("Database must be an existing file inside the application data directory")
    return path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def integrity_check(path: Path) -> None:
    if path.is_symlink() or not path.is_file():
        raise ValueError("Database file is missing or is a symlink")
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=10)) as db:
        result = db.execute("PRAGMA integrity_check").fetchall()
        if result != [("ok",)]:
            raise ValueError("SQLite integrity check failed")
        count = db.execute("SELECT count(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
        if not count:
            raise ValueError("Refusing to accept an empty database without tables")


def sidecar_path(path: Path) -> Path:
    return path.with_suffix(".json")


def attachments_bundle_path(path: Path) -> Path:
    return path.with_suffix(".attachments.tar.gz")


def verify_bundle(path: Path, attachment_bundle: Path, database_hash: str,
                  database_size: int) -> int:
    from app.attachments import storage_path

    entries = []
    with tempfile.TemporaryDirectory(prefix="certificate-backup-verify-") as directory:
        staged_database = Path(directory) / "certificates.db"
        with tarfile.open(attachment_bundle, mode="r:gz") as archive:
            members = archive.getmembers()
            by_name = {member.name: member for member in members}
            if len(by_name) != len(members) or "database.sqlite3" not in by_name or "attachments-manifest.json" not in by_name:
                raise ValueError("Attachments bundle contains missing or duplicate entries")
            for member in members:
                if not member.isfile() or member.name.startswith("/") or ".." in Path(member.name).parts:
                    raise ValueError("Attachments bundle contains an unsafe path")
            db_member = by_name["database.sqlite3"]
            source = archive.extractfile(db_member)
            if source is None:
                raise ValueError("Database is missing from attachments bundle")
            digest = hashlib.sha256()
            size = 0
            with staged_database.open("xb") as destination:
                while chunk := source.read(1024 * 1024):
                    destination.write(chunk)
                    digest.update(chunk)
                    size += len(chunk)
            if size != database_size or digest.hexdigest() != database_hash:
                raise ValueError("Database in attachments bundle does not match the backup")
            manifest_member = archive.extractfile(by_name["attachments-manifest.json"])
            if manifest_member is None:
                raise ValueError("Attachments manifest is missing")
            bundle_manifest = json.load(manifest_member)
            if not isinstance(bundle_manifest, dict) or bundle_manifest.get("format_version") != 1:
                raise ValueError("Attachments manifest format is invalid")
            entries = bundle_manifest.get("attachments")
            if not isinstance(entries, list):
                raise ValueError("Attachments list is invalid")
            expected_members = {"database.sqlite3", "attachments-manifest.json"}
            attachment_keys = set()
            for entry in entries:
                if not isinstance(entry, dict):
                    raise ValueError("Attachment manifest entry is invalid")
                relative = entry.get("path")
                parts = Path(str(relative)).parts
                if (len(parts) != 4 or parts[0] != "attachments" or not parts[1].isdigit()
                        or parts[2] not in {"pdf", "image"}):
                    raise ValueError("Attachment path is invalid")
                key = (int(parts[1]), parts[2], parts[3])
                if key in attachment_keys:
                    raise ValueError("Duplicate attachment path")
                attachment_keys.add(key)
                storage_path(PROJECT_ROOT / "data" / "attachments", key[0], key[1], key[2])
                member = by_name.get(relative)
                if member is None or not member.isfile() or member.size != entry.get("size"):
                    raise ValueError("Attachment is missing or has a size mismatch")
                content = archive.extractfile(member)
                if content is None:
                    raise ValueError("Attachment data cannot be read")
                item_digest = hashlib.sha256()
                item_size = 0
                while chunk := content.read(1024 * 1024):
                    item_digest.update(chunk)
                    item_size += len(chunk)
                if item_size != entry.get("size") or item_digest.hexdigest() != entry.get("sha256"):
                    raise ValueError("Attachment checksum verification failed")
                expected_members.add(relative)
            if set(by_name) != expected_members:
                raise ValueError("Attachments bundle has unexpected files")
            integrity_check(staged_database)
            with closing(sqlite3.connect(staged_database)) as db:
                tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if "record_attachments" in tables:
                    database_keys = {
                        (int(record_id), kind, storage_key): (int(size), sha)
                        for record_id, kind, storage_key, size, sha in db.execute(
                            "SELECT record_id, kind, storage_key, size_bytes, sha256 FROM record_attachments"
                        )
                    }
                    listed_keys = {
                        (int(Path(entry["path"]).parts[1]), Path(entry["path"]).parts[2], Path(entry["path"]).parts[3]):
                        (entry["size"], entry["sha256"])
                        for entry in entries
                    }
                    if database_keys != listed_keys:
                        raise ValueError("Attachments bundle does not match database records")
    return len(entries)


def verify_backup(path: Path) -> dict:
    integrity_check(path)
    manifest_path = sidecar_path(path)
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise ValueError("Backup manifest is missing or is a symlink")
    metadata = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(metadata, dict) or metadata.get("format_version") not in {1, 2} or metadata.get("file") != path.name:
        raise ValueError("Backup manifest does not match the file")
    if metadata.get("size") != path.stat().st_size or metadata.get("sha256") != sha256(path):
        raise ValueError("Backup size or SHA-256 check failed")
    if metadata["format_version"] == 2:
        archive = attachments_bundle_path(path)
        if (metadata.get("attachments_file") != archive.name or not archive.is_file()
                or archive.is_symlink() or metadata.get("attachments_size") != archive.stat().st_size
                or metadata.get("attachments_sha256") != sha256(archive)):
            raise ValueError("Attachments bundle checksum verification failed")
        metadata["attachments_count"] = verify_bundle(
            path, archive, metadata["sha256"], metadata["size"]
        )
    return metadata


@contextmanager
def backup_lock(directory: Path):
    """OS lock released automatically even if the process is killed."""
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(directory / ".backup.lock", flags, 0o600)
    try:
        if os.name == "nt":
            import msvcrt
            if os.fstat(descriptor).st_size == 0:
                os.write(descriptor, b"0")
            os.lseek(descriptor, 0, os.SEEK_SET)
            msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(descriptor)


def prune_backups(directory: Path, current: Path, retain_days: int, now: datetime) -> int:
    """Only prune this program's complete, strictly named backup pairs."""
    cutoff = now - timedelta(days=retain_days)
    removed = 0
    for path in directory.iterdir():
        match = NAME.fullmatch(path.name)
        if not match or path == current or path.is_symlink() or not path.is_file():
            continue
        manifest = sidecar_path(path)
        if manifest.is_symlink() or not manifest.is_file():
            continue
        try:
            timestamp = datetime.strptime(match[1], "%Y%m%dT%H%M%S%fZ").replace(tzinfo=timezone.utc)
            metadata = json.loads(manifest.read_text(encoding="utf-8"))
            if (not isinstance(metadata, dict) or timestamp >= cutoff
                    or metadata.get("format_version") not in {1, 2} or metadata.get("file") != path.name):
                continue
        except (ValueError, TypeError, OSError):
            LOG.warning("Skipping unrecognized retention candidate: %s", path.name)
            continue
        # Neither globs nor recursive deletion are used; unrelated files stay untouched.
        path.unlink()
        manifest.unlink()
        if metadata.get("format_version") == 2:
            bundle_name = metadata.get("attachments_file")
            bundle = directory / bundle_name if isinstance(bundle_name, str) and Path(bundle_name).name == bundle_name else None
            if bundle is not None and not bundle.is_symlink() and bundle.is_file():
                bundle.unlink()
        removed += 1
        LOG.info("Removed expired backup: %s", path.name)
    return removed


def create_backup(source: Path, directory: Path, retain_days: int = 30,
                  timeout_seconds: float = 600) -> Path:
    if retain_days < 1 or timeout_seconds <= 0:
        raise ValueError("Retention and backup timeout must be positive")
    if source.is_symlink() or not source.is_file():
        raise ValueError("Source database is missing or is a symlink")
    if directory.is_symlink():
        raise ValueError("Backup directory must not be a symlink")
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    directory = directory.resolve(strict=True)
    if source.resolve().is_relative_to(directory):
        raise ValueError("Backup directory must not contain the source database")
    if os.name != "nt":
        if directory.stat().st_uid != os.geteuid():
            raise ValueError("Backup directory must belong to the backup process owner")
        directory.chmod(0o700)
    from app.attachments import attachment_storage_lock, storage_path

    with attachment_storage_lock(source.parent), backup_lock(directory):
        now = datetime.now(timezone.utc)
        basename = f"certificates-{now.strftime('%Y%m%dT%H%M%S%fZ')}-{uuid.uuid4().hex[:12]}"
        final_path = directory / (basename + ".sqlite3")
        final_sidecar = sidecar_path(final_path)
        final_bundle = attachments_bundle_path(final_path)
        deadline = time.monotonic() + timeout_seconds

        def progress(_status: int, _remaining: int, _total: int) -> None:
            if time.monotonic() > deadline:
                raise TimeoutError("Online database backup exceeded its timeout")

        with tempfile.TemporaryDirectory(prefix=".staging-", dir=directory) as staging:
            staged = Path(staging) / final_path.name
            staged_sidecar = sidecar_path(staged)
            staged_bundle = attachments_bundle_path(staged)
            with closing(sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True, timeout=10)) as src:
                with closing(sqlite3.connect(staged)) as dst:
                    src.backup(dst, pages=256, progress=progress, sleep=0.1)
                    # Ensure all copied data is in one standalone file, including WAL data.
                    dst.execute("PRAGMA journal_mode=DELETE").fetchone()
            staged.chmod(0o600)
            integrity_check(staged)

            attachment_entries = []
            with closing(sqlite3.connect(staged)) as snapshot:
                tables = {row[0] for row in snapshot.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                rows = snapshot.execute(
                    "SELECT record_id, kind, storage_key, size_bytes, sha256 FROM record_attachments"
                ).fetchall() if "record_attachments" in tables else []
            base = source.parent / "attachments"
            if base.is_symlink():
                raise ValueError("附件根目录不能是符号链接")
            if rows and not base.is_dir():
                raise ValueError("数据库中有附件记录，但服务器附件目录不存在")
            files_for_archive = []
            for record_id, kind, storage_key, expected_size, expected_hash in rows:
                member_name = f"attachments/{int(record_id)}/{kind}/{storage_key}"
                attachment = storage_path(base.resolve(), int(record_id), kind, storage_key)
                if attachment.is_symlink() or not attachment.is_file():
                    raise ValueError(f"附件文件缺失：{member_name}")
                size = attachment.stat().st_size
                digest = sha256(attachment)
                if size != int(expected_size) or digest != expected_hash:
                    raise ValueError(f"附件文件与数据库校验信息不符：{member_name}")
                attachment_entries.append({"path": member_name, "size": size, "sha256": digest})
                files_for_archive.append((attachment, member_name))

            bundle_manifest = {"format_version": 1, "attachments": attachment_entries}
            with tarfile.open(staged_bundle, mode="w:gz") as archive:
                archive.add(staged, arcname="database.sqlite3", recursive=False)
                for attachment, member_name in files_for_archive:
                    archive.add(attachment, arcname=member_name, recursive=False)
                payload = json.dumps(bundle_manifest, ensure_ascii=False, sort_keys=True).encode("utf-8") + b"\n"
                member = tarfile.TarInfo("attachments-manifest.json")
                member.size = len(payload)
                member.mode = 0o600
                archive.addfile(member, __import__("io").BytesIO(payload))
            staged_bundle.chmod(0o600)
            metadata = {
                "format_version": 2, "file": final_path.name,
                "created_at": now.isoformat(), "sha256": sha256(staged),
                "size": staged.stat().st_size, "integrity_check": "ok",
                "attachments_file": final_bundle.name,
                "attachments_sha256": sha256(staged_bundle),
                "attachments_size": staged_bundle.stat().st_size,
                "attachments_count": len(attachment_entries),
            }
            with staged_sidecar.open("x", encoding="utf-8") as stream:
                json.dump(metadata, stream, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            staged_sidecar.chmod(0o600)
            with staged.open("r+b") as stream:
                os.fsync(stream.fileno())
            with staged_bundle.open("r+b") as stream:
                os.fsync(stream.fileno())
            # Publish only after the SQLite snapshot, attachment archive and hashes pass.
            verify_backup(staged)
            os.rename(staged_bundle, final_bundle)
            os.rename(staged_sidecar, final_sidecar)
            os.rename(staged, final_path)
            if os.name != "nt":
                descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
        LOG.info("Backup succeeded: %s; bytes=%s; attachments=%s; integrity=ok; SHA256=%s",
                 final_path.name, metadata["size"], metadata["attachments_count"], metadata["sha256"])
        removed = prune_backups(directory, final_path, retain_days, now)
        LOG.info("Retention complete: days=%s; expired_backup_sets_removed=%s", retain_days, removed)
        return final_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-dir", type=Path, default=Path("/opt/certificate-manager"))
    parser.add_argument("--backup-dir", type=Path, default=Path("/var/backups/certificate-manager"))
    parser.add_argument("--retain-days", type=int, default=30)
    parser.add_argument("--verify", type=Path, help="Verify a backup and its SHA-256 manifest without restoring")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    os.umask(0o077)
    try:
        if args.verify:
            verify_backup(args.verify)
            LOG.info("Backup verification passed: %s", args.verify.name)
        else:
            source = database_path(args.app_dir)
            create_backup(source, args.backup_dir, args.retain_days)
        return 0
    except Exception as exc:
        # Deliberately omit dotenv content, DATABASE_URL, credentials and data rows.
        LOG.error("Backup/verification failed (%s): %s", type(exc).__name__, exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
