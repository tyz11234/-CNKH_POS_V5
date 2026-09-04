from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox

from cnkh_pos.services.checkout_rounding import RoundedSalesService
from cnkh_pos.services.discounts import allocate_order_discount
from cnkh_pos.services.money import clamp_discount_cents, line_amount_cents
from cnkh_pos.services.sales import SaleLine
from cnkh_pos.ui.dialogs.checkout import SaleCompletedDialog
from cnkh_pos.ui.dialogs.discount import DiscountDialog
from cnkh_pos.ui.dialogs.rounded_checkout import RoundedCheckoutDialog
from cnkh_pos.ui.staff.window import StaffWindow as BaseStaffWindow


class StaffWindowEnhanced(BaseStaffWindow):
    """Stable Staff POS plus working %/RM discounts and final checkout rounding."""

    def _edit_discount(self) -> None:
        row = self.cart.currentRow()
        if row < 0:
            QMessageBox.information(self, "Discount", "请先选择购物车商品。")
            return
        product_id = int(self.cart.item(row, 0).data(Qt.ItemDataRole.UserRole))
        gross = self._maximum_discount(product_id)
        dialog = DiscountDialog(
            gross,
            self,
            title="商品 Discount / 商品折扣",
            current_discount_cents=self.cart_discounts.get(product_id, 0),
        )
        if dialog.exec() != DiscountDialog.DialogCode.Accepted:
            return
        self.cart_discounts[product_id] = clamp_discount_cents(
            dialog.discount_cents, gross
        )
        self._rebuild_cart()

    def _sale_lines_with_order_discount(self, order_discount_cents: int) -> list[SaleLine]:
        prepared: list[tuple[int, object, int, int, int]] = []
        conn = self.database.connect(readonly=True)
        try:
            for product_id, quantity in self.cart_quantities.items():
                row = conn.execute(
                    "SELECT selling_price_cents FROM products WHERE id=? AND is_deleted=0",
                    (product_id,),
                ).fetchone()
                if row is None:
                    raise LookupError(f"product {product_id} is not available")
                gross = line_amount_cents(int(row["selling_price_cents"]), quantity)
                item_discount = clamp_discount_cents(
                    self.cart_discounts.get(product_id, 0), gross
                )
                prepared.append(
                    (product_id, quantity, gross, item_discount, gross - item_discount)
                )
        finally:
            conn.close()

        allocation = allocate_order_discount(
            [(product_id, net) for product_id, _qty, _gross, _discount, net in prepared],
            order_discount_cents,
        )
        return [
            SaleLine(
                product_id,
                quantity,
                quantity,
                discount_cents=item_discount + allocation[product_id],
            )
            for product_id, quantity, _gross, item_discount, _net in prepared
        ]

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
        can_discount = bool(self.user.permissions.get("apply_discount", False))
        dialog.checkout_discount_mode.setEnabled(can_discount)
        dialog.checkout_discount_value.setEnabled(can_discount)
        if not can_discount:
            message = "需要管理员授予折扣权限"
            dialog.checkout_discount_mode.setToolTip(message)
            dialog.checkout_discount_value.setToolTip(message)
        if dialog.exec() != RoundedCheckoutDialog.DialogCode.Accepted:
            return
        try:
            lines = self._sale_lines_with_order_discount(dialog.discount_cents)
            result = RoundedSalesService(self.database).create_sale(
                lines=lines,
                payment_method=dialog.payment_method,
                paid_cents=dialog.paid_cents,
                cashier_id=self.user.id,
                customer_id=dialog.customer_id,
                deposit_method=dialog.deposit_method,
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
