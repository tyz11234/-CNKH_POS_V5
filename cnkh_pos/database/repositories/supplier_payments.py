from __future__ import annotations

import sqlite3

from cnkh_pos.database.migrations import utc_now_text


class SupplierPaymentRepository:
    @staticmethod
    def add(
        conn: sqlite3.Connection,
        *,
        supplier_id: int,
        amount_cents: int,
        payment_method: str,
        note: str,
        operator_id: int | None,
        purchase_id: int | None = None,
    ) -> int:
        if amount_cents <= 0:
            raise ValueError("supplier payment must be positive")
        cursor = conn.execute(
            """
            INSERT INTO supplier_payments (
                supplier_id, purchase_id, amount_cents, payment_method,
                note, operator_id, paid_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                supplier_id,
                purchase_id,
                amount_cents,
                payment_method.upper(),
                note,
                operator_id,
                utc_now_text(),
            ),
        )
        return int(cursor.lastrowid)
