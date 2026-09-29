from contextlib import closing
from datetime import datetime, timedelta, timezone
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sqlite3
import stat
import tempfile
import unittest
from unittest.mock import patch


MODULE_PATH = Path(__file__).resolve().parents[1] / "deploy/database-backup/backup.py"
SPEC = importlib.util.spec_from_file_location("database_backup", MODULE_PATH)
backup = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(backup)


class DatabaseBackupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="certificate-backup-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.app = self.root / "app"
        (self.app / "data").mkdir(parents=True)
        self.source = self.app / "data/certificates.db"
        self.destination = self.root / "backups"
        (self.app / ".env").write_text("DATABASE_URL=sqlite:///./data/certificates.db\n", encoding="utf-8")
        with closing(sqlite3.connect(self.source)) as db:
            db.execute("CREATE TABLE certificates(id INTEGER PRIMARY KEY, title TEXT)")
            db.execute("INSERT INTO certificates(title) VALUES ('证书测试')")
            db.commit()

    def old_backup(self):
        path = backup.create_backup(self.source, self.destination)
        old = datetime.now(timezone.utc) - timedelta(days=40)
        old_name = f"certificates-{old.strftime('%Y%m%dT%H%M%S%fZ')}-0123456789ab.sqlite3"
        target = path.with_name(old_name)
        manifest = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
        path.rename(target)
        path.with_suffix(".json").unlink()
        manifest["file"] = target.name
        manifest["created_at"] = old.isoformat()
        target.with_suffix(".json").write_text(json.dumps(manifest), encoding="utf-8")
        return target

    def test_backup_and_restore_in_isolated_database(self):
        path = backup.create_backup(self.source, self.destination)
        metadata = backup.verify_backup(path)
        self.assertEqual(metadata["sha256"], backup.sha256(path))
        self.assertEqual(metadata["size"], path.stat().st_size)
        self.assertEqual(metadata["integrity_check"], "ok")
        restored = self.root / "restored.db"
        shutil.copyfile(path, restored)
        with closing(sqlite3.connect(restored)) as db:
            self.assertEqual(db.execute("SELECT title FROM certificates").fetchall(), [("证书测试",)])
        if os.name != "nt":
            self.assertEqual(stat.S_IMODE(self.destination.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(path.with_suffix(".json").stat().st_mode), 0o600)

    def test_online_wal_snapshot_contains_committed_not_uncommitted_rows(self):
        with closing(sqlite3.connect(self.source)) as writer:
            writer.execute("PRAGMA journal_mode=WAL")
            writer.execute("PRAGMA wal_autocheckpoint=0")
            writer.execute("INSERT INTO certificates(title) VALUES ('WAL committed')")
            writer.commit()
            writer.execute("INSERT INTO certificates(title) VALUES ('uncommitted')")
            path = backup.create_backup(self.source, self.destination)
            with closing(sqlite3.connect(path)) as db:
                self.assertEqual(db.execute("SELECT title FROM certificates ORDER BY id").fetchall(),
                                 [("证书测试",), ("WAL committed",)])
                self.assertEqual(db.execute("PRAGMA journal_mode").fetchone()[0], "delete")
            self.assertFalse(path.with_name(path.name + "-wal").exists())
            writer.rollback()
        backup.verify_backup(path)

    def test_retention_deletes_only_old_managed_pairs_after_success(self):
        old = self.old_backup()
        unrelated = self.destination / "keep-me.db"
        unrelated.write_bytes(b"not a backup")
        unmatched = self.destination / "certificates-manual.sqlite3"
        unmatched.write_bytes(b"manual")
        old_without_manifest = self.destination / "certificates-20000101T000000000000Z-abcdefabcdef.sqlite3"
        old_without_manifest.write_bytes(b"no manifest")
        newest = backup.create_backup(self.source, self.destination)
        self.assertFalse(old.exists())
        self.assertFalse(old.with_suffix(".json").exists())
        self.assertTrue(newest.exists())
        self.assertTrue(unrelated.exists())
        self.assertTrue(unmatched.exists())
        self.assertTrue(old_without_manifest.exists())

    def test_failed_new_backup_does_not_delete_old_backups(self):
        old = self.old_backup()
        with patch.object(backup, "verify_backup", side_effect=ValueError("simulated check failure")):
            with self.assertRaises(ValueError):
                backup.create_backup(self.source, self.destination)
        self.assertTrue(old.exists())
        self.assertTrue(old.with_suffix(".json").exists())
        self.assertEqual(list(self.destination.glob("*.sqlite3")), [old])
        self.assertFalse(list(self.destination.glob(".staging-*")))

    def test_corruption_fails_without_publishing_or_pruning(self):
        old = self.old_backup()
        self.source.write_bytes(b"this is not a sqlite database")
        with self.assertRaises(sqlite3.DatabaseError):
            backup.create_backup(self.source, self.destination)
        self.assertTrue(old.exists())
        self.assertEqual(list(self.destination.glob("*.sqlite3")), [old])

    def test_hash_mismatch_and_missing_manifest_rejected(self):
        path = backup.create_backup(self.source, self.destination)
        with path.open("ab") as stream:
            stream.write(b"tamper")
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            backup.verify_backup(path)
        path.with_suffix(".json").unlink()
        with self.assertRaisesRegex(ValueError, "manifest"):
            backup.verify_backup(path)

    def test_missing_source_not_created(self):
        missing = self.app / "data/missing.db"
        with self.assertRaises(ValueError):
            backup.create_backup(missing, self.destination)
        self.assertFalse(missing.exists())
        self.assertFalse(self.destination.exists())

    def test_empty_database_rejected(self):
        self.source.unlink()
        with closing(sqlite3.connect(self.source)):
            pass
        with self.assertRaisesRegex(ValueError, "empty database"):
            backup.create_backup(self.source, self.destination)
        self.assertFalse(list(self.destination.glob("*.sqlite3")))

    def test_database_url_and_source_containment(self):
        with patch.dict(os.environ, {"DATABASE_URL": "sqlite:///./data/certificates.db"}):
            self.assertEqual(backup.database_path(self.app), self.source.resolve())
        for value in ("sqlite:///:memory:", "postgresql://localhost/db", "sqlite:///./data/certificates.db?mode=ro"):
            with patch.dict(os.environ, {"DATABASE_URL": value}):
                with self.assertRaises(ValueError):
                    backup.database_path(self.app)
        outside = self.root / "outside.db"
        shutil.copyfile(self.source, outside)
        with patch.dict(os.environ, {"DATABASE_URL": "sqlite:///" + outside.as_posix()}):
            with self.assertRaisesRegex(ValueError, "inside"):
                backup.database_path(self.app)
        with patch.dict(os.environ, {"DATABASE_URL": "sqlite:///./data/missing.db"}):
            with self.assertRaises(FileNotFoundError):
                backup.database_path(self.app)
        self.assertFalse((self.app / "data/missing.db").exists())

    def test_file_lock_excludes_concurrent_backup_and_releases(self):
        self.destination.mkdir()
        with backup.backup_lock(self.destination):
            with self.assertRaises(OSError):
                with backup.backup_lock(self.destination):
                    self.fail("Second process acquired the same backup lock")
        with backup.backup_lock(self.destination):
            pass

    def test_timeout_never_publishes_partial_database(self):
        with patch.object(backup.time, "monotonic", side_effect=[0, 100]):
            with self.assertRaises(TimeoutError):
                backup.create_backup(self.source, self.destination, timeout_seconds=1)
        self.assertFalse(list(self.destination.glob("*.sqlite3")))

    def test_unsafe_retention_or_backup_directory_rejected(self):
        with self.assertRaises(ValueError):
            backup.create_backup(self.source, self.destination, retain_days=0)
        with self.assertRaisesRegex(ValueError, "contain the source"):
            backup.create_backup(self.source, self.app / "data")

    def test_symlink_backup_directory_rejected(self):
        self.destination.mkdir()
        link = self.root / "linked-backups"
        try:
            link.symlink_to(self.destination, target_is_directory=True)
        except OSError:
            self.skipTest("Creating symlinks is not permitted on this Windows host")
        with self.assertRaisesRegex(ValueError, "symlink"):
            backup.create_backup(self.source, link)


if __name__ == "__main__":
    unittest.main()
