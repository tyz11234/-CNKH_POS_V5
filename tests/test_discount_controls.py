from __future__ import annotations

import tempfile
from decimal import Decimal
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QDialog

from cnkh_pos.database.bootstrap import bootstrap_database
from cnkh_pos.database.connection import Database
from cnkh_pos.services.auth import AuthenticatedUser, AuthService
from cnkh_pos.services.catalog import CatalogService, ProductInput
from cnkh_pos.services.checkout_rounding import RoundedSalesService
from cnkh_pos.services.discounts import (
    discount_from_amount_cents,
    discount_from_percent_cents,
)
from cnkh_pos.services.sales import SaleLine
from cnkh_pos.ui.dialogs.discount import DiscountDialog
from cnkh_pos.ui.staff.enhanced_window import StaffWindowEnhanced


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


@pytest.fixture
def prepared_database():
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        database = Database(root / "hardware_pos.db")
        bootstrap_database(database.path, root / "backups")
        with database.transaction() as conn:
            user_id = AuthService.create_user(
                conn,
                username="discount",
                display_name="Discount Tester",
                password="SafePass123!",
                role="ADMIN",
                permissions={"apply_discount": True},
                admin_id=None,
            )
        user = AuthenticatedUser(
            user_id,
            "discount",
            "Discount Tester",
            "ADMIN",
            {"apply_discount": True},
        )
        yield database, user


def test_percent_and_fixed_discount_calculations_are_exact() -> None:
    assert discount_from_percent_cents(1000, 10) == 100
    assert discount_from_percent_cents(1000, Decimal("12.5")) == 125
    assert discount_from_percent_cents(999, 10) == 100
    assert discount_from_percent_cents(1000, 100) == 1000
    assert discount_from_amount_cents(1000, 333) == 333
    assert discount_from_amount_cents(1000, 1500) == 1000
    with pytest.raises(ValueError):
        discount_from_percent_cents(1000, 100.01)
    with pytest.raises(ValueError):
        discount_from_amount_cents(1000, -1)


def test_discount_dialog_supports_percent_and_fixed_amount() -> None:
    _app()
    dialog = DiscountDialog(1000)
    assert dialog.mode.currentData() == "PERCENT"
    dialog.value.setValue(12.5)
    assert dialog.calculated_discount_cents() == 125
    assert "RM 8.75" in dialog.preview.text()

    dialog.mode.setCurrentIndex(dialog.mode.findData("AMOUNT"))
    dialog.value.setValue(3.33)
    assert dialog.calculated_discount_cents() == 333
    assert "RM 6.67" in dialog.preview.text()
    dialog.close()


def test_staff_discount_immediately_reduces_line_and_cart_total(
    prepared_database, monkeypatch
) -> None:
    _app()
    database, user = prepared_database
    product_id = CatalogService(database).add_product(
        ProductInput(
            name="Discount Product",
            selling_price_cents=1000,
            stock="5",
        ),
        admin_id=user.id,
    )
    window = StaffWindowEnhanced(database, user)
    window._add_to_cart(product_id)
    window.cart.setCurrentCell(0, 0)

    def accept_fixed(self) -> int:
        self.discount_cents = 250
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(DiscountDialog, "exec", accept_fixed)
    window._edit_discount()

    assert window.cart_discounts[product_id] == 250
    assert window._cart_total() == 750
    assert window.cart.item(0, 3).text() == "RM 2.50"
    assert window.cart.item(0, 4).text() == "RM 7.50"
    assert window.total_label.text() == "RM 7.50"
    assert window.discount_button.text() == "Discount（% / RM）"
    window.close()


def test_discount_reaches_persisted_sale_amounts(prepared_database) -> None:
    database, user = prepared_database
    product_id = CatalogService(database).add_product(
        ProductInput(
            name="Persist Discount",
            selling_price_cents=1000,
            stock="2",
        ),
        admin_id=user.id,
    )
    sale = RoundedSalesService(database).create_sale(
        lines=[
            SaleLine(
                product_id,
                Decimal("1"),
                Decimal("1"),
                discount_cents=250,
            )
        ],
        payment_method="CASH",
        paid_cents=1000,
        cashier_id=user.id,
    )
    conn = database.connect(readonly=True)
    try:
        stored_sale = conn.execute(
            "SELECT subtotal_cents,discount_cents,total_cents FROM sales WHERE id=?",
            (sale.sale_id,),
        ).fetchone()
        stored_item = conn.execute(
            "SELECT discount_cents,subtotal_cents FROM sale_items WHERE sale_id=?",
            (sale.sale_id,),
        ).fetchone()
    finally:
        conn.close()
    assert tuple(stored_sale) == (1000, 250, 750)
    assert tuple(stored_item) == (250, 750)
