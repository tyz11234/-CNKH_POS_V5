from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from cnkh_pos.database.bootstrap import bootstrap_database


class SupplierPaymentMigrationTests(unittest.TestCase):
    CASES = {
        "amount": ("12.345", 1235),
        "paid_cents": (1235, 1235),
        "payment_cents": (1235, 1235),
        "amount_cents": (1235, 1235),
    }

    def _make_legacy(self, path: Path, column: str, value: object) -> None:
        conn = sqlite3.connect(path)
        value_type = "REAL" if column == "amount" else "INTEGER"
        conn.execute(
            f"""
            CREATE TABLE supplier_payments (
                id INTEGER PRIMARY KEY,
                supplier_id INTEGER,
                {column} {value_type} NOT NULL,
                method TEXT,
                notes TEXT,
                payment_date TEXT
            )
            """
        )
        conn.execute(
            f"INSERT INTO supplier_payments(supplier_id, {column}, method, notes, payment_date) "
            "VALUES (NULL, ?, 'bank', 'legacy note', '2025-03-01 10:00:00')",
            (value,),
        )
        conn.commit()
        conn.close()

    def test_all_known_legacy_amount_columns_are_preserved(self) -> None:
        for column, (value, expected) in self.CASES.items():
            with self.subTest(column=column), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                db_path = root / "hardware_pos.db"
                self._make_legacy(db_path, column, value)
                result = bootstrap_database(db_path, root / "backups")
                self.assertIsNotNone(result.backup_path)
                conn = sqlite3.connect(db_path)
                conn.row_factory = sqlite3.Row
                try:
                    row = conn.execute("SELECT * FROM supplier_payments").fetchone()
                    self.assertEqual(row["amount_cents"], expected)
                    self.assertEqual(row["payment_method"], "BANK")
                    self.assertEqual(row["note"], "legacy note")
                    source = json.loads(row["legacy_source_json"])
                    self.assertEqual(str(source[column]), str(value))
                finally:
                    conn.close()


if __name__ == "__main__":
    unittest.main()
