from __future__ import annotations

import sqlite3
from pathlib import Path

from cnkh_pos.database.bootstrap import bootstrap_database
from cnkh_pos.database.connection import Database
from cnkh_pos.services.auth import verify_password
from cnkh_pos.services.backup import BackupService


class RestoreService:
    def __init__(self, database: Database, backup_dir: Path):
        self.database = database
        self.backup_dir = Path(backup_dir)

    def restore(self, backup_path: Path, *, admin_id: int, password: str) -> Path:
        backup_path = Path(backup_path)
        if not backup_path.is_file():
            raise FileNotFoundError(backup_path)
        if backup_path.resolve() == self.database.path.resolve():
            raise ValueError("the active database cannot be selected as its own backup")
        conn = self.database.connect(readonly=True)
        try:
            admin = conn.execute(
                "SELECT password_hash,role,is_active FROM users WHERE id=?", (admin_id,)
            ).fetchone()
            if (
                admin is None
                or admin["role"] != "ADMIN"
                or not admin["is_active"]
                or not verify_password(password, admin["password_hash"])
            ):
                raise PermissionError("administrator password verification failed")
        finally:
            conn.close()
        source = sqlite3.connect(backup_path)
        try:
            if source.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("selected backup failed integrity check")
        finally:
            source.close()
        safety = (
            BackupService(self.backup_dir).create(
                self.database.path, reason="pre_restore"
            ).path
        )
        BackupService(self.backup_dir).prune(keep=30)
        try:
            source = sqlite3.connect(backup_path)
            target = sqlite3.connect(self.database.path)
            try:
                source.backup(target)
            finally:
                target.close()
                source.close()
            bootstrap_database(self.database.path, self.backup_dir)
        except BaseException:
            source = sqlite3.connect(safety)
            target = sqlite3.connect(self.database.path)
            try:
                source.backup(target)
            finally:
                target.close()
                source.close()
            bootstrap_database(self.database.path, self.backup_dir)
            raise
        return safety
