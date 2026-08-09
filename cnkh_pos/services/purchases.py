from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from cnkh_pos.database.connection import Database
from cnkh_pos.database.migrations import utc_now_text
from cnkh_pos.database.repositories import SupplierPaymentRepository
from cnkh_pos.services.audit import AuditService
from cnkh_pos.services.document_numbers import next_document_number
from cnkh_pos.services.quantities import parse_quantity, quantity_text


class PurchaseError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class PurchaseLine:
    product_id: int
    quantity: Decimal
    unit_cost_cents: int


@dataclass(frozen=True, slots=True)
class PurchaseResult:
    purchase_id: int
    purchase_no: str
    total_cents: int
    status: str


def _subtotal(cost_cents: int, quantity: Decimal) -> int:
    return int(
        (Decimal(cost_cents) * quantity).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    )


class PurchaseService:
    def __init__(self, database: Database):
        self.database = database

    def create_purchase(
        self,
        *,
        supplier_id: int,
        lines: list[PurchaseLine],
        paid_cents: int,
        payment_method: str,
        operator_id: int,
        business_date: date | None = None,
    ) -> PurchaseResult:
        if not lines:
            raise PurchaseError("purchase has no items")
        if payment_method.upper() not in {"CASH", "CARD", "DUITNOW_QR"}:
            raise PurchaseError("unsupported payment method")
        combined: dict[int, PurchaseLine] = {}
        for line in lines:
            quantity = parse_quantity(line.quantity, allow_zero=False)
            if line.unit_cost_cents < 0:
                raise PurchaseError("purchase cost cannot be negative")
            previous = combined.get(line.product_id)
            combined[line.product_id] = PurchaseLine(
                product_id=line.product_id,
                quantity=quantity
                if previous is None
                else parse_quantity(previous.quantity, allow_zero=False) + quantity,
                unit_cost_cents=line.unit_cost_cents,
            )
        normalized_lines = list(combined.values())
        with self.database.transaction() as conn:
            supplier = conn.execute(
                "SELECT id FROM suppliers WHERE id=? AND is_deleted=0", (supplier_id,)
            ).fetchone()
            if supplier is None:
                raise PurchaseError("supplier is not available")
            prepared: list[tuple[object, Decimal, int]] = []
            total = 0
            allowed_product_ids = {
                int(row[0])
                for row in conn.execute(
                    """SELECT product_id FROM supplier_products
                       WHERE supplier_id=? AND is_active=1""",
                    (supplier_id,),
                )
            }
            if not allowed_product_ids:
                raise PurchaseError(
                    "supplier has no product catalogue; configure supplied products first"
                )
            for line in normalized_lines:
                quantity = parse_quantity(line.quantity, allow_zero=False)
                if line.product_id not in allowed_product_ids:
                    raise PurchaseError("product is not registered for this supplier")
                product = conn.execute(
                    "SELECT * FROM products WHERE id=? AND is_deleted=0",
                    (line.product_id,),
                ).fetchone()
                if product is None:
                    raise PurchaseError("product is not available")
                line_total = _subtotal(line.unit_cost_cents, quantity)
                total += line_total
                prepared.append((product, quantity, line_total))
            if paid_cents < 0 or paid_cents > total:
                raise PurchaseError("invalid paid amount")
            status = (
                "PAID"
                if paid_cents == total
                else ("PARTIAL" if paid_cents else "UNPAID")
            )
            now = utc_now_text()
            purchase_no = next_document_number(
                conn, "PURCHASE", business_date or date.today(), "PI-"
            )
            cursor = conn.execute(
                """INSERT INTO purchases(
                    purchase_no, supplier_id, total_cents, paid_cents, status, purchased_at, created_by
                ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (purchase_no, supplier_id, total, paid_cents, status, now, operator_id),
            )
            purchase_id = int(cursor.lastrowid)
            for line, (product, quantity, line_total) in zip(
                normalized_lines, prepared, strict=True
            ):
                conn.execute(
                    """INSERT INTO purchase_items(
                        purchase_id, product_id, product_name_snapshot, quantity_decimal,
                        unit_cost_cents, subtotal_cents
                    ) VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        purchase_id,
                        product["id"],
                        product["name"],
                        quantity_text(quantity),
                        line.unit_cost_cents,
                        line_total,
                    ),
                )
                old_stock = parse_quantity(product["stock_decimal"])
                new_stock = old_stock + quantity
                conn.execute(
                    "UPDATE products SET stock_decimal=?, cost_cents=?, updated_at=? WHERE id=?",
                    (
                        quantity_text(new_stock),
                        line.unit_cost_cents,
                        now,
                        product["id"],
                    ),
                )
                conn.execute(
                    """INSERT INTO stock_movements(
                        product_id, source_type, reference, old_stock_decimal, change_decimal,
                        new_stock_decimal, operator_id, created_at
                    ) VALUES (?, 'PURCHASE', ?, ?, ?, ?, ?, ?)""",
                    (
                        product["id"],
                        purchase_no,
                        quantity_text(old_stock),
                        quantity_text(quantity),
                        quantity_text(new_stock),
                        operator_id,
                        now,
                    ),
                )
                if int(product["cost_cents"]) != line.unit_cost_cents:
                    conn.execute(
                        """INSERT INTO product_price_history(
                            product_id, old_cost_cents, new_cost_cents, old_selling_price_cents,
                            new_selling_price_cents, admin_id, changed_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        (
                            product["id"],
                            product["cost_cents"],
                            line.unit_cost_cents,
                            product["selling_price_cents"],
                            product["selling_price_cents"],
                            operator_id,
                            now,
                        ),
                    )
            if paid_cents:
                SupplierPaymentRepository.add(
                    conn,
                    supplier_id=supplier_id,
                    purchase_id=purchase_id,
                    amount_cents=paid_cents,
                    payment_method=payment_method,
                    note="Initial purchase payment",
                    operator_id=operator_id,
                )
            AuditService.record(
                conn,
                action="CREATE",
                module="PURCHASES",
                user_id=operator_id,
                record_type="PURCHASE",
                record_id=purchase_id,
                new_value={
                    "purchase_no": purchase_no,
                    "total_cents": total,
                    "paid_cents": paid_cents,
                    "status": status,
                },
            )
            return PurchaseResult(purchase_id, purchase_no, total, status)

    def delete_purchase(self, *, purchase_id: int, admin_id: int) -> None:
        with self.database.transaction() as conn:
            purchase = conn.execute(
                "SELECT * FROM purchases WHERE id=?", (purchase_id,)
            ).fetchone()
            if purchase is None:
                raise LookupError("purchase not found")
            items = conn.execute(
                "SELECT * FROM purchase_items WHERE purchase_id=?", (purchase_id,)
            ).fetchall()
            now = utc_now_text()
            for item in items:
                quantity = parse_quantity(item["quantity_decimal"])
                reversed_before = parse_quantity(item["reversed_stock_decimal"])
                reverse = max(Decimal("0"), quantity - reversed_before)
                if item["product_id"] is not None and reverse:
                    product = conn.execute(
                        "SELECT stock_decimal FROM products WHERE id=?",
                        (item["product_id"],),
                    ).fetchone()
                    if product is not None:
                        old_stock = parse_quantity(product["stock_decimal"])
                        if reverse > old_stock:
                            raise PurchaseError(
                                "cannot delete purchase because part of its stock has already been sold or adjusted"
                            )
                        new_stock = old_stock - reverse
                        conn.execute(
                            "UPDATE products SET stock_decimal=?, updated_at=? WHERE id=?",
                            (quantity_text(new_stock), now, item["product_id"]),
                        )
                        conn.execute(
                            """INSERT INTO stock_movements(
                                product_id, source_type, reference, old_stock_decimal, change_decimal,
                                new_stock_decimal, operator_id, created_at
                            ) VALUES (?, 'DELETE_PURCHASE', ?, ?, ?, ?, ?, ?)""",
                            (
                                item["product_id"],
                                purchase["purchase_no"],
                                quantity_text(old_stock),
                                quantity_text(-reverse),
                                quantity_text(new_stock),
                                admin_id,
                                now,
                            ),
                        )
            conn.execute(
                "UPDATE supplier_payments SET voided_at=?, note=note || ' [VOID: purchase deleted]' WHERE purchase_id=? AND voided_at IS NULL",
                (now, purchase_id),
            )
            snapshot = dict(purchase)
            snapshot["items"] = [dict(item) for item in items]
            AuditService.record(
                conn,
                action="DELETE",
                module="PURCHASES",
                user_id=admin_id,
                record_type="PURCHASE",
                record_id=purchase_id,
                old_value=snapshot,
                detail="Permanent delete; stock reversed; linked payments retained as void history",
            )
            conn.execute("DELETE FROM purchases WHERE id=?", (purchase_id,))
