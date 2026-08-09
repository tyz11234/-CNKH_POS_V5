from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from cnkh_pos.database.connection import Database
from cnkh_pos.database.migrations import utc_now_text
from cnkh_pos.services.auth import verify_password
from cnkh_pos.services.backup import BackupService


@dataclass(frozen=True, slots=True)
class AuditClearResult:
    removed_count: int
    backup_path: Path


class AuditMaintenanceService:
    def __init__(self, database: Database, backup_dir: Path):
        self.database = database
        self.backup_dir = Path(backup_dir)

    def clear(self, *, admin_id: int, password: str) -> AuditClearResult:
        conn = self.database.connect(readonly=True)
        try:
            row = conn.execute(
                """SELECT password_hash FROM users
                   WHERE id=? AND role='ADMIN' AND is_active=1""",
                (admin_id,),
            ).fetchone()
        finally:
            conn.close()
        if row is None or not verify_password(password, str(row["password_hash"])):
            raise PermissionError("administrator password verification failed")

        backup_service = BackupService(self.backup_dir)
        safety = backup_service.create(self.database.path, reason="pre_audit_clear")
        backup_service.prune(keep=30)
        with self.database.transaction() as conn:
            count = int(conn.execute("SELECT COUNT(*) FROM audit_logs").fetchone()[0])
            conn.execute("DELETE FROM audit_logs")
            conn.execute(
                """INSERT INTO system_checks(check_type,status,detail,checked_at)
                   VALUES ('AUDIT_CLEAR','PASS',?,?)""",
                (
                    f"Admin #{admin_id} cleared {count} audit rows; backup={safety.path.name}",
                    utc_now_text(),
                ),
            )
        return AuditClearResult(count, safety.path)
