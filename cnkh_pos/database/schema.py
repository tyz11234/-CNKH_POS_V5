from __future__ import annotations

import sqlite3

CORE_SCHEMA: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS schema_migrations (
        version INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        applied_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY,
        username TEXT NOT NULL COLLATE NOCASE UNIQUE,
        display_name TEXT NOT NULL,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL CHECK(role IN ('ADMIN','STAFF')),
        permissions_json TEXT NOT NULL DEFAULT '{}',
        is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0,1)),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS categories (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL COLLATE NOCASE UNIQUE,
        is_deleted INTEGER NOT NULL DEFAULT 0 CHECK(is_deleted IN (0,1)),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS products (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        aliases TEXT NOT NULL DEFAULT '',
        category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
        sku TEXT COLLATE NOCASE UNIQUE,
        barcode TEXT UNIQUE,
        cost_cents INTEGER NOT NULL DEFAULT 0 CHECK(cost_cents >= 0),
        selling_price_cents INTEGER NOT NULL DEFAULT 0 CHECK(selling_price_cents >= 0),
        stock_decimal TEXT NOT NULL DEFAULT '0',
        unit TEXT NOT NULL DEFAULT 'pcs',
        location TEXT NOT NULL DEFAULT '',
        low_stock_decimal TEXT NOT NULL DEFAULT '0',
        is_deleted INTEGER NOT NULL DEFAULT 0 CHECK(is_deleted IN (0,1)),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS customers (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        phone TEXT NOT NULL DEFAULT '',
        notes TEXT NOT NULL DEFAULT '',
        is_deleted INTEGER NOT NULL DEFAULT 0 CHECK(is_deleted IN (0,1)),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS suppliers (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        phone TEXT NOT NULL DEFAULT '',
        email TEXT NOT NULL DEFAULT '',
        notes TEXT NOT NULL DEFAULT '',
        is_deleted INTEGER NOT NULL DEFAULT 0 CHECK(is_deleted IN (0,1)),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS purchases (
        id INTEGER PRIMARY KEY,
        purchase_no TEXT NOT NULL UNIQUE,
        supplier_id INTEGER REFERENCES suppliers(id) ON DELETE RESTRICT,
        total_cents INTEGER NOT NULL DEFAULT 0 CHECK(total_cents >= 0),
        paid_cents INTEGER NOT NULL DEFAULT 0 CHECK(paid_cents >= 0),
        status TEXT NOT NULL DEFAULT 'UNPAID' CHECK(status IN ('UNPAID','PARTIAL','PAID')),
        purchased_at TEXT NOT NULL,
        created_by INTEGER REFERENCES users(id),
        is_deleted INTEGER NOT NULL DEFAULT 0 CHECK(is_deleted IN (0,1))
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sales (
        id INTEGER PRIMARY KEY,
        receipt_no TEXT NOT NULL UNIQUE,
        subtotal_cents INTEGER NOT NULL CHECK(subtotal_cents >= 0),
        discount_cents INTEGER NOT NULL DEFAULT 0 CHECK(discount_cents >= 0),
        total_cents INTEGER NOT NULL CHECK(total_cents >= 0),
        paid_cents INTEGER NOT NULL CHECK(paid_cents >= 0),
        change_cents INTEGER NOT NULL DEFAULT 0 CHECK(change_cents >= 0),
        payment_method TEXT NOT NULL CHECK(payment_method IN ('CASH','CARD','DUITNOW_QR','CREDIT')),
        customer_id INTEGER REFERENCES customers(id) ON DELETE SET NULL,
        cashier_id INTEGER REFERENCES users(id),
        sold_at TEXT NOT NULL,
        is_deleted INTEGER NOT NULL DEFAULT 0 CHECK(is_deleted IN (0,1))
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sale_items (
        id INTEGER PRIMARY KEY,
        sale_id INTEGER NOT NULL REFERENCES sales(id) ON DELETE CASCADE,
        product_id INTEGER REFERENCES products(id) ON DELETE SET NULL,
        product_name_snapshot TEXT NOT NULL,
        sku_snapshot TEXT,
        barcode_snapshot TEXT,
        unit_snapshot TEXT NOT NULL,
        quantity_decimal TEXT NOT NULL,
        stock_deduction_decimal TEXT NOT NULL,
        unit_price_cents INTEGER NOT NULL CHECK(unit_price_cents >= 0),
        discount_cents INTEGER NOT NULL DEFAULT 0 CHECK(discount_cents >= 0),
        subtotal_cents INTEGER NOT NULL CHECK(subtotal_cents >= 0),
        returned_stock_decimal TEXT NOT NULL DEFAULT '0'
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS stock_movements (
        id INTEGER PRIMARY KEY,
        product_id INTEGER REFERENCES products(id) ON DELETE SET NULL,
        source_type TEXT NOT NULL,
        reference TEXT NOT NULL,
        old_stock_decimal TEXT NOT NULL,
        change_decimal TEXT NOT NULL,
        new_stock_decimal TEXT NOT NULL,
        operator_id INTEGER REFERENCES users(id),
        created_at TEXT NOT NULL,
        notes TEXT NOT NULL DEFAULT ''
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS customer_payments (
        id INTEGER PRIMARY KEY,
        customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE RESTRICT,
        amount_cents INTEGER NOT NULL CHECK(amount_cents > 0),
        payment_method TEXT NOT NULL,
        note TEXT NOT NULL DEFAULT '',
        operator_id INTEGER REFERENCES users(id),
        paid_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS supplier_payments (
        id INTEGER PRIMARY KEY,
        supplier_id INTEGER REFERENCES suppliers(id) ON DELETE RESTRICT,
        purchase_id INTEGER REFERENCES purchases(id) ON DELETE SET NULL,
        amount_cents INTEGER NOT NULL CHECK(amount_cents > 0),
        payment_method TEXT NOT NULL DEFAULT 'CASH',
        note TEXT NOT NULL DEFAULT '',
        operator_id INTEGER REFERENCES users(id),
        paid_at TEXT NOT NULL,
        legacy_source_json TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS quick_amounts (
        id INTEGER PRIMARY KEY,
        amount_cents INTEGER NOT NULL CHECK(amount_cents > 0),
        is_enabled INTEGER NOT NULL DEFAULT 1 CHECK(is_enabled IN (0,1)),
        sort_order INTEGER NOT NULL DEFAULT 0,
        UNIQUE(amount_cents)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS receipt_sequences (
        business_date TEXT PRIMARY KEY,
        last_sequence INTEGER NOT NULL CHECK(last_sequence > 0)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value_json TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        updated_by INTEGER REFERENCES users(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS audit_logs (
        id INTEGER PRIMARY KEY,
        occurred_at TEXT NOT NULL,
        user_id INTEGER REFERENCES users(id),
        username_snapshot TEXT NOT NULL DEFAULT '',
        action TEXT NOT NULL,
        module TEXT NOT NULL,
        record_type TEXT NOT NULL DEFAULT '',
        record_id TEXT NOT NULL DEFAULT '',
        old_value_json TEXT,
        new_value_json TEXT,
        detail TEXT NOT NULL DEFAULT ''
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS system_checks (
        id INTEGER PRIMARY KEY,
        check_type TEXT NOT NULL,
        status TEXT NOT NULL,
        detail TEXT NOT NULL,
        checked_at TEXT NOT NULL
    )
    """,
)

INDEX_SCHEMA: tuple[str, ...] = (
    "CREATE INDEX IF NOT EXISTS idx_products_name ON products(name COLLATE NOCASE)",
    "CREATE INDEX IF NOT EXISTS idx_products_barcode ON products(barcode)",
    "CREATE INDEX IF NOT EXISTS idx_products_category ON products(category_id, is_deleted)",
    "CREATE INDEX IF NOT EXISTS idx_sales_sold_at ON sales(sold_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_purchases_purchased_at ON purchases(purchased_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_stock_movements_product_time ON stock_movements(product_id, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_audit_time ON audit_logs(occurred_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_supplier_payments_supplier_time ON supplier_payments(supplier_id, paid_at DESC)",
)

OPERATIONS_SCHEMA: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS supplier_products (
        supplier_id INTEGER NOT NULL REFERENCES suppliers(id) ON DELETE CASCADE,
        product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
        supplier_sku TEXT NOT NULL DEFAULT '',
        is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0,1)),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        PRIMARY KEY(supplier_id, product_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS purchase_items (
        id INTEGER PRIMARY KEY,
        purchase_id INTEGER NOT NULL REFERENCES purchases(id) ON DELETE CASCADE,
        product_id INTEGER REFERENCES products(id) ON DELETE SET NULL,
        product_name_snapshot TEXT NOT NULL,
        quantity_decimal TEXT NOT NULL,
        unit_cost_cents INTEGER NOT NULL CHECK(unit_cost_cents >= 0),
        subtotal_cents INTEGER NOT NULL CHECK(subtotal_cents >= 0),
        reversed_stock_decimal TEXT NOT NULL DEFAULT '0'
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sale_returns (
        id INTEGER PRIMARY KEY,
        return_no TEXT NOT NULL UNIQUE,
        sale_id INTEGER NOT NULL REFERENCES sales(id) ON DELETE RESTRICT,
        total_cents INTEGER NOT NULL CHECK(total_cents >= 0),
        refund_method TEXT NOT NULL DEFAULT 'ORIGINAL',
        reason TEXT NOT NULL,
        operator_id INTEGER REFERENCES users(id),
        returned_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sale_return_items (
        id INTEGER PRIMARY KEY,
        return_id INTEGER NOT NULL REFERENCES sale_returns(id) ON DELETE CASCADE,
        sale_item_id INTEGER NOT NULL REFERENCES sale_items(id) ON DELETE RESTRICT,
        quantity_decimal TEXT NOT NULL,
        stock_restored_decimal TEXT NOT NULL,
        refund_cents INTEGER NOT NULL CHECK(refund_cents >= 0)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS customer_debts (
        id INTEGER PRIMARY KEY,
        customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE RESTRICT,
        sale_id INTEGER UNIQUE REFERENCES sales(id) ON DELETE RESTRICT,
        original_cents INTEGER NOT NULL CHECK(original_cents > 0),
        balance_cents INTEGER NOT NULL CHECK(balance_cents >= 0),
        status TEXT NOT NULL CHECK(status IN ('OPEN','CLOSED')),
        opened_at TEXT NOT NULL,
        settled_at TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS held_orders (
        id INTEGER PRIMARY KEY,
        hold_no TEXT NOT NULL UNIQUE,
        payload_json TEXT NOT NULL,
        cashier_id INTEGER REFERENCES users(id),
        held_at TEXT NOT NULL,
        retrieved_at TEXT,
        status TEXT NOT NULL DEFAULT 'HELD' CHECK(status IN ('HELD','RETRIEVED','CANCELLED'))
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS stocktakes (
        id INTEGER PRIMARY KEY,
        stocktake_no TEXT NOT NULL UNIQUE,
        started_at TEXT NOT NULL,
        completed_at TEXT,
        operator_id INTEGER REFERENCES users(id),
        notes TEXT NOT NULL DEFAULT '',
        product_count INTEGER NOT NULL DEFAULT 0,
        variance_count INTEGER NOT NULL DEFAULT 0,
        increase_count INTEGER NOT NULL DEFAULT 0,
        decrease_count INTEGER NOT NULL DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'DRAFT' CHECK(status IN ('DRAFT','COMPLETED','CANCELLED'))
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS stocktake_items (
        id INTEGER PRIMARY KEY,
        stocktake_id INTEGER NOT NULL REFERENCES stocktakes(id) ON DELETE CASCADE,
        product_id INTEGER REFERENCES products(id) ON DELETE SET NULL,
        product_name_snapshot TEXT NOT NULL,
        barcode_snapshot TEXT,
        sku_snapshot TEXT,
        system_stock_decimal TEXT NOT NULL,
        physical_count_decimal TEXT NOT NULL,
        variance_decimal TEXT NOT NULL,
        unit_snapshot TEXT NOT NULL,
        location_snapshot TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS product_price_history (
        id INTEGER PRIMARY KEY,
        product_id INTEGER REFERENCES products(id) ON DELETE SET NULL,
        old_cost_cents INTEGER NOT NULL,
        new_cost_cents INTEGER NOT NULL,
        old_selling_price_cents INTEGER NOT NULL,
        new_selling_price_cents INTEGER NOT NULL,
        admin_id INTEGER REFERENCES users(id),
        changed_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS daily_cash_closings (
        id INTEGER PRIMARY KEY,
        business_date TEXT NOT NULL,
        cashier_id INTEGER REFERENCES users(id),
        opening_cash_cents INTEGER NOT NULL DEFAULT 0,
        system_cash_cents INTEGER NOT NULL,
        actual_cash_cents INTEGER NOT NULL,
        variance_cents INTEGER NOT NULL,
        note TEXT NOT NULL DEFAULT '',
        closed_at TEXT NOT NULL,
        UNIQUE(business_date, cashier_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS backup_history (
        id INTEGER PRIMARY KEY,
        path TEXT NOT NULL,
        reason TEXT NOT NULL,
        database_size INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        operator_id INTEGER REFERENCES users(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS app_version_history (
        version TEXT PRIMARY KEY,
        release_date TEXT NOT NULL,
        new_features TEXT NOT NULL,
        bug_fixes TEXT NOT NULL,
        db_migration_version INTEGER NOT NULL
    )
    """,
)

OPERATIONS_INDEX_SCHEMA: tuple[str, ...] = (
    "CREATE INDEX IF NOT EXISTS idx_supplier_products_product ON supplier_products(product_id, is_active)",
    "CREATE INDEX IF NOT EXISTS idx_purchase_items_purchase ON purchase_items(purchase_id)",
    "CREATE INDEX IF NOT EXISTS idx_returns_sale ON sale_returns(sale_id, returned_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_customer_debts_status ON customer_debts(status, customer_id)",
    "CREATE INDEX IF NOT EXISTS idx_stocktakes_date ON stocktakes(started_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_price_history_product ON product_price_history(product_id, changed_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_daily_closing_date ON daily_cash_closings(business_date DESC)",
)


def apply_statements(conn: sqlite3.Connection, statements: tuple[str, ...]) -> None:
    for statement in statements:
        conn.execute(statement)
