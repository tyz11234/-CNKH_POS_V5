from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox

from cnkh_pos.services.checkout_rounding import RoundedSalesService
from cnkh_pos.services.sales import SaleLine
from cnkh_pos.ui.dialogs.checkout import SaleCompletedDialog
from cnkh_pos.ui.dialogs.discount import DiscountDialog
from cnkh_pos.ui.dialogs.rounded_checkout import RoundedCheckoutDialog
from cnkh_pos.ui.staff.window import StaffWindow as BaseStaffWindow


class StaffWindowEnhanced(BaseStaffWindow):
    """Stable Staff POS plus checkout rounding and reliable discount editing."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.discount_button.setText("Discount（% / RM）")
        self.discount_button.setToolTip(
            "可按百分比或固定金额设置所选商品折扣"
            if self.discount_button.isEnabled()
            else "需要管理员授予折扣权限"
        )

    def _edit_discount(self) -> None:
        row = self.cart.currentRow()
        if row < 0:
            QMessageBox.information(self, "Discount", "请先选择购物车商品。")
            return
        item = self.cart.item(row, 0)
        if item is None:
            QMessageBox.information(self, "Discount", "请先选择购物车商品。")
            return
        product_id = int(item.data(Qt.ItemDataRole.UserRole))
        maximum = self._maximum_discount(product_id)
        dialog = DiscountDialog(
            maximum,
            self.cart_discounts.get(product_id, 0),
            self,
        )
        if dialog.exec() != DiscountDialog.DialogCode.Accepted:
            return
        discount = min(maximum, max(0, int(dialog.discount_cents)))
        if discount:
            self.cart_discounts[product_id] = discount
        else:
            self.cart_discounts.pop(product_id, None)
        self._rebuild_cart()

    def _checkout(self) -> None:
        raw_total = self._cart_total()
        if not self.cart_quantities:
            QMessageBox.information(self, "Cart", "购物车是空的。")
            return
        dialog = RoundedCheckoutDialog(
            raw_total,
            self._quick_amounts(),
            self,
            customers=self._customers(),
            quick_settings_callback=self._open_quick_amount_settings,
        )
        if dialog.exec() != RoundedCheckoutDialog.DialogCode.Accepted:
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
            result = RoundedSalesService(self.database).create_sale(
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
        completed = SaleCompletedDialog(
            result.receipt_no,
            result.total_cents,
            result.paid_cents,
            dialog.payment_method,
            self,
        )
        completed.exec()
        if completed.print_requested:
            self._print_sale(result.sale_id)
