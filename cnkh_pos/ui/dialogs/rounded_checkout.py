from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QPushButton,
    QWidget,
)

from cnkh_pos.services.discounts import discount_cents_from_value
from cnkh_pos.services.money import format_myr, round_checkout_cents
from cnkh_pos.ui.dialogs.checkout import CheckoutDialog


class RoundedCheckoutDialog(CheckoutDialog):
    """Checkout with %/RM order discount plus CNKH settlement rounding."""

    def __init__(
        self,
        total_cents: int,
        quick_amounts: list[int] | None = None,
        parent=None,
        *,
        customers: list[tuple[int, str]] | None = None,
        quick_settings_callback=None,
        paths=None,
        is_admin: bool = False,
    ):
        self.raw_total_cents = int(total_cents)
        super().__init__(
            round_checkout_cents(self.raw_total_cents),
            quick_amounts,
            parent,
            customers=customers,
            quick_settings_callback=quick_settings_callback,
            paths=paths,
            is_admin=is_admin,
        )
        self.setMinimumHeight(700)
        self.total_display = self.findChild(QLabel, "MoneyHero")
        self.checkout_discount_mode = QComboBox()
        self.checkout_discount_mode.setObjectName("CheckoutDiscountMode")
        self.checkout_discount_mode.addItem("百分比 %", "PERCENT")
        self.checkout_discount_mode.addItem("固定金额 RM", "FIXED")
        self.checkout_discount_value = QDoubleSpinBox()
        self.checkout_discount_value.setObjectName("CheckoutDiscountValue")
        self.checkout_discount_value.setDecimals(2)
        self.checkout_discount_value.setSingleStep(1.0)
        self.checkout_discount_preview = QLabel()
        self.checkout_discount_preview.setObjectName("CheckoutDiscountPreview")

        discount_panel = QWidget()
        discount_form = QFormLayout(discount_panel)
        discount_form.setContentsMargins(0, 4, 0, 4)
        discount_form.addRow("整单 Discount", self.checkout_discount_mode)
        discount_form.addRow("折扣数值", self.checkout_discount_value)
        discount_form.addRow("折扣后金额", self.checkout_discount_preview)
        root = self.layout()
        root.insertWidget(max(0, root.count() - 2), discount_panel)

        self.checkout_discount_mode.currentIndexChanged.connect(
            self._discount_mode_changed
        )
        self.checkout_discount_value.valueChanged.connect(self._discount_changed)
        self._discount_mode_changed()

    @property
    def discount_cents(self) -> int:
        return discount_cents_from_value(
            self.raw_total_cents,
            mode=str(self.checkout_discount_mode.currentData()),
            value=self.checkout_discount_value.value(),
        )

    @property
    def discounted_total_cents(self) -> int:
        return self.raw_total_cents - self.discount_cents

    @property
    def rounding_cents(self) -> int:
        return self.total_cents - self.discounted_total_cents

    def _selected_method(self) -> str:
        button = self.method_group.checkedButton()
        return str(button.property("paymentMethod")) if button else "CASH"

    def _discount_mode_changed(self, _index: int = -1) -> None:
        if self.checkout_discount_mode.currentData() == "PERCENT":
            self.checkout_discount_value.setSuffix(" %")
            self.checkout_discount_value.setMaximum(100.0)
        else:
            self.checkout_discount_value.setSuffix(" RM")
            self.checkout_discount_value.setMaximum(self.raw_total_cents / 100)
        self._discount_changed()

    def _discount_changed(self, _value: float = 0.0) -> None:
        discounted = self.discounted_total_cents
        self.checkout_discount_preview.setText(
            f"{format_myr(self.raw_total_cents)} − {format_myr(self.discount_cents)} = "
            f"{format_myr(discounted)}"
        )
        self._refresh_settlement_total()

    def _refresh_settlement_total(self) -> None:
        method = self._selected_method()
        discounted = self.discounted_total_cents
        self.total_cents = (
            discounted if method == "CREDIT" else round_checkout_cents(discounted)
        )
        self._refresh_total_display()
        if method in {"CARD", "DUITNOW_QR"}:
            self._set_paid(self.total_cents)
        else:
            self._update_change(self.paid_input.text())

    def _refresh_total_display(self) -> None:
        if self.total_display is None:
            return
        self.total_display.setText(format_myr(self.total_cents))
        details = [f"原金额 {format_myr(self.raw_total_cents)}"]
        if self.discount_cents:
            details.append(f"Discount -{format_myr(self.discount_cents)}")
        if self.rounding_cents:
            sign = "+" if self.rounding_cents > 0 else "-"
            details.append(f"结账进位 {sign}{abs(self.rounding_cents)} sen")
        self.total_display.setToolTip("；".join(details))

    def _method_changed(self, button: QPushButton, checked: bool) -> None:
        if not checked:
            return
        method = str(button.property("paymentMethod"))
        discounted = self.discounted_total_cents
        self.total_cents = (
            discounted if method == "CREDIT" else round_checkout_cents(discounted)
        )
        self._refresh_total_display()
        super()._method_changed(button, checked)
