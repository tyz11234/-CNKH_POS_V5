from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas

from cnkh_pos.database.connection import Database
from cnkh_pos.services.money import format_myr

WINDOWS_DEFAULT_PRINTER = "__WINDOWS_DEFAULT__"


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
        width = 42
        lines = [
            str(receipt.settings.get("store_name", "CNKH Hardware")).center(width),
            str(receipt.settings.get("address", "")).center(width),
            str(receipt.settings.get("phone", "")).center(width),
            "-" * width,
            f"Receipt: {receipt.receipt_no}",
            f"Date: {receipt.sold_at}",
            f"Cashier: {receipt.cashier}",
            "-" * width,
        ]
        for item in receipt.items:
            lines.append(str(item["product_name_snapshot"])[:width])
            qty = item["quantity_decimal"]
            detail = f"  {qty} {item['unit_snapshot']} x {format_myr(int(item['unit_price_cents']))}"
            lines.append(f"{detail:<30}{format_myr(int(item['subtotal_cents'])):>12}")
            if int(item["discount_cents"]):
                lines.append(
                    f"  Discount / 折扣{format_myr(-int(item['discount_cents'])):>25}"
                )
        lines.extend(
            [
                "-" * width,
                f"SUBTOTAL{format_myr(receipt.subtotal_cents):>34}",
                f"DISCOUNT{format_myr(-receipt.discount_cents):>34}",
                f"TOTAL{format_myr(receipt.total_cents):>37}",
                f"PAID{format_myr(receipt.paid_cents):>38}",
                f"CHANGE{format_myr(receipt.change_cents):>36}",
                f"Payment: {receipt.payment_method}",
                "-" * width,
                str(receipt.settings.get("footer", "")).center(width),
                str(receipt.settings.get("notes", "")).center(width),
            ]
        )
        return "\n".join(line for line in lines if line.strip())

    def render_pdf(self, receipt: Receipt, path: Path) -> Path:
        text = self.render_text(receipt)
        line_height = 4.2 * mm
        height = max(120 * mm, (text.count("\n") + 5) * line_height)
        canvas = Canvas(str(path), pagesize=(80 * mm, height))
        canvas.setFont("Courier", 7.5)
        y = height - 8 * mm
        for line in text.splitlines():
            canvas.drawString(4 * mm, y, line)
            y -= line_height
        canvas.save()
        return path

    def print_receipt(
        self, receipt: Receipt, *, output_pdf: Path | None = None
    ) -> None:
        """Print through Qt. Tests can select PDF output without requiring hardware."""
        from PySide6.QtCore import QSizeF
        from PySide6.QtGui import QPageSize, QTextDocument
        from PySide6.QtPrintSupport import QPrinter, QPrinterInfo

        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        printer.setPageSize(
            QPageSize(QSizeF(80, 297), QPageSize.Unit.Millimeter, "80mm")
        )
        if output_pdf is not None:
            printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
            printer.setOutputFileName(str(output_pdf))
        else:
            available = set(QPrinterInfo.availablePrinterNames())
            target = resolve_printer_target(
                receipt.settings,
                available_printers=available,
                default_printer_available=not QPrinterInfo.defaultPrinter().isNull(),
            )
            if target is not None:
                printer.setPrinterName(target)
        document = QTextDocument()
        escaped = (
            self.render_text(receipt)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )
        document.setHtml(
            f"<pre style='font-family:Consolas;font-size:8pt'>{escaped}</pre>"
        )
        document.print_(printer)
