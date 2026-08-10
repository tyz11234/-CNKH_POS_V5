from __future__ import annotations

import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

from cnkh_pos.database.bootstrap import bootstrap_database
from cnkh_pos.database.connection import Database
from cnkh_pos.services.auth import AuthService
from cnkh_pos.services.backup import BackupService
from cnkh_pos.services.catalog import CatalogService, ProductInput
from cnkh_pos.services.daily_closing import DailyClosingService
from cnkh_pos.services.held_orders import HeldOrderService, cart_state_from_held_payload
from cnkh_pos.services.printing import RECEIPT_TEXT_WIDTH, PrintingService
from cnkh_pos.services.restore import RestoreService
from cnkh_pos.services.sales import SaleLine, SalesService


class ReleaseServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.database = Database(self.root / "hardware_pos.db")
        self.backups = self.root / "backups"
        bootstrap_database(self.database.path, self.backups)
        with self.database.transaction() as conn:
            self.admin = AuthService.create_user(
                conn,
                username="admin",
                display_name="Admin",
                password="SafePass123!",
                role="ADMIN",
                permissions={},
                admin_id=None,
            )
        self.product = CatalogService(self.database).add_product(
            ProductInput(
                name="PVC Cable", selling_price_cents=280, stock="100", unit="meter"
            ),
            admin_id=self.admin,
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_hold_and_retrieve_preserves_cart(self) -> None:
        service = HeldOrderService(self.database)
        held = service.hold(
            {
                "items": [
                    {
                        "product_id": self.product,
                        "quantity": "2.5",
                        "discount_cents": 50,
                    }
                ]
            },
            cashier_id=self.admin,
        )
        retrieved = service.retrieve_latest(cashier_id=self.admin)
        self.assertEqual(retrieved.hold_no, held.hold_no)
        self.assertEqual(retrieved.payload["items"][0]["quantity"], "2.5")

    def test_retrieved_cart_omits_zero_discount_entries(self) -> None:
        quantities, discounts = cart_state_from_held_payload(
            {
                "items": [
                    {"product_id": 101, "quantity": "2", "discount_cents": 50},
                    {"product_id": 202, "quantity": "1", "discount_cents": 0},
                ]
            }
        )
        self.assertEqual(
            quantities, {101: Decimal("2"), 202: Decimal("1")}
        )
        self.assertEqual(discounts, {101: 50})

    def test_receipt_generation_and_reprint_lookup_do_not_change_sale_or_stock(
        self,
    ) -> None:
        sale = SalesService(self.database).create_sale(
            lines=[SaleLine(self.product, Decimal("2"), Decimal("2"))],
            payment_method="CASH",
            paid_cents=1000,
            cashier_id=self.admin,
        )
        conn = self.database.connect(readonly=True)
        before = tuple(
            conn.execute(
                "SELECT (SELECT COUNT(*) FROM sales),(SELECT stock_decimal FROM products WHERE id=?)",
                (self.product,),
            ).fetchone()
        )
        conn.close()
        printing = PrintingService(self.database)
        receipt = printing.latest_receipt()
        self.assertEqual(receipt.sale_id, sale.sale_id)
        text = printing.render_text(receipt)
        self.assertIn(sale.receipt_no, text)
        lines = text.splitlines()
        self.assertLessEqual(max(map(len, lines)), RECEIPT_TEXT_WIDTH)
        self.assertTrue(
            any(line.startswith("SUBTOTAL") and line.endswith("RM 5.60") for line in lines)
        )
        self.assertTrue(
            any(line.startswith("TOTAL") and line.endswith("RM 5.60") for line in lines)
        )
        self.assertTrue(
            any(line.startswith("PAID") and line.endswith("RM 10.00") for line in lines)
        )
        self.assertTrue(
            any(line.startswith("CHANGE") and line.endswith("RM 4.40") for line in lines)
        )
        pdf = printing.render_pdf(receipt, self.root / "receipt.pdf")
        self.assertGreater(pdf.stat().st_size, 500)
        conn = self.database.connect(readonly=True)
        after = tuple(
            conn.execute(
                "SELECT (SELECT COUNT(*) FROM sales),(SELECT stock_decimal FROM products WHERE id=?)",
                (self.product,),
            ).fetchone()
        )
        conn.close()
        self.assertEqual(before, after)

    def test_daily_closing_saves_variance(self) -> None:
        SalesService(self.database).create_sale(
            lines=[SaleLine(self.product, Decimal("1"), Decimal("1"))],
            payment_method="CASH",
            paid_cents=500,
            cashier_id=self.admin,
        )
        result = DailyClosingService(self.database).complete(
            business_date=date.today().isoformat(),
            cashier_id=self.admin,
            actual_cash_cents=300,
            note="counted",
        )
        self.assertEqual(result.system_cash_cents, 280)
        self.assertEqual(result.variance_cents, 20)

    def test_restore_requires_password_and_restores_backup_bytes(self) -> None:
        backup = (
            BackupService(self.backups)
            .create(self.database.path, reason="checkpoint")
            .path
        )
        CatalogService(self.database).add_product(
            ProductInput(name="Temporary Item"), admin_id=self.admin
        )
        with self.assertRaises(PermissionError):
            RestoreService(self.database, self.backups).restore(
                backup, admin_id=self.admin, password="wrong password"
            )
        safety = RestoreService(self.database, self.backups).restore(
            backup, admin_id=self.admin, password="SafePass123!"
        )
        self.assertTrue(safety.exists())
        conn = self.database.connect(readonly=True)
        try:
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) FROM products WHERE name='Temporary Item'"
                ).fetchone()[0],
                0,
            )
            self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
