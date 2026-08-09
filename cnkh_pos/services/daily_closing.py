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

    def system_cash(self, *, business_date: date) -> int:
        conn = self.database.connect(readonly=True)
        try:
            return int(
                conn.execute(
                    """SELECT COALESCE(SUM(total_cents),0) FROM sales
                   WHERE payment_method='CASH' AND is_deleted=0 AND substr(sold_at,1,10)=?""",
                    (business_date.isoformat(),),
                ).fetchone()[0]
            )
        finally:
            conn.close()

    def complete(
        self, *, business_date: date, cashier_id: int, actual_cash_cents: int, note: str
    ) -> DailyClosingResult:
        if actual_cash_cents < 0:
            raise ValueError("actual cash cannot be negative")
        with self.database.transaction() as conn:
            system = int(
                conn.execute(
                    """SELECT COALESCE(SUM(total_cents),0) FROM sales
                   WHERE payment_method='CASH' AND is_deleted=0 AND substr(sold_at,1,10)=?""",
                    (business_date.isoformat(),),
                ).fetchone()[0]
            )
            variance = actual_cash_cents - system
            cursor = conn.execute(
                """INSERT INTO daily_cash_closings(
                    business_date,cashier_id,system_cash_cents,actual_cash_cents,
                    variance_cents,note,closed_at) VALUES (?,?,?,?,?,?,?)""",
                (
                    business_date.isoformat(),
                    cashier_id,
                    system,
                    actual_cash_cents,
                    variance,
                    note,
                    utc_now_text(),
                ),
            )
            closing_id = int(cursor.lastrowid)
            AuditService.record(
                conn,
                action="DAILY_CLOSING",
                module="CASH",
                user_id=cashier_id,
                record_type="DAILY_CASH_CLOSING",
                record_id=closing_id,
                new_value={
                    "system_cash_cents": system,
                    "actual_cash_cents": actual_cash_cents,
                    "variance_cents": variance,
                },
            )
            return DailyClosingResult(closing_id, system, actual_cash_cents, variance)
