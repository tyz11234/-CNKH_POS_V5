from __future__ import annotations

import sqlite3
from pathlib import Path

from cnkh_pos.database.bootstrap import bootstrap_database
from cnkh_pos.database.connection import Database
from cnkh_pos.services.auth import verify_password
from cnkh_pos.services.backup import BackupService


class RestoreError(RuntimeError):
    """User-facing restore failure with bilingual context."""


class RestoreService:
    def __init__(self, database: Database, backup_dir: Path):
        self.database = database
        self.backup_dir = Path(backup_dir)

    def restore(self, backup_path: Path, *, admin_id: int, password: str) -> Path:
        backup_path = Path(backup_path)
        if not backup_path.is_file():
            raise FileNotFoundError(
                "Backup file not found / 找不到备份文件: "
                f"{backup_path}. Active database was not replaced / 当前数据库未被替换。"
            )
        if backup_path.resolve() == self.database.path.resolve():
            raise ValueError(
                "The active database cannot be selected as its own backup / "
                "不能选择当前数据库作为备份来源。Database was not replaced / 数据库未被替换。"
            )
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
                raise PermissionError(
                    "Administrator password verification failed / 管理员密码验证失败。"
                    " Database was not replaced / 数据库未被替换。"
                )
        finally:
            conn.close()
        source = sqlite3.connect(backup_path)
        try:
            if source.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError(
                    "Selected backup failed integrity check / 所选备份未通过完整性检查。"
                    f" Backup file kept / 备份文件已保留: {backup_path}."
                    " Active database was not replaced / 当前数据库未被替换。"
                )
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
        except BaseException as exc:
            source = sqlite3.connect(safety)
            target = sqlite3.connect(self.database.path)
            try:
                source.backup(target)
            finally:
                target.close()
                source.close()
            bootstrap_database(self.database.path, self.backup_dir)
            raise RestoreError(
                f"Restore failed / 恢复失败: {exc}. "
                f"Original database restored from safety backup / 已从安全备份还原原数据库: {safety}. "
                f"Selected backup file was not modified / 所选备份文件未改动: {backup_path}."
            ) from exc
        return safety
