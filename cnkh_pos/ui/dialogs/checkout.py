from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from cnkh_pos.services.money import format_myr, rm_to_cents


class CheckoutDialog(QDialog):
    """Large mouse-first payment dialog. Committing a sale belongs to SalesService."""

    def __init__(
        self, total_cents: int, quick_amounts: list[int] | None = None, parent=None
    ):
        super().__init__(parent)
        self.total_cents = total_cents
        self.paid_cents = 0
        self.payment_method = "CASH"
        self.setWindowTitle("结账 / 收款")
        self.setModal(True)
        self.setMinimumSize(560, 650)
        self.resize(600, 700)
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(12)

        title = QLabel("结账 / 收款")
        title.setObjectName("PageTitle")
        root.addWidget(title)
        root.addWidget(self._caption("应收金额"))
        total = QLabel(format_myr(total_cents))
        total.setObjectName("MoneyHero")
        total.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(total)

        root.addWidget(self._caption("实收金额"))
        self.paid_input = QLineEdit()
        self.paid_input.setObjectName("PaymentInput")
        self.paid_input.setPlaceholderText("RM 0.00")
        self.paid_input.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.paid_input.textChanged.connect(self._update_change)
        root.addWidget(self.paid_input)

        root.addWidget(self._caption("付款方式"))
        methods = QHBoxLayout()
        self.method_group = QButtonGroup(self)
        self.method_group.setExclusive(True)
        for index, (label, value) in enumerate(
            (
                ("Cash", "CASH"),
                ("Card", "CARD"),
                ("DuitNow QR", "DUITNOW_QR"),
                ("Credit", "CREDIT"),
            )
        ):
            button = QPushButton(label)
            button.setCheckable(True)
            button.setProperty("paymentMethod", value)
            self.method_group.addButton(button)
            methods.addWidget(button)
            if index == 0:
                button.setChecked(True)
        root.addLayout(methods)

        quick_header = QHBoxLayout()
        quick_header.addWidget(self._caption("快捷金额"))
        quick_header.addStretch(1)
        settings = QPushButton("⚙ 设置")
        quick_header.addWidget(settings)
        root.addLayout(quick_header)
        quick_grid = QGridLayout()
        for index, cents in enumerate(
            quick_amounts or [1000, 2000, 5000, 10000, 20000]
        ):
            button = QPushButton(format_myr(cents).replace(".00", ""))
            button.setObjectName("QuickAmountButton")
            button.clicked.connect(
                lambda checked=False, amount=cents: self._set_paid(amount)
            )
            quick_grid.addWidget(button, index // 3, index % 3)
        root.addLayout(quick_grid)

        change_row = QHBoxLayout()
        change_row.addWidget(self._caption("找零金额"))
        change_row.addStretch(1)
        self.change_label = QLabel("RM 0.00")
        self.change_label.setStyleSheet(
            "color:#168A3F; font-size:22px; font-weight:800;"
        )
        change_row.addWidget(self.change_label)
        root.addLayout(change_row)
        root.addStretch(1)

        actions = QHBoxLayout()
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        confirm = QPushButton("确认收款")
        confirm.setObjectName("SuccessButton")
        confirm.setMinimumHeight(54)
        confirm.clicked.connect(self._confirm)
        actions.addWidget(cancel)
        actions.addWidget(confirm, 2)
        root.addLayout(actions)

    @staticmethod
    def _caption(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("SectionTitle")
        return label

    def _set_paid(self, cents: int) -> None:
        self.paid_input.setText(f"{cents / 100:.2f}")

    def _update_change(self, value: str) -> None:
        cleaned = value.upper().replace("RM", "").replace(",", "").strip()
        try:
            paid = rm_to_cents(cleaned or "0")
        except ValueError:
            self.change_label.setText("—")
            return
        self.change_label.setText(format_myr(max(0, paid - self.total_cents)))

    def _confirm(self) -> None:
        selected = self.method_group.checkedButton()
        self.payment_method = (
            str(selected.property("paymentMethod")) if selected else "CASH"
        )
        cleaned = (
            self.paid_input.text().upper().replace("RM", "").replace(",", "").strip()
        )
        if self.payment_method in {"CARD", "DUITNOW_QR"} and not cleaned:
            self.paid_cents = self.total_cents
        else:
            try:
                self.paid_cents = rm_to_cents(cleaned or "0")
            except ValueError:
                self.paid_input.setFocus()
                return
        if self.payment_method != "CREDIT" and self.paid_cents < self.total_cents:
            self.paid_input.setStyleSheet("border:2px solid #E5484D;")
            self.paid_input.setFocus()
            return
        self.accept()


class SaleCompletedDialog(QDialog):
    def __init__(
        self,
        receipt_no: str,
        total_cents: int,
        paid_cents: int,
        method: str,
        parent=None,
    ):
        super().__init__(parent)
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
            ("Change", format_myr(max(0, paid_cents - total_cents))),
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
        print_button.clicked.connect(self._request_print)
        skip = QPushButton("暂不打印")
        skip.clicked.connect(self.accept)
        actions.addWidget(print_button)
        actions.addWidget(skip)
        layout.addLayout(actions)

    def _request_print(self) -> None:
        self.print_requested = True
        self.accept()
