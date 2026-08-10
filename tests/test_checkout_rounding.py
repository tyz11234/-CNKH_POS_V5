from __future__ import annotations

import tempfile
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from cnkh_pos.database.bootstrap import bootstrap_database
from cnkh_pos.database.connection import Database
from cnkh_pos.services.auth import AuthService
from cnkh_pos.services.catalog import CatalogService, ProductInput
from cnkh_pos.services.checkout_rounding import (
    RoundedReturnService,
    RoundedSalesService,
)
from cnkh_pos.services.daily_closing import DailyClosingService
from cnkh_pos.services.money import checkout_rounding_cents, round_checkout_cents
from cnkh_pos.services.printing import PrintingService
from cnkh_pos.services.reports import ReportService
from cnkh_pos.services.sales import SaleLine
from cnkh_pos.ui.dialogs.rounded_checkout import RoundedCheckoutDialog


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


@pytest.fixture
def database_and_admin():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        database = Database(root / "hardware_pos.db")
        bootstrap_database(database.path, root / "backups")
        with database.transaction() as conn:
            admin_id = AuthService.create_user(
                conn,
                username="admin",
                display_name="Admin",
                password="SafePass123!",
                role="ADMIN",
                permissions={},
                admin_id=None,
            )
        yield database, admin_id


def _product(database: Database, admin_id: int, price: int, name: str) -> int:
    return CatalogService(database).add_product(
        ProductInput(name=name, selling_price_cents=price, stock="10"),
        admin_id=admin_id,
    )


def test_checkout_rounding_rule_matches_requested_examples() -> None:
    assert round_checkout_cents(67) == 70
    assert round_checkout_cents(42) == 40
    assert round_checkout_cents(45) == 45
    assert round_checkout_cents(40) == 40
    assert checkout_rounding_cents(67) == 3
    assert checkout_rounding_cents(42) == -2
    assert checkout_rounding_cents(45) == 0
    with pytest.raises(ValueError):
        round_checkout_cents(-1)


def test_non_credit_sales_store_rounded_total_but_exact_line_values(
    database_and_admin,
) -> None:
    database, admin_id = database_and_admin
    service = RoundedSalesService(database)
    cases = ((67, 70), (42, 40), (45, 45))
    for index, (price, expected) in enumerate(cases):
        product_id = _product(database, admin_id, price, f"P{index}")
        result = service.create_sale(
            lines=[SaleLine(product_id, Decimal("1"), Decimal("1"))],
            payment_method="CASH",
            paid_cents=expected,
            cashier_id=admin_id,
        )
        assert result.total_cents == expected
        assert result.change_cents == 0
        conn = database.connect(readonly=True)
        try:
            sale = conn.execute(
                "SELECT subtotal_cents,discount_cents,total_cents,paid_cents,change_cents FROM sales WHERE id=?",
                (result.sale_id,),
            ).fetchone()
            item = conn.execute(
                "SELECT subtotal_cents FROM sale_items WHERE sale_id=?",
                (result.sale_id,),
            ).fetchone()
        finally:
            conn.close()
        assert int(sale["subtotal_cents"]) == price
        assert int(sale["discount_cents"]) == 0
        assert int(sale["total_cents"]) == expected
        assert int(sale["paid_cents"]) == expected
        assert int(sale["change_cents"]) == 0
        assert int(item["subtotal_cents"]) == price


def test_credit_sale_keeps_exact_unrounded_balance(database_and_admin) -> None:
    database, admin_id = database_and_admin
    with database.transaction() as conn:
        customer_id = int(
            conn.execute(
                "INSERT INTO customers(name,created_at,updated_at) VALUES ('Credit Customer',datetime('now'),datetime('now'))"
            ).lastrowid
        )
    product_id = _product(database, admin_id, 67, "Credit P")
    result = RoundedSalesService(database).create_sale(
        lines=[SaleLine(product_id, Decimal("1"), Decimal("1"))],
        payment_method="CREDIT",
        paid_cents=0,
        cashier_id=admin_id,
        customer_id=customer_id,
    )
    assert result.total_cents == 67
    conn = database.connect(readonly=True)
    try:
        debt = conn.execute(
            "SELECT original_cents,balance_cents FROM customer_debts WHERE sale_id=?",
            (result.sale_id,),
        ).fetchone()
    finally:
        conn.close()
    assert tuple(debt) == (67, 67)


def test_checkout_dialog_switches_between_rounded_and_exact_credit_total() -> None:
    _app()
    dialog = RoundedCheckoutDialog(67, customers=[(1, "Customer")])
    assert dialog.total_cents == 70
    assert dialog.total_display.text() == "RM 0.70"
    credit = next(
        button
        for button in dialog.method_group.buttons()
        if button.property("paymentMethod") == "CREDIT"
    )
    credit.setChecked(True)
    assert dialog.total_cents == 67
    assert dialog.total_display.text() == "RM 0.67"
    cash = next(
        button
        for button in dialog.method_group.buttons()
        if button.property("paymentMethod") == "CASH"
    )
    cash.setChecked(True)
    assert dialog.total_cents == 70
    dialog.close()


@pytest.mark.parametrize("price,rounded", [(67, 70), (42, 40)])
def test_full_return_reverses_checkout_rounding_and_reports(
    price, rounded, database_and_admin
) -> None:
    database, admin_id = database_and_admin
    product_id = _product(database, admin_id, price, f"Return {price}")
    sale = RoundedSalesService(database).create_sale(
        lines=[SaleLine(product_id, Decimal("1"), Decimal("1"))],
        payment_method="CASH",
        paid_cents=rounded,
        cashier_id=admin_id,
    )
    conn = database.connect(readonly=True)
    try:
        item_id = int(
            conn.execute(
                "SELECT id FROM sale_items WHERE sale_id=?", (sale.sale_id,)
            ).fetchone()[0]
        )
    finally:
        conn.close()
    return_no = RoundedReturnService(database).create_return(
        sale_id=sale.sale_id,
        quantities_by_sale_item={item_id: Decimal("1")},
        reason="full return",
        operator_id=admin_id,
        refund_method="CASH",
    )
    conn = database.connect(readonly=True)
    try:
        returned = conn.execute(
            "SELECT total_cents FROM sale_returns WHERE return_no=?", (return_no,)
        ).fetchone()
        item_refund = conn.execute(
            """SELECT SUM(sri.refund_cents) FROM sale_return_items sri
               JOIN sale_returns sr ON sr.id=sri.return_id WHERE sr.return_no=?""",
            (return_no,),
        ).fetchone()[0]
    finally:
        conn.close()
    assert int(returned[0]) == rounded
    assert int(item_refund) == price
    today = date.today().isoformat()
    summary = ReportService(database).summary(start_date=today, end_date=today)
    assert summary.sales_cents == 0
    assert summary.gross_profit_cents == 0


def test_daily_cash_and_receipt_use_final_rounded_total(database_and_admin) -> None:
    database, admin_id = database_and_admin
    product_id = _product(database, admin_id, 67, "Receipt Round")
    sale = RoundedSalesService(database).create_sale(
        lines=[SaleLine(product_id, Decimal("1"), Decimal("1"))],
        payment_method="CASH",
        paid_cents=70,
        cashier_id=admin_id,
    )
    assert DailyClosingService(database).system_cash(business_date=date.today()) == 70
    printing = PrintingService(database)
    text = printing.render_text(printing.receipt(sale.sale_id))
    lines = text.splitlines()
    assert any(line.startswith("SUBTOTAL") and line.endswith("RM 0.67") for line in lines)
    assert any(line.startswith("TOTAL") and line.endswith("RM 0.70") for line in lines)
    assert any(line.startswith("PAID") and line.endswith("RM 0.70") for line in lines)
    assert any(line.startswith("CHANGE") and line.endswith("RM 0.00") for line in lines)
