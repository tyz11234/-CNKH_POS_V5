from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from cnkh_pos.database.connection import Database


@dataclass(frozen=True, slots=True)
class ReportSummary:
    sales_cents: int
    gross_profit_cents: int
    transaction_count: int
    purchases_cents: int
    current_receivable_cents: int
    current_payable_cents: int


class ReportService:
    def __init__(self, database: Database):
        self.database = database

    def summary(self, *, start_date: str, end_date: str) -> ReportSummary:
        try:
            start = date.fromisoformat(start_date)
            end = date.fromisoformat(end_date)
        except ValueError as exc:
            raise ValueError("report dates must use YYYY-MM-DD") from exc
        if start > end:
            raise ValueError("start date cannot be after end date")
        conn = self.database.connect(readonly=True)
        try:
            gross_sales, count = conn.execute(
                """SELECT COALESCE(SUM(total_cents),0),COUNT(*) FROM sales
                   WHERE is_deleted=0 AND substr(sold_at,1,10) BETWEEN ? AND ?""",
                (start_date, end_date),
            ).fetchone()
            profit = 0
            for row in conn.execute(
                """SELECT si.subtotal_cents,si.unit_cost_cents_snapshot,
                          si.stock_deduction_decimal
                   FROM sale_items si JOIN sales s ON s.id=si.sale_id
                   WHERE s.is_deleted=0 AND substr(s.sold_at,1,10) BETWEEN ? AND ?""",
                (start_date, end_date),
            ):
                cost = int(
                    (
                        Decimal(int(row["unit_cost_cents_snapshot"]))
                        * Decimal(str(row["stock_deduction_decimal"]))
                    ).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
                )
                profit += int(row["subtotal_cents"]) - cost
            returned_sales = int(
                conn.execute(
                    """SELECT COALESCE(SUM(total_cents),0) FROM sale_returns
                       WHERE substr(returned_at,1,10) BETWEEN ? AND ?""",
                    (start_date, end_date),
                ).fetchone()[0]
            )
            for row in conn.execute(
                """SELECT sri.refund_cents,sri.stock_restored_decimal,
                          si.unit_cost_cents_snapshot
                   FROM sale_return_items sri
                   JOIN sale_returns sr ON sr.id=sri.return_id
                   JOIN sale_items si ON si.id=sri.sale_item_id
                   WHERE substr(sr.returned_at,1,10) BETWEEN ? AND ?""",
                (start_date, end_date),
            ):
                restored_cost = int(
                    (
                        Decimal(int(row["unit_cost_cents_snapshot"]))
                        * Decimal(str(row["stock_restored_decimal"]))
                    ).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
                )
                profit -= int(row["refund_cents"]) - restored_cost
            purchases = conn.execute(
                """SELECT COALESCE(SUM(total_cents),0) FROM purchases
                   WHERE is_deleted=0 AND substr(purchased_at,1,10) BETWEEN ? AND ?""",
                (start_date, end_date),
            ).fetchone()[0]
            receivable = conn.execute(
                "SELECT COALESCE(SUM(balance_cents),0) FROM customer_debts WHERE status='OPEN'"
            ).fetchone()[0]
            payable = conn.execute(
                """SELECT COALESCE(SUM(total_cents-paid_cents),0) FROM purchases
                   WHERE is_deleted=0"""
            ).fetchone()[0]
        finally:
            conn.close()
        return ReportSummary(
            sales_cents=int(gross_sales) - returned_sales,
            gross_profit_cents=profit,
            transaction_count=int(count),
            purchases_cents=int(purchases),
            current_receivable_cents=int(receivable),
            current_payable_cents=int(payable),
        )
