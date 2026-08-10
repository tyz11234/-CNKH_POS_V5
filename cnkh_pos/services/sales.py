from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from cnkh_pos.database.connection import Database
from cnkh_pos.database.migrations import utc_now_text
from cnkh_pos.services.audit import AuditService
from cnkh_pos.services.document_numbers import configured_document_prefix
from cnkh_pos.services.quantities import parse_quantity, quantity_text
from cnkh_pos.services.receipt_numbers import next_receipt_number


class SaleError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class SaleLine:
    product_id: int
    quantity: Decimal
    stock_deduction: Decimal
    discount_cents: int = 0
    price_override_cents: int | None = None


@dataclass(frozen=True, slots=True)
class SaleResult:
    sale_id: int
    receipt_no: str
    total_cents: int
    paid_cents: int
    change_cents: int


def _line_total(unit_price_cents: int, quantity: Decimal) -> int:
    return int(
        (Decimal(unit_price_cents) * quantity).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )


class SalesService:
    def __init__(self, database: Database):
        self.database = database

    def create_sale(
        self,
        *,
        lines: list[SaleLine],
        payment_method: str,
        paid_cents: int,
        cashier_id: int,
        customer_id: int | None = None,
        business_date: date | None = None,
    ) -> SaleResult:
        if not lines:
            raise SaleError("cart is empty")
        product_ids = [line.product_id for line in lines]
        if len(product_ids) != len(set(product_ids)):
            raise SaleError("cart contains duplicate product lines")
        method = payment_method.upper()
        if method not in {"CASH", "CARD", "DUITNOW_QR", "CREDIT"}:
            raise SaleError("unsupported payment method")
        prepared: list[dict[str, object]] = []
        with self.database.transaction() as conn:
            subtotal = 0
            total_discount = 0
            for line in lines:
                quantity = parse_quantity(line.quantity, allow_zero=False)
                deduction = parse_quantity(line.stock_deduction, allow_zero=False)
                row = conn.execute(
                    "SELECT * FROM products WHERE id=? AND is_deleted=0",
                    (line.product_id,),
                ).fetchone()
                if row is None:
                    raise SaleError(f"product {line.product_id} is not available")
                old_stock = parse_quantity(row["stock_decimal"])
                if deduction > old_stock:
                    raise SaleError(f"insufficient stock for {row['name']}")
                price = int(
                    row["selling_price_cents"]
                    if line.price_override_cents is None
                    else line.price_override_cents
                )
                if price < 0 or line.discount_cents < 0:
                    raise SaleError("price and discount cannot be negative")
                gross = _line_total(price, quantity)
                if line.discount_cents > gross:
                    raise SaleError("line discount exceeds line amount")
                net = gross - line.discount_cents
                subtotal += gross
                total_discount += line.discount_cents
                prepared.append(
                    {
                        "line": line,
                        "row": row,
                        "quantity": quantity,
                        "deduction": deduction,
                        "old_stock": old_stock,
                        "price": price,
                        "net": net,
                    }
                )
            total = subtotal - total_discount
            if method == "CREDIT":
                if customer_id is None:
                    raise SaleError("credit sale requires a customer")
                customer = conn.execute(
                    "SELECT id FROM customers WHERE id=? AND is_deleted=0",
                    (customer_id,),
                ).fetchone()
                if customer is None:
                    raise SaleError("credit customer is not available")
                if paid_cents < 0 or paid_cents > total:
                    raise SaleError("invalid paid amount")
                change = 0
            else:
                if paid_cents < total:
                    raise SaleError("paid amount is less than total")
                change = paid_cents - total

            sold_at = utc_now_text()
            receipt_no = next_receipt_number(conn, business_date or date.today())
            cursor = conn.execute(
                """
                INSERT INTO sales(
                    receipt_no, subtotal_cents, discount_cents, total_cents,
                    paid_cents, change_cents, payment_method, customer_id, cashier_id, sold_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    receipt_no,
                    subtotal,
                    total_discount,
                    total,
                    paid_cents,
                    change,
                    method,
                    customer_id,
                    cashier_id,
                    sold_at,
                ),
            )
            sale_id = int(cursor.lastrowid)
            for item in prepared:
                line = item["line"]
                row = item["row"]
                quantity = item["quantity"]
                deduction = item["deduction"]
                old_stock = item["old_stock"]
                new_stock = old_stock - deduction
                conn.execute(
                    """
                    INSERT INTO sale_items(
                        sale_id, product_id, product_name_snapshot, sku_snapshot,
                        barcode_snapshot, unit_snapshot, quantity_decimal,
                        stock_deduction_decimal, unit_price_cents, discount_cents,
                        subtotal_cents, unit_cost_cents_snapshot
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        sale_id,
                        row["id"],
                        row["name"],
                        row["sku"],
                        row["barcode"],
                        row["unit"],
                        quantity_text(quantity),
                        quantity_text(deduction),
                        item["price"],
                        line.discount_cents,
                        item["net"],
                        row["cost_cents"],
                    ),
                )
                conn.execute(
                    "UPDATE products SET stock_decimal=?, updated_at=? WHERE id=?",
                    (quantity_text(new_stock), sold_at, row["id"]),
                )
                conn.execute(
                    """INSERT INTO stock_movements(
                        product_id, source_type, reference, old_stock_decimal, change_decimal,
                        new_stock_decimal, operator_id, created_at
                    ) VALUES (?, 'SALE', ?, ?, ?, ?, ?, ?)""",
                    (
                        row["id"],
                        receipt_no,
                        quantity_text(old_stock),
                        quantity_text(-deduction),
                        quantity_text(new_stock),
                        cashier_id,
                        sold_at,
                    ),
                )
            if method == "CREDIT" and total > paid_cents:
                conn.execute(
                    """INSERT INTO customer_debts(
                        customer_id, sale_id, original_cents, balance_cents, status, opened_at
                    ) VALUES (?, ?, ?, ?, 'OPEN', ?)""",
                    (
                        customer_id,
                        sale_id,
                        total - paid_cents,
                        total - paid_cents,
                        sold_at,
                    ),
                )
            AuditService.record(
                conn,
                action="CREATE",
                module="SALES",
                user_id=cashier_id,
                record_type="SALE",
                record_id=sale_id,
                new_value={
                    "receipt_no": receipt_no,
                    "total_cents": total,
                    "payment_method": method,
                },
            )
            return SaleResult(sale_id, receipt_no, total, paid_cents, change)

    def delete_sale(self, *, sale_id: int, admin_id: int) -> None:
        """Permanently removes a sale after restoring only stock not already returned."""
        with self.database.transaction() as conn:
            sale = conn.execute("SELECT * FROM sales WHERE id=?", (sale_id,)).fetchone()
            if sale is None:
                raise LookupError("sale not found")
            items = conn.execute(
                "SELECT * FROM sale_items WHERE sale_id=?", (sale_id,)
            ).fetchall()
            deleted_at = utc_now_text()
            for item in items:
                deduction = parse_quantity(item["stock_deduction_decimal"])
                returned = parse_quantity(item["returned_stock_decimal"])
                restore = max(Decimal("0"), deduction - returned)
                if item["product_id"] is not None and restore:
                    product = conn.execute(
                        "SELECT stock_decimal FROM products WHERE id=?",
                        (item["product_id"],),
                    ).fetchone()
                    if product is not None:
                        old_stock = parse_quantity(product["stock_decimal"])
                        new_stock = old_stock + restore
                        conn.execute(
                            "UPDATE products SET stock_decimal=?, updated_at=? WHERE id=?",
                            (quantity_text(new_stock), deleted_at, item["product_id"]),
                        )
                        conn.execute(
                            """INSERT INTO stock_movements(
                                product_id, source_type, reference, old_stock_decimal, change_decimal,
                                new_stock_decimal, operator_id, created_at, notes
                            ) VALUES (?, 'DELETE_SALE', ?, ?, ?, ?, ?, ?, ?)""",
                            (
                                item["product_id"],
                                sale["receipt_no"],
                                quantity_text(old_stock),
                                quantity_text(restore),
                                quantity_text(new_stock),
                                admin_id,
                                deleted_at,
                                "Restored unreturned portion only",
                            ),
                        )
            debt = conn.execute(
                "SELECT id FROM customer_debts WHERE sale_id=?", (sale_id,)
            ).fetchone()
            if debt is not None:
                conn.execute(
                    "UPDATE customer_payments SET debt_id=NULL WHERE debt_id=?",
                    (debt["id"],),
                )
                conn.execute("DELETE FROM customer_debts WHERE id=?", (debt["id"],))
            return_ids = [
                row[0]
                for row in conn.execute(
                    "SELECT id FROM sale_returns WHERE sale_id=?", (sale_id,)
                )
            ]
            for return_id in return_ids:
                conn.execute(
                    "DELETE FROM sale_return_items WHERE return_id=?", (return_id,)
                )
            conn.execute("DELETE FROM sale_returns WHERE sale_id=?", (sale_id,))
            snapshot = dict(sale)
            snapshot["items"] = [dict(item) for item in items]
            AuditService.record(
                conn,
                action="DELETE",
                module="SALES",
                user_id=admin_id,
                record_type="SALE",
                record_id=sale_id,
                old_value=snapshot,
                detail="Permanent delete after inventory reversal",
            )
            conn.execute("DELETE FROM sales WHERE id=?", (sale_id,))


class ReturnService:
    def __init__(self, database: Database):
        self.database = database

    def create_return(
        self,
        *,
        sale_id: int,
        quantities_by_sale_item: dict[int, Decimal],
        reason: str,
        operator_id: int,
        refund_method: str = "ORIGINAL",
    ) -> str:
        if not quantities_by_sale_item:
            raise SaleError("return has no items")
        reason = reason.strip()
        if not reason:
            raise SaleError("return reason is required")
        with self.database.transaction() as conn:
            sale = conn.execute("SELECT * FROM sales WHERE id=?", (sale_id,)).fetchone()
            if sale is None:
                raise LookupError("sale not found")
            returned_at = utc_now_text()
            method = refund_method.upper()
            if method == "ORIGINAL":
                method = (
                    "CREDIT_ADJUSTMENT"
                    if sale["payment_method"] == "CREDIT"
                    else str(sale["payment_method"])
                )
            if method not in {"CASH", "CARD", "DUITNOW_QR", "CREDIT_ADJUSTMENT"}:
                raise SaleError("unsupported refund method")
            prefix = configured_document_prefix(conn, "RETURN", "RTN-")
            number = f"{prefix}{sale['receipt_no']}-{int(conn.execute('SELECT COUNT(*) FROM sale_returns WHERE sale_id=?', (sale_id,)).fetchone()[0]) + 1:02d}"
            prepared: list[tuple[sqlite3.Row, Decimal, Decimal, int]] = []
            total_refund = 0
            for item_id, raw_quantity in quantities_by_sale_item.items():
                quantity = parse_quantity(raw_quantity, allow_zero=False)
                item = conn.execute(
                    "SELECT * FROM sale_items WHERE id=? AND sale_id=?",
                    (item_id, sale_id),
                ).fetchone()
                if item is None:
                    raise SaleError("sale item does not belong to sale")
                sold = parse_quantity(item["quantity_decimal"])
                prior_returns = conn.execute(
                    """SELECT sri.quantity_decimal,sri.stock_restored_decimal,
                              sri.refund_cents
                       FROM sale_return_items sri
                       JOIN sale_returns sr ON sr.id=sri.return_id
                       WHERE sri.sale_item_id=?""",
                    (item_id,),
                ).fetchall()
                already_quantity = sum(
                    (parse_quantity(row["quantity_decimal"]) for row in prior_returns),
                    Decimal("0"),
                )
                if quantity + already_quantity > sold:
                    raise SaleError("return quantity exceeds sold quantity")
                deduction = parse_quantity(item["stock_deduction_decimal"])
                restored_before = sum(
                    (
                        parse_quantity(row["stock_restored_decimal"])
                        for row in prior_returns
                    ),
                    Decimal("0"),
                )
                if quantity + already_quantity == sold:
                    stock_restore = max(Decimal("0"), deduction - restored_before)
                else:
                    stock_restore = (
                        (deduction * quantity / sold)
                        .quantize(Decimal("0.000001"))
                        .normalize()
                    )
                line_net = int(item["subtotal_cents"])
                refunded_before = sum(int(row["refund_cents"]) for row in prior_returns)
                if quantity + already_quantity == sold:
                    refund = line_net - refunded_before
                else:
                    refund = int(
                        (Decimal(line_net) * quantity / sold).quantize(
                            Decimal("1"), rounding=ROUND_HALF_UP
                        )
                    )
                total_refund += refund
                prepared.append((item, quantity, stock_restore, refund))
            if method == "CREDIT_ADJUSTMENT":
                debt = conn.execute(
                    "SELECT * FROM customer_debts WHERE sale_id=?", (sale_id,)
                ).fetchone()
                if debt is None or int(debt["balance_cents"]) < total_refund:
                    raise SaleError(
                        "credit balance is lower than refund; choose Cash, Card or DuitNow refund"
                    )
                balance = int(debt["balance_cents"]) - total_refund
                status = "CLOSED" if balance == 0 else "OPEN"
                conn.execute(
                    """UPDATE customer_debts SET balance_cents=?,status=?,settled_at=?
                       WHERE id=?""",
                    (balance, status, returned_at if status == "CLOSED" else None, debt["id"]),
                )
            cursor = conn.execute(
                """INSERT INTO sale_returns(
                    return_no,sale_id,total_cents,refund_method,reason,operator_id,returned_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (number, sale_id, total_refund, method, reason, operator_id, returned_at),
            )
            return_id = int(cursor.lastrowid)
            for item, quantity, restore, refund in prepared:
                conn.execute(
                    "INSERT INTO sale_return_items(return_id, sale_item_id, quantity_decimal, stock_restored_decimal, refund_cents) VALUES (?, ?, ?, ?, ?)",
                    (
                        return_id,
                        item["id"],
                        quantity_text(quantity),
                        quantity_text(restore),
                        refund,
                    ),
                )
                conn.execute(
                    "UPDATE sale_items SET returned_stock_decimal=? WHERE id=?",
                    (
                        quantity_text(
                            parse_quantity(item["returned_stock_decimal"]) + restore
                        ),
                        item["id"],
                    ),
                )
                if item["product_id"] is not None:
                    product = conn.execute(
                        "SELECT stock_decimal FROM products WHERE id=?",
                        (item["product_id"],),
                    ).fetchone()
                    old_stock = parse_quantity(product["stock_decimal"])
                    new_stock = old_stock + restore
                    conn.execute(
                        "UPDATE products SET stock_decimal=?, updated_at=? WHERE id=?",
                        (quantity_text(new_stock), returned_at, item["product_id"]),
                    )
                    conn.execute(
                        """INSERT INTO stock_movements(product_id, source_type, reference,
                           old_stock_decimal, change_decimal, new_stock_decimal, operator_id, created_at)
                           VALUES (?, 'RETURN', ?, ?, ?, ?, ?, ?)""",
                        (
                            item["product_id"],
                            number,
                            quantity_text(old_stock),
                            quantity_text(restore),
                            quantity_text(new_stock),
                            operator_id,
                            returned_at,
                        ),
                    )
            AuditService.record(
                conn,
                action="RETURN",
                module="SALES",
                user_id=operator_id,
                record_type="SALE_RETURN",
                record_id=return_id,
                new_value={
                    "return_no": number,
                    "refund_cents": total_refund,
                    "refund_method": method,
                },
            )
            return number
