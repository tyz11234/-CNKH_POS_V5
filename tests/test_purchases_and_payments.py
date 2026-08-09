from __future__ import annotations

import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from cnkh_pos.database.bootstrap import bootstrap_database
from cnkh_pos.database.connection import Database
from cnkh_pos.database.migrations import utc_now_text
from cnkh_pos.services.auth import AuthService
from cnkh_pos.services.payments import CustomerPaymentService, SupplierPaymentService
from cnkh_pos.services.purchases import PurchaseLine, PurchaseService
from cnkh_pos.services.sales import SaleLine, SalesService


class PurchaseAndPaymentTests(unittest.TestCase):
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
                    """INSERT INTO products(name, cost_cents, selling_price_cents, stock_decimal, unit, created_at, updated_at)
                   VALUES ('Cable', 200, 400, '10', 'meter', ?, ?)""",
                    (now, now),
                ).lastrowid
            )
            self.supplier_id = int(
                conn.execute(
                    "INSERT INTO suppliers(name, created_at, updated_at) VALUES ('Supplier A', ?, ?)",
                    (now, now),
                ).lastrowid
            )
            self.customer_id = int(
                conn.execute(
                    "INSERT INTO customers(name, created_at, updated_at) VALUES ('Customer A', ?, ?)",
                    (now, now),
                ).lastrowid
            )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _stock(self) -> Decimal:
        conn = self.database.connect(readonly=True)
        try:
            return Decimal(
                conn.execute(
                    "SELECT stock_decimal FROM products WHERE id=?", (self.product_id,)
                ).fetchone()[0]
            )
        finally:
            conn.close()

    def test_purchase_adds_stock_and_delete_reverses_it(self) -> None:
        service = PurchaseService(self.database)
        result = service.create_purchase(
            supplier_id=self.supplier_id,
            lines=[PurchaseLine(self.product_id, Decimal("2.5"), 250)],
            paid_cents=0,
            payment_method="CASH",
            operator_id=self.admin_id,
        )
        self.assertEqual(result.total_cents, 625)
        self.assertEqual(result.status, "UNPAID")
        self.assertEqual(self._stock(), Decimal("12.5"))
        service.delete_purchase(purchase_id=result.purchase_id, admin_id=self.admin_id)
        self.assertEqual(self._stock(), Decimal("10"))

    def test_supplier_each_payment_is_independent_and_status_changes(self) -> None:
        result = PurchaseService(self.database).create_purchase(
            supplier_id=self.supplier_id,
            lines=[PurchaseLine(self.product_id, Decimal("5"), 200)],
            paid_cents=200,
            payment_method="CASH",
            operator_id=self.admin_id,
        )
        payments = SupplierPaymentService(self.database)
        payments.record_payment(
            purchase_id=result.purchase_id,
            amount_cents=300,
            payment_method="DUITNOW_QR",
            note="second",
            operator_id=self.admin_id,
        )
        payments.record_payment(
            purchase_id=result.purchase_id,
            amount_cents=500,
            payment_method="CARD",
            note="final",
            operator_id=self.admin_id,
        )
        conn = self.database.connect(readonly=True)
        try:
            purchase = conn.execute(
                "SELECT paid_cents, status FROM purchases WHERE id=?",
                (result.purchase_id,),
            ).fetchone()
            self.assertEqual(tuple(purchase), (1000, "PAID"))
            rows = conn.execute(
                "SELECT amount_cents, payment_method FROM supplier_payments WHERE purchase_id=? ORDER BY id",
                (result.purchase_id,),
            ).fetchall()
            self.assertEqual(
                [tuple(row) for row in rows],
                [(200, "CASH"), (300, "DUITNOW_QR"), (500, "CARD")],
            )
        finally:
            conn.close()

    def test_customer_payments_preserve_history_and_settlement_time(self) -> None:
        sale = SalesService(self.database).create_sale(
            lines=[SaleLine(self.product_id, Decimal("2"), Decimal("2"))],
            payment_method="CREDIT",
            paid_cents=0,
            cashier_id=self.admin_id,
            customer_id=self.customer_id,
        )
        conn = self.database.connect(readonly=True)
        try:
            debt_id = int(
                conn.execute(
                    "SELECT id FROM customer_debts WHERE sale_id=?", (sale.sale_id,)
                ).fetchone()[0]
            )
        finally:
            conn.close()
        service = CustomerPaymentService(self.database)
        service.record_payment(
            debt_id=debt_id,
            amount_cents=300,
            payment_method="CASH",
            note="part",
            operator_id=self.admin_id,
        )
        service.record_payment(
            debt_id=debt_id,
            amount_cents=500,
            payment_method="CARD",
            note="final",
            operator_id=self.admin_id,
        )
        conn = self.database.connect(readonly=True)
        try:
            debt = conn.execute(
                "SELECT balance_cents, status, settled_at FROM customer_debts WHERE id=?",
                (debt_id,),
            ).fetchone()
            self.assertEqual(debt["balance_cents"], 0)
            self.assertEqual(debt["status"], "CLOSED")
            self.assertIsNotNone(debt["settled_at"])
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) FROM customer_payments WHERE debt_id=?", (debt_id,)
                ).fetchone()[0],
                2,
            )
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
