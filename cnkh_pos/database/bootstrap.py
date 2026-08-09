from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from cnkh_pos.config import SCHEMA_VERSION
from cnkh_pos.database.connection import Database
from cnkh_pos.database.migrations import MigrationManager
from cnkh_pos.services.backup import BackupService


class DatabaseStartupError(RuntimeError):
    """Fatal safety-gate failure. Callers must not continue in write mode."""


@dataclass(frozen=True, slots=True)
class StartupResult:
    database_path: Path
    fresh_database: bool
    integrity_messages: tuple[str, ...]
    backup_path: Path | None
    schema_before: int
    schema_after: int
    completed_at: datetime


def bootstrap_database(database_path: Path, backup_dir: Path) -> StartupResult:
    database_path = Path(database_path)
    fresh = not database_path.exists()
    database = Database(database_path)
    backup_path: Path | None = None

    ok, messages = database.integrity_check()
    if not ok:
        raise DatabaseStartupError(
            "Database integrity check failed. No migration was attempted. "
            + " | ".join(messages)
        )

    schema_before = 0
    if not fresh:
        conn = database.connect(readonly=True)
        try:
            schema_before = int(conn.execute("PRAGMA user_version").fetchone()[0])
        finally:
            conn.close()

    if not fresh and schema_before < SCHEMA_VERSION:
        try:
            backup_service = BackupService(backup_dir)
            backup_path = backup_service.create(
                database_path, reason="pre_migration"
            ).path
            backup_service.prune(keep=30)
        except BaseException as exc:
            raise DatabaseStartupError(
                "Could not create the required pre-migration backup. No migration was attempted."
            ) from exc

    conn = database.connect()
    try:
        try:
            before, after = MigrationManager().migrate(conn)
        except BaseException as exc:
            raise DatabaseStartupError(
                "Database migration failed and was rolled back. The application is locked from write mode."
            ) from exc
    finally:
        conn.close()

    return StartupResult(
        database_path=database_path,
        fresh_database=fresh,
        integrity_messages=tuple(messages),
        backup_path=backup_path,
        schema_before=before,
        schema_after=after,
        completed_at=datetime.now().astimezone(),
    )
