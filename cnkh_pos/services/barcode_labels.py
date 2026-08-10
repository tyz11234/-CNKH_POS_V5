from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from reportlab.graphics import renderPDF
from reportlab.graphics.barcode import createBarcodeDrawing
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen.canvas import Canvas

from cnkh_pos.database.connection import Database
from cnkh_pos.services.money import format_myr

LABEL_CJK_FONT = "STSong-Light"


@dataclass(frozen=True, slots=True)
class LabelProfile:
    key: str
    label: str
    width_mm: float
    height_mm: float


@dataclass(frozen=True, slots=True)
class ProductLabel:
    product_id: int
    name: str
    sku: str
    barcode: str
    price_cents: int


LABEL_PROFILES: tuple[LabelProfile, ...] = (
    LabelProfile("40x30", "40 × 30 mm — Standard / 标准", 40.0, 30.0),
    LabelProfile("35x25", "35 × 25 mm — Compact / 小型", 35.0, 25.0),
    LabelProfile("50x30", "50 × 30 mm — Wide / 宽型", 50.0, 30.0),
    LabelProfile("60x40", "60 × 40 mm — Large / 大型", 60.0, 40.0),
)


def get_label_profile(key: str) -> LabelProfile:
    for profile in LABEL_PROFILES:
        if profile.key == key:
            return profile
    raise ValueError(f"unsupported label profile: {key}")


def validate_copy_count(copies: int) -> int:
    copies = int(copies)
    if not 1 <= copies <= 999:
        raise ValueError("label copies must be between 1 and 999")
    return copies


def _ean13_checksum_is_valid(value: str) -> bool:
    if len(value) != 13 or not value.isdigit():
        return False
    payload = [int(character) for character in value[:12]]
    weighted = sum(payload[0::2]) + (3 * sum(payload[1::2]))
    check = (10 - (weighted % 10)) % 10
    return check == int(value[-1])


def barcode_symbology(value: str) -> str:
    normalized = normalize_barcode(value)
    return "EAN13" if _ean13_checksum_is_valid(normalized) else "Code128"


def normalize_barcode(value: object) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError("product has no barcode")
    if len(normalized) > 64:
        raise ValueError("barcode is too long to print reliably on a product label")
    if any(ord(character) < 32 or ord(character) > 126 for character in normalized):
        raise ValueError("barcode must contain printable ASCII characters only")
    return normalized


def load_product_label(database: Database, product_id: int) -> ProductLabel:
    conn = database.connect(readonly=True)
    try:
        row = conn.execute(
            """SELECT id,name,COALESCE(sku,'') sku,COALESCE(barcode,'') barcode,
                      selling_price_cents
               FROM products WHERE id=? AND is_deleted=0""",
            (int(product_id),),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        raise LookupError("product not found")
    barcode = normalize_barcode(row["barcode"])
    return ProductLabel(
        product_id=int(row["id"]),
        name=str(row["name"]),
        sku=str(row["sku"]),
        barcode=barcode,
        price_cents=int(row["selling_price_cents"]),
    )


def list_label_products(
    database: Database, query: str = "", *, limit: int = 200
) -> list[ProductLabel]:
    query = str(query).strip()
    conn = database.connect(readonly=True)
    try:
        if query:
            like = f"%{query}%"
            rows = conn.execute(
                """SELECT id,name,COALESCE(sku,'') sku,COALESCE(barcode,'') barcode,
                          selling_price_cents
                   FROM products
                   WHERE is_deleted=0
                     AND (name LIKE ? OR COALESCE(sku,'') LIKE ? OR COALESCE(barcode,'') LIKE ?)
                   ORDER BY name COLLATE NOCASE LIMIT ?""",
                (like, like, like, int(limit)),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT id,name,COALESCE(sku,'') sku,COALESCE(barcode,'') barcode,
                          selling_price_cents
                   FROM products WHERE is_deleted=0
                   ORDER BY name COLLATE NOCASE LIMIT ?""",
                (int(limit),),
            ).fetchall()
    finally:
        conn.close()
    return [
        ProductLabel(
            product_id=int(row["id"]),
            name=str(row["name"]),
            sku=str(row["sku"]),
            barcode=str(row["barcode"]),
            price_cents=int(row["selling_price_cents"]),
        )
        for row in rows
    ]


def _barcode_drawing(value: str, profile: LabelProfile):
    symbology = barcode_symbology(value)
    bar_height = max(7.0, profile.height_mm * 0.38) * mm
    kwargs: dict[str, object] = {
        "value": value,
        "barHeight": bar_height,
        "humanReadable": False,
    }
    if symbology == "Code128":
        kwargs["barWidth"] = 0.22 * mm
    return createBarcodeDrawing(symbology, **kwargs)


def _register_cjk_font() -> None:
    try:
        pdfmetrics.getFont(LABEL_CJK_FONT)
    except KeyError:
        pdfmetrics.registerFont(UnicodeCIDFont(LABEL_CJK_FONT))


def _fit_pdf_text(
    canvas: Canvas,
    text: str,
    *,
    max_width: float,
    font_name: str,
    start_size: float,
    minimum_size: float,
) -> tuple[str, float]:
    size = start_size
    while size > minimum_size and canvas.stringWidth(text, font_name, size) > max_width:
        size -= 0.25
    if canvas.stringWidth(text, font_name, size) <= max_width:
        return text, size
    candidate = text
    while candidate and canvas.stringWidth(candidate + "…", font_name, size) > max_width:
        candidate = candidate[:-1]
    return (candidate + "…" if candidate else ""), size


def render_product_label_pdf(
    label: ProductLabel,
    profile: LabelProfile,
    copies: int,
    path: Path,
) -> Path:
    copies = validate_copy_count(copies)
    barcode = normalize_barcode(label.barcode)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    _register_cjk_font()

    page_width = profile.width_mm * mm
    page_height = profile.height_mm * mm
    canvas = Canvas(str(path), pagesize=(page_width, page_height))
    margin = 1.5 * mm

    for copy_index in range(copies):
        font_name = LABEL_CJK_FONT if any(ord(char) > 127 for char in label.name) else "Helvetica"
        product_name, name_size = _fit_pdf_text(
            canvas,
            label.name,
            max_width=page_width - (2 * margin),
            font_name=font_name,
            start_size=7.5 if profile.height_mm >= 30 else 6.5,
            minimum_size=5.0,
        )
        canvas.setFont(font_name, name_size)
        canvas.drawCentredString(page_width / 2, page_height - 4.8 * mm, product_name)

        drawing = _barcode_drawing(barcode, profile)
        target_width = page_width - (2 * margin)
        target_height = max(7.0 * mm, page_height - 13.5 * mm)
        scale_x = target_width / float(drawing.width)
        scale_y = target_height / float(drawing.height)
        scale = min(scale_x, scale_y)
        draw_width = float(drawing.width) * scale
        draw_height = float(drawing.height) * scale
        draw_x = (page_width - draw_width) / 2
        draw_y = 7.2 * mm
        canvas.saveState()
        canvas.translate(draw_x, draw_y)
        canvas.scale(scale, scale)
        renderPDF.draw(drawing, canvas, 0, 0)
        canvas.restoreState()

        canvas.setFont("Helvetica", 5.5 if profile.height_mm < 30 else 6.0)
        canvas.drawCentredString(page_width / 2, 4.5 * mm, barcode)
        canvas.setFont("Helvetica-Bold", 6.5 if profile.height_mm < 30 else 7.0)
        canvas.drawRightString(page_width - margin, 1.7 * mm, format_myr(label.price_cents))
        if label.sku:
            canvas.setFont("Helvetica", 5.0)
            canvas.drawString(margin, 1.7 * mm, f"SKU {label.sku}"[:24])

        if copy_index + 1 < copies:
            canvas.showPage()
    canvas.save()
    return path


def print_product_labels(
    label: ProductLabel,
    profile: LabelProfile,
    copies: int,
    *,
    parent=None,
) -> bool:
    """Open the Windows print dialog and print one physical label per page."""
    copies = validate_copy_count(copies)
    barcode = normalize_barcode(label.barcode)

    from PySide6.QtCore import QByteArray, QMarginsF, QRectF, QSizeF, Qt
    from PySide6.QtGui import QFont, QFontMetrics, QPageLayout, QPageSize, QPainter
    from PySide6.QtPrintSupport import QPrintDialog, QPrinter
    from PySide6.QtSvg import QSvgRenderer
    from PySide6.QtWidgets import QDialog

    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    page_size = QPageSize(
        QSizeF(profile.width_mm, profile.height_mm),
        QPageSize.Unit.Millimeter,
        profile.label,
    )
    printer.setPageSize(page_size)
    printer.setPageMargins(QMarginsF(0, 0, 0, 0), QPageLayout.Unit.Millimeter)
    printer.setFullPage(True)
    printer.setCopyCount(1)

    dialog = QPrintDialog(printer, parent)
    dialog.setWindowTitle("Print Product Barcode Labels / 打印商品条码标签")
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return False

    # Reapply the requested media after printer selection. Some drivers reset the
    # page definition while the native dialog is open.
    printer.setPageSize(page_size)
    printer.setPageMargins(QMarginsF(0, 0, 0, 0), QPageLayout.Unit.Millimeter)
    printer.setFullPage(True)
    printer.setCopyCount(1)

    drawing = _barcode_drawing(barcode, profile)
    svg_bytes = drawing.asString("svg")
    renderer = QSvgRenderer(QByteArray(svg_bytes))
    if not renderer.isValid():
        raise RuntimeError("failed to prepare barcode graphic")

    painter = QPainter(printer)
    if not painter.isActive():
        raise RuntimeError("printer could not start a label print job")
    try:
        dpi = max(203, int(printer.resolution()))
        page_rect = printer.pageLayout().fullRectPixels(dpi)
        width = float(page_rect.width())
        height = float(page_rect.height())
        px_per_mm = dpi / 25.4
        margin = 1.4 * px_per_mm

        for copy_index in range(copies):
            painter.save()
            painter.translate(float(page_rect.x()), float(page_rect.y()))
            painter.fillRect(QRectF(0, 0, width, height), Qt.GlobalColor.white)
            painter.setPen(Qt.GlobalColor.black)

            name_font = QFont("Microsoft YaHei UI")
            name_font.setPointSizeF(7.0 if profile.height_mm >= 30 else 6.0)
            name_font.setBold(True)
            painter.setFont(name_font)
            name_metrics = QFontMetrics(name_font)
            name_text = name_metrics.elidedText(
                label.name,
                Qt.TextElideMode.ElideRight,
                max(1, int(width - (2 * margin))),
            )
            name_height = 4.6 * px_per_mm
            painter.drawText(
                QRectF(margin, margin * 0.55, width - (2 * margin), name_height),
                Qt.AlignmentFlag.AlignCenter,
                name_text,
            )

            bottom_reserved = 6.2 * px_per_mm
            barcode_top = 5.1 * px_per_mm
            barcode_rect = QRectF(
                margin,
                barcode_top,
                width - (2 * margin),
                max(1.0, height - barcode_top - bottom_reserved),
            )
            renderer.render(painter, barcode_rect)

            code_font = QFont("Arial")
            code_font.setPointSizeF(5.5 if profile.height_mm < 30 else 6.0)
            painter.setFont(code_font)
            painter.drawText(
                QRectF(margin, height - 5.7 * px_per_mm, width - (2 * margin), 2.8 * px_per_mm),
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
                barcode,
            )

            detail_font = QFont("Arial")
            detail_font.setPointSizeF(5.2 if profile.height_mm < 30 else 5.8)
            painter.setFont(detail_font)
            detail_y = height - 2.8 * px_per_mm
            if label.sku:
                sku_metrics = QFontMetrics(detail_font)
                sku_text = sku_metrics.elidedText(
                    f"SKU {label.sku}",
                    Qt.TextElideMode.ElideRight,
                    max(1, int((width * 0.55) - margin)),
                )
                painter.drawText(
                    QRectF(margin, detail_y, width * 0.55, 2.2 * px_per_mm),
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                    sku_text,
                )

            price_font = QFont("Arial")
            price_font.setPointSizeF(6.2 if profile.height_mm < 30 else 7.0)
            price_font.setBold(True)
            painter.setFont(price_font)
            painter.drawText(
                QRectF(width * 0.48, detail_y, (width * 0.52) - margin, 2.2 * px_per_mm),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                format_myr(label.price_cents),
            )
            painter.restore()

            if copy_index + 1 < copies and not printer.newPage():
                raise RuntimeError("printer could not advance to the next label")
    finally:
        painter.end()
    return True
