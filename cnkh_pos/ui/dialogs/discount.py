from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QVBoxLayout,
)

from cnkh_pos.services.discounts import (
    discount_from_amount_cents,
    discount_from_percent_cents,
)
from cnkh_pos.services.money import format_myr, rm_to_cents


class DiscountDialog(QDialog):
    """Mouse-friendly line discount editor supporting percent or fixed MYR."""

    def __init__(
        self,
        line_cents: int,
        current_discount_cents: int = 0,
        parent=None,
    ):
        super().__init__(parent)
        self.line_cents = max(0, int(line_cents))
        self.current_discount_cents = min(
            self.line_cents, max(0, int(current_discount_cents))
        )
        self.discount_cents = self.current_discount_cents
        self.setWindowTitle("Discount / 折扣")
        self.setMinimumWidth(430)

        root = QVBoxLayout(self)
        form = QFormLayout()
        self.mode = QComboBox()
        self.mode.addItem("百分比 %", "PERCENT")
        self.mode.addItem("固定金额 RM", "AMOUNT")
        self.value = QDoubleSpinBox()
        self.value.setDecimals(2)
        self.value.setMinimum(0)
        self.value.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.preview = QLabel()
        self.preview.setObjectName("MoneyHero")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignRight)
        form.addRow("Discount Mode", self.mode)
        form.addRow("Value", self.value)
        form.addRow("折扣后金额", self.preview)
        root.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept_discount)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self.mode.currentIndexChanged.connect(self._configure_mode)
        self.value.valueChanged.connect(self._update_preview)
        self._configure_mode()
        if self.current_discount_cents:
            self.mode.setCurrentIndex(self.mode.findData("AMOUNT"))
            self.value.setValue(self.current_discount_cents / 100)
        self._update_preview()

    def _configure_mode(self, _index: int = -1) -> None:
        if self.mode.currentData() == "PERCENT":
            self.value.setPrefix("")
            self.value.setSuffix(" %")
            self.value.setMaximum(100.0)
            if self.value.value() > 100:
                self.value.setValue(100)
        else:
            self.value.setPrefix("RM ")
            self.value.setSuffix("")
            self.value.setMaximum(self.line_cents / 100)
            if self.value.value() > self.line_cents / 100:
                self.value.setValue(self.line_cents / 100)
        self._update_preview()

    def calculated_discount_cents(self) -> int:
        if self.mode.currentData() == "PERCENT":
            return discount_from_percent_cents(self.line_cents, self.value.value())
        return discount_from_amount_cents(
            self.line_cents, rm_to_cents(str(self.value.value()))
        )

    def _update_preview(self, _value: float = 0.0) -> None:
        discount = self.calculated_discount_cents()
        self.preview.setText(
            f"{format_myr(self.line_cents - discount)}  "
            f"(Discount {format_myr(discount)})"
        )

    def _accept_discount(self) -> None:
        self.discount_cents = self.calculated_discount_cents()
        self.accept()
