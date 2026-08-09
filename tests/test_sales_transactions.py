from __future__ import annotations

import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

from cnkh_pos.database.bootstrap import bootstrap_database
from cnkh_pos.database.connection import Database
from cnkh_pos.database.migrations import utc_now_text
from cnkh_pos.services.auth import AuthService
from cnkh_pos.services.sales import ReturnService, SaleError, SaleLine, SalesService


class SalesTransactionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.database = Database(root / "hardware_pos.db")
        bootstrap_database(self.database.path, root / "backups")
        with self.database.transaction() as conn:
            self.admin_id = AuthService.create_user(
                conn,
                username="admin",
                display_name="Admin",
                password="SafePass123!",
                role="ADMIN",
                permissions={},
                admin_id=None,
            )
            now = utc_now_text()
            self.product_id = int(
                conn.execute(
                    """INSERT INTO products(name, sku, barcode, cost_cents, selling_price_cents,
                       stock_decimal, unit, created_at, updated_at)
                   VALUES ('Pipe 20mm', 'PIPE20', '955500001', 200, 450, '10.5', 'meter', ?, ?)""",
                    (now, now),
                ).lastrowid
            )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _stock(self) -> Decimal:
        conn = self.database.connect(readonly=True)
        try:
            return Decimal(
                str(
                    conn.execute(
                        "SELECT stock_decimal FROM products WHERE id=?",
                        (self.product_id,),
                    ).fetchone()[0]
                )
            )
        finally:
            conn.close()

    def test_sale_is_atomic_and_deducts_decimal_stock(self) -> None:
        result = SalesService(self.database).create_sale(
            lines=[SaleLine(self.product_id, Decimal("2.5"), Decimal("2.5"))],
            payment_method="CASH",
            paid_cents=2000,
            cashier_id=self.admin_id,
            business_date=date(2026, 8, 9),
        )
        self.assertEqual(result.receipt_no, "CNKH20260809-001")
        self.assertEqual(result.total_cents, 1125)
        self.assertEqual(result.change_cents, 875)
        self.assertEqual(self._stock(), Decimal("8"))
        conn = self.database.connect(readonly=True)
        try:
            movement = conn.execute(
                "SELECT source_type, change_decimal FROM stock_movements ORDER BY id DESC"
            ).fetchone()
            self.assertEqual(tuple(movement), ("SALE", "-2.5"))
        finally:
            conn.close()

    def test_failed_sale_writes_nothing(self) -> None:
        with self.assertRaises(SaleError):
            SalesService(self.database).create_sale(
                lines=[SaleLine(self.product_id, Decimal("1"), Decimal("99"))],
                payment_method="CASH",
                paid_cents=1000,
                cashier_id=self.admin_id,
            )
        self.assertEqual(self._stock(), Decimal("10.5"))
        conn = self.database.connect(readonly=True)
        try:
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM sales").fetchone()[0], 0
            )
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM stock_movements").fetchone()[0], 0
            )
        finally:
            conn.close()

    def test_delete_sale_restores_stock(self) -> None:
        service = SalesService(self.database)
        result = service.create_sale(
            lines=[SaleLine(self.product_id, Decimal("3"), Decimal("3"))],
            payment_method="CARD",
            paid_cents=1350,
            cashier_id=self.admin_id,
        )
        service.delete_sale(sale_id=result.sale_id, admin_id=self.admin_id)
        self.assertEqual(self._stock(), Decimal("10.5"))
        conn = self.database.connect(readonly=True)
        try:
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM sales").fetchone()[0], 0
            )
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) FROM audit_logs WHERE action='DELETE'"
                ).fetchone()[0],
                1,
            )
        finally:
            conn.close()

    def test_partial_return_then_delete_does_not_restore_twice(self) -> None:
        service = SalesService(self.database)
        result = service.create_sale(
            lines=[SaleLine(self.product_id, Decimal("4"), Decimal("4"))],
            payment_method="CASH",
            paid_cents=2000,
            cashier_id=self.admin_id,
        )
        conn = self.database.connect(readonly=True)
        try:
            sale_item_id = int(
                conn.execute(
                    "SELECT id FROM sale_items WHERE sale_id=?", (result.sale_id,)
                ).fetchone()[0]
            )
        finally:
            conn.close()
        ReturnService(self.database).create_return(
            sale_id=result.sale_id,
            quantities_by_sale_item={sale_item_id: Decimal("1.5")},
            reason="Customer return",
            operator_id=self.admin_id,
        )
        self.assertEqual(self._stock(), Decimal("8"))
        service.delete_sale(sale_id=result.sale_id, admin_id=self.admin_id)
        self.assertEqual(self._stock(), Decimal("10.5"))


if __name__ == "__main__":
    unittest.main()
