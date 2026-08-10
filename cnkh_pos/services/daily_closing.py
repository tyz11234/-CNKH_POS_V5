from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from cnkh_pos.database.connection import Database
from cnkh_pos.database.migrations import utc_now_text
from cnkh_pos.services.audit import AuditService


@dataclass(frozen=True, slots=True)
class DailyClosingResult:
    id: int
    system_cash_cents: int
    actual_cash_cents: int
    variance_cents: int


class DailyClosingService:
    def __init__(self, database: Database):
        self.database = database

    @staticmethod
    def _cash_movement(conn, business_date: date) -> int:
        day = business_date.isoformat()
        cash_sales = int(
            conn.execute(
                """SELECT COALESCE(SUM(paid_cents - change_cents),0) FROM sales
                   WHERE payment_method='CASH' AND is_deleted=0
                   AND substr(sold_at,1,10)=?""",
                (day,),
            ).fetchone()[0]
        )
        customer_receipts = int(
            conn.execute(
                """SELECT COALESCE(SUM(amount_cents),0) FROM customer_payments
                   WHERE upper(payment_method)='CASH' AND substr(paid_at,1,10)=?""",
                (day,),
            ).fetchone()[0]
        )
        supplier_payments = int(
            conn.execute(
                """SELECT COALESCE(SUM(amount_cents),0) FROM supplier_payments
                   WHERE upper(payment_method)='CASH' AND voided_at IS NULL
                   AND substr(paid_at,1,10)=?""",
                (day,),
            ).fetchone()[0]
        )
        cash_returns = int(
            conn.execute(
                """SELECT COALESCE(SUM(r.total_cents),0) FROM sale_returns r
                   WHERE r.refund_method='CASH' AND substr(r.returned_at,1,10)=?""",
                (day,),
            ).fetchone()[0]
        )
        return cash_sales + customer_receipts - supplier_payments - cash_returns

    def system_cash(self, *, business_date: date, opening_cash_cents: int = 0) -> int:
        if opening_cash_cents < 0:
            raise ValueError("opening cash cannot be negative")
        conn = self.database.connect(readonly=True)
        try:
            return opening_cash_cents + self._cash_movement(conn, business_date)
        finally:
            conn.close()

    def complete(
        self,
        *,
        business_date: date,
        cashier_id: int,
        actual_cash_cents: int,
        note: str,
        opening_cash_cents: int = 0,
    ) -> DailyClosingResult:
        if actual_cash_cents < 0:
            raise ValueError("actual cash cannot be negative")
        if opening_cash_cents < 0:
            raise ValueError("opening cash cannot be negative")
        with self.database.transaction() as conn:
            system = opening_cash_cents + self._cash_movement(conn, business_date)
            variance = actual_cash_cents - system
            try:
                cursor = conn.execute(
                    """INSERT INTO daily_cash_closings(
                        business_date,cashier_id,opening_cash_cents,system_cash_cents,
                        actual_cash_cents,variance_cents,note,closed_at)
                        VALUES (?,?,?,?,?,?,?,?)""",
                    (
                        business_date.isoformat(),
                        cashier_id,
                        opening_cash_cents,
                        system,
                        actual_cash_cents,
                        variance,
                        note,
                        utc_now_text(),
                    ),
                )
            except Exception as exc:
                if "UNIQUE constraint failed" in str(exc):
                    raise ValueError(
                        "this user has already completed today's cash closing"
                    ) from exc
                raise
            closing_id = int(cursor.lastrowid)
            AuditService.record(
                conn,
                action="DAILY_CLOSING",
                module="CASH",
                user_id=cashier_id,
                record_type="DAILY_CASH_CLOSING",
                record_id=closing_id,
                new_value={
                    "opening_cash_cents": opening_cash_cents,
                    "system_cash_cents": system,
                    "actual_cash_cents": actual_cash_cents,
                    "variance_cents": variance,
                },
            )
            return DailyClosingResult(closing_id, system, actual_cash_cents, variance)
