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
from cnkh_pos.services.checkout_sales import CheckoutSalesService
from cnkh_pos.services.daily_closing import DailyClosingService
from cnkh_pos.services.money import (
    cash_rounding_adjustment_cents,
    round_cash_change_cents,
)
from cnkh_pos.services.sales import SaleLine
from cnkh_pos.ui.dialogs.cash_checkout import CashRoundedCheckoutDialog


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


@pytest.fixture
def prepared_database():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        database = Database(root / "hardware_pos.db")
        bootstrap_database(database.path, root / "backups")
        with database.transaction() as conn:
            admin_id = AuthService.create_user(
                conn,
                username="cashround",
                display_name="Cash Round",
                password="SafePass123!",
                role="ADMIN",
                permissions={},
                admin_id=None,
            )
        yield database, admin_id


def _cash_sale(database: Database, admin_id: int, *, price_cents: int, paid_cents: int):
    product_id = CatalogService(database).add_product(
        ProductInput(
            name=f"Cash round {price_cents}",
            selling_price_cents=price_cents,
            stock="2",
        ),
        admin_id=admin_id,
    )
    return CheckoutSalesService(database).create_sale(
        lines=[SaleLine(product_id, Decimal("1"), Decimal("1"))],
        payment_method="CASH",
        paid_cents=paid_cents,
        cashier_id=admin_id,
        business_date=date.today(),
    )


def test_requested_cash_change_rounding_examples() -> None:
    assert round_cash_change_cents(67) == 70
    assert round_cash_change_cents(42) == 40
    assert round_cash_change_cents(45) == 45
    assert round_cash_change_cents(0) == 0
    assert round_cash_change_cents(99) == 100


def test_cash_checkout_persists_rounded_change_and_returns_same_value(prepared_database) -> None:
    database, admin_id = prepared_database
    sale_67 = _cash_sale(database, admin_id, price_cents=933, paid_cents=1000)
    sale_42 = _cash_sale(database, admin_id, price_cents=958, paid_cents=1000)
    sale_45 = _cash_sale(database, admin_id, price_cents=955, paid_cents=1000)

    assert sale_67.change_cents == 70
    assert sale_42.change_cents == 40
    assert sale_45.change_cents == 45

    conn = database.connect(readonly=True)
    try:
        persisted = [
            int(
                conn.execute(
                    "SELECT change_cents FROM sales WHERE id=?", (sale.sale_id,)
                ).fetchone()[0]
            )
            for sale in (sale_67, sale_42, sale_45)
        ]
    finally:
        conn.close()
    assert persisted == [70, 40, 45]


def test_cash_rounding_adjustment_direction_is_auditable() -> None:
    assert cash_rounding_adjustment_cents(
        total_cents=933, paid_cents=1000, change_cents=70
    ) == -3
    assert cash_rounding_adjustment_cents(
        total_cents=958, paid_cents=1000, change_cents=40
    ) == 2
    assert cash_rounding_adjustment_cents(
        total_cents=955, paid_cents=1000, change_cents=45
    ) == 0


def test_daily_closing_uses_actual_cash_retained_after_rounding(prepared_database) -> None:
    database, admin_id = prepared_database
    _cash_sale(database, admin_id, price_cents=933, paid_cents=1000)  # keeps 930
    _cash_sale(database, admin_id, price_cents=958, paid_cents=1000)  # keeps 960
    _cash_sale(database, admin_id, price_cents=955, paid_cents=1000)  # keeps 955
    assert DailyClosingService(database).system_cash(
        business_date=date.today(), opening_cash_cents=0
    ) == 2845


def test_card_payment_is_not_cash_rounded(prepared_database) -> None:
    database, admin_id = prepared_database
    product_id = CatalogService(database).add_product(
        ProductInput(name="Card exact", selling_price_cents=933, stock="1"),
        admin_id=admin_id,
    )
    result = CheckoutSalesService(database).create_sale(
        lines=[SaleLine(product_id, Decimal("1"), Decimal("1"))],
        payment_method="CARD",
        paid_cents=1000,
        cashier_id=admin_id,
    )
    assert result.change_cents == 67
    conn = database.connect(readonly=True)
    try:
        assert int(
            conn.execute(
                "SELECT change_cents FROM sales WHERE id=?", (result.sale_id,)
            ).fetchone()[0]
        ) == 67
    finally:
        conn.close()


def test_checkout_dialog_previews_cash_rounding_but_not_card() -> None:
    _app()
    dialog = CashRoundedCheckoutDialog(933, quick_amounts=[])
    dialog.paid_input.setText("10.00")
    assert dialog.change_label.text() == "RM 0.70"

    card = next(
        button
        for button in dialog.method_group.buttons()
        if button.property("paymentMethod") == "CARD"
    )
    card.setChecked(True)
    dialog.paid_input.setText("10.00")
    assert dialog.change_label.text() == "RM 0.67"
    dialog.close()
