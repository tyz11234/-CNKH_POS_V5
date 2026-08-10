from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


_CASH_CHANGE_ROUNDING_TRIGGER = """
CREATE TRIGGER IF NOT EXISTS trg_sales_cash_change_rounding
AFTER INSERT ON sales
WHEN NEW.payment_method = 'CASH'
BEGIN
    UPDATE sales
    SET change_cents = CASE
        WHEN (NEW.change_cents % 10) <= 4
            THEN NEW.change_cents - (NEW.change_cents % 10)
        WHEN (NEW.change_cents % 10) = 5
            THEN NEW.change_cents
        ELSE NEW.change_cents + (10 - (NEW.change_cents % 10))
    END
    WHERE id = NEW.id;
END
"""


class Database:
    """Connection factory with the durability policy shared by every module."""

    def __init__(self, path: Path | str):
        self.path = Path(path)

    def connect(self, *, readonly: bool = False) -> sqlite3.Connection:
        if readonly:
            uri = self.path.resolve().as_uri() + "?mode=ro"
            conn = sqlite3.connect(uri, uri=True, timeout=10.0)
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self.path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 10000")
        if not readonly:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA synchronous = FULL")
            sales_exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='sales'"
            ).fetchone()
            if sales_exists is not None:
                conn.execute(_CASH_CHANGE_ROUNDING_TRIGGER)
        return conn

    @contextmanager
    def transaction(self, *, immediate: bool = True) -> Iterator[sqlite3.Connection]:
        conn = self.connect()
        try:
            conn.isolation_level = None
            conn.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
            yield conn
            conn.execute("COMMIT")
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

    def integrity_check(self) -> tuple[bool, list[str]]:
        if not self.path.exists():
            return True, ["new_database"]
        conn = self.connect(readonly=True)
        try:
            messages = [str(row[0]) for row in conn.execute("PRAGMA integrity_check")]
            return messages == ["ok"], messages
        finally:
            conn.close()
