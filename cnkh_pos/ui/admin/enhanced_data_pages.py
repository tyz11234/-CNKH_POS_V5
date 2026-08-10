from __future__ import annotations

from dataclasses import replace

from PySide6.QtWidgets import QComboBox, QDialog, QFormLayout, QMessageBox

from cnkh_pos.database.connection import Database
from cnkh_pos.services.auth import AuthenticatedUser
from cnkh_pos.services.catalog import CatalogService, ProductInput
from cnkh_pos.services.sales import SalesService
from cnkh_pos.ui.admin.data_pages import ProductDialog, ProductsPage, SalesPage


class ProductDialogWithBarcodeMode(ProductDialog):
    """Product editor with an explicit auto/manual barcode choice for new items."""

    def __init__(
        self,
        database: Database,
        parent=None,
        *,
        product_id: int | None = None,
    ):
        super().__init__(database, parent, product_id=product_id)
        form = self.layout().itemAt(0).layout()
        if not isinstance(form, QFormLayout):
            raise RuntimeError("product form layout is unavailable")

        barcode_label = form.labelForField(self.barcode)
        if barcode_label is not None:
            barcode_label.setText("Barcode")

        self.barcode_mode: QComboBox | None = None
        if product_id is None:
            self.barcode_mode = QComboBox()
            self.barcode_mode.addItem("系统自动生成 EAN-13", "AUTO")
            self.barcode_mode.addItem("手动输入", "MANUAL")
            barcode_row, _ = form.getWidgetPosition(self.barcode)
            form.insertRow(barcode_row, "Barcode Mode", self.barcode_mode)
            self.barcode_mode.currentIndexChanged.connect(self._barcode_mode_changed)
            self._barcode_mode_changed()
        else:
            self.barcode.setPlaceholderText("保留或修改现有 Barcode")

    def _barcode_mode_changed(self, _index: int = -1) -> None:
        if self.barcode_mode is None:
            return
        manual = self.barcode_mode.currentData() == "MANUAL"
        self.barcode.setEnabled(manual)
        if manual:
            self.barcode.setPlaceholderText("输入商品 Barcode（不可与现有商品重复）")
        else:
            self.barcode.clear()
            self.barcode.setPlaceholderText("保存后由系统自动生成唯一 EAN-13")

    def value(self) -> ProductInput:
        data = super().value()
        if self.product_id is None and self.barcode_mode is not None:
            if self.barcode_mode.currentData() == "AUTO":
                return replace(data, barcode=None)
            if not self.barcode.text().strip():
                raise ValueError("手动 Barcode 不能为空")
        return data


class ProductsPageEnhanced(ProductsPage):
    """Keeps the stable products page while changing only new-product barcode entry."""

    def add_product(self) -> None:
        dialog = ProductDialogWithBarcodeMode(self.database, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            CatalogService(self.database).add_product(
                dialog.value(), admin_id=self.user.id
            )
            self.refresh()
        except Exception as exc:
            QMessageBox.warning(self, "Product", str(exc))


class SalesPageEnhanced(SalesPage):
    """Adds admin-only permanent sale deletion using the existing safe service path."""

    def __init__(self, database: Database, user: AuthenticatedUser):
        super().__init__(database, user)
        self.add_action("删除销售记录", self.delete_sale, style="DangerButton")

    def delete_sale(self) -> None:
        sale_id = self.selected_id()
        if sale_id is None:
            QMessageBox.information(self, "Delete Sale", "请先选择销售记录。")
            return
        row = self.table.currentRow()
        receipt_no = self.table.item(row, 1).text() if row >= 0 else str(sale_id)
        answer = QMessageBox.question(
            self,
            "Delete Sale / 删除销售记录",
            (
                f"确定永久删除销售记录 {receipt_no}？\n\n"
                "系统会恢复尚未因退货而恢复的库存，并清理这笔销售关联的退货/赊账记录；"
                "删除动作会保留在审计日志中。此操作不可撤销。"
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            SalesService(self.database).delete_sale(
                sale_id=sale_id, admin_id=self.user.id
            )
        except Exception as exc:
            QMessageBox.warning(self, "Delete Sale", str(exc))
            return
        self.refresh()
        QMessageBox.information(self, "Delete Sale", f"销售记录 {receipt_no} 已删除。")
