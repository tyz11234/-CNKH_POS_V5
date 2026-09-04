"""Prompt + share print-layout PDF e-receipt via WhatsApp (PC)."""

from __future__ import annotations

from PySide6.QtWidgets import QInputDialog, QMessageBox

from cnkh_pos.services.e_receipt import (
    normalize_my_phone,
    send_e_receipt_pdf,
    write_contact_vcf,
    customer_phone_for_sale,
)


def send_e_receipt_for_sale(parent, database, sale_id: int) -> None:
    name, phone = customer_phone_for_sale(database, sale_id)

    if not normalize_my_phone(phone):
        phone, ok = QInputDialog.getText(
            parent,
            "E-receipt / 电子收据",
            "客户手机号 / Customer phone (MY):",
            text=phone or "",
        )
        if not ok:
            return
        phone = str(phone).strip()
        if not normalize_my_phone(phone):
            QMessageBox.warning(parent, "E-receipt", "无效手机号 / Invalid phone")
            return
        if not name:
            name, _ok2 = QInputDialog.getText(
                parent,
                "E-receipt",
                "客户姓名 / Customer name (optional):",
            )
            name = str(name or "").strip()

    try:
        write_contact_vcf(name or phone, phone)
    except Exception:
        pass

    ok, message = send_e_receipt_pdf(
        database, sale_id, phone_raw=phone, customer_name=name
    )
    if not ok:
        QMessageBox.warning(parent, "E-receipt", message)
        return
    QMessageBox.information(parent, "E-receipt / 电子收据 PDF", message)
