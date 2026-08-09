from __future__ import annotations

from decimal import Decimal

from cnkh_pos.database.connection import Database
from cnkh_pos.database.migrations import utc_now_text
from cnkh_pos.services.audit import AuditService
from cnkh_pos.services.quantities import (
    parse_quantity,
    parse_signed_quantity,
    quantity_text,
)


class StocktakeError(RuntimeError):
    pass


class StocktakeService:
    def __init__(self, database: Database):
        self.database = database

    def create_draft(self, *, operator_id: int, notes: str = "") -> tuple[int, str]:
        with self.database.transaction() as conn:
            now = utc_now_text()
            day = now[:10].replace("-", "")
            count = (
                int(
                    conn.execute(
                        "SELECT COUNT(*) FROM stocktakes WHERE stocktake_no LIKE ?",
                        (f"ST-{day}-%",),
                    ).fetchone()[0]
                )
                + 1
            )
            number = f"ST-{day}-{count:03d}"
            cursor = conn.execute(
                "INSERT INTO stocktakes(stocktake_no, started_at, operator_id, notes) VALUES (?, ?, ?, ?)",
                (number, now, operator_id, notes),
            )
            stocktake_id = int(cursor.lastrowid)
            products = conn.execute(
                "SELECT * FROM products WHERE is_deleted=0 ORDER BY name COLLATE NOCASE"
            ).fetchall()
            for product in products:
                conn.execute(
                    """INSERT INTO stocktake_items(
                        stocktake_id, product_id, product_name_snapshot, barcode_snapshot,
                        sku_snapshot, system_stock_decimal, physical_count_decimal,
                        variance_decimal, unit_snapshot, location_snapshot
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, '0', ?, ?)""",
                    (
                        stocktake_id,
                        product["id"],
                        product["name"],
                        product["barcode"],
                        product["sku"],
                        product["stock_decimal"],
                        product["stock_decimal"],
                        product["unit"],
                        product["location"],
                    ),
                )
            conn.execute(
                "UPDATE stocktakes SET product_count=? WHERE id=?",
                (len(products), stocktake_id),
            )
            AuditService.record(
                conn,
                action="CREATE",
                module="STOCKTAKE",
                user_id=operator_id,
                record_type="STOCKTAKE",
                record_id=stocktake_id,
                new_value={"stocktake_no": number, "product_count": len(products)},
            )
            return stocktake_id, number

    def set_physical_count(
        self, *, stocktake_id: int, product_id: int, count: Decimal | str
    ) -> None:
        physical = parse_quantity(count)
        with self.database.transaction() as conn:
            header = conn.execute(
                "SELECT status FROM stocktakes WHERE id=?", (stocktake_id,)
            ).fetchone()
            if header is None or header["status"] != "DRAFT":
                raise StocktakeError("only a draft stocktake can be edited")
            item = conn.execute(
                "SELECT system_stock_decimal FROM stocktake_items WHERE stocktake_id=? AND product_id=?",
                (stocktake_id, product_id),
            ).fetchone()
            if item is None:
                raise LookupError("stocktake product not found")
            variance = physical - parse_quantity(item["system_stock_decimal"])
            conn.execute(
                "UPDATE stocktake_items SET physical_count_decimal=?, variance_decimal=? WHERE stocktake_id=? AND product_id=?",
                (
                    quantity_text(physical),
                    quantity_text(variance),
                    stocktake_id,
                    product_id,
                ),
            )

    def complete(self, *, stocktake_id: int, operator_id: int) -> None:
        with self.database.transaction() as conn:
            header = conn.execute(
                "SELECT * FROM stocktakes WHERE id=?", (stocktake_id,)
            ).fetchone()
            if header is None or header["status"] != "DRAFT":
                raise StocktakeError("stocktake is not an open draft")
            items = conn.execute(
                "SELECT * FROM stocktake_items WHERE stocktake_id=?", (stocktake_id,)
            ).fetchall()
            now = utc_now_text()
            differences = increases = decreases = 0
            for item in items:
                variance = parse_signed_quantity(item["variance_decimal"])
                if variance == 0:
                    continue
                differences += 1
                increases += int(variance > 0)
                decreases += int(variance < 0)
                if item["product_id"] is None:
                    continue
                current = conn.execute(
                    "SELECT stock_decimal FROM products WHERE id=?",
                    (item["product_id"],),
                ).fetchone()
                if current is None:
                    continue
                old_current = parse_quantity(current["stock_decimal"])
                physical = parse_quantity(item["physical_count_decimal"])
                change = physical - old_current
                conn.execute(
                    "UPDATE products SET stock_decimal=?, updated_at=? WHERE id=?",
                    (quantity_text(physical), now, item["product_id"]),
                )
                conn.execute(
                    """INSERT INTO stock_movements(product_id, source_type, reference,
                       old_stock_decimal, change_decimal, new_stock_decimal, operator_id, created_at)
                       VALUES (?, 'STOCKTAKE', ?, ?, ?, ?, ?, ?)""",
                    (
                        item["product_id"],
                        header["stocktake_no"],
                        quantity_text(old_current),
                        quantity_text(change),
                        quantity_text(physical),
                        operator_id,
                        now,
                    ),
                )
            conn.execute(
                """UPDATE stocktakes SET completed_at=?, operator_id=?, variance_count=?,
                    increase_count=?, decrease_count=?, status='COMPLETED' WHERE id=?""",
                (now, operator_id, differences, increases, decreases, stocktake_id),
            )
            AuditService.record(
                conn,
                action="COMPLETE",
                module="STOCKTAKE",
                user_id=operator_id,
                record_type="STOCKTAKE",
                record_id=stocktake_id,
                new_value={
                    "variance_count": differences,
                    "increase_count": increases,
                    "decrease_count": decreases,
                    "status": "COMPLETED",
                },
            )
