"""WhatsApp e-receipt helpers for CNKH POS (PC).

Primary payload is the **same PDF layout** as thermal/print
(``PrintingService.render_pdf`` / ``render_text``). Temp file only; deleted
after share attempt.
"""

from __future__ import annotations

import re
import tempfile
import time
import webbrowser
from pathlib import Path
from urllib.parse import quote

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication

from cnkh_pos.services.printing import PrintingService, Receipt

STORE_NAME = "CNKH Hardware"


def normalize_my_phone(raw: str) -> str:
    """Strip spaces/dashes; MY local 0… → 60…. Digits only or ''."""
    digits = re.sub(r"[^\d+]", "", (raw or "").strip())
    if digits.startswith("+"):
        digits = digits[1:]
    digits = re.sub(r"\D", "", digits)
    if not digits:
        return ""
    if digits.startswith("0") and len(digits) >= 9:
        digits = "60" + digits[1:]
    return digits


def short_whatsapp_caption(receipt: Receipt) -> str:
    """Brief caption sent with PDF (not a substitute for the receipt)."""
    store = str(receipt.settings.get("store_name") or STORE_NAME)
    return (
        f"{store}\n"
        f"电子收据 PDF / E-Receipt PDF\n"
        f"单号 / No: {receipt.receipt_no}\n"
        f"请查看附件收据 / Please see attached receipt PDF."
    )


def whatsapp_url(phone_raw: str, text: str) -> str:
    digits = normalize_my_phone(phone_raw)
    return f"https://wa.me/{digits}?text={quote(text)}"


def write_contact_vcf(name: str, phone_raw: str) -> Path | None:
    """Best-effort Windows/desktop contact via temporary .vcf."""
    digits = normalize_my_phone(phone_raw)
    if not digits:
        return None
    display = (name or "").strip() or digits
    local = digits
    if digits.startswith("60") and len(digits) >= 10:
        local = "0" + digits[2:]
    body = (
        "BEGIN:VCARD\n"
        "VERSION:3.0\n"
        f"FN:{display}\n"
        f"TEL;TYPE=CELL:{local}\n"
        "END:VCARD\n"
    )
    path = Path(tempfile.gettempdir()) / f"cnkh_contact_{digits}.vcf"
    path.write_text(body, encoding="utf-8")
    try:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
    except Exception:
        webbrowser.open(path.as_uri())
    return path


def customer_phone_for_sale(database, sale_id: int) -> tuple[str, str]:
    conn = database.connect(readonly=True)
    try:
        row = conn.execute(
            """SELECT c.name, c.phone FROM sales s
               LEFT JOIN customers c ON c.id = s.customer_id
               WHERE s.id=?""",
            (sale_id,),
        ).fetchone()
        if row is None:
            return "", ""
        return str(row["name"] or ""), str(row["phone"] or "")
    finally:
        conn.close()


def render_print_receipt_pdf(database, sale_id: int, path: Path) -> tuple[Receipt, Path]:
    """Write the official print-layout PDF to ``path``."""
    printing = PrintingService(database)
    receipt = printing.receipt(sale_id)
    printing.render_pdf(receipt, path)
    return receipt, path


def send_e_receipt_pdf(
    database,
    sale_id: int,
    *,
    phone_raw: str,
    customer_name: str = "",
) -> tuple[bool, str]:
    """Generate print PDF in temp → open/share → open WhatsApp caption → delete.

    Returns (ok, message).
    """
    digits = normalize_my_phone(phone_raw)
    if not digits:
        return False, "invalid phone"

    tmp_dir = Path(tempfile.mkdtemp(prefix="cnkh_ereceipt_"))
    pdf_path = tmp_dir / f"CNKH_Receipt_{sale_id}.pdf"
    try:
        receipt, pdf_path = render_print_receipt_pdf(database, sale_id, pdf_path)
        caption = short_whatsapp_caption(receipt)
        # Also expose full print text as secondary (clipboard) for staff
        print_text = PrintingService.render_text(receipt)

        # 1) Open PDF so user can attach / share via WhatsApp Desktop
        opened_pdf = bool(QDesktopServices.openUrl(QUrl.fromLocalFile(str(pdf_path))))
        # Copy print text to clipboard if possible
        try:
            clipboard = QApplication.clipboard()
            if clipboard is not None:
                clipboard.setText(print_text)
        except Exception:
            pass

        # 2) Open WhatsApp chat with short caption (PDF must be attached manually
        #    on Desktop/Web — wa.me cannot attach files)
        url = whatsapp_url(digits, caption)
        try:
            QDesktopServices.openUrl(QUrl(url))
        except Exception:
            webbrowser.open(url)

        # Brief pause so OS / WhatsApp can read the file before cleanup
        time.sleep(1.2)
        msg = (
            "已生成打印版收据 PDF（临时文件）并打开 WhatsApp。\n"
            "请在 WhatsApp 中附加刚打开的 PDF 发送给客户。\n"
            "完整小票文本已复制到剪贴板（可选）。\n"
            f"PDF opened={opened_pdf}"
        )
        if customer_name:
            msg = f"客户 / Customer: {customer_name}\n" + msg
        return True, msg
    finally:
        # Mandatory cleanup — never leave junk PDFs
        try:
            if pdf_path.exists():
                pdf_path.unlink()
        except Exception:
            pass
        try:
            # remove empty temp dir (ignore if still locked briefly)
            if tmp_dir.exists():
                for child in tmp_dir.iterdir():
                    try:
                        child.unlink()
                    except Exception:
                        pass
                tmp_dir.rmdir()
        except Exception:
            pass


# Back-compat helpers used by unit tests / older call sites
def build_e_receipt_text(**kwargs) -> str:
    """Deprecated short text — prefer PrintingService.render_text.

    Kept for unit tests of phone normalize / caption builders.
    """
    from cnkh_pos.services.money import format_myr  # local

    receipt_no = kwargs["receipt_no"]
    sold_at = kwargs["sold_at"]
    payment_method = kwargs["payment_method"]
    total_cents = int(kwargs["total_cents"])
    lines = kwargs.get("lines") or []
    store_name = kwargs.get("store_name") or STORE_NAME
    parts = [
        store_name,
        f"Receipt: {receipt_no}",
        f"Date: {sold_at}",
        "-" * 40,
    ]
    for line in lines:
        name = str(line.get("name") or line.get("product_name_snapshot") or "Item")
        qty = line.get("qty") or line.get("quantity_decimal") or 1
        unit = int(line.get("unit_price_cents") or 0)
        sub = int(line.get("subtotal_cents") or line.get("line_total_cents") or unit)
        parts.append(name)
        parts.append(f"  {qty} x {format_myr(unit)}  {format_myr(sub)}")
    parts.extend(
        [
            "-" * 40,
            f"TOTAL {format_myr(total_cents)}",
            f"Payment: {payment_method}",
        ]
    )
    return "\n".join(parts)


def e_receipt_text_for_sale(database, sale_id: int) -> tuple[str, str, str]:
    """Return (print_text, customer_name, customer_phone)."""
    printing = PrintingService(database)
    receipt = printing.receipt(sale_id)
    name, phone = customer_phone_for_sale(database, sale_id)
    return PrintingService.render_text(receipt), name, phone


def open_whatsapp(phone_raw: str, text: str) -> bool:
    digits = normalize_my_phone(phone_raw)
    if not digits:
        return False
    url = whatsapp_url(digits, text)
    try:
        return bool(QDesktopServices.openUrl(QUrl(url)))
    except Exception:
        webbrowser.open(url)
        return True
