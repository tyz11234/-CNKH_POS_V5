from __future__ import annotations

import tempfile
from pathlib import Path

from PySide6.QtWidgets import QApplication, QDialog

from cnkh_pos.database.bootstrap import bootstrap_database
from cnkh_pos.database.connection import Database
from cnkh_pos.services.auth import AuthenticatedUser, AuthService
from cnkh_pos.services.catalog import CatalogService, ProductInput
from cnkh_pos.services.discounts import (
    allocate_order_discount,
    discount_cents_from_value,
)
from cnkh_pos.ui.dialogs.discount import DiscountDialog
from cnkh_pos.ui.dialogs.rounded_checkout import RoundedCheckoutDialog
from cnkh_pos.ui.staff.enhanced_window import StaffWindowEnhanced


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _database_and_user():
    temp = tempfile.TemporaryDirectory()
    root = Path(temp.name)
    database = Database(root / "hardware_pos.db")
    bootstrap_database(database.path, root / "backups")
    with database.transaction() as conn:
        user_id = AuthService.create_user(
            conn,
            username="staff",
            display_name="Staff",
            password="SafePass123!",
            role="STAFF",
            permissions={"apply_discount": True},
            admin_id=None,
        )
    user = AuthenticatedUser(
        user_id,
        "staff",
        "Staff",
        "STAFF",
        {"apply_discount": True},
    )
    return temp, database, user


def test_discount_helper_supports_percent_and_fixed_rm() -> None:
    assert discount_cents_from_value(1000, mode="PERCENT", value="10") == 100
    assert discount_cents_from_value(1000, mode="FIXED", value="1.25") == 125
    allocation = allocate_order_discount([(1, 600), (2, 400)], 125)
    assert sum(allocation.values()) == 125
    assert allocation[1] + allocation[2] == 125


def test_item_fixed_discount_reduces_cart_total(monkeypatch) -> None:
    _app()
    temp, database, user = _database_and_user()
    try:
        product_id = CatalogService(database).add_product(
            ProductInput(name="Discount Item", selling_price_cents=1000, stock="5"),
            admin_id=user.id,
        )
        window = StaffWindowEnhanced(database, user)
        window._add_to_cart(product_id)
        window.cart.setCurrentCell(0, 0)

        def fake_exec(dialog: DiscountDialog):
            dialog.mode.setCurrentIndex(dialog.mode.findData("FIXED"))
            dialog.value.setValue(1.25)
            return QDialog.DialogCode.Accepted

        monkeypatch.setattr(DiscountDialog, "exec", fake_exec)
        window._edit_discount()
        assert window.cart_discounts[product_id] == 125
        assert window._cart_total() == 875
        assert window.total_label.text() == "RM 8.75"
        window.close()
    finally:
        temp.cleanup()


def test_item_percentage_discount_reduces_cart_total(monkeypatch) -> None:
    _app()
    temp, database, user = _database_and_user()
    try:
        product_id = CatalogService(database).add_product(
            ProductInput(name="Percent Item", selling_price_cents=2000, stock="5"),
            admin_id=user.id,
        )
        window = StaffWindowEnhanced(database, user)
        window._add_to_cart(product_id)
        window.cart.setCurrentCell(0, 0)

        def fake_exec(dialog: DiscountDialog):
            dialog.mode.setCurrentIndex(dialog.mode.findData("PERCENT"))
            dialog.value.setValue(10)
            return QDialog.DialogCode.Accepted

        monkeypatch.setattr(DiscountDialog, "exec", fake_exec)
        window._edit_discount()
        assert window.cart_discounts[product_id] == 200
        assert window._cart_total() == 1800
        assert window.total_label.text() == "RM 18.00"
        window.close()
    finally:
        temp.cleanup()


def test_checkout_order_discount_supports_percent_and_fixed_and_then_rounds() -> None:
    _app()
    dialog = RoundedCheckoutDialog(1067)
    dialog.checkout_discount_mode.setCurrentIndex(
        dialog.checkout_discount_mode.findData("PERCENT")
    )
    dialog.checkout_discount_value.setValue(10)
    assert dialog.discount_cents == 107
    assert dialog.discounted_total_cents == 960
    assert dialog.total_cents == 960

    dialog.checkout_discount_mode.setCurrentIndex(
        dialog.checkout_discount_mode.findData("FIXED")
    )
    dialog.checkout_discount_value.setValue(0.03)
    assert dialog.discount_cents == 3
    assert dialog.discounted_total_cents == 1064
    assert dialog.total_cents == 1060
    dialog.close()
