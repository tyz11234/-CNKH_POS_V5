from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from cnkh_pos.services.money import format_myr, rm_to_cents, round_cash_change_cents
from cnkh_pos.ui.dialogs.checkout import CheckoutDialog, SaleCompletedDialog


class CashRoundedCheckoutDialog(CheckoutDialog):
    """Checkout dialog that previews the requested cash-change rounding rule."""

    def _selected_method(self) -> str:
        selected = self.method_group.checkedButton()
        return str(selected.property("paymentMethod")) if selected else "CASH"

    def _method_changed(self, button: QPushButton, checked: bool) -> None:
        super()._method_changed(button, checked)
        if checked:
            self._update_change(self.paid_input.text())

    def _update_change(self, value: str) -> None:
        cleaned = value.upper().replace("RM", "").replace(",", "").strip()
        try:
            paid = rm_to_cents(cleaned or "0")
        except ValueError:
            self.change_label.setText("—")
            return
        raw_change = max(0, paid - self.total_cents)
        change = (
            round_cash_change_cents(raw_change)
            if self._selected_method() == "CASH"
            else raw_change
        )
        self.change_label.setText(format_myr(change))


class CashRoundedSaleCompletedDialog(SaleCompletedDialog):
    """Completion dialog that shows the persisted rounded cash change."""

    def __init__(
        self,
        receipt_no: str,
        total_cents: int,
        paid_cents: int,
        change_cents: int,
        method: str,
        parent=None,
    ):
        # Do not call the base constructor because it derives change from paid-total.
        # For cash sales the persisted rounded change can intentionally differ.
        super(SaleCompletedDialog, self).__init__(parent)
        self.print_requested = False
        self.setWindowTitle("Sale Completed / 销售完成")
        self.setMinimumWidth(520)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 26, 28, 26)
        title = QLabel("✓  Sale Completed / 销售完成")
        title.setStyleSheet("color:#168A3F; font-size:22px; font-weight:800;")
        layout.addWidget(title)
        for key, value in (
            ("Receipt No", receipt_no),
            ("Total", format_myr(total_cents)),
            ("Paid", format_myr(paid_cents)),
            ("Change", format_myr(change_cents)),
            ("Payment Method", method),
        ):
            row = QHBoxLayout()
            row.addWidget(QLabel(key))
            row.addStretch(1)
            result = QLabel(value)
            result.setStyleSheet("font-weight:700;")
            row.addWidget(result)
            layout.addLayout(row)
        actions = QHBoxLayout()
        print_button = QPushButton("打印小票")
        print_button.setObjectName("SuccessButton")
        print_button.setProperty("acceptanceName", "PrintReceiptButton")
        print_button.clicked.connect(self._request_print)
        self.print_button = print_button
        skip = QPushButton("暂不打印")
        skip.setObjectName("SkipPrintButton")
        skip.clicked.connect(self.accept)
        self.skip_button = skip
        actions.addWidget(print_button)
        actions.addWidget(skip)
        layout.addLayout(actions)
