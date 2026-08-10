from __future__ import annotations

from PySide6.QtWidgets import QMessageBox

from cnkh_pos.services.checkout_sales import CheckoutSalesService
from cnkh_pos.services.sales import SaleLine
from cnkh_pos.ui.dialogs.cash_checkout import (
    CashRoundedCheckoutDialog,
    CashRoundedSaleCompletedDialog,
)
from cnkh_pos.ui.staff.window import StaffWindow as BaseStaffWindow


class StaffWindow(BaseStaffWindow):
    """Stable staff window with the requested cash-change checkout rule."""

    def _checkout(self) -> None:
        total = self._cart_total()
        if not self.cart_quantities:
            QMessageBox.information(self, "Cart", "购物车是空的。")
            return
        dialog = CashRoundedCheckoutDialog(
            total,
            self._quick_amounts(),
            self,
            customers=self._customers(),
            quick_settings_callback=self._open_quick_amount_settings,
        )
        if dialog.exec() != CashRoundedCheckoutDialog.DialogCode.Accepted:
            return
        try:
            lines = [
                SaleLine(
                    product_id,
                    quantity,
                    quantity,
                    discount_cents=self.cart_discounts.get(product_id, 0),
                )
                for product_id, quantity in self.cart_quantities.items()
            ]
            result = CheckoutSalesService(self.database).create_sale(
                lines=lines,
                payment_method=dialog.payment_method,
                paid_cents=dialog.paid_cents,
                cashier_id=self.user.id,
                customer_id=dialog.customer_id,
            )
        except Exception as exc:
            QMessageBox.critical(self, "Checkout", str(exc))
            return
        self._clear_cart()
        self._load_product_table()
        completed = CashRoundedSaleCompletedDialog(
            result.receipt_no,
            result.total_cents,
            result.paid_cents,
            result.change_cents,
            dialog.payment_method,
            self,
        )
        completed.exec()
        if completed.print_requested:
            self._print_sale(result.sale_id)
