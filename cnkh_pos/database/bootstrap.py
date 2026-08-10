from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from cnkh_pos.config import SCHEMA_VERSION
from cnkh_pos.database.connection import Database
from cnkh_pos.database.migrations import MigrationError, MigrationManager
from cnkh_pos.services.backup import BackupService


class DatabaseStartupError(RuntimeError):
    """Fatal safety-gate failure. Callers must not continue in write mode."""


REQUIRED_SCHEMA_COLUMNS: dict[str, set[str]] = {
    "users": {"id", "username", "password_hash", "role", "permissions_json"},
    "products": {
        "id",
        "name",
        "barcode",
        "cost_cents",
        "selling_price_cents",
        "stock_decimal",
        "is_deleted",
    },
    "customers": {"id", "name", "phone", "notes", "is_deleted"},
    "suppliers": {"id", "name", "phone", "email", "notes", "is_deleted"},
    "purchases": {"id", "purchase_no", "total_cents", "paid_cents", "status"},
    "purchase_items": {
        "purchase_id",
        "product_id",
        "quantity_decimal",
        "unit_cost_cents",
        "reversed_stock_decimal",
    },
    "supplier_products": {"supplier_id", "product_id", "is_active"},
    "supplier_payments": {
        "supplier_id",
        "purchase_id",
        "amount_cents",
        "payment_method",
        "voided_at",
    },
    "sales": {"id", "receipt_no", "total_cents", "payment_method", "sold_at"},
    "sale_items": {
        "sale_id",
        "quantity_decimal",
        "stock_deduction_decimal",
        "subtotal_cents",
        "unit_cost_cents_snapshot",
        "returned_stock_decimal",
    },
    "sale_returns": {"sale_id", "total_cents", "refund_method", "returned_at"},
    "sale_return_items": {
        "return_id",
        "sale_item_id",
        "quantity_decimal",
        "stock_restored_decimal",
        "refund_cents",
    },
    "customer_debts": {"customer_id", "sale_id", "balance_cents", "status"},
    "customer_payments": {"customer_id", "debt_id", "amount_cents", "payment_method"},
    "held_orders": {"payload_json", "cashier_id", "status"},
    "stocktakes": {"stocktake_no", "status", "variance_count"},
    "stocktake_items": {"stocktake_id", "product_id", "physical_count_decimal"},
    "daily_cash_closings": {
        "business_date",
        "cashier_id",
        "opening_cash_cents",
        "system_cash_cents",
        "actual_cash_cents",
    },
    "settings": {"key", "value_json"},
    "audit_logs": {"occurred_at", "action", "module", "detail"},
    "system_checks": {"check_type", "status", "detail", "checked_at"},
    "document_sequences": {"document_type", "business_date", "last_sequence"},
    "receipt_sequences": {"business_date", "last_sequence"},
}


def validate_database_schema(conn) -> None:
    version = int(conn.execute("PRAGMA user_version").fetchone()[0])
    if version != SCHEMA_VERSION:
        raise MigrationError(
            f"database schema validation expected {SCHEMA_VERSION}, found {version}"
        )
    tables = {
        str(row[0])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    }
    missing_tables = sorted(set(REQUIRED_SCHEMA_COLUMNS) - tables)
    if missing_tables:
        raise MigrationError(
            "database schema is missing required tables: " + ", ".join(missing_tables)
        )
    for table, required_columns in REQUIRED_SCHEMA_COLUMNS.items():
        actual = {str(row[1]) for row in conn.execute(f'PRAGMA table_info("{table}")')}
        missing = sorted(required_columns - actual)
        if missing:
            raise MigrationError(
                f"database table {table} is missing required columns: {', '.join(missing)}"
            )
    foreign_key_errors = conn.execute("PRAGMA foreign_key_check").fetchall()
    if foreign_key_errors:
        sample = "; ".join(
            f"{row[0]} row {row[1]} -> {row[2]}" for row in foreign_key_errors[:5]
        )
        raise MigrationError("database foreign-key validation failed: " + sample)


@dataclass(frozen=True, slots=True)
class StartupResult:
    database_path: Path
    fresh_database: bool
    integrity_messages: tuple[str, ...]
    backup_path: Path | None
    schema_before: int
    schema_after: int
    completed_at: datetime


def bootstrap_database(database_path: Path, backup_dir: Path) -> StartupResult:
    database_path = Path(database_path)
    fresh = not database_path.exists()
    database = Database(database_path)
    backup_path: Path | None = None

    ok, messages = database.integrity_check()
    if not ok:
        raise DatabaseStartupError(
            "Database integrity check failed. No migration was attempted. "
            + " | ".join(messages)
        )

    schema_before = 0
    if not fresh:
        conn = database.connect(readonly=True)
        try:
            schema_before = int(conn.execute("PRAGMA user_version").fetchone()[0])
        finally:
            conn.close()

    if not fresh and schema_before < SCHEMA_VERSION:
        try:
            backup_service = BackupService(backup_dir)
            backup_path = backup_service.create(
                database_path, reason="pre_migration"
            ).path
            backup_service.prune(keep=30)
        except BaseException as exc:
            raise DatabaseStartupError(
                "Could not create the required pre-migration backup. No migration was attempted."
            ) from exc

    conn = database.connect()
    try:
        try:
            before, after = MigrationManager().migrate(conn)
            validate_database_schema(conn)
        except BaseException as exc:
            raise DatabaseStartupError(
                "Database migration or schema validation failed. The application is locked from write mode."
            ) from exc
    finally:
        conn.close()

    return StartupResult(
        database_path=database_path,
        fresh_database=fresh,
        integrity_messages=tuple(messages),
        backup_path=backup_path,
        schema_before=before,
        schema_after=after,
        completed_at=datetime.now().astimezone(),
    )
