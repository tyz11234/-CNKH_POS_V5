from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from cnkh_pos.config import SCHEMA_VERSION
from cnkh_pos.database.schema import (
    CORE_SCHEMA,
    INDEX_SCHEMA,
    OPERATIONS_INDEX_SCHEMA,
    OPERATIONS_SCHEMA,
    apply_statements,
)


class MigrationError(RuntimeError):
    pass


def utc_now_text() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
        ).fetchone()
        is not None
    )


def _columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [str(row[1]) for row in conn.execute(f'PRAGMA table_info("{table}")')]


def _money_to_cents(value: object, *, already_cents: bool) -> int:
    if value is None or value == "":
        raise MigrationError("supplier payment has an empty amount")
    try:
        number = Decimal(str(value))
    except InvalidOperation as exc:
        raise MigrationError(f"invalid supplier payment amount: {value!r}") from exc
    if not already_cents:
        number *= 100
    cents = int(number.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    if cents <= 0:
        raise MigrationError(f"supplier payment must be positive: {value!r}")
    return cents


def migration_001_core(conn: sqlite3.Connection) -> None:
    apply_statements(conn, CORE_SCHEMA)


def migration_002_supplier_payments(conn: sqlite3.Connection) -> None:
    if not _table_exists(conn, "supplier_payments"):
        # Normally created by migration 1, but keep this migration independently safe.
        apply_statements(conn, CORE_SCHEMA)
        return

    columns = _columns(conn, "supplier_payments")
    canonical = {
        "id",
        "supplier_id",
        "purchase_id",
        "amount_cents",
        "payment_method",
        "note",
        "operator_id",
        "paid_at",
        "legacy_source_json",
    }
    if canonical.issubset(columns):
        return

    amount_column = next(
        (
            name
            for name in ("amount_cents", "payment_cents", "paid_cents", "amount")
            if name in columns
        ),
        None,
    )
    if amount_column is None:
        raise MigrationError(
            "legacy supplier_payments has no recognized money column; "
            f"found: {', '.join(columns)}"
        )

    archive = "supplier_payments_legacy_v2"
    suffix = 2
    while _table_exists(conn, archive):
        suffix += 1
        archive = f"supplier_payments_legacy_v{suffix}"
    conn.execute(f'ALTER TABLE supplier_payments RENAME TO "{archive}"')

    supplier_payment_statement = next(
        statement
        for statement in CORE_SCHEMA
        if "CREATE TABLE IF NOT EXISTS supplier_payments" in statement
    )
    conn.execute(supplier_payment_statement)

    rows = conn.execute(f'SELECT * FROM "{archive}" ORDER BY rowid').fetchall()
    row_columns = [
        item[0]
        for item in conn.execute(f'SELECT * FROM "{archive}" LIMIT 0').description
    ]
    for index, row in enumerate(rows, start=1):
        source = dict(zip(row_columns, row, strict=True))
        legacy_id = source.get("id")
        paid_at = (
            source.get("paid_at")
            or source.get("payment_date")
            or source.get("created_at")
            or source.get("date")
            or utc_now_text()
        )
        method = source.get("payment_method") or source.get("method") or "CASH"
        note = source.get("note") or source.get("notes") or ""
        cents = _money_to_cents(
            source.get(amount_column), already_cents=amount_column != "amount"
        )
        conn.execute(
            """
            INSERT INTO supplier_payments (
                id, supplier_id, purchase_id, amount_cents, payment_method,
                note, operator_id, paid_at, legacy_source_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                legacy_id if legacy_id is not None else index,
                source.get("supplier_id"),
                source.get("purchase_id"),
                cents,
                str(method).upper(),
                str(note),
                source.get("operator_id")
                or source.get("created_by")
                or source.get("user_id"),
                str(paid_at),
                json.dumps(source, ensure_ascii=False, default=str, sort_keys=True),
            ),
        )


def migration_003_indexes_and_defaults(conn: sqlite3.Connection) -> None:
    apply_statements(conn, INDEX_SCHEMA)
    existing = conn.execute("SELECT COUNT(*) FROM quick_amounts").fetchone()[0]
    if existing == 0:
        conn.executemany(
            "INSERT INTO quick_amounts(amount_cents, is_enabled, sort_order) VALUES (?, 1, ?)",
            [(1000, 10), (2000, 20), (5000, 30), (10000, 40), (20000, 50)],
        )


def migration_004_operations_schema(conn: sqlite3.Connection) -> None:
    apply_statements(conn, OPERATIONS_SCHEMA)
    apply_statements(conn, OPERATIONS_INDEX_SCHEMA)
    customer_payment_columns = _columns(conn, "customer_payments")
    if "debt_id" not in customer_payment_columns:
        conn.execute(
            "ALTER TABLE customer_payments ADD COLUMN debt_id INTEGER REFERENCES customer_debts(id)"
        )
    supplier_payment_columns = _columns(conn, "supplier_payments")
    if "voided_at" not in supplier_payment_columns:
        conn.execute("ALTER TABLE supplier_payments ADD COLUMN voided_at TEXT")


def migration_005_release_metadata(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO app_version_history(
            version, release_date, new_features, bug_fixes, db_migration_version
        ) VALUES (?, ?, ?, ?, ?)
        """,
        (
            "5.0.0-alpha.1",
            "2026-08-09",
            "V5 architecture; safe migrations; Qt design system",
            "Legacy supplier payment amount normalization",
            5,
        ),
    )


def migration_006_transaction_snapshots(conn: sqlite3.Connection) -> None:
    if "unit_cost_cents_snapshot" not in _columns(conn, "sale_items"):
        conn.execute(
            "ALTER TABLE sale_items ADD COLUMN unit_cost_cents_snapshot INTEGER NOT NULL DEFAULT 0"
        )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS document_sequences (
            document_type TEXT NOT NULL,
            business_date TEXT NOT NULL,
            last_sequence INTEGER NOT NULL CHECK(last_sequence > 0),
            PRIMARY KEY(document_type, business_date)
        )
        """
    )


def migration_007_cash_closing_and_release_metadata(conn: sqlite3.Connection) -> None:
    supplier_products_statement = next(
        statement
        for statement in OPERATIONS_SCHEMA
        if "CREATE TABLE IF NOT EXISTS supplier_products" in statement
    )
    conn.execute(supplier_products_statement)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_supplier_products_product ON supplier_products(product_id, is_active)"
    )
    if "opening_cash_cents" not in _columns(conn, "daily_cash_closings"):
        conn.execute(
            "ALTER TABLE daily_cash_closings ADD COLUMN opening_cash_cents INTEGER NOT NULL DEFAULT 0"
        )
    if "refund_method" not in _columns(conn, "sale_returns"):
        conn.execute(
            "ALTER TABLE sale_returns ADD COLUMN refund_method TEXT NOT NULL DEFAULT 'ORIGINAL'"
        )
    conn.execute(
        """
        INSERT OR REPLACE INTO app_version_history(
            version, release_date, new_features, bug_fixes, db_migration_version
        ) VALUES (?, ?, ?, ?, ?)
        """,
        (
            "5.0.0-alpha.4",
            "2026-08-10",
            "Operational completion: users, catalog workflow, reports, held orders",
            "Inventory, discounted returns, cash closing, settings and backup fixes",
            7,
        ),
    )


@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    name: str
    run: Callable[[sqlite3.Connection], None]


MIGRATIONS: tuple[Migration, ...] = (
    Migration(1, "core_schema", migration_001_core),
    Migration(2, "normalize_supplier_payments", migration_002_supplier_payments),
    Migration(3, "indexes_and_defaults", migration_003_indexes_and_defaults),
    Migration(4, "operations_schema", migration_004_operations_schema),
    Migration(5, "release_metadata", migration_005_release_metadata),
    Migration(6, "transaction_snapshots", migration_006_transaction_snapshots),
    Migration(
        7,
        "cash_closing_and_release_metadata",
        migration_007_cash_closing_and_release_metadata,
    ),
)


class MigrationManager:
    def current_version(self, conn: sqlite3.Connection) -> int:
        return int(conn.execute("PRAGMA user_version").fetchone()[0])

    def migrate(self, conn: sqlite3.Connection) -> tuple[int, int]:
        before = self.current_version(conn)
        if before > SCHEMA_VERSION:
            raise MigrationError(
                f"database schema {before} is newer than supported schema {SCHEMA_VERSION}"
            )
        conn.isolation_level = None
        conn.execute("BEGIN IMMEDIATE")
        try:
            # Always ensure the migration ledger exists before logging migrations.
            conn.execute(CORE_SCHEMA[0])
            for migration in MIGRATIONS:
                if migration.version <= before:
                    continue
                migration.run(conn)
                conn.execute(
                    "INSERT OR REPLACE INTO schema_migrations(version, name, applied_at) VALUES (?, ?, ?)",
                    (migration.version, migration.name, utc_now_text()),
                )
                conn.execute(f"PRAGMA user_version = {migration.version}")
            conn.execute("COMMIT")
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        return before, self.current_version(conn)
