from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from contextlib import ExitStack
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from cnkh_pos.database.bootstrap import DatabaseStartupError, bootstrap_database
from cnkh_pos.database.connection import Database
from cnkh_pos.services.auth import AuthService
from cnkh_pos.services.backup import BackupService
from cnkh_pos.services.catalog import CatalogService, ProductInput
from cnkh_pos.services.excel_import import ExcelImportService
from cnkh_pos.services.held_orders import HeldOrderService, cart_state_from_held_payload
from cnkh_pos.services.money import clamp_discount_cents, line_amount_cents, rm_to_cents
from cnkh_pos.services.reports import ReportService
from cnkh_pos.services.sales import ReturnService, SaleError, SaleLine, SalesService
from tools.packaged_self_test import _safe_console, _write_report


class StabilizationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.database = Database(self.root / "hardware_pos.db")
        bootstrap_database(self.database.path, self.root / "backups")
        with self.database.transaction() as conn:
            self.admin_id = AuthService.create_user(
                conn,
                username="admin",
                display_name="Admin",
                password="AdminPass123!",
                role="ADMIN",
                permissions={},
                admin_id=None,
            )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_report_is_exact_and_subtracts_returns_by_return_date(self) -> None:
        product_id = CatalogService(self.database).add_product(
            ProductInput(
                name="Bundle",
                cost_cents=100,
                selling_price_cents=500,
                stock="20",
            ),
            admin_id=self.admin_id,
        )
        sale = SalesService(self.database).create_sale(
            lines=[
                SaleLine(
                    product_id,
                    Decimal("2"),
                    Decimal("3"),
                    discount_cents=100,
                )
            ],
            payment_method="CASH",
            paid_cents=900,
            cashier_id=self.admin_id,
        )
        conn = self.database.connect(readonly=True)
        try:
            sold_at = str(
                conn.execute(
                    "SELECT sold_at FROM sales WHERE id=?", (sale.sale_id,)
                ).fetchone()[0]
            )
            sale_item_id = int(
                conn.execute(
                    "SELECT id FROM sale_items WHERE sale_id=?", (sale.sale_id,)
                ).fetchone()[0]
            )
        finally:
            conn.close()
        day = sold_at[:10]
        before = ReportService(self.database).summary(start_date=day, end_date=day)
        self.assertEqual(before.sales_cents, 900)
        self.assertEqual(before.gross_profit_cents, 600)

        ReturnService(self.database).create_return(
            sale_id=sale.sale_id,
            quantities_by_sale_item={sale_item_id: Decimal("1")},
            reason="Customer return",
            operator_id=self.admin_id,
            refund_method="CASH",
        )
        after = ReportService(self.database).summary(start_date=day, end_date=day)
        self.assertEqual(after.sales_cents, 450)
        self.assertEqual(after.gross_profit_cents, 300)
        self.assertEqual(after.transaction_count, 1)

    def test_report_rejects_invalid_iso_dates(self) -> None:
        service = ReportService(self.database)
        with self.assertRaisesRegex(ValueError, "YYYY-MM-DD"):
            service.summary(start_date="2026-99-99", end_date="2026-08-10")

    def test_schema_version_cannot_hide_a_missing_required_table(self) -> None:
        conn = sqlite3.connect(self.database.path)
        try:
            conn.execute("DROP TABLE supplier_products")
            conn.commit()
        finally:
            conn.close()
        with self.assertRaises(DatabaseStartupError):
            bootstrap_database(self.database.path, self.root / "backups")

    def test_schema_version_cannot_hide_a_missing_required_column(self) -> None:
        conn = sqlite3.connect(self.database.path)
        try:
            conn.execute("ALTER TABLE customers DROP COLUMN notes")
            conn.commit()
        finally:
            conn.close()
        with self.assertRaises(DatabaseStartupError):
            bootstrap_database(self.database.path, self.root / "backups")

    def test_schema_validation_rejects_foreign_key_corruption(self) -> None:
        conn = sqlite3.connect(self.database.path)
        try:
            conn.execute("PRAGMA foreign_keys=OFF")
            conn.execute(
                """INSERT INTO supplier_products(
                    supplier_id,product_id,supplier_sku,is_active,created_at,updated_at
                ) VALUES (999999,999999,'',1,'2026-08-10T00:00:00Z','2026-08-10T00:00:00Z')"""
            )
            conn.commit()
        finally:
            conn.close()
        with self.assertRaises(DatabaseStartupError):
            bootstrap_database(self.database.path, self.root / "backups")

    def test_product_create_audit_contains_full_input(self) -> None:
        CatalogService(self.database).add_product(
            ProductInput(
                name="Audited Product",
                aliases="alias one",
                cost_cents=123,
                selling_price_cents=456,
                stock="7.5",
                location="Rack A",
            ),
            admin_id=self.admin_id,
        )
        conn = self.database.connect(readonly=True)
        try:
            payload = json.loads(
                conn.execute(
                    """SELECT new_value_json FROM audit_logs
                       WHERE module='PRODUCTS' AND action='CREATE'
                       ORDER BY id DESC LIMIT 1"""
                ).fetchone()[0]
            )
        finally:
            conn.close()
        self.assertEqual(payload["aliases"], "alias one")
        self.assertEqual(payload["cost_cents"], 123)
        self.assertEqual(payload["selling_price_cents"], 456)
        self.assertEqual(payload["stock"], "7.5")

    def test_excel_barcode_normalization_only_removes_numeric_suffix(self) -> None:
        self.assertEqual(ExcelImportService.barcode_text(4006381333931.0), "4006381333931")
        self.assertEqual(ExcelImportService.barcode_text("4006381333931.0"), "4006381333931")
        self.assertEqual(ExcelImportService.barcode_text("ABC.0"), "ABC.0")
        self.assertEqual(ExcelImportService.barcode_text("123.045"), "123.045")

    def test_held_order_rejects_duplicate_lines_and_unbounded_limits(self) -> None:
        with self.assertRaisesRegex(ValueError, "duplicate"):
            cart_state_from_held_payload(
                {
                    "items": [
                        {"product_id": 1, "quantity": "1"},
                        {"product_id": 1, "quantity": "2"},
                    ]
                }
            )
        service = HeldOrderService(self.database)
        with self.assertRaises(ValueError):
            service.list_held(cashier_id=self.admin_id, limit=0)
        with self.assertRaises(ValueError):
            service.list_held(cashier_id=self.admin_id, limit=201)

    def test_return_reason_is_enforced_by_service_layer(self) -> None:
        product_id = CatalogService(self.database).add_product(
            ProductInput(name="Return Item", selling_price_cents=100, stock="2"),
            admin_id=self.admin_id,
        )
        sale = SalesService(self.database).create_sale(
            lines=[SaleLine(product_id, Decimal("1"), Decimal("1"))],
            payment_method="CASH",
            paid_cents=100,
            cashier_id=self.admin_id,
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
        with self.assertRaisesRegex(SaleError, "reason"):
            ReturnService(self.database).create_return(
                sale_id=sale.sale_id,
                quantities_by_sale_item={item_id: Decimal("1")},
                reason="   ",
                operator_id=self.admin_id,
            )

    def test_final_fractional_return_restores_exact_remaining_stock(self) -> None:
        product_id = CatalogService(self.database).add_product(
            ProductInput(name="Fraction Pack", selling_price_cents=300, stock="10"),
            admin_id=self.admin_id,
        )
        sale = SalesService(self.database).create_sale(
            lines=[SaleLine(product_id, Decimal("3"), Decimal("1"))],
            payment_method="CASH",
            paid_cents=900,
            cashier_id=self.admin_id,
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
        service = ReturnService(self.database)
        for index in range(3):
            service.create_return(
                sale_id=sale.sale_id,
                quantities_by_sale_item={item_id: Decimal("1")},
                reason=f"Part {index + 1}",
                operator_id=self.admin_id,
                refund_method="CASH",
            )
        conn = self.database.connect(readonly=True)
        try:
            stock, restored = conn.execute(
                """SELECT p.stock_decimal,si.returned_stock_decimal
                   FROM sale_items si JOIN products p ON p.id=si.product_id
                   WHERE si.id=?""",
                (item_id,),
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(stock, "10")
        self.assertEqual(restored, "1")


    def test_backup_copy_passes_sqlite_integrity_check(self) -> None:
        backup = BackupService(self.root / "backups").create(
            self.database.path, reason="integrity_regression"
        ).path
        conn = sqlite3.connect(backup)
        try:
            self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        finally:
            conn.close()

    def test_staff_cart_money_rounding_and_discount_clamp(self) -> None:
        self.assertEqual(line_amount_cents(1, Decimal("0.5")), 1)
        self.assertEqual(line_amount_cents(5, Decimal("0.5")), 3)
        self.assertEqual(line_amount_cents(199, Decimal("0.333333")), 66)
        self.assertEqual(clamp_discount_cents(100, 66), 66)
        self.assertEqual(clamp_discount_cents(-1, 66), 0)
        self.assertEqual(rm_to_cents("0.005"), 1)

    def test_ui_stabilization_guards_are_present_in_current_source(self) -> None:
        root = Path(__file__).resolve().parents[1]
        staff = (root / "cnkh_pos/ui/staff/window.py").read_text(encoding="utf-8")
        data_pages = (root / "cnkh_pos/ui/admin/data_pages.py").read_text(encoding="utf-8")
        dashboard = (root / "cnkh_pos/ui/admin/dashboard.py").read_text(encoding="utf-8")
        self.assertIn("resizeSection(2, 116)", staff)
        self.assertIn("self.total_label.setMinimumWidth(220)", staff)
        self.assertIn("clamp_discount_cents", staff)
        self.assertIn("line_amount_cents", staff)
        self.assertGreaterEqual(data_pages.count("self.page_size + 1"), 6)
        self.assertGreaterEqual(data_pages.count("setDecimals(6)"), 3)
        self.assertIn("if col in (0, 1):", data_pages)
        self.assertIn("~Qt.ItemFlag.ItemIsEditable", data_pages)
        self.assertIn("def _remove_item", data_pages)
        self.assertIn("self.items.removeRow(row)", data_pages)
        self.assertIn("ReportService(self.database).summary", dashboard)
        self.assertIn("summary.gross_profit_cents", dashboard)

    def test_windowed_self_test_reporting_does_not_require_console_streams(self) -> None:
        report = self.root / "reports" / "self-test.json"
        _write_report(report, {"status": "PASS", "mode": "admin"})
        self.assertEqual(json.loads(report.read_text(encoding="utf-8"))["status"], "PASS")
        with ExitStack() as stack:
            stack.enter_context(patch.object(sys, "stdout", None))
            stack.enter_context(patch.object(sys, "stderr", None))
            _safe_console("must not crash")

    def test_windows_gate_waits_for_gui_exes_and_uses_reported_exit_codes(self) -> None:
        workflow = (
            Path(__file__).resolve().parents[1]
            / ".github"
            / "workflows"
            / "windows-release.yml"
        ).read_text(encoding="utf-8")
        self.assertGreaterEqual(workflow.count("Start-Process"), 5)
        self.assertGreaterEqual(workflow.count("-Wait -PassThru"), 5)
        self.assertIn("CNKH_POS_SELF_TEST_REPORT", workflow)
        self.assertIn("installed-admin.json", workflow)
        self.assertIn("installed-staff.json", workflow)
        self.assertGreaterEqual(workflow.count("ConvertFrom-Json"), 4)
        self.assertGreaterEqual(workflow.count("self-test report is missing"), 4)
        self.assertGreaterEqual(workflow.count('status -ne "PASS"'), 4)
        self.assertIn("Installed EXE normal launch smoke test", workflow)
        self.assertIn("installed-normal-launch.json", workflow)
        self.assertIn('ExpectedTitle "CNKH POS Admin Login"', workflow)
        self.assertIn('ExpectedTitle "CNKH POS Staff Login"', workflow)
        self.assertIn("MainWindowHandle", workflow)
        self.assertIn("python -m unittest discover -s tests -v", workflow)
        self.assertIn("python -m compileall -q cnkh_pos tools tests admin_launcher.py staff_launcher.py", workflow)
        self.assertNotIn("$LASTEXITCODE", workflow)


if __name__ == "__main__":
    unittest.main()
