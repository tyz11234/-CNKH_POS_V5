from __future__ import annotations

import html
import json
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen.canvas import Canvas

from cnkh_pos.config import RECEIPT_QR_IMAGE_NAME, AppPaths
from cnkh_pos.database.connection import Database
from cnkh_pos.services.money import format_myr

WINDOWS_DEFAULT_PRINTER = "__WINDOWS_DEFAULT__"
RECEIPT_TEXT_WIDTH = 40
RECEIPT_PDF_CJK_FONT = "STSong-Light"
RECEIPT_QR_SIZE_MM = 30.0


def receipt_qr_enabled(settings: dict[str, object]) -> bool:
    value = settings.get("qr_enabled", False)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def resolve_receipt_qr_path(
    settings: dict[str, object], *, paths: AppPaths | None = None
) -> Path | None:
    """Return an existing QR image path when enabled in receipt settings."""
    if not receipt_qr_enabled(settings):
        return None
    configured = str(settings.get("qr_image", "") or "").strip()
    app_paths = paths or AppPaths.default()
    candidates: list[Path] = []
    if configured:
        candidate = Path(configured)
        if candidate.is_absolute():
            candidates.append(candidate)
        else:
            candidates.append(app_paths.assets / candidate.name)
            candidates.append(app_paths.data / candidate.name)
    candidates.append(app_paths.assets / RECEIPT_QR_IMAGE_NAME)
    candidates.append(app_paths.receipt_qr_image)
    seen: set[Path] = set()
    for path in candidates:
        resolved = path if path.is_absolute() else path
        key = resolved.resolve() if resolved.exists() else resolved
        if key in seen:
            continue
        seen.add(key)
        if resolved.is_file() and resolved.stat().st_size > 0:
            return resolved
    return None


def _character_width(character: str) -> int:
    return 2 if unicodedata.east_asian_width(character) in {"W", "F"} else 1


def _display_width(value: object) -> int:
    return sum(_character_width(character) for character in str(value))


def _truncate_display(value: object, width: int) -> str:
    result: list[str] = []
    used = 0
    for character in str(value):
        character_width = _character_width(character)
        if used + character_width > width:
            break
        result.append(character)
        used += character_width
    return "".join(result)


def _truncate_display_tail(value: object, width: int) -> str:
    result: list[str] = []
    used = 0
    for character in reversed(str(value)):
        character_width = _character_width(character)
        if used + character_width > width:
            break
        result.append(character)
        used += character_width
    return "".join(reversed(result))


def _center_display(value: object, width: int = RECEIPT_TEXT_WIDTH) -> str:
    text = _truncate_display(str(value).strip(), width)
    remaining = max(0, width - _display_width(text))
    left = remaining // 2
    return (" " * left) + text + (" " * (remaining - left))


def _wrap_display(value: object, width: int = RECEIPT_TEXT_WIDTH) -> list[str]:
    normalized = str(value).replace("\r\n", "\n").replace("\r", "\n")
    wrapped: list[str] = []
    for logical_line in normalized.split("\n"):
        text = logical_line.strip()
        if not text:
            continue
        chunk: list[str] = []
        used = 0
        for character in text:
            character_width = _character_width(character)
            if chunk and used + character_width > width:
                wrapped.append("".join(chunk).rstrip())
                chunk = []
                used = 0
            chunk.append(character)
            used += character_width
        if chunk:
            wrapped.append("".join(chunk).rstrip())
    return wrapped


def _centered_setting_lines(
    value: object, width: int = RECEIPT_TEXT_WIDTH
) -> list[str]:
    return [_center_display(line, width) for line in _wrap_display(value, width)]


def resolve_printer_target(
    settings: dict[str, object],
    *,
    available_printers: set[str],
    default_printer_available: bool,
) -> str | None:
    """Return a named printer or None for an explicitly selected Windows default."""
    mode = str(settings.get("printer_mode", "")).strip().upper()
    configured = str(settings.get("printer_name", "")).strip()
    if not mode and configured:
        mode = "NAMED"  # Backward-compatible with an older saved named printer.
    if mode == "DEFAULT":
        if not default_printer_available:
            raise RuntimeError("Windows has no default printer")
        return None
    if mode == "NAMED":
        if not configured:
            raise RuntimeError("no printer has been selected")
        if configured not in available_printers:
            raise RuntimeError(f"configured printer is unavailable: {configured}")
        return configured
    raise RuntimeError(
        "no printer has been selected; choose Windows default or a named printer in Admin Settings"
    )


def _receipt_pair(left: object, right: object, *, width: int = RECEIPT_TEXT_WIDTH) -> str:
    """Fit a left label/detail and right value into one plain-text receipt line."""
    right_text = str(right)
    right_width = _display_width(right_text)
    if right_width >= width:
        return _truncate_display_tail(right_text, width)
    left_width = width - right_width
    left_text = _truncate_display(left, left_width)
    padding = max(0, left_width - _display_width(left_text))
    return f"{left_text}{' ' * padding}{right_text}"


@dataclass(frozen=True, slots=True)
class Receipt:
    sale_id: int
    receipt_no: str
    sold_at: str
    cashier: str
    payment_method: str
    subtotal_cents: int
    discount_cents: int
    total_cents: int
    paid_cents: int
    change_cents: int
    items: tuple[dict[str, object], ...]
    settings: dict[str, object]


class PrintingService:
    def __init__(self, database: Database):
        self.database = database

    def latest_receipt(self) -> Receipt:
        conn = self.database.connect(readonly=True)
        try:
            row = conn.execute(
                "SELECT id FROM sales WHERE is_deleted=0 ORDER BY sold_at DESC,id DESC LIMIT 1"
            ).fetchone()
            if row is None:
                raise LookupError("no completed sale to reprint")
            return self.receipt(int(row["id"]), conn=conn)
        finally:
            conn.close()

    def receipt(self, sale_id: int, *, conn=None) -> Receipt:
        owned = conn is None
        conn = conn or self.database.connect(readonly=True)
        try:
            sale = conn.execute(
                """SELECT s.*,COALESCE(u.display_name,'') cashier FROM sales s
                   LEFT JOIN users u ON u.id=s.cashier_id WHERE s.id=? AND s.is_deleted=0""",
                (sale_id,),
            ).fetchone()
            if sale is None:
                raise LookupError("sale not found")
            items = conn.execute(
                """SELECT product_name_snapshot,sku_snapshot,barcode_snapshot,unit_snapshot,
                   quantity_decimal,unit_price_cents,discount_cents,subtotal_cents
                   FROM sale_items WHERE sale_id=? ORDER BY id""",
                (sale_id,),
            ).fetchall()
            setting = conn.execute(
                "SELECT value_json FROM settings WHERE key='receipt'"
            ).fetchone()
            settings = (
                json.loads(setting[0])
                if setting
                else {
                    "store_name": "CNKH Hardware",
                    "address": "",
                    "phone": "",
                    "footer": "Thank you / 谢谢光临",
                    "notes": "",
                    "printer_name": "",
                    "printer_mode": "UNCONFIGURED",
                }
            )
            return Receipt(
                sale_id=int(sale["id"]),
                receipt_no=str(sale["receipt_no"]),
                sold_at=str(sale["sold_at"]),
                cashier=str(sale["cashier"]),
                payment_method=str(sale["payment_method"]),
                subtotal_cents=int(sale["subtotal_cents"]),
                discount_cents=int(sale["discount_cents"]),
                total_cents=int(sale["total_cents"]),
                paid_cents=int(sale["paid_cents"]),
                change_cents=int(sale["change_cents"]),
                items=tuple(dict(row) for row in items),
                settings=settings,
            )
        finally:
            if owned:
                conn.close()

    @staticmethod
    def render_text(receipt: Receipt) -> str:
        width = RECEIPT_TEXT_WIDTH
        lines: list[str] = []
        lines.extend(
            _centered_setting_lines(
                receipt.settings.get("store_name", "CNKH Hardware"), width
            )
        )
        lines.extend(_centered_setting_lines(receipt.settings.get("address", ""), width))
        lines.extend(_centered_setting_lines(receipt.settings.get("phone", ""), width))
        lines.extend(
            [
                "-" * width,
                _truncate_display(f"Receipt: {receipt.receipt_no}", width),
                _truncate_display(f"Date: {receipt.sold_at}", width),
                _truncate_display(f"Cashier: {receipt.cashier}", width),
                "-" * width,
            ]
        )
        for item in receipt.items:
            lines.append(_truncate_display(item["product_name_snapshot"], width))
            qty = item["quantity_decimal"]
            detail = f"  {qty} {item['unit_snapshot']} x {format_myr(int(item['unit_price_cents']))}"
            lines.append(
                _receipt_pair(detail, format_myr(int(item["subtotal_cents"])), width=width)
            )
            if int(item["discount_cents"]):
                lines.append(
                    _receipt_pair(
                        "  Discount / 折扣",
                        format_myr(-int(item["discount_cents"])),
                        width=width,
                    )
                )
        lines.extend(
            [
                "-" * width,
                _receipt_pair("SUBTOTAL", format_myr(receipt.subtotal_cents), width=width),
                _receipt_pair("DISCOUNT", format_myr(-receipt.discount_cents), width=width),
                _receipt_pair("TOTAL", format_myr(receipt.total_cents), width=width),
                _receipt_pair("PAID", format_myr(receipt.paid_cents), width=width),
                _receipt_pair("CHANGE", format_myr(receipt.change_cents), width=width),
                _truncate_display(f"Payment: {receipt.payment_method}", width),
                "-" * width,
            ]
        )
        lines.extend(_centered_setting_lines(receipt.settings.get("footer", ""), width))
        lines.extend(_centered_setting_lines(receipt.settings.get("notes", ""), width))
        if resolve_receipt_qr_path(receipt.settings) is not None:
            lines.append(_center_display("[QR image attached]", width))
        return "\n".join(line for line in lines if line.strip())

    @staticmethod
    def render_html(receipt: Receipt) -> str:
        """Render a width-safe thermal receipt for Qt printing.

        Monetary values live in a dedicated right-aligned table column rather than
        being positioned with spaces. This prevents clipping when a printer driver
        reports a narrower printable area than the nominal 80 mm page width.
        """

        def esc(value: object) -> str:
            return html.escape(str(value), quote=True)

        def pair(left: object, right: object, *, css_class: str = "") -> str:
            class_attr = f' class="{css_class}"' if css_class else ""
            return (
                f'<table{class_attr}><tr><td class="left">{esc(left)}</td>'
                f'<td class="amount">{esc(right)}</td></tr></table>'
            )

        sections = [
            '<div class="center store">'
            + esc(receipt.settings.get("store_name", "CNKH Hardware"))
            + "</div>",
        ]
        address = str(receipt.settings.get("address", "")).strip()
        phone = str(receipt.settings.get("phone", "")).strip()
        if address:
            sections.append(f'<div class="center">{esc(address)}</div>')
        if phone:
            sections.append(f'<div class="center">{esc(phone)}</div>')
        sections.extend(
            [
                '<div class="rule"></div>',
                f'<div>Receipt: {esc(receipt.receipt_no)}</div>',
                f'<div>Date: {esc(receipt.sold_at)}</div>',
                f'<div>Cashier: {esc(receipt.cashier)}</div>',
                '<div class="rule"></div>',
            ]
        )
        for item in receipt.items:
            sections.append(
                f'<div class="product">{esc(item["product_name_snapshot"])}</div>'
            )
            qty = item["quantity_decimal"]
            detail = (
                f"{qty} {item['unit_snapshot']} x "
                f"{format_myr(int(item['unit_price_cents']))}"
            )
            sections.append(
                pair(detail, format_myr(int(item["subtotal_cents"])), css_class="item")
            )
            if int(item["discount_cents"]):
                sections.append(
                    pair(
                        "Discount / 折扣",
                        format_myr(-int(item["discount_cents"])),
                        css_class="item",
                    )
                )
        sections.extend(
            [
                '<div class="rule"></div>',
                pair("SUBTOTAL", format_myr(receipt.subtotal_cents), css_class="summary"),
                pair("DISCOUNT", format_myr(-receipt.discount_cents), css_class="summary"),
                pair("TOTAL", format_myr(receipt.total_cents), css_class="summary total"),
                pair("PAID", format_myr(receipt.paid_cents), css_class="summary"),
                pair("CHANGE", format_myr(receipt.change_cents), css_class="summary"),
                f'<div class="payment">Payment: {esc(receipt.payment_method)}</div>',
                '<div class="rule"></div>',
            ]
        )
        footer = str(receipt.settings.get("footer", "")).strip()
        notes = str(receipt.settings.get("notes", "")).strip()
        if footer:
            sections.append(f'<div class="center">{esc(footer)}</div>')
        if notes:
            sections.append(f'<div class="center">{esc(notes)}</div>')
        qr_path = resolve_receipt_qr_path(receipt.settings)
        if qr_path is not None:
            uri = qr_path.resolve().as_uri()
            sections.append(
                f'<div class="center qr"><img src="{esc(uri)}" '
                f'alt="Payment QR" style="width:30mm;height:30mm;"/></div>'
            )

        body = "".join(sections)
        return f"""
<html><head><style>
html, body {{ margin: 0; padding: 0; }}
body {{ font-family: Consolas, 'Microsoft YaHei UI', 'Microsoft YaHei', SimSun, 'Courier New', monospace; font-size: 7.5pt; color: #000; }}
.center {{ text-align: center; overflow-wrap: anywhere; }}
.store {{ font-weight: 700; margin-bottom: 1mm; }}
.rule {{ border-top: 1px dashed #000; margin: 1.5mm 0; height: 0; }}
.product {{ margin-top: 0.8mm; overflow-wrap: anywhere; }}
table {{ width: 100%; border-collapse: collapse; table-layout: fixed; margin: 0; padding: 0; }}
td {{ margin: 0; padding: 0; vertical-align: top; }}
td.left {{ width: 68%; overflow-wrap: anywhere; }}
td.amount {{ width: 32%; text-align: right; white-space: nowrap; }}
table.summary td.left {{ font-weight: 600; }}
table.total td {{ font-weight: 800; }}
.payment {{ margin-top: 0.8mm; }}
</style></head><body>{body}</body></html>
""".strip()

    def render_pdf(self, receipt: Receipt, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        text = self.render_text(receipt)
        # Drop the textual QR marker from PDF body; the image is drawn instead.
        pdf_lines = [
            line
            for line in text.splitlines()
            if "[QR image attached]" not in line
        ]
        qr_path = resolve_receipt_qr_path(receipt.settings)
        line_height = 4.2 * mm
        qr_block = (RECEIPT_QR_SIZE_MM + 8) * mm if qr_path is not None else 0
        height = max(
            120 * mm, (len(pdf_lines) + 5) * line_height + qr_block
        )
        try:
            pdfmetrics.getFont(RECEIPT_PDF_CJK_FONT)
        except KeyError:
            pdfmetrics.registerFont(UnicodeCIDFont(RECEIPT_PDF_CJK_FONT))
        canvas = Canvas(str(path), pagesize=(80 * mm, height))
        y = height - 8 * mm
        for line in pdf_lines:
            font_name = (
                RECEIPT_PDF_CJK_FONT
                if any(ord(character) > 127 for character in line)
                else "Courier"
            )
            canvas.setFont(font_name, 7.5)
            canvas.drawString(4 * mm, y, line)
            y -= line_height
        if qr_path is not None:
            size = RECEIPT_QR_SIZE_MM * mm
            x = (80 * mm - size) / 2.0
            y = max(4 * mm, y - size)
            canvas.drawImage(
                str(qr_path),
                x,
                y,
                width=size,
                height=size,
                preserveAspectRatio=True,
                mask="auto",
            )
        canvas.save()
        return path

    def print_receipt(
        self, receipt: Receipt, *, output_pdf: Path | None = None
    ) -> None:
        """Print the verified 80mm PDF layout through Qt at thermal-printer DPI."""
        import tempfile

        from PySide6.QtCore import (
            QBuffer,
            QByteArray,
            QIODevice,
            QMarginsF,
            QRectF,
            QSize,
            QSizeF,
            Qt,
        )
        from PySide6.QtGui import QPageLayout, QPageSize, QPainter
        from PySide6.QtPdf import QPdfDocument
        from PySide6.QtPrintSupport import QPrinter, QPrinterInfo

        target_pdf = Path(output_pdf) if output_pdf is not None else None
        with tempfile.TemporaryDirectory() as folder:
            source_pdf = Path(folder) / "receipt-layout.pdf"
            self.render_pdf(receipt, source_pdf)

            # Load from memory rather than asking QPdfDocument to keep the Windows
            # file open. This prevents the PDF engine from blocking temp cleanup.
            source_data = QByteArray(source_pdf.read_bytes())
            source_pdf.unlink()
            buffer = QBuffer()
            buffer.setData(source_data)
            if not buffer.open(QIODevice.OpenModeFlag.ReadOnly):
                raise RuntimeError("receipt PDF buffer could not be opened")
            document = QPdfDocument()
            document.load(buffer)
            if document.pageCount() != 1:
                document.close()
                buffer.close()
                raise RuntimeError("receipt PDF could not be loaded for printing")
            page_points = document.pagePointSize(0)
            if page_points.width() <= 0 or page_points.height() <= 0:
                document.close()
                buffer.close()
                raise RuntimeError("receipt PDF reported an invalid page size")

            printer = QPrinter(QPrinter.PrinterMode.HighResolution)
            if target_pdf is not None:
                target_pdf.parent.mkdir(parents=True, exist_ok=True)
                printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
                printer.setOutputFileName(str(target_pdf))
            else:
                available = set(QPrinterInfo.availablePrinterNames())
                target = resolve_printer_target(
                    receipt.settings,
                    available_printers=available,
                    default_printer_available=not QPrinterInfo.defaultPrinter().isNull(),
                )
                if target is not None:
                    printer.setPrinterName(target)

            # 203 dpi is the dominant resolution for retail 80mm thermal printers.
            # Rasterizing the already-verified PDF avoids the QTextDocument/Windows
            # font-path corruption that can turn receipt glyphs into black blocks.
            printer.setResolution(203)
            source_height_mm = float(page_points.height()) * 25.4 / 72.0
            # Thermal receipt rolls should advance only for rendered content;
            # do not force an A4-length 297 mm page that wastes blank paper.
            paper_height_mm = source_height_mm
            printer.setPageSize(
                QPageSize(
                    QSizeF(80.0, paper_height_mm),
                    QPageSize.Unit.Millimeter,
                    "80mm Receipt",
                )
            )
            printer.setPageMargins(
                QMarginsF(0, 0, 0, 0), QPageLayout.Unit.Millimeter
            )
            printer.setFullPage(True)

            dpi = max(203, int(printer.resolution()))
            render_size = QSize(
                max(1, int(round(float(page_points.width()) * dpi / 72.0))),
                max(1, int(round(float(page_points.height()) * dpi / 72.0))),
            )
            image = document.render(0, render_size)
            if image.isNull():
                document.close()
                buffer.close()
                raise RuntimeError("receipt PDF could not be rasterized for printing")

            painter = QPainter(printer)
            if not painter.isActive():
                document.close()
                buffer.close()
                raise RuntimeError("printer could not start an 80mm receipt print job")
            try:
                page_rect = printer.pageLayout().fullRectPixels(dpi)
                painter.fillRect(QRectF(page_rect), Qt.GlobalColor.white)
                scale = min(
                    float(page_rect.width()) / float(image.width()),
                    float(page_rect.height()) / float(image.height()),
                )
                draw_width = float(image.width()) * scale
                draw_height = float(image.height()) * scale
                target_rect = QRectF(
                    float(page_rect.x()) + (float(page_rect.width()) - draw_width) / 2.0,
                    float(page_rect.y()),
                    draw_width,
                    draw_height,
                )
                painter.drawImage(target_rect, image)
            finally:
                painter.end()
                document.close()
                buffer.close()

            if printer.printerState() == QPrinter.PrinterState.Error:
                raise RuntimeError("printer reported an error while sending the receipt")
            if target_pdf is not None and (
                not target_pdf.is_file() or target_pdf.stat().st_size == 0
            ):
                raise RuntimeError("PDF receipt output was not created")
