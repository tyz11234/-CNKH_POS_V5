from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from cnkh_pos.config import SCHEMA_VERSION
from cnkh_pos.database.bootstrap import DatabaseStartupError, bootstrap_database


class DatabaseBootstrapTests(unittest.TestCase):
    def test_fresh_database_reaches_latest_schema_without_backup(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            result = bootstrap_database(root / "hardware_pos.db", root / "backups")
            self.assertTrue(result.fresh_database)
            self.assertIsNone(result.backup_path)
            self.assertEqual(result.schema_after, SCHEMA_VERSION)
            conn = sqlite3.connect(result.database_path)
            try:
                self.assertEqual(
                    conn.execute("SELECT COUNT(*) FROM quick_amounts").fetchone()[0], 5
                )
                self.assertEqual(
                    conn.execute("PRAGMA integrity_check").fetchone()[0], "ok"
                )
            finally:
                conn.close()

    def test_unknown_legacy_payment_amount_rolls_back_and_keeps_backup(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            db_path = root / "hardware_pos.db"
            conn = sqlite3.connect(db_path)
            conn.execute(
                "CREATE TABLE supplier_payments(id INTEGER PRIMARY KEY, mystery_money TEXT)"
            )
            conn.execute(
                "INSERT INTO supplier_payments(mystery_money) VALUES ('12.00')"
            )
            conn.commit()
            conn.close()

            with self.assertRaises(DatabaseStartupError):
                bootstrap_database(db_path, root / "backups")

            backups = list((root / "backups").glob("*.db"))
            self.assertEqual(len(backups), 1)
            conn = sqlite3.connect(db_path)
            try:
                columns = [
                    row[1]
                    for row in conn.execute("PRAGMA table_info(supplier_payments)")
                ]
                self.assertEqual(columns, ["id", "mystery_money"])
                self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 0)
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
