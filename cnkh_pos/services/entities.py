from __future__ import annotations

from dataclasses import dataclass

from cnkh_pos.database.connection import Database
from cnkh_pos.database.migrations import utc_now_text
from cnkh_pos.services.audit import AuditService


@dataclass(frozen=True, slots=True)
class EntityInput:
    name: str
    phone: str = ""
    email: str = ""
    notes: str = ""


class EntityService:
    def __init__(self, database: Database, entity: str):
        if entity not in {"customers", "suppliers"}:
            raise ValueError("unsupported entity")
        self.database = database
        self.entity = entity
        self.module = "CUSTOMERS" if entity == "customers" else "SUPPLIERS"

    @staticmethod
    def _validate(data: EntityInput) -> EntityInput:
        name = data.name.strip()
        if not name:
            raise ValueError("name is required")
        return EntityInput(
            name=name,
            phone=data.phone.strip(),
            email=data.email.strip(),
            notes=data.notes.strip(),
        )

    def add(self, data: EntityInput, *, admin_id: int) -> int:
        data = self._validate(data)
        now = utc_now_text()
        with self.database.transaction() as conn:
            if self.entity == "customers":
                cursor = conn.execute(
                    """INSERT INTO customers(name,phone,notes,created_at,updated_at)
                       VALUES (?,?,?,?,?)""",
                    (data.name, data.phone, data.notes, now, now),
                )
            else:
                cursor = conn.execute(
                    """INSERT INTO suppliers(name,phone,email,notes,created_at,updated_at)
                       VALUES (?,?,?,?,?,?)""",
                    (data.name, data.phone, data.email, data.notes, now, now),
                )
            entity_id = int(cursor.lastrowid)
            AuditService.record(
                conn,
                action="CREATE",
                module=self.module,
                user_id=admin_id,
                record_type=self.entity[:-1].upper(),
                record_id=entity_id,
                new_value={
                    "name": data.name,
                    "phone": data.phone,
                    "email": data.email,
                    "notes": data.notes,
                },
            )
            return entity_id

    def update(self, entity_id: int, data: EntityInput, *, admin_id: int) -> None:
        data = self._validate(data)
        with self.database.transaction() as conn:
            before = conn.execute(
                f"SELECT * FROM {self.entity} WHERE id=? AND is_deleted=0",
                (entity_id,),
            ).fetchone()
            if before is None:
                raise LookupError("record not found")
            if self.entity == "customers":
                conn.execute(
                    "UPDATE customers SET name=?,phone=?,notes=?,updated_at=? WHERE id=?",
                    (data.name, data.phone, data.notes, utc_now_text(), entity_id),
                )
            else:
                conn.execute(
                    """UPDATE suppliers SET name=?,phone=?,email=?,notes=?,updated_at=?
                       WHERE id=?""",
                    (
                        data.name,
                        data.phone,
                        data.email,
                        data.notes,
                        utc_now_text(),
                        entity_id,
                    ),
                )
            AuditService.record(
                conn,
                action="UPDATE",
                module=self.module,
                user_id=admin_id,
                record_type=self.entity[:-1].upper(),
                record_id=entity_id,
                old_value=dict(before),
                new_value={
                    "name": data.name,
                    "phone": data.phone,
                    "email": data.email,
                    "notes": data.notes,
                },
            )

    def delete(self, entity_id: int, *, admin_id: int) -> None:
        with self.database.transaction() as conn:
            before = conn.execute(
                f"SELECT * FROM {self.entity} WHERE id=? AND is_deleted=0",
                (entity_id,),
            ).fetchone()
            if before is None:
                raise LookupError("record not found")
            if self.entity == "customers":
                open_count = int(
                    conn.execute(
                        """SELECT COUNT(*) FROM customer_debts
                           WHERE customer_id=? AND status='OPEN'""",
                        (entity_id,),
                    ).fetchone()[0]
                )
                if open_count:
                    raise ValueError("customer still has open debt and cannot be deleted")
            else:
                open_count = int(
                    conn.execute(
                        """SELECT COUNT(*) FROM purchases
                           WHERE supplier_id=? AND is_deleted=0 AND status<>'PAID'""",
                        (entity_id,),
                    ).fetchone()[0]
                )
                if open_count:
                    raise ValueError(
                        "supplier still has unpaid purchases and cannot be deleted"
                    )
            conn.execute(
                f"UPDATE {self.entity} SET is_deleted=1,updated_at=? WHERE id=?",
                (utc_now_text(), entity_id),
            )
            AuditService.record(
                conn,
                action="DELETE",
                module=self.module,
                user_id=admin_id,
                record_type=self.entity[:-1].upper(),
                record_id=entity_id,
                old_value=dict(before),
                new_value={"is_deleted": 1},
                detail="Soft delete; historical documents remain linked",
            )

    def supplier_product_ids(self, supplier_id: int) -> set[int]:
        if self.entity != "suppliers":
            raise ValueError("supplier product mapping is only available for suppliers")
        conn = self.database.connect(readonly=True)
        try:
            return {
                int(row[0])
                for row in conn.execute(
                    """SELECT product_id FROM supplier_products
                       WHERE supplier_id=? AND is_active=1""",
                    (supplier_id,),
                )
            }
        finally:
            conn.close()

    def set_supplier_products(
        self, supplier_id: int, product_ids: set[int], *, admin_id: int
    ) -> None:
        if self.entity != "suppliers":
            raise ValueError("supplier product mapping is only available for suppliers")
        with self.database.transaction() as conn:
            supplier = conn.execute(
                "SELECT id FROM suppliers WHERE id=? AND is_deleted=0", (supplier_id,)
            ).fetchone()
            if supplier is None:
                raise LookupError("supplier not found")
            valid_ids = {
                int(row[0])
                for row in conn.execute(
                    "SELECT id FROM products WHERE is_deleted=0"
                )
            }
            if not product_ids.issubset(valid_ids):
                raise ValueError("one or more selected products are unavailable")
            before = {
                int(row[0])
                for row in conn.execute(
                    """SELECT product_id FROM supplier_products
                       WHERE supplier_id=? AND is_active=1""",
                    (supplier_id,),
                )
            }
            now = utc_now_text()
            conn.execute(
                "UPDATE supplier_products SET is_active=0,updated_at=? WHERE supplier_id=?",
                (now, supplier_id),
            )
            for product_id in sorted(product_ids):
                conn.execute(
                    """INSERT INTO supplier_products(
                        supplier_id,product_id,is_active,created_at,updated_at
                    ) VALUES (?,?,1,?,?)
                    ON CONFLICT(supplier_id,product_id) DO UPDATE SET
                        is_active=1,updated_at=excluded.updated_at""",
                    (supplier_id, product_id, now, now),
                )
            AuditService.record(
                conn,
                action="UPDATE_PRODUCTS",
                module="SUPPLIERS",
                user_id=admin_id,
                record_type="SUPPLIER",
                record_id=supplier_id,
                old_value={"product_ids": sorted(before)},
                new_value={"product_ids": sorted(product_ids)},
            )
