from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox

from cnkh_pos.config import RECEIPT_QR_IMAGE_NAME, AppPaths
from cnkh_pos.database.bootstrap import bootstrap_database
from cnkh_pos.database.connection import Database
from cnkh_pos.services.auth import AuthenticatedUser, AuthService
from cnkh_pos.services.printing import (
    WINDOWS_DEFAULT_PRINTER,
    PrintingService,
    Receipt,
    resolve_receipt_qr_path,
)
from cnkh_pos.ui.admin.settings_pages import ReceiptSettingsWidget


def _app() -> QApplication:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication([])


def _tiny_png(path: Path) -> Path:
    path.write_bytes(
        bytes.fromhex(
            "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
            "0000000a49444154789c63000100000500010d0a2db40000000049454e44ae426082"
        )
    )
    return path


@pytest.fixture
def local_paths(monkeypatch, tmp_path):
    local = tmp_path / "localapp"
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    paths = AppPaths.default()
    paths.ensure_directories()
    return paths


@pytest.fixture
def prepared_db(tmp_path):
    db_root = tmp_path / "db"
    db_root.mkdir()
    database = Database(db_root / "hardware_pos.db")
    bootstrap_database(database.path, db_root / "backups")
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
    return database, user


def test_saving_receipt_settings_copies_qr_image(
    prepared_db, local_paths, monkeypatch, tmp_path
):
    _app()
    database, user = prepared_db
    paths = local_paths
    widget = ReceiptSettingsWidget(database, user)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
    index = widget.printer.findData(WINDOWS_DEFAULT_PRINTER)
    assert index >= 0
    widget.printer.setCurrentIndex(index)
    source = _tiny_png(tmp_path / "upload_qr.png")
    widget._qr_source_path = str(source)
    widget.qr_enabled.setChecked(True)
    widget.save()
    target = paths.assets / RECEIPT_QR_IMAGE_NAME
    assert target.is_file()
    assert target.read_bytes() == source.read_bytes()
    conn = database.connect(readonly=True)
    try:
        row = conn.execute(
            "SELECT value_json FROM settings WHERE key='receipt'"
        ).fetchone()
    finally:
        conn.close()
    value = json.loads(row[0])
    assert value["qr_enabled"] is True
    assert value["qr_image"] == RECEIPT_QR_IMAGE_NAME
    widget.close()


def test_render_pdf_includes_configured_qr_image(local_paths, tmp_path):
    paths = local_paths
    qr = _tiny_png(paths.assets / RECEIPT_QR_IMAGE_NAME)
    receipt = Receipt(
        sale_id=1,
        receipt_no="CNKH20260904-001",
        sold_at="2026-09-04T12:00:00+08:00",
        cashier="Cashier",
        payment_method="CASH",
        subtotal_cents=100,
        discount_cents=0,
        total_cents=100,
        paid_cents=100,
        change_cents=0,
        items=(
            {
                "product_name_snapshot": "Nail",
                "quantity_decimal": "1",
                "unit_snapshot": "pcs",
                "unit_price_cents": 100,
                "discount_cents": 0,
                "subtotal_cents": 100,
            },
        ),
        settings={
            "store_name": "CNKH Hardware",
            "address": "",
            "phone": "",
            "footer": "Thank you",
            "notes": "",
            "qr_enabled": True,
            "qr_image": RECEIPT_QR_IMAGE_NAME,
        },
    )
    assert resolve_receipt_qr_path(receipt.settings, paths=paths) == qr
    output = PrintingService(database=None).render_pdf(
        receipt, tmp_path / "with-qr.pdf"
    )
    assert output.is_file()
    assert output.stat().st_size > 400
    pdf_bytes = output.read_bytes()
    assert b"/XObject" in pdf_bytes or b"Image" in pdf_bytes or b"IDAT" in pdf_bytes
    text = PrintingService.render_text(receipt)
    assert "[QR image attached]" in text
