from __future__ import annotations

from decimal import Decimal

from cnkh_pos.database.connection import Database
from cnkh_pos.services.audit import AuditService
from cnkh_pos.services.money import line_amount_cents, round_checkout_cents
from cnkh_pos.services.quantities import parse_quantity
from cnkh_pos.services.sales import (
    ReturnService,
    SaleError,
    SaleLine,
    SaleResult,
    SalesService,
)


def _raw_total(database: Database, lines: list[SaleLine]) -> int:
    if not lines:
        raise SaleError("cart is empty")
    total = 0
    conn = database.connect(readonly=True)
    try:
        for line in lines:
            quantity = parse_quantity(line.quantity, allow_zero=False)
            row = conn.execute(
                "SELECT selling_price_cents FROM products WHERE id=? AND is_deleted=0",
                (line.product_id,),
            ).fetchone()
            if row is None:
                raise SaleError(f"product {line.product_id} is not available")
            price = int(
                row["selling_price_cents"]
                if line.price_override_cents is None
                else line.price_override_cents
            )
            gross = line_amount_cents(price, quantity)
            if line.discount_cents < 0 or line.discount_cents > gross:
                raise SaleError("invalid line discount")
            total += gross - int(line.discount_cents)
    finally:
        conn.close()
    return total


class RoundedSalesService(SalesService):
    """Sales service that rounds only the final non-credit checkout total.

    Product prices, quantities and line subtotals remain exact. The signed rounding
    adjustment is recoverable as:
        total_cents - (subtotal_cents - discount_cents)
    so older schema-compatible databases keep working without destructive changes.
    """

    def create_sale(
        self,
        *,
        lines: list[SaleLine],
        payment_method: str,
        paid_cents: int,
        cashier_id: int,
        customer_id: int | None = None,
        business_date=None,
    ) -> SaleResult:
        method = payment_method.upper()
        raw_total = _raw_total(self.database, lines)
        settlement_total = raw_total if method == "CREDIT" else round_checkout_cents(raw_total)
        if method != "CREDIT" and paid_cents < settlement_total:
            raise SaleError("paid amount is less than rounded checkout total")
        if method == "CREDIT" and (paid_cents < 0 or paid_cents > raw_total):
            raise SaleError("invalid paid amount")

        # SalesService validates against the exact item total. For a rounded-down
        # non-credit sale we provide a temporary synthetic tender, then atomically
        # replace the stored settlement values with the customer's real tender.
        base_paid = paid_cents
        if method != "CREDIT" and base_paid < raw_total:
            base_paid = raw_total

        result = super().create_sale(
            lines=lines,
            payment_method=method,
            paid_cents=base_paid,
            cashier_id=cashier_id,
            customer_id=customer_id,
            business_date=business_date,
        )
        if method == "CREDIT":
            return result

        adjustment = settlement_total - raw_total
        change = paid_cents - settlement_total
        with self.database.transaction() as conn:
            conn.execute(
                "UPDATE sales SET total_cents=?, paid_cents=?, change_cents=? WHERE id=?",
                (settlement_total, paid_cents, change, result.sale_id),
            )
            if adjustment:
                AuditService.record(
                    conn,
                    action="ROUNDING",
                    module="SALES",
                    user_id=cashier_id,
                    record_type="SALE",
                    record_id=result.sale_id,
                    old_value={"checkout_total_cents": raw_total},
                    new_value={
                        "checkout_total_cents": settlement_total,
                        "rounding_cents": adjustment,
                    },
                    detail="CNKH checkout rounding applied after line totals",
                )
        return SaleResult(
            result.sale_id,
            result.receipt_no,
            settlement_total,
            paid_cents,
            change,
        )


class RoundedReturnService(ReturnService):
    """Allocates a sale's checkout rounding adjustment on the final full return."""

    def create_return(self, **kwargs) -> str:
        sale_id = int(kwargs["sale_id"])
        number = super().create_return(**kwargs)
        with self.database.transaction() as conn:
            sale = conn.execute("SELECT * FROM sales WHERE id=?", (sale_id,)).fetchone()
            if sale is None or str(sale["payment_method"]) == "CREDIT":
                return number

            items = conn.execute(
                "SELECT id,quantity_decimal FROM sale_items WHERE sale_id=?",
                (sale_id,),
            ).fetchall()
            fully_returned = True
            for item in items:
                returned = sum(
                    (
                        parse_quantity(row[0])
                        for row in conn.execute(
                            """SELECT sri.quantity_decimal FROM sale_return_items sri
                               JOIN sale_returns sr ON sr.id=sri.return_id
                               WHERE sr.sale_id=? AND sri.sale_item_id=?""",
                            (sale_id, item["id"]),
                        )
                    ),
                    Decimal("0"),
                )
                if returned != parse_quantity(item["quantity_decimal"]):
                    fully_returned = False
                    break
            if not fully_returned:
                return number

            raw_total = int(sale["subtotal_cents"]) - int(sale["discount_cents"])
            sale_adjustment = int(sale["total_cents"]) - raw_total
            if not sale_adjustment:
                return number

            allocated = 0
            returns = conn.execute(
                "SELECT id,total_cents FROM sale_returns WHERE sale_id=? ORDER BY id",
                (sale_id,),
            ).fetchall()
            for returned in returns:
                item_refund = int(
                    conn.execute(
                        "SELECT COALESCE(SUM(refund_cents),0) FROM sale_return_items WHERE return_id=?",
                        (returned["id"],),
                    ).fetchone()[0]
                )
                allocated += int(returned["total_cents"]) - item_refund
            remaining = sale_adjustment - allocated
            if not remaining:
                return number

            current = conn.execute(
                "SELECT id,total_cents FROM sale_returns WHERE return_no=?",
                (number,),
            ).fetchone()
            if current is None:
                raise RuntimeError("created return could not be reloaded")
            adjusted_refund = int(current["total_cents"]) + remaining
            if adjusted_refund < 0:
                raise SaleError("rounded refund cannot be negative")
            conn.execute(
                "UPDATE sale_returns SET total_cents=? WHERE id=?",
                (adjusted_refund, current["id"]),
            )
            AuditService.record(
                conn,
                action="ROUNDING",
                module="SALES",
                user_id=int(kwargs["operator_id"]),
                record_type="SALE_RETURN",
                record_id=current["id"],
                old_value={"refund_cents": int(current["total_cents"])},
                new_value={
                    "refund_cents": adjusted_refund,
                    "rounding_cents": remaining,
                },
                detail="Final full return includes original checkout rounding",
            )
        return number
