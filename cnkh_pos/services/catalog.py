from __future__ import annotations

import secrets
import sqlite3
from dataclasses import dataclass

from cnkh_pos.database.connection import Database
from cnkh_pos.database.migrations import utc_now_text
from cnkh_pos.services.audit import AuditService
from cnkh_pos.services.quantities import parse_quantity, quantity_text


def ean13_check_digit(first_twelve: str) -> str:
    if len(first_twelve) != 12 or not first_twelve.isdigit():
        raise ValueError("EAN-13 body must contain 12 digits")
    total = sum(
        int(value) * (1 if index % 2 == 0 else 3)
        for index, value in enumerate(first_twelve)
    )
    return str((10 - total % 10) % 10)


def is_valid_ean13(value: str) -> bool:
    return (
        len(value) == 13
        and value.isdigit()
        and value[-1] == ean13_check_digit(value[:12])
    )


def generate_internal_ean13(conn: sqlite3.Connection) -> str:
    for _ in range(100):
        body = "20" + f"{secrets.randbelow(10_000_000_000):010d}"
        barcode = body + ean13_check_digit(body)
        if (
            conn.execute(
                "SELECT 1 FROM products WHERE barcode=?", (barcode,)
            ).fetchone()
            is None
        ):
            return barcode
    raise RuntimeError("could not allocate an internal EAN-13")


@dataclass(frozen=True, slots=True)
class ProductInput:
    name: str
    aliases: str = ""
    category_id: int | None = None
    sku: str | None = None
    cost_cents: int = 0
    selling_price_cents: int = 0
    stock: str = "0"
    unit: str = "pcs"
    location: str = ""
    low_stock: str = "0"
    barcode: str | None = None


class CatalogService:
    def __init__(self, database: Database):
        self.database = database

    def add_product(self, data: ProductInput, *, admin_id: int) -> int:
        with self.database.transaction() as conn:
            self._validate_product(conn, data)
            now = utc_now_text()
            barcode = (data.barcode or "").strip() or generate_internal_ean13(conn)
            cursor = conn.execute(
                """INSERT INTO products(
                    name, aliases, category_id, sku, cost_cents, selling_price_cents,
                    stock_decimal, unit, location, low_stock_decimal, barcode, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    data.name.strip(),
                    data.aliases.strip(),
                    data.category_id,
                    self._optional(data.sku),
                    data.cost_cents,
                    data.selling_price_cents,
                    quantity_text(parse_quantity(data.stock)),
                    data.unit.strip(),
                    data.location.strip(),
                    quantity_text(parse_quantity(data.low_stock)),
                    barcode,
                    now,
                    now,
                ),
            )
            product_id = int(cursor.lastrowid)
            AuditService.record(
                conn,
                action="CREATE",
                module="PRODUCTS",
                user_id=admin_id,
                record_type="PRODUCT",
                record_id=product_id,
                new_value={**data.__dict__, "barcode": barcode}
                if hasattr(data, "__dict__")
                else {"name": data.name, "barcode": barcode},
            )
            return product_id

    def update_product(
        self, product_id: int, data: ProductInput, *, admin_id: int
    ) -> None:
        with self.database.transaction() as conn:
            before = conn.execute(
                "SELECT * FROM products WHERE id=? AND is_deleted=0", (product_id,)
            ).fetchone()
            if before is None:
                raise LookupError("product not found")
            self._validate_product(conn, data, exclude_id=product_id)
            barcode = (data.barcode or "").strip() or str(
                before["barcode"] or generate_internal_ean13(conn)
            )
            now = utc_now_text()
            conn.execute(
                """UPDATE products SET name=?, aliases=?, category_id=?, sku=?, cost_cents=?,
                    selling_price_cents=?, stock_decimal=?, unit=?, location=?, low_stock_decimal=?,
                    barcode=?, updated_at=? WHERE id=?""",
                (
                    data.name.strip(),
                    data.aliases.strip(),
                    data.category_id,
                    self._optional(data.sku),
                    data.cost_cents,
                    data.selling_price_cents,
                    quantity_text(parse_quantity(data.stock)),
                    data.unit.strip(),
                    data.location.strip(),
                    quantity_text(parse_quantity(data.low_stock)),
                    barcode,
                    now,
                    product_id,
                ),
            )
            if (
                int(before["cost_cents"]) != data.cost_cents
                or int(before["selling_price_cents"]) != data.selling_price_cents
            ):
                conn.execute(
                    """INSERT INTO product_price_history(
                       product_id, old_cost_cents, new_cost_cents, old_selling_price_cents,
                       new_selling_price_cents, admin_id, changed_at) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        product_id,
                        before["cost_cents"],
                        data.cost_cents,
                        before["selling_price_cents"],
                        data.selling_price_cents,
                        admin_id,
                        now,
                    ),
                )
            AuditService.record(
                conn,
                action="UPDATE",
                module="PRODUCTS",
                user_id=admin_id,
                record_type="PRODUCT",
                record_id=product_id,
                old_value=dict(before),
                new_value={
                    "name": data.name,
                    "cost_cents": data.cost_cents,
                    "selling_price_cents": data.selling_price_cents,
                    "stock_decimal": quantity_text(parse_quantity(data.stock)),
                    "barcode": barcode,
                },
            )

    def delete_products(self, product_ids: list[int], *, admin_id: int) -> int:
        """Safe historical deletion: removes business data while retaining an FK tombstone."""
        deleted = 0
        with self.database.transaction() as conn:
            for product_id in sorted(set(product_ids)):
                row = conn.execute(
                    "SELECT * FROM products WHERE id=? AND is_deleted=0", (product_id,)
                ).fetchone()
                if row is None:
                    continue
                AuditService.record(
                    conn,
                    action="DELETE",
                    module="PRODUCTS",
                    user_id=admin_id,
                    record_type="PRODUCT",
                    record_id=product_id,
                    old_value=dict(row),
                    new_value={"is_deleted": 1},
                    detail="Historical FK tombstone retained",
                )
                conn.execute(
                    """UPDATE products SET name=?, aliases='', category_id=NULL, sku=NULL,
                       barcode=NULL, location='', is_deleted=1, updated_at=? WHERE id=?""",
                    (f"[Deleted Product #{product_id}]", utc_now_text(), product_id),
                )
                deleted += 1
        return deleted

    @staticmethod
    def _optional(value: str | None) -> str | None:
        cleaned = (value or "").strip()
        return cleaned or None

    @staticmethod
    def _validate_product(
        conn: sqlite3.Connection, data: ProductInput, exclude_id: int | None = None
    ) -> None:
        if not data.name.strip():
            raise ValueError("product name is required")
        if not data.unit.strip():
            raise ValueError("unit is required")
        if data.cost_cents < 0 or data.selling_price_cents < 0:
            raise ValueError("money cannot be negative")
        parse_quantity(data.stock)
        parse_quantity(data.low_stock)
        for column, raw in (("sku", data.sku), ("barcode", data.barcode)):
            value = (raw or "").strip()
            if not value:
                continue
            row = conn.execute(
                f"SELECT id FROM products WHERE {column}=? COLLATE NOCASE AND id<>COALESCE(?, -1)",
                (value, exclude_id),
            ).fetchone()
            if row is not None:
                raise ValueError(f"duplicate {column}")


class CategoryService:
    def __init__(self, database: Database):
        self.database = database

    def add(self, name: str, *, admin_id: int) -> int:
        cleaned = name.strip()
        if not cleaned:
            raise ValueError("category name is required")
        with self.database.transaction() as conn:
            now = utc_now_text()
            category_id = int(
                conn.execute(
                    "INSERT INTO categories(name, created_at, updated_at) VALUES (?, ?, ?)",
                    (cleaned, now, now),
                ).lastrowid
            )
            AuditService.record(
                conn,
                action="CREATE",
                module="CATEGORIES",
                user_id=admin_id,
                record_type="CATEGORY",
                record_id=category_id,
                new_value={"name": cleaned},
            )
            return category_id

    def rename(self, category_id: int, name: str, *, admin_id: int) -> None:
        cleaned = name.strip()
        if not cleaned:
            raise ValueError("category name is required")
        with self.database.transaction() as conn:
            row = conn.execute(
                "SELECT name FROM categories WHERE id=? AND is_deleted=0",
                (category_id,),
            ).fetchone()
            if row is None:
                raise LookupError("category not found")
            conn.execute(
                "UPDATE categories SET name=?, updated_at=? WHERE id=?",
                (cleaned, utc_now_text(), category_id),
            )
            AuditService.record(
                conn,
                action="UPDATE",
                module="CATEGORIES",
                user_id=admin_id,
                record_type="CATEGORY",
                record_id=category_id,
                old_value={"name": row["name"]},
                new_value={"name": cleaned},
            )

    def delete(self, category_id: int, *, admin_id: int) -> int:
        with self.database.transaction() as conn:
            row = conn.execute(
                "SELECT name FROM categories WHERE id=? AND is_deleted=0",
                (category_id,),
            ).fetchone()
            if row is None:
                raise LookupError("category not found")
            product_count = int(
                conn.execute(
                    "SELECT COUNT(*) FROM products WHERE category_id=? AND is_deleted=0",
                    (category_id,),
                ).fetchone()[0]
            )
            conn.execute(
                "UPDATE products SET category_id=NULL, updated_at=? WHERE category_id=?",
                (utc_now_text(), category_id),
            )
            conn.execute("DELETE FROM categories WHERE id=?", (category_id,))
            AuditService.record(
                conn,
                action="DELETE",
                module="CATEGORIES",
                user_id=admin_id,
                record_type="CATEGORY",
                record_id=category_id,
                old_value={"name": row["name"], "product_count": product_count},
                detail="Products safely moved to uncategorized",
            )
            return product_count
