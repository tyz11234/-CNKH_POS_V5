from __future__ import annotations

import tempfile
from decimal import Decimal
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton

from cnkh_pos.database.bootstrap import bootstrap_database
from cnkh_pos.database.connection import Database
from cnkh_pos.services.auth import AuthenticatedUser, AuthService
from cnkh_pos.services.catalog import CatalogService, ProductInput, is_valid_ean13
from cnkh_pos.services.sales import ReturnService, SaleLine, SalesService
from cnkh_pos.ui.admin.enhanced_data_pages import (
    ProductDialogWithBarcodeMode,
    SalesPageEnhanced,
)


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
                username="admin",
                display_name="Admin",
                password="SafePass123!",
                role="ADMIN",
                permissions={},
                admin_id=None,
            )
        user = AuthenticatedUser(admin_id, "admin", "Admin", "ADMIN", {})
        yield database, user


def test_new_product_dialog_defaults_to_system_generated_barcode(prepared_database) -> None:
    _app()
    database, _user = prepared_database
    dialog = ProductDialogWithBarcodeMode(database)
    assert dialog.barcode_mode is not None
    assert dialog.barcode_mode.currentData() == "AUTO"
    assert not dialog.barcode.isEnabled()
    dialog.name.setText("Auto Barcode Product")
    assert dialog.value().barcode is None
    dialog.close()


def test_new_product_dialog_manual_barcode_is_explicit_and_required(prepared_database) -> None:
    _app()
    database, _user = prepared_database
    dialog = ProductDialogWithBarcodeMode(database)
    assert dialog.barcode_mode is not None
    dialog.barcode_mode.setCurrentIndex(dialog.barcode_mode.findData("MANUAL"))
    assert dialog.barcode.isEnabled()
    dialog.name.setText("Manual Barcode Product")
    with pytest.raises(ValueError, match="手动 Barcode 不能为空"):
        dialog.value()
    dialog.barcode.setText("CNKH-MANUAL-001")
    assert dialog.value().barcode == "CNKH-MANUAL-001"
    dialog.close()


def test_catalog_auto_generates_ean13_and_manual_barcode_still_works(prepared_database) -> None:
    database, user = prepared_database
    service = CatalogService(database)
    automatic_id = service.add_product(
        ProductInput(name="Automatic"), admin_id=user.id
    )
    manual_id = service.add_product(
        ProductInput(name="Manual", barcode="CNKH-MANUAL-002"), admin_id=user.id
    )
    conn = database.connect(readonly=True)
    try:
        automatic = str(
            conn.execute("SELECT barcode FROM products WHERE id=?", (automatic_id,)).fetchone()[0]
        )
        manual = str(
            conn.execute("SELECT barcode FROM products WHERE id=?", (manual_id,)).fetchone()[0]
        )
    finally:
        conn.close()
    assert is_valid_ean13(automatic)
    assert manual == "CNKH-MANUAL-002"
    with pytest.raises(ValueError, match="duplicate barcode"):
        service.add_product(
            ProductInput(name="Duplicate", barcode="CNKH-MANUAL-002"),
            admin_id=user.id,
        )


def test_delete_sale_restores_only_unreturned_stock_and_keeps_audit(prepared_database) -> None:
    database, user = prepared_database
    product_id = CatalogService(database).add_product(
        ProductInput(
            name="Delete Sale Product",
            selling_price_cents=500,
            stock="10",
        ),
        admin_id=user.id,
    )
    sale = SalesService(database).create_sale(
        lines=[SaleLine(product_id, Decimal("4"), Decimal("4"))],
        payment_method="CASH",
        paid_cents=2000,
        cashier_id=user.id,
    )
    conn = database.connect(readonly=True)
    try:
        sale_item_id = int(
            conn.execute("SELECT id FROM sale_items WHERE sale_id=?", (sale.sale_id,)).fetchone()[0]
        )
    finally:
        conn.close()
    ReturnService(database).create_return(
        sale_id=sale.sale_id,
        quantities_by_sale_item={sale_item_id: Decimal("1")},
        reason="test return",
        operator_id=user.id,
        refund_method="CASH",
    )
    SalesService(database).delete_sale(sale_id=sale.sale_id, admin_id=user.id)

    conn = database.connect(readonly=True)
    try:
        stock = Decimal(
            str(conn.execute("SELECT stock_decimal FROM products WHERE id=?", (product_id,)).fetchone()[0])
        )
        sale_count = int(
            conn.execute("SELECT COUNT(*) FROM sales WHERE id=?", (sale.sale_id,)).fetchone()[0]
        )
        return_count = int(
            conn.execute("SELECT COUNT(*) FROM sale_returns WHERE sale_id=?", (sale.sale_id,)).fetchone()[0]
        )
        audit_count = int(
            conn.execute(
                "SELECT COUNT(*) FROM audit_logs WHERE module='SALES' AND action='DELETE' AND record_id=?",
                (str(sale.sale_id),),
            ).fetchone()[0]
        )
        movement = conn.execute(
            "SELECT change_decimal FROM stock_movements WHERE source_type='DELETE_SALE' AND reference=?",
            (sale.receipt_no,),
        ).fetchone()
    finally:
        conn.close()

    assert stock == Decimal("10")
    assert sale_count == 0
    assert return_count == 0
    assert audit_count == 1
    assert Decimal(str(movement[0])) == Decimal("3")


def test_sales_page_delete_button_uses_safe_service_path(prepared_database, monkeypatch) -> None:
    _app()
    database, user = prepared_database
    product_id = CatalogService(database).add_product(
        ProductInput(name="UI Delete", selling_price_cents=100, stock="2"),
        admin_id=user.id,
    )
    sale = SalesService(database).create_sale(
        lines=[SaleLine(product_id, Decimal("1"), Decimal("1"))],
        payment_method="CASH",
        paid_cents=100,
        cashier_id=user.id,
    )
    page = SalesPageEnhanced(database, user)
    assert "删除销售记录" in [button.text() for button in page.findChildren(QPushButton)]
    page.table.setCurrentCell(0, 0)
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: None)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: None)
    page.delete_sale()
    conn = database.connect(readonly=True)
    try:
        assert conn.execute("SELECT COUNT(*) FROM sales WHERE id=?", (sale.sale_id,)).fetchone()[0] == 0
        assert Decimal(
            str(conn.execute("SELECT stock_decimal FROM products WHERE id=?", (product_id,)).fetchone()[0])
        ) == Decimal("2")
    finally:
        conn.close()
    page.close()
