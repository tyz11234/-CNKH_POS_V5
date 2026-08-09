from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import sqlite3
from dataclasses import dataclass

from cnkh_pos.database.migrations import utc_now_text
from cnkh_pos.services.audit import AuditService


PBKDF2_ITERATIONS = 600_000


def hash_password(password: str) -> str:
    if len(password) < 8:
        raise ValueError("password must contain at least 8 characters")
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, rounds, salt_hex, digest_hex = stored.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        expected = bytes.fromhex(digest_hex)
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt_hex), int(rounds)
        )
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


@dataclass(frozen=True, slots=True)
class AuthenticatedUser:
    id: int
    username: str
    display_name: str
    role: str
    permissions: dict[str, bool]


class AuthService:
    @staticmethod
    def authenticate(
        conn: sqlite3.Connection, username: str, password: str, *, required_role: str
    ) -> AuthenticatedUser:
        row = conn.execute(
            "SELECT * FROM users WHERE username=? COLLATE NOCASE AND is_active=1",
            (username.strip(),),
        ).fetchone()
        if (
            row is None
            or row["role"] != required_role
            or not verify_password(password, row["password_hash"])
        ):
            raise PermissionError("invalid username, password, or application role")
        AuditService.record(
            conn,
            action="LOGIN",
            module="AUTH",
            user_id=int(row["id"]),
            username=str(row["username"]),
            record_type="USER",
            record_id=row["id"],
        )
        return AuthenticatedUser(
            id=int(row["id"]),
            username=str(row["username"]),
            display_name=str(row["display_name"]),
            role=str(row["role"]),
            permissions=json.loads(row["permissions_json"]),
        )

    @staticmethod
    def create_user(
        conn: sqlite3.Connection,
        *,
        username: str,
        display_name: str,
        password: str,
        role: str,
        permissions: dict[str, bool] | None,
        admin_id: int | None,
    ) -> int:
        role = role.upper()
        if role not in {"ADMIN", "STAFF"}:
            raise ValueError("invalid role")
        now = utc_now_text()
        cursor = conn.execute(
            """INSERT INTO users(username, display_name, password_hash, role, permissions_json, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                username.strip(),
                display_name.strip(),
                hash_password(password),
                role,
                json.dumps(permissions or {}, sort_keys=True),
                now,
                now,
            ),
        )
        user_id = int(cursor.lastrowid)
        AuditService.record(
            conn,
            action="CREATE",
            module="USERS",
            user_id=admin_id,
            record_type="USER",
            record_id=user_id,
            new_value={
                "username": username,
                "display_name": display_name,
                "role": role,
                "permissions": permissions or {},
            },
        )
        return user_id

    @staticmethod
    def delete_user(
        conn: sqlite3.Connection, *, target_id: int, current_admin_id: int
    ) -> None:
        if target_id == current_admin_id:
            raise ValueError("current administrator cannot delete their own account")
        row = conn.execute(
            "SELECT username, role FROM users WHERE id=?", (target_id,)
        ).fetchone()
        if row is None:
            raise LookupError("user not found")
        if row["role"] == "ADMIN":
            count = int(
                conn.execute(
                    "SELECT COUNT(*) FROM users WHERE role='ADMIN' AND is_active=1"
                ).fetchone()[0]
            )
            if count <= 1:
                raise ValueError("cannot delete the last administrator")
        conn.execute(
            "UPDATE users SET is_active=0, updated_at=? WHERE id=?",
            (utc_now_text(), target_id),
        )
        AuditService.record(
            conn,
            action="DELETE",
            module="USERS",
            user_id=current_admin_id,
            record_type="USER",
            record_id=target_id,
            old_value={
                "username": row["username"],
                "role": row["role"],
                "is_active": 1,
            },
            new_value={"is_active": 0},
        )

    @staticmethod
    def reset_password(
        conn: sqlite3.Connection, *, target_id: int, new_password: str, admin_id: int
    ) -> None:
        conn.execute(
            "UPDATE users SET password_hash=?, updated_at=? WHERE id=?",
            (hash_password(new_password), utc_now_text(), target_id),
        )
        AuditService.record(
            conn,
            action="RESET_PASSWORD",
            module="USERS",
            user_id=admin_id,
            record_type="USER",
            record_id=target_id,
            detail="Password reset; secrets are never logged.",
        )
