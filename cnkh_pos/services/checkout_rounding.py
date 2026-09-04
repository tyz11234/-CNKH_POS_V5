from __future__ import annotations

from cnkh_pos.database.connection import Database
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

    Settlement values are written in the same BEGIN IMMEDIATE transaction as the
    sale rows — never as a follow-up UPDATE after commit.
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
        deposit_method: str | None = None,
    ) -> SaleResult:
        method = payment_method.upper()
        raw_total = _raw_total(self.database, lines)
        settlement_total = (
            raw_total if method == "CREDIT" else round_checkout_cents(raw_total)
        )
        if method != "CREDIT" and paid_cents < settlement_total:
            raise SaleError("paid amount is less than rounded checkout total")
        if method == "CREDIT" and (paid_cents < 0 or paid_cents > raw_total):
            raise SaleError("invalid paid amount")

        return super().create_sale(
            lines=lines,
            payment_method=method,
            paid_cents=paid_cents,
            cashier_id=cashier_id,
            customer_id=customer_id,
            business_date=business_date,
            settlement_total_cents=(
                None if method == "CREDIT" else settlement_total
            ),
            deposit_method=deposit_method,
        )


class RoundedReturnService(ReturnService):
    """Allocates a sale's checkout rounding adjustment on the final full return."""

    def create_return(self, **kwargs) -> str:
        kwargs["apply_checkout_rounding"] = True
        return super().create_return(**kwargs)
