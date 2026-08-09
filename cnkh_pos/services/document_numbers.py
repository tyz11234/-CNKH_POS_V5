from __future__ import annotations

import sqlite3
from datetime import date


def next_document_number(
    conn: sqlite3.Connection, document_type: str, day: date, prefix: str
) -> str:
    kind = document_type.upper()
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
