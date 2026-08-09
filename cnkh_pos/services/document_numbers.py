from __future__ import annotations

import json
import re
import sqlite3
from datetime import date

from cnkh_pos.database.migrations import utc_now_text
from cnkh_pos.services.audit import AuditService

DEFAULT_DOCUMENT_PREFIXES: dict[str, str] = {
    "RECEIPT": "CNKH",
    "PURCHASE": "PI-",
    "RETURN": "RTN-",
    "STOCKTAKE": "ST-",
}


def normalize_document_prefix(value: object) -> str:
    prefix = str(value).strip().upper()
    if not re.fullmatch(r"[A-Z0-9/_-]{1,12}", prefix):
        raise ValueError(
            "prefix must contain 1-12 letters, numbers, /, _ or - characters"
        )
    return prefix


def document_prefixes(conn: sqlite3.Connection) -> dict[str, str]:
    result = dict(DEFAULT_DOCUMENT_PREFIXES)
    row = conn.execute(
        "SELECT value_json FROM settings WHERE key='document_prefixes'"
    ).fetchone()
    if row is None:
        return result
    try:
        stored = json.loads(row[0])
    except (TypeError, ValueError, json.JSONDecodeError):
        return result
    if not isinstance(stored, dict):
        return result
    for key in DEFAULT_DOCUMENT_PREFIXES:
        if key in stored:
            try:
                result[key] = normalize_document_prefix(stored[key])
            except ValueError:
                continue
    return result


def configured_document_prefix(
    conn: sqlite3.Connection, document_type: str, fallback: str
) -> str:
    kind = document_type.upper()
    return document_prefixes(conn).get(kind, normalize_document_prefix(fallback))


def save_document_prefixes(
    conn: sqlite3.Connection, values: dict[str, str], *, admin_id: int
) -> dict[str, str]:
    normalized = {
        key: normalize_document_prefix(values.get(key, default))
        for key, default in DEFAULT_DOCUMENT_PREFIXES.items()
    }
    before = document_prefixes(conn)
    conn.execute(
        """INSERT OR REPLACE INTO settings(key,value_json,updated_at,updated_by)
           VALUES ('document_prefixes',?,?,?)""",
        (json.dumps(normalized, sort_keys=True), utc_now_text(), admin_id),
    )
    AuditService.record(
        conn,
        action="UPDATE",
        module="SETTINGS",
        user_id=admin_id,
        record_type="DOCUMENT_PREFIXES",
        record_id="document_prefixes",
        old_value=before,
        new_value=normalized,
    )
    return normalized


def next_document_number(
    conn: sqlite3.Connection, document_type: str, day: date, prefix: str
) -> str:
    kind = document_type.upper()
    prefix = configured_document_prefix(conn, kind, prefix)
    day_text = day.isoformat()
    row = conn.execute(
        "SELECT last_sequence FROM document_sequences WHERE document_type=? AND business_date=?",
        (kind, day_text),
    ).fetchone()
    sequence = 1 if row is None else int(row[0]) + 1
    if row is None:
        conn.execute(
            "INSERT INTO document_sequences(document_type, business_date, last_sequence) VALUES (?, ?, ?)",
            (kind, day_text, sequence),
        )
    else:
        conn.execute(
            "UPDATE document_sequences SET last_sequence=? WHERE document_type=? AND business_date=?",
            (sequence, kind, day_text),
        )
    return f"{prefix}{day:%Y%m%d}-{sequence:03d}"
