from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True, slots=True)
class BackupResult:
    path: Path
    created_at: datetime


class BackupService:
    def __init__(self, backup_dir: Path):
        self.backup_dir = Path(backup_dir)

    def create(self, database_path: Path, *, reason: str) -> BackupResult:
        database_path = Path(database_path)
        if not database_path.exists():
            raise FileNotFoundError(database_path)
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        now = datetime.now().astimezone()
        safe_reason = "".join(c if c.isalnum() or c in "-_" else "_" for c in reason)
        target = self.backup_dir / (
            f"hardware_pos_{now:%Y%m%d_%H%M%S_%f}_{safe_reason}.db"
        )
        source_conn = sqlite3.connect(database_path)
        target_conn = sqlite3.connect(target)
        try:
            source_conn.backup(target_conn)
            integrity = [str(row[0]) for row in target_conn.execute("PRAGMA integrity_check")]
            if integrity != ["ok"]:
                raise RuntimeError(
                    "new backup failed integrity check: " + " | ".join(integrity)
                )
        except BaseException:
            target_conn.close()
            source_conn.close()
            target.unlink(missing_ok=True)
            raise
        else:
            target_conn.close()
            source_conn.close()
        return BackupResult(target, now)

    def prune(self, *, keep: int = 30) -> list[Path]:
        if keep < 1:
            raise ValueError("keep must be at least 1")
        files = sorted(self.backup_dir.glob("hardware_pos_*.db"), reverse=True)
        removed: list[Path] = []
        for path in files[keep:]:
            path.unlink()
            removed.append(path)
        return removed


class ShutdownBackupGuard:
    """Creates at most one retained backup for one application shutdown flow."""

    def __init__(self, database_path: Path, backup_dir: Path, *, mode: str):
        self.database_path = Path(database_path)
        self.backup_dir = Path(backup_dir)
        self.mode = mode.lower()
        self._result: BackupResult | None = None

    def run(self) -> BackupResult:
        if self._result is None:
            service = BackupService(self.backup_dir)
            self._result = service.create(
                self.database_path, reason=f"auto_close_{self.mode}"
            )
            service.prune(keep=30)
        return self._result
