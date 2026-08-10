from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from decimal import Decimal
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSize
from PySide6.QtPdf import QPdfDocument
from PySide6.QtWidgets import QApplication

from cnkh_pos.database.bootstrap import bootstrap_database
from cnkh_pos.database.connection import Database
from cnkh_pos.services.auth import AuthService
from cnkh_pos.services.barcode_labels import (
    get_label_profile,
    load_product_label,
    render_product_label_pdf,
)
from cnkh_pos.services.catalog import CatalogService, ProductInput, is_valid_ean13
from cnkh_pos.services.checkout_rounding import RoundedSalesService
from cnkh_pos.services.printing import PrintingService
from cnkh_pos.services.sales import SaleLine

pytestmark = pytest.mark.skipif(
    sys.platform != "win32",
    reason="final printable evidence is intentionally generated on Windows",
)

EVIDENCE_DIR = Path("self-test-artifacts")


def test_final_barcode_label_and_80mm_receipt_evidence() -> None:
    app = QApplication.instance() or QApplication([])
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        database = Database(root / "hardware_pos.db")
        bootstrap_database(database.path, root / "backups")
        with database.transaction() as conn:
            admin_id = AuthService.create_user(
                conn,
                username="print-evidence-admin",
                display_name="Print Evidence Admin",
                password="PrintEvidence123!",
                role="ADMIN",
                permissions={},
                admin_id=None,
            )

        product_id = CatalogService(database).add_product(
            ProductInput(
                name="PVC 电线 4mm",
                sku="PVC-4MM-EVIDENCE",
                cost_cents=180,
                selling_price_cents=1280,
                stock="10",
                unit="pcs",
                location="EVIDENCE",
            ),
            admin_id=admin_id,
        )
        label = load_product_label(database, product_id)
        assert is_valid_ean13(label.barcode)

        label_pdf = render_product_label_pdf(
            label,
            get_label_profile("50x30"),
            4,
            EVIDENCE_DIR / "final-product-label-50x30-4copies.pdf",
        )
        label_pages = len(re.findall(rb"/Type\s*/Page\b", label_pdf.read_bytes()))
        assert label_pages == 4
        assert label_pdf.stat().st_size > 1000

        sale = RoundedSalesService(database).create_sale(
            lines=[
                SaleLine(
                    product_id,
                    Decimal("2"),
                    Decimal("2"),
                    price_override_cents=283,
                )
            ],
            payment_method="CASH",
            paid_cents=670,
            cashier_id=admin_id,
        )
        assert sale.total_cents == 570
        assert sale.change_cents == 100

        printing = PrintingService(database)
        receipt = printing.receipt(sale.sale_id)
        text = printing.render_text(receipt)
        assert "TOTAL" in text and "RM 5.70" in text
        assert "PAID" in text and "RM 6.70" in text
        assert "CHANGE" in text and "RM 1.00" in text

        reportlab_pdf = printing.render_pdf(
            receipt,
            EVIDENCE_DIR / "final-receipt-reportlab-80mm.pdf",
        )
        qt_pdf = EVIDENCE_DIR / "final-receipt-qt-80mm.pdf"
        printing.print_receipt(receipt, output_pdf=qt_pdf)
        app.processEvents()
        assert reportlab_pdf.stat().st_size > 500
        assert qt_pdf.is_file() and qt_pdf.stat().st_size > 500

        # Render the PDF that has passed through the actual Qt/QPrinter path.
        # The old QTextDocument regression collapsed normal glyphs into a narrow
        # column of black rectangles; require receipt content to span the page.
        qt_document = QPdfDocument()
        qt_document.load(str(qt_pdf))
        assert qt_document.pageCount() == 1
        preview = qt_document.render(0, QSize(400, 1485))
        assert not preview.isNull()
        preview_path = EVIDENCE_DIR / "final-receipt-qt-80mm-preview.png"
        assert preview.save(str(preview_path), "PNG")
        qt_document.close()

        from PIL import Image, ImageOps

        with Image.open(preview_path) as preview_image:
            grayscale = preview_image.convert("L")
            ink = ImageOps.invert(grayscale).point(
                lambda value: 255 if value >= 32 else 0
            )
            bbox = ink.getbbox()
            preview_width = grayscale.width
        assert bbox is not None
        qt_ink_width_ratio = (bbox[2] - bbox[0]) / preview_width
        assert qt_ink_width_ratio >= 0.65

        payload = {
            "status": "PASS",
            "label": {
                "profile": "50x30",
                "copies": 4,
                "pages": label_pages,
                "product": label.name,
                "sku": label.sku,
                "barcode": label.barcode,
                "price_cents": label.price_cents,
                "pdf": label_pdf.name,
                "bytes": label_pdf.stat().st_size,
            },
            "receipt": {
                "sale_id": sale.sale_id,
                "receipt_no": sale.receipt_no,
                "total_cents": sale.total_cents,
                "paid_cents": sale.paid_cents,
                "change_cents": sale.change_cents,
                "reportlab_pdf": reportlab_pdf.name,
                "reportlab_bytes": reportlab_pdf.stat().st_size,
                "qt_pdf": qt_pdf.name,
                "qt_bytes": qt_pdf.stat().st_size,
                "qt_ink_width_ratio": round(qt_ink_width_ratio, 4),
            },
        }
        (EVIDENCE_DIR / "final-print-evidence.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
