from __future__ import annotations

import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from openpyxl import load_workbook

from cnkh_pos.database.bootstrap import bootstrap_database
from cnkh_pos.database.connection import Database
from cnkh_pos.services.auth import AuthService
from cnkh_pos.services.catalog import (
    CatalogService,
    CategoryService,
    ProductInput,
    is_valid_ean13,
)
from cnkh_pos.services.excel_import import ExcelImportService
from cnkh_pos.services.stocktake import StocktakeError, StocktakeService


class CatalogStocktakeAuthImportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.root = root
        self.database = Database(root / "hardware_pos.db")
        bootstrap_database(self.database.path, root / "backups")
        with self.database.transaction() as conn:
            self.admin1 = AuthService.create_user(
                conn,
                username="admin1",
                display_name="Admin One",
                password="SafePass123!",
                role="ADMIN",
                permissions={},
                admin_id=None,
            )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_multi_admin_self_and_last_admin_rules(self) -> None:
        with self.database.transaction() as conn:
            admin2 = AuthService.create_user(
                conn,
                username="admin2",
                display_name="Admin Two",
                password="SafePass456!",
                role="ADMIN",
                permissions={},
                admin_id=self.admin1,
            )
            with self.assertRaises(ValueError):
                AuthService.delete_user(
                    conn, target_id=self.admin1, current_admin_id=self.admin1
                )
            AuthService.delete_user(
                conn, target_id=admin2, current_admin_id=self.admin1
            )
        # Last active administrator cannot be deleted even when called by a synthetic different id.
        with self.database.transaction() as conn:
            with self.assertRaises(ValueError):
                AuthService.delete_user(
                    conn, target_id=self.admin1, current_admin_id=999
                )

    def test_category_crud_safely_uncategorizes_products(self) -> None:
        categories = CategoryService(self.database)
        category_id = categories.add("Water Pipe", admin_id=self.admin1)
        categories.rename(category_id, "PVC Pipe", admin_id=self.admin1)
        product_id = CatalogService(self.database).add_product(
            ProductInput(
                name="Pipe 20mm", category_id=category_id, selling_price_cents=450
            ),
            admin_id=self.admin1,
        )
        affected = categories.delete(category_id, admin_id=self.admin1)
        self.assertEqual(affected, 1)
        conn = self.database.connect(readonly=True)
        try:
            self.assertIsNone(
                conn.execute(
                    "SELECT category_id FROM products WHERE id=?", (product_id,)
                ).fetchone()[0]
            )
        finally:
            conn.close()

    def test_generated_barcode_is_unique_valid_ean13(self) -> None:
        service = CatalogService(self.database)
        first = service.add_product(ProductInput(name="Item A"), admin_id=self.admin1)
        second = service.add_product(ProductInput(name="Item B"), admin_id=self.admin1)
        conn = self.database.connect(readonly=True)
        try:
            values = [
                row[0]
                for row in conn.execute(
                    "SELECT barcode FROM products WHERE id IN (?,?)", (first, second)
                )
            ]
            self.assertEqual(len(set(values)), 2)
            self.assertTrue(all(is_valid_ean13(value) for value in values))
        finally:
            conn.close()

    def test_stocktake_history_keeps_original_snapshot(self) -> None:
        product_id = CatalogService(self.database).add_product(
            ProductInput(name="Cable", stock="10.5", unit="meter", location="Rack A"),
            admin_id=self.admin1,
        )
        service = StocktakeService(self.database)
        stocktake_id, _ = service.create_draft(operator_id=self.admin1, notes="monthly")
        service.set_physical_count(
            stocktake_id=stocktake_id, product_id=product_id, count=Decimal("8.25")
        )
        service.complete(stocktake_id=stocktake_id, operator_id=self.admin1)
        with self.assertRaises(StocktakeError):
            service.set_physical_count(
                stocktake_id=stocktake_id, product_id=product_id, count="9"
            )
        conn = self.database.connect(readonly=True)
        try:
            item = conn.execute(
                "SELECT system_stock_decimal, physical_count_decimal, variance_decimal FROM stocktake_items WHERE stocktake_id=?",
                (stocktake_id,),
            ).fetchone()
            self.assertEqual(tuple(item), ("10.5", "8.25", "-2.25"))
            self.assertEqual(
                conn.execute(
                    "SELECT stock_decimal FROM products WHERE id=?", (product_id,)
                ).fetchone()[0],
                "8.25",
            )
        finally:
            conn.close()

    def test_excel_template_preview_validation_and_import(self) -> None:
        service = ExcelImportService(self.database)
        path = service.create_template(self.root / "products.xlsx")
        workbook = load_workbook(path)
        sheet = workbook.active
        sheet[2][10].value = "4006381333931"  # valid EAN-13
        sheet.append(["", "", "", "DUP", 1, 2, 1, "pcs", "", 0, "123"])
        workbook.save(path)
        workbook.close()
        preview = service.preview(path)
        self.assertEqual(len(preview), 2)
        self.assertEqual(preview[0].errors, [])
        self.assertIn("Missing Required Field: Product Name", preview[1].errors)
        self.assertIn("Invalid Barcode", preview[1].errors)
        summary = service.commit(preview, admin_id=self.admin1)
        self.assertEqual((summary.success, summary.errors), (1, 1))


if __name__ == "__main__":
    unittest.main()
