from __future__ import annotations

import json
import sqlite3

from cnkh_pos.database.migrations import utc_now_text


class AuditService:
    @staticmethod
    def record(
        conn: sqlite3.Connection,
        *,
        action: str,
        module: str,
        user_id: int | None = None,
        username: str = "",
        record_type: str = "",
        record_id: str | int = "",
        old_value: object | None = None,
        new_value: object | None = None,
        detail: str = "",
    ) -> int:
        cursor = conn.execute(
            """
            INSERT INTO audit_logs(
                occurred_at, user_id, username_snapshot, action, module,
                record_type, record_id, old_value_json, new_value_json, detail
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                utc_now_text(),
                user_id,
                username,
                action,
                module,
                record_type,
                str(record_id),
                None
                if old_value is None
                else json.dumps(
                    old_value, ensure_ascii=False, default=str, sort_keys=True
                ),
                None
                if new_value is None
                else json.dumps(
                    new_value, ensure_ascii=False, default=str, sort_keys=True
                ),
                detail,
            ),
        )
        return int(cursor.lastrowid)
