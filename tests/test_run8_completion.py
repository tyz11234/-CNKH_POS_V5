from __future__ import annotations

import sqlite3
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

from cnkh_pos.database.bootstrap import bootstrap_database
from cnkh_pos.database.connection import Database
from cnkh_pos.services.auth import AuthService
from cnkh_pos.services.backup import ShutdownBackupGuard
from cnkh_pos.services.catalog import CatalogService, ProductInput
from cnkh_pos.services.daily_closing import DailyClosingService
from cnkh_pos.services.document_numbers import save_document_prefixes
from cnkh_pos.services.entities import EntityInput, EntityService
from cnkh_pos.services.held_orders import HeldOrderService
from cnkh_pos.services.maintenance import AuditMaintenanceService
from cnkh_pos.services.payments import CustomerPaymentService, PaymentError
from cnkh_pos.services.printing import resolve_printer_target
from cnkh_pos.services.purchases import PurchaseError, PurchaseLine, PurchaseService
from cnkh_pos.services.reports import ReportService
from cnkh_pos.services.sales import ReturnService, SaleLine, SalesService
from cnkh_pos.services.stocktake import StocktakeService


class Run8CompletionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.database = Database(self.root / "hardware_pos.db")
        self.backups = self.root / "backups"
        bootstrap_database(self.database.path, self.backups)
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
            self.staff_id = AuthService.create_user(
                conn,
                username="staff",
                display_name="Staff",
                password="SafePass456!",
                role="STAFF",
                permissions={"reprint_receipt": True},
                admin_id=self.admin_id,
            )
        catalog = CatalogService(self.database)
        self.product_id = catalog.add_product(
            ProductInput(
                name="Run8 Cable",
                sku="R8-CABLE",
                cost_cents=125,
                selling_price_cents=333,
                stock="20",
                unit="meter",
            ),
            admin_id=self.admin_id,
        )
        self.other_product_id = catalog.add_product(
            ProductInput(
                name="Run8 Hammer",
                sku="R8-HAMMER",
                cost_cents=500,
                selling_price_cents=900,
                stock="5",
            ),
            admin_id=self.admin_id,
        )
        self.customer_id = EntityService(self.database, "customers").add(
            EntityInput("Test Customer", "0123456789", notes="customer note"),
            admin_id=self.admin_id,
        )
        self.supplier_id = EntityService(self.database, "suppliers").add(
            EntityInput(
                "Test Supplier",
                "0198765432",
                "supplier@example.com",
                "supplier note",
            ),
            admin_id=self.admin_id,
        )
        EntityService(self.database, "suppliers").set_supplier_products(
            self.supplier_id, {self.product_id}, admin_id=self.admin_id
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _stock(self, product_id: int | None = None) -> Decimal:
        conn = self.database.connect(readonly=True)
        try:
            value = conn.execute(
                "SELECT stock_decimal FROM products WHERE id=?",
                (product_id or self.product_id,),
            ).fetchone()[0]
            return Decimal(str(value))
        finally:
            conn.close()

    def test_entities_store_full_details_and_enforce_safe_delete(self) -> None:
        service = EntityService(self.database, "customers")
        service.update(
            self.customer_id,
            EntityInput("Updated Customer", "0111111111", notes="updated note"),
            admin_id=self.admin_id,
        )
        conn = self.database.connect(readonly=True)
        try:
            customer = conn.execute(
                "SELECT name,phone,notes FROM customers WHERE id=?",
                (self.customer_id,),
            ).fetchone()
            supplier = conn.execute(
                "SELECT phone,email,notes FROM suppliers WHERE id=?",
                (self.supplier_id,),
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(tuple(customer), ("Updated Customer", "0111111111", "updated note"))
        self.assertEqual(
            tuple(supplier),
            ("0198765432", "supplier@example.com", "supplier note"),
        )

        sale = SalesService(self.database).create_sale(
            lines=[SaleLine(self.product_id, Decimal("1"), Decimal("1"))],
            payment_method="CREDIT",
            paid_cents=0,
            cashier_id=self.staff_id,
            customer_id=self.customer_id,
        )
        with self.assertRaisesRegex(ValueError, "open debt"):
            service.delete(self.customer_id, admin_id=self.admin_id)
        conn = self.database.connect(readonly=True)
        try:
            debt_id = int(
                conn.execute(
                    "SELECT id FROM customer_debts WHERE sale_id=?", (sale.sale_id,)
                ).fetchone()[0]
            )
        finally:
            conn.close()
        CustomerPaymentService(self.database).record_payment(
            debt_id=debt_id,
            amount_cents=sale.total_cents,
            payment_method="CARD",
            note="settled",
            operator_id=self.admin_id,
        )
        service.delete(self.customer_id, admin_id=self.admin_id)

    def test_supplier_catalog_is_many_to_many_and_enforced_by_purchase_service(self) -> None:
        second_supplier = EntityService(self.database, "suppliers").add(
            EntityInput("Second Supplier"), admin_id=self.admin_id
        )
        EntityService(self.database, "suppliers").set_supplier_products(
            second_supplier,
            {self.product_id, self.other_product_id},
            admin_id=self.admin_id,
        )
        self.assertEqual(
            EntityService(self.database, "suppliers").supplier_product_ids(
                second_supplier
            ),
            {self.product_id, self.other_product_id},
        )
        with self.assertRaisesRegex(PurchaseError, "not registered"):
            PurchaseService(self.database).create_purchase(
                supplier_id=self.supplier_id,
                lines=[PurchaseLine(self.other_product_id, Decimal("1"), 500)],
                paid_cents=0,
                payment_method="CASH",
                operator_id=self.admin_id,
            )

    def test_duplicate_purchase_lines_merge_without_losing_stock(self) -> None:
        before = self._stock()
        result = PurchaseService(self.database).create_purchase(
            supplier_id=self.supplier_id,
            lines=[
                PurchaseLine(self.product_id, Decimal("1.25"), 200),
                PurchaseLine(self.product_id, Decimal("2.75"), 200),
            ],
            paid_cents=0,
            payment_method="CASH",
            operator_id=self.admin_id,
        )
        self.assertEqual(result.total_cents, 800)
        self.assertEqual(self._stock(), before + Decimal("4"))
        conn = self.database.connect(readonly=True)
        try:
            item = conn.execute(
                "SELECT quantity_decimal FROM purchase_items WHERE purchase_id=?",
                (result.purchase_id,),
            ).fetchall()
        finally:
            conn.close()
        self.assertEqual([row[0] for row in item], ["4"])

    def test_supplier_with_unpaid_purchase_cannot_be_deleted(self) -> None:
        purchase = PurchaseService(self.database).create_purchase(
            supplier_id=self.supplier_id,
            lines=[PurchaseLine(self.product_id, Decimal("1"), 200)],
            paid_cents=0,
            payment_method="CASH",
            operator_id=self.admin_id,
        )
        with self.assertRaisesRegex(ValueError, "unpaid purchases"):
            EntityService(self.database, "suppliers").delete(
                self.supplier_id, admin_id=self.admin_id
            )
        self.assertGreater(purchase.purchase_id, 0)

    def test_deleting_paid_purchase_voids_but_preserves_payment_history(self) -> None:
        purchase = PurchaseService(self.database).create_purchase(
            supplier_id=self.supplier_id,
            lines=[PurchaseLine(self.product_id, Decimal("1"), 200)],
            paid_cents=200,
            payment_method="CASH",
            operator_id=self.admin_id,
        )
        PurchaseService(self.database).delete_purchase(
            purchase_id=purchase.purchase_id, admin_id=self.admin_id
        )
        conn = self.database.connect(readonly=True)
        try:
            payment = conn.execute(
                """SELECT purchase_id,voided_at,note FROM supplier_payments
                   ORDER BY id DESC LIMIT 1"""
            ).fetchone()
        finally:
            conn.close()
        self.assertIsNone(payment["purchase_id"])
        self.assertIsNotNone(payment["voided_at"])
        self.assertIn("VOID", payment["note"])

    def test_purchase_delete_cannot_make_stock_negative(self) -> None:
        purchase = PurchaseService(self.database).create_purchase(
            supplier_id=self.supplier_id,
            lines=[PurchaseLine(self.product_id, Decimal("2"), 200)],
            paid_cents=0,
            payment_method="CASH",
            operator_id=self.admin_id,
        )
        SalesService(self.database).create_sale(
            lines=[SaleLine(self.product_id, Decimal("21"), Decimal("21"))],
            payment_method="CASH",
            paid_cents=10000,
            cashier_id=self.staff_id,
        )
        self.assertEqual(self._stock(), Decimal("1"))
        with self.assertRaisesRegex(PurchaseError, "already been sold"):
            PurchaseService(self.database).delete_purchase(
                purchase_id=purchase.purchase_id, admin_id=self.admin_id
            )
        self.assertEqual(self._stock(), Decimal("1"))

    def test_account_permissions_can_be_updated_with_last_admin_protection(self) -> None:
        with self.database.transaction() as conn:
            AuthService.update_user(
                conn,
                target_id=self.staff_id,
                display_name="Senior Cashier",
                role="STAFF",
                permissions={
                    "apply_discount": True,
                    "manage_quick_amounts": True,
                    "reprint_receipt": False,
                },
                current_admin_id=self.admin_id,
            )
        with self.database.transaction() as conn:
            staff = AuthService.authenticate(
                conn, "staff", "SafePass456!", required_role="STAFF"
            )
        self.assertEqual(staff.display_name, "Senior Cashier")
        self.assertTrue(staff.permissions["apply_discount"])
        self.assertFalse(staff.permissions["reprint_receipt"])
        with self.assertRaisesRegex(ValueError, "demote their own"):
            with self.database.transaction() as conn:
                AuthService.update_user(
                    conn,
                    target_id=self.admin_id,
                    display_name="Admin",
                    role="STAFF",
                    permissions={},
                    current_admin_id=self.admin_id,
                )

    def test_held_orders_are_isolated_by_cashier(self) -> None:
        held = HeldOrderService(self.database).hold(
            {"items": [{"product_id": self.product_id, "quantity": "1"}]},
            cashier_id=self.staff_id,
        )
        with self.database.transaction() as conn:
            other_staff = AuthService.create_user(
                conn,
                username="other",
                display_name="Other",
                password="SafePass789!",
                role="STAFF",
                permissions={},
                admin_id=self.admin_id,
            )
        self.assertEqual(HeldOrderService(self.database).list_held(cashier_id=other_staff), [])
        with self.assertRaises(LookupError):
            HeldOrderService(self.database).retrieve(
                held.id, cashier_id=other_staff
            )

    def test_discounted_return_uses_net_amount_and_credit_adjustment(self) -> None:
        sale = SalesService(self.database).create_sale(
            lines=[
                SaleLine(
                    self.product_id,
                    Decimal("2"),
                    Decimal("2"),
                    discount_cents=66,
                )
            ],
            payment_method="CREDIT",
            paid_cents=0,
            cashier_id=self.staff_id,
            customer_id=self.customer_id,
        )
        conn = self.database.connect(readonly=True)
        try:
            item_id = int(
                conn.execute(
                    "SELECT id FROM sale_items WHERE sale_id=?", (sale.sale_id,)
                ).fetchone()[0]
            )
        finally:
            conn.close()
        ReturnService(self.database).create_return(
            sale_id=sale.sale_id,
            quantities_by_sale_item={item_id: Decimal("2")},
            reason="Full credit return",
            operator_id=self.admin_id,
        )
        conn = self.database.connect(readonly=True)
        try:
            returned = conn.execute(
                "SELECT total_cents,refund_method FROM sale_returns WHERE sale_id=?",
                (sale.sale_id,),
            ).fetchone()
            debt = conn.execute(
                "SELECT balance_cents,status FROM customer_debts WHERE sale_id=?",
                (sale.sale_id,),
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(tuple(returned), (600, "CREDIT_ADJUSTMENT"))
        self.assertEqual(tuple(debt), (0, "CLOSED"))

    def test_report_profit_is_exact_and_discount_aware(self) -> None:
        sale = SalesService(self.database).create_sale(
            lines=[
                SaleLine(
                    self.product_id,
                    Decimal("1.5"),
                    Decimal("1.5"),
                    discount_cents=25,
                )
            ],
            payment_method="CARD",
            paid_cents=475,
            cashier_id=self.staff_id,
        )
        summary = ReportService(self.database).summary(
            start_date=sale.receipt_no[4:12][:4]
            + "-"
            + sale.receipt_no[8:10]
            + "-"
            + sale.receipt_no[10:12],
            end_date=date.today().isoformat(),
        )
        self.assertEqual(summary.sales_cents, 475)
        self.assertEqual(summary.gross_profit_cents, 287)
        self.assertEqual(summary.transaction_count, 1)

    def test_daily_closing_includes_all_cash_flows(self) -> None:
        cash_sale = SalesService(self.database).create_sale(
            lines=[
                SaleLine(
                    self.product_id,
                    Decimal("1"),
                    Decimal("1"),
                    price_override_cents=100,
                )
            ],
            payment_method="CASH",
            paid_cents=100,
            cashier_id=self.staff_id,
        )
        conn = self.database.connect(readonly=True)
        try:
            sale_item_id = int(
                conn.execute(
                    "SELECT id FROM sale_items WHERE sale_id=?", (cash_sale.sale_id,)
                ).fetchone()[0]
            )
        finally:
            conn.close()
        ReturnService(self.database).create_return(
            sale_id=cash_sale.sale_id,
            quantities_by_sale_item={sale_item_id: Decimal("1")},
            reason="Cash refund",
            operator_id=self.admin_id,
            refund_method="CASH",
        )
        credit = SalesService(self.database).create_sale(
            lines=[
                SaleLine(
                    self.product_id,
                    Decimal("1"),
                    Decimal("1"),
                    price_override_cents=100,
                )
            ],
            payment_method="CREDIT",
            paid_cents=0,
            cashier_id=self.staff_id,
            customer_id=self.customer_id,
        )
        conn = self.database.connect(readonly=True)
        try:
            debt_id = int(
                conn.execute(
                    "SELECT id FROM customer_debts WHERE sale_id=?", (credit.sale_id,)
                ).fetchone()[0]
            )
        finally:
            conn.close()
        CustomerPaymentService(self.database).record_payment(
            debt_id=debt_id,
            amount_cents=50,
            payment_method="CASH",
            note="cash receipt",
            operator_id=self.admin_id,
        )
        PurchaseService(self.database).create_purchase(
            supplier_id=self.supplier_id,
            lines=[PurchaseLine(self.product_id, Decimal("1"), 100)],
            paid_cents=100,
            payment_method="CASH",
            operator_id=self.admin_id,
        )
        self.assertEqual(
            DailyClosingService(self.database).system_cash(
                business_date=date.today(), opening_cash_cents=500
            ),
            450,
        )

    def test_printer_resolution_requires_explicit_valid_choice(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "no printer"):
            resolve_printer_target(
                {"printer_mode": "UNCONFIGURED"},
                available_printers={"POS-80"},
                default_printer_available=True,
            )
        self.assertIsNone(
            resolve_printer_target(
                {"printer_mode": "DEFAULT", "printer_name": ""},
                available_printers=set(),
                default_printer_available=True,
            )
        )
        self.assertEqual(
            resolve_printer_target(
                {"printer_mode": "NAMED", "printer_name": "POS-80"},
                available_printers={"POS-80"},
                default_printer_available=False,
            ),
            "POS-80",
        )
        with self.assertRaisesRegex(RuntimeError, "unavailable"):
            resolve_printer_target(
                {"printer_mode": "NAMED", "printer_name": "Removed"},
                available_printers={"POS-80"},
                default_printer_available=True,
            )

    def test_audit_clear_requires_password_backs_up_and_leaves_system_record(self) -> None:
        service = AuditMaintenanceService(self.database, self.backups)
        with self.assertRaises(PermissionError):
            service.clear(admin_id=self.admin_id, password="wrong")
        self.assertEqual(list(self.backups.glob("*.db")), [])
        result = service.clear(admin_id=self.admin_id, password="SafePass123!")
        self.assertTrue(result.backup_path.exists())
        self.assertGreater(result.removed_count, 0)
        conn = self.database.connect(readonly=True)
        try:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM audit_logs").fetchone()[0], 0)
            check = conn.execute(
                "SELECT status,detail FROM system_checks WHERE check_type='AUDIT_CLEAR'"
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(check["status"], "PASS")
        self.assertIn(result.backup_path.name, check["detail"])

    def test_shutdown_backup_runs_once_and_respects_retention(self) -> None:
        guard = ShutdownBackupGuard(
            self.database.path, self.backups, mode="admin"
        )
        first = guard.run()
        second = guard.run()
        self.assertEqual(first.path, second.path)
        self.assertEqual(len(list(self.backups.glob("hardware_pos_*.db"))), 1)

    def test_document_prefixes_apply_to_new_documents(self) -> None:
        with self.database.transaction() as conn:
            save_document_prefixes(
                conn,
                {
                    "RECEIPT": "RC-",
                    "PURCHASE": "BUY-",
                    "RETURN": "RET-",
                    "STOCKTAKE": "COUNT-",
                },
                admin_id=self.admin_id,
            )
        sale = SalesService(self.database).create_sale(
            lines=[SaleLine(self.product_id, Decimal("1"), Decimal("1"))],
            payment_method="CASH",
            paid_cents=1000,
            cashier_id=self.staff_id,
        )
        self.assertTrue(sale.receipt_no.startswith("RC-"))
        purchase = PurchaseService(self.database).create_purchase(
            supplier_id=self.supplier_id,
            lines=[PurchaseLine(self.product_id, Decimal("1"), 100)],
            paid_cents=0,
            payment_method="CASH",
            operator_id=self.admin_id,
        )
        self.assertTrue(purchase.purchase_no.startswith("BUY-"))
        stocktake_no = StocktakeService(self.database).create_draft(
            operator_id=self.admin_id
        )[1]
        self.assertTrue(stocktake_no.startswith("COUNT-"))
        conn = self.database.connect(readonly=True)
        try:
            item_id = int(
                conn.execute(
                    "SELECT id FROM sale_items WHERE sale_id=?", (sale.sale_id,)
                ).fetchone()[0]
            )
        finally:
            conn.close()
        return_no = ReturnService(self.database).create_return(
            sale_id=sale.sale_id,
            quantities_by_sale_item={item_id: Decimal("1")},
            reason="Prefix test",
            operator_id=self.admin_id,
        )
        self.assertTrue(return_no.startswith("RET-"))

    def test_payment_method_validation_and_notes(self) -> None:
        sale = SalesService(self.database).create_sale(
            lines=[SaleLine(self.product_id, Decimal("1"), Decimal("1"))],
            payment_method="CREDIT",
            paid_cents=0,
            cashier_id=self.staff_id,
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
        with self.assertRaisesRegex(PaymentError, "unsupported"):
            CustomerPaymentService(self.database).record_payment(
                debt_id=debt_id,
                amount_cents=10,
                payment_method="CRYPTO",
                note="invalid",
                operator_id=self.admin_id,
            )
        CustomerPaymentService(self.database).record_payment(
            debt_id=debt_id,
            amount_cents=10,
            payment_method="DUITNOW_QR",
            note="  bank reference 123  ",
            operator_id=self.admin_id,
        )
        conn = self.database.connect(readonly=True)
        try:
            payment = conn.execute(
                "SELECT payment_method,note FROM customer_payments ORDER BY id DESC LIMIT 1"
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(tuple(payment), ("DUITNOW_QR", "bank reference 123"))


class Run8MigrationTests(unittest.TestCase):
    def test_latest_database_restart_does_not_create_migration_backups(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            database = root / "hardware_pos.db"
            backups = root / "backups"
            first = bootstrap_database(database, backups)
            second = bootstrap_database(database, backups)
            self.assertIsNone(first.backup_path)
            self.assertIsNone(second.backup_path)
            self.assertEqual(list(backups.glob("*.db")), [])

    def test_schema_six_upgrade_creates_supplier_catalog_and_one_backup(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            database = root / "hardware_pos.db"
            backups = root / "backups"
            bootstrap_database(database, backups)
            conn = sqlite3.connect(database)
            conn.execute("DROP TABLE supplier_products")
            conn.execute("DELETE FROM schema_migrations WHERE version=7")
            conn.execute("PRAGMA user_version=6")
            conn.commit()
            conn.close()
            result = bootstrap_database(database, backups)
            self.assertEqual(result.schema_before, 6)
            self.assertEqual(result.schema_after, 7)
            self.assertIsNotNone(result.backup_path)
            self.assertEqual(len(list(backups.glob("*.db"))), 1)
            conn = sqlite3.connect(database)
            try:
                self.assertIsNotNone(
                    conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' AND name='supplier_products'"
                    ).fetchone()
                )
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
