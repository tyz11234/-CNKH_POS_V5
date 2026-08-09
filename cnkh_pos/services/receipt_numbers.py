from __future__ import annotations

import sqlite3
from datetime import date

from cnkh_pos.services.document_numbers import configured_document_prefix


def next_receipt_number(conn: sqlite3.Connection, business_date: date) -> str:
    day = business_date.isoformat()
    row = conn.execute(
        "SELECT last_sequence FROM receipt_sequences WHERE business_date = ?", (day,)
    ).fetchone()
    if row is None:
        sequence = 1
        conn.execute(
            "INSERT INTO receipt_sequences(business_date, last_sequence) VALUES (?, ?)",
            (day, sequence),
        )
    else:
        sequence = int(row[0]) + 1
        conn.execute(
            "UPDATE receipt_sequences SET last_sequence = ? WHERE business_date = ?",
            (sequence, day),
        )
    prefix = configured_document_prefix(conn, "RECEIPT", "CNKH")
    return f"{prefix}{business_date:%Y%m%d}-{sequence:03d}"
