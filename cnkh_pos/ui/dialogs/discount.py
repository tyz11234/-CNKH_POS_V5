from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QMessageBox,
    QVBoxLayout,
)

from cnkh_pos.services.discounts import discount_cents_from_value
from cnkh_pos.services.money import format_myr


class DiscountDialog(QDialog):
    def __init__(
        self,
        gross_cents: int,
        parent=None,
        *,
        title: str = "Discount / 折扣",
        current_discount_cents: int = 0,
    ):
        super().__init__(parent)
        self.gross_cents = max(0, int(gross_cents))
        self.setWindowTitle(title)
        self.setMinimumWidth(420)
        root = QVBoxLayout(self)
        form = QFormLayout()
        self.mode = QComboBox()
        self.mode.addItem("百分比 %", "PERCENT")
        self.mode.addItem("固定金额 RM", "FIXED")
        self.value = QDoubleSpinBox()
        self.value.setDecimals(2)
        self.value.setSingleStep(1.0)
        self.preview = QLabel()
        form.addRow("Discount Mode", self.mode)
        form.addRow("Discount Value", self.value)
        form.addRow("折扣后金额", self.preview)
        root.addLayout(form)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept_if_valid)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self.mode.currentIndexChanged.connect(self._mode_changed)
        self.value.valueChanged.connect(self._update_preview)
        if current_discount_cents > 0:
            self.mode.setCurrentIndex(self.mode.findData("FIXED"))
            self.value.setValue(min(current_discount_cents, self.gross_cents) / 100)
        else:
            self._mode_changed()
        self._update_preview()

    def _mode_changed(self, _index: int = -1) -> None:
        if self.mode.currentData() == "PERCENT":
            self.value.setSuffix(" %")
            self.value.setMaximum(100.0)
        else:
            self.value.setSuffix(" RM")
            self.value.setMaximum(self.gross_cents / 100)
        self._update_preview()

    @property
    def discount_cents(self) -> int:
        return discount_cents_from_value(
            self.gross_cents,
            mode=str(self.mode.currentData()),
            value=self.value.value(),
        )

    def _update_preview(self, _value: float = 0.0) -> None:
        try:
            discount = self.discount_cents
        except ValueError:
            self.preview.setText("—")
            return
        self.preview.setText(
            f"{format_myr(self.gross_cents)} − {format_myr(discount)} = "
            f"{format_myr(self.gross_cents - discount)}"
        )

    def _accept_if_valid(self) -> None:
        try:
            self.discount_cents
        except ValueError as exc:
            QMessageBox.warning(self, "Discount", str(exc))
            return
        self.accept()
