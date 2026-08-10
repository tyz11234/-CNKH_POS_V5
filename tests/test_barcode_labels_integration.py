from __future__ import annotations

import os
import tempfile
from pathlib import Path

from PySide6.QtCore import QByteArray
from PySide6.QtGui import QImage, QPainter
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication, QSpinBox, QTabWidget

from cnkh_pos.database.bootstrap import bootstrap_database
from cnkh_pos.database.connection import Database
from cnkh_pos.services.auth import AuthService, AuthenticatedUser
from cnkh_pos.services.barcode_labels import (
    _barcode_drawing,
    get_label_profile,
    load_product_label,
)
from cnkh_pos.services.catalog import CatalogService, ProductInput
from cnkh_pos.ui.admin.barcode_labels import BarcodeLabelsPage
from cnkh_pos.ui.admin.window import AdminWindow


def _app() -> QApplication:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication([])


def _database(root: Path) -> tuple[Database, int, AuthenticatedUser, int]:
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
        admin = AuthService.authenticate(
            conn, "admin", "SafePass123!", required_role="ADMIN"
        )
    product_id = CatalogService(database).add_product(
        ProductInput(
            name="PVC Cable Label Test",
            sku="LBL-001",
            barcode=None,
            selling_price_cents=1280,
            stock="10",
            unit="pcs",
        ),
        admin_id=admin_id,
    )
    return database, admin_id, admin, product_id


def test_generated_catalog_barcode_flows_into_label_page() -> None:
    _app()
    with tempfile.TemporaryDirectory() as folder:
        database, _admin_id, _admin, product_id = _database(Path(folder))
        label = load_product_label(database, product_id)
        assert len(label.barcode) == 13
        assert label.barcode.isdigit()

        page = BarcodeLabelsPage(database)
        assert page.table.rowCount() == 1
        assert page.table.item(0, 1).text() == "PVC Cable Label Test"
        assert page.table.item(0, 3).text() == label.barcode
        assert page.profile.currentData() == "40x30"
        copies = page.findChild(QSpinBox)
        assert copies is not None
        assert copies.minimum() == 1
        assert copies.maximum() == 999
        page.deleteLater()


def test_admin_product_area_contains_barcode_labels_tab_without_replacing_existing_tabs() -> None:
    app = _app()
    with tempfile.TemporaryDirectory() as folder:
        database, _admin_id, admin, _product_id = _database(Path(folder))
        window = AdminWindow(database, admin)
        app.processEvents()
        tab_titles = [
            tabs.tabText(index)
            for tabs in window.findChildren(QTabWidget)
            for index in range(tabs.count())
        ]
        assert "Products / 商品" in tab_titles
        assert "Barcode Labels / 条码标签" in tab_titles
        assert "Stocktake / 盘点" in tab_titles
        window.close()
        window.deleteLater()


def test_barcode_svg_is_valid_for_qt_renderer_used_by_windows_print_path() -> None:
    _app()
    drawing = _barcode_drawing("4006381333931", get_label_profile("40x30"))
    renderer = QSvgRenderer(QByteArray(drawing.asString("svg")))
    assert renderer.isValid()
    image = QImage(400, 300, QImage.Format.Format_ARGB32)
    image.fill(0xFFFFFFFF)
    painter = QPainter(image)
    try:
        renderer.render(painter)
    finally:
        painter.end()
    assert not image.isNull()
