from __future__ import annotations

from PySide6.QtWidgets import QLabel, QPushButton

from cnkh_pos.services.money import format_myr, round_checkout_cents
from cnkh_pos.ui.dialogs.checkout import CheckoutDialog


class RoundedCheckoutDialog(CheckoutDialog):
    """Checkout dialog that applies CNKH rounding to non-credit settlement only."""

    def __init__(
        self,
        total_cents: int,
        quick_amounts: list[int] | None = None,
        parent=None,
        *,
        customers: list[tuple[int, str]] | None = None,
        quick_settings_callback=None,
    ):
        self.raw_total_cents = int(total_cents)
        rounded_total = round_checkout_cents(self.raw_total_cents)
        super().__init__(
            rounded_total,
            quick_amounts,
            parent,
            customers=customers,
            quick_settings_callback=quick_settings_callback,
        )
        self.total_display = self.findChild(QLabel, "MoneyHero")
        self._refresh_total_display()

    @property
    def rounding_cents(self) -> int:
        return self.total_cents - self.raw_total_cents

    def _refresh_total_display(self) -> None:
        if self.total_display is not None:
            self.total_display.setText(format_myr(self.total_cents))
            adjustment = self.rounding_cents
            if adjustment:
                sign = "+" if adjustment > 0 else "-"
                self.total_display.setToolTip(
                    f"原金额 {format_myr(self.raw_total_cents)}；结账进位 {sign}{abs(adjustment)} sen"
                )
            else:
                self.total_display.setToolTip("")

    def _method_changed(self, button: QPushButton, checked: bool) -> None:
        if not checked:
            return
        method = str(button.property("paymentMethod"))
        self.total_cents = (
            self.raw_total_cents
            if method == "CREDIT"
            else round_checkout_cents(self.raw_total_cents)
        )
        self._refresh_total_display()
        super()._method_changed(button, checked)
