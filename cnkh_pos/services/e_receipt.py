"""WhatsApp e-receipt helpers for CNKH POS (PC).

Primary payload is the **same PDF layout** as thermal/print
(``PrintingService.render_pdf`` / ``render_text``).

PDFs stay in private EReceiptCache for 7 days then purge.
Do not auto-open wa.me (cannot attach files).
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
import time
import webbrowser
from pathlib import Path
from urllib.parse import quote

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication

from cnkh_pos.config import AppPaths
from cnkh_pos.services.printing import PrintingService, Receipt

STORE_NAME = "黄金发宝号"


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



ERECEIPT_TTL_DAYS = 7


def e_receipt_cache_dir() -> Path:
    paths = AppPaths.default()
    paths.ensure_directories()
    d = paths.ereceipt_cache
    d.mkdir(parents=True, exist_ok=True)
    return d


def purge_e_receipt_cache(*, ttl_days: int = ERECEIPT_TTL_DAYS) -> int:
    """Delete cached PDFs older than ttl_days. Returns deleted count."""
    d = e_receipt_cache_dir()
    cutoff = time.time() - ttl_days * 86400
    n = 0
    for child in d.glob("*.pdf"):
        try:
            if child.stat().st_mtime < cutoff:
                child.unlink(missing_ok=True)
                n += 1
        except OSError:
            pass
    return n


def clear_e_receipt_cache() -> int:
    """Delete all cached e-receipt PDFs. Returns deleted count."""
    d = e_receipt_cache_dir()
    n = 0
    for child in d.glob("*.pdf"):
        try:
            child.unlink(missing_ok=True)
            n += 1
        except OSError:
            pass
    return n


def count_e_receipt_cache() -> int:
    return sum(1 for _ in e_receipt_cache_dir().glob("*.pdf"))


def _reveal_in_file_manager(path: Path) -> bool:
    """Open file manager with the PDF selected (Windows/Linux/macOS)."""
    path = path.resolve()
    try:
        if os.name == "nt":
            subprocess.Popen(["explorer", f"/select,{path}"])
            return True
        if path.parent.exists():
            return bool(QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent))))
    except Exception:
        pass
    return bool(QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))))


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
    """Write print PDF into private 7-day cache and open it for OS share.

    Does not auto-open wa.me (cannot attach PDF). Returns (ok, message).
    """
    digits = normalize_my_phone(phone_raw)
    if not digits:
        return False, "invalid phone"

    purged = purge_e_receipt_cache()
    cache = e_receipt_cache_dir()
    pdf_path = cache / f"CNKH_Receipt_{sale_id}.pdf"
    receipt, pdf_path = render_print_receipt_pdf(database, sale_id, pdf_path)
    caption = short_whatsapp_caption(receipt)
    print_text = PrintingService.render_text(receipt)

    try:
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(caption + "\n\n---\n" + print_text)
    except Exception:
        pass

    opened_pdf = bool(QDesktopServices.openUrl(QUrl.fromLocalFile(str(pdf_path))))
    revealed = _reveal_in_file_manager(pdf_path)

    msg = (
        "已生成打印版收据 PDF，并放入私有缓存（保留 7 天，到期自动删）。\n"
        "请用系统分享 / 拖到 WhatsApp 发送给客户（不要依赖 wa.me，无法带附件）。\n"
        "说明文字+小票文本已复制到剪贴板。\n"
        f"路径: {pdf_path}\n"
        f"PDF opened={opened_pdf} folder={revealed} purged={purged}"
    )
    if customer_name:
        msg = f"客户 / Customer: {customer_name}\n" + msg
    return True, msg



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
