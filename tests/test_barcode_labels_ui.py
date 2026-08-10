from __future__ import annotations

import os
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QTabWidget

from cnkh_pos.database.bootstrap import bootstrap_database
from cnkh_pos.database.connection import Database
from cnkh_pos.services.auth import AuthService
from cnkh_pos.services.catalog import CatalogService, ProductInput
from cnkh_pos.ui.admin.barcode_labels import BarcodeLabelsPage
from cnkh_pos.ui.admin.data_pages import StocktakePage
from cnkh_pos.ui.admin.window import AdminWindow


def _build_admin_window():
    temporary = tempfile.TemporaryDirectory()
    root = Path(temporary.name)
    database = Database(root / "hardware_pos.db")
    bootstrap_database(database.path, root / "backups")
    with database.transaction() as conn:
        admin_id = AuthService.create_user(
            conn,
            username="label_admin",
            display_name="Label Admin",
            password="SafePass123!",
            role="ADMIN",
            permissions={},
            admin_id=None,
        )
        admin = AuthService.authenticate(
            conn, "label_admin", "SafePass123!", required_role="ADMIN"
        )
    CatalogService(database).add_product(
        ProductInput(
            name="PVC 电线 4mm",
            sku="PVC-4MM",
            selling_price_cents=1280,
            stock="25",
        ),
        admin_id=admin_id,
    )
    app = QApplication.instance() or QApplication([])
    window = AdminWindow(database, admin)
    app.processEvents()
    return temporary, app, window


def test_barcode_labels_are_additive_without_moving_stocktake_tab() -> None:
    temporary, app, window = _build_admin_window()
    try:
        catalog_tabs = window.pages.widget(window.page_keys["products"])
        assert isinstance(catalog_tabs, QTabWidget)
        assert isinstance(catalog_tabs.widget(1), StocktakePage)
        assert isinstance(catalog_tabs.widget(2), BarcodeLabelsPage)
        assert catalog_tabs.tabText(2) == "Barcode Labels / 条码标签"
    finally:
        window.close()
        app.processEvents()
        temporary.cleanup()


def test_barcode_label_page_defaults_and_user_copy_count() -> None:
    temporary, app, window = _build_admin_window()
    try:
        catalog_tabs = window.pages.widget(window.page_keys["products"])
        page = catalog_tabs.widget(2)
        assert isinstance(page, BarcodeLabelsPage)
        assert page.profile.currentData() == "50x30"
        assert page.copies.minimum() == 1
        assert page.copies.maximum() == 999
        page.copies.setValue(37)
        assert page.copies.value() == 37
        assert page.table.rowCount() == 1
        assert page.table.item(0, 1).text() == "PVC 电线 4mm"
        assert len(page.table.item(0, 3).text()) == 13
    finally:
        window.close()
        app.processEvents()
        temporary.cleanup()
