from __future__ import annotations

import sqlite3
import tempfile
import unittest
from datetime import date
from pathlib import Path

from cnkh_pos.database.bootstrap import bootstrap_database
from cnkh_pos.database.connection import Database
from cnkh_pos.database.repositories import SupplierPaymentRepository
from cnkh_pos.services.product_search import search_products
from cnkh_pos.services.quantities import parse_quantity, quantity_text
from cnkh_pos.services.receipt_numbers import next_receipt_number


class ServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.db_path = root / "hardware_pos.db"
        bootstrap_database(self.db_path, root / "backups")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_decimal_quantity_is_exact(self) -> None:
        self.assertEqual(quantity_text(parse_quantity("2.500")), "2.5")
        self.assertEqual(quantity_text(parse_quantity("0.125")), "0.125")

    def test_receipt_sequence_resets_by_business_date(self) -> None:
        database = Database(self.db_path)
        with database.transaction() as conn:
            self.assertEqual(
                next_receipt_number(conn, date(2026, 8, 9)), "CNKH20260809-001"
            )
            self.assertEqual(
                next_receipt_number(conn, date(2026, 8, 9)), "CNKH20260809-002"
            )
            self.assertEqual(
                next_receipt_number(conn, date(2026, 8, 10)), "CNKH20260810-001"
            )

    def test_supplier_payment_button_repository_write(self) -> None:
        database = Database(self.db_path)
        with database.transaction() as conn:
            conn.execute(
                "INSERT INTO suppliers(name, created_at, updated_at) VALUES ('Test Supplier', 'x', 'x')"
            )
            supplier_id = int(conn.execute("SELECT id FROM suppliers").fetchone()[0])
            payment_id = SupplierPaymentRepository.add(
                conn,
                supplier_id=supplier_id,
                amount_cents=23500,
                payment_method="cash",
                note="invoice part payment",
                operator_id=None,
            )
        conn = sqlite3.connect(self.db_path)
        try:
            row = conn.execute(
                "SELECT amount_cents, payment_method, note FROM supplier_payments WHERE id=?",
                (payment_id,),
            ).fetchone()
            self.assertEqual(row, (23500, "CASH", "invoice part payment"))
        finally:
            conn.close()

    def test_search_covers_alias_category_location_and_exact_barcode(self) -> None:
        database = Database(self.db_path)
        with database.transaction() as conn:
            conn.execute(
                "INSERT INTO categories(name, created_at, updated_at) VALUES ('Water Pipe', 'x', 'x')"
            )
            category_id = int(conn.execute("SELECT id FROM categories").fetchone()[0])
            conn.execute(
                """
                INSERT INTO products(
                    name, aliases, category_id, sku, barcode, selling_price_cents,
                    stock_decimal, unit, location, created_at, updated_at
                ) VALUES ('PVC Pipe 20mm', 'paip pvc 管子', ?, 'PIPE20', '955501040020',
                          450, '80.5', 'meter', 'Rack B2', 'x', 'x')
                """,
                (category_id,),
            )
        conn = database.connect(readonly=True)
        try:
            for term in ("paip", "Water", "B2", "PIPE20"):
                self.assertEqual(search_products(conn, term)[0].name, "PVC Pipe 20mm")
            exact = search_products(conn, "955501040020")[0]
            self.assertTrue(exact.exact_barcode)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
