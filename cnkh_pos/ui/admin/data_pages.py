from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from cnkh_pos.config import APP_VERSION, AppPaths
from cnkh_pos.database.connection import Database
from cnkh_pos.services.auth import AuthenticatedUser
from cnkh_pos.services.backup import BackupService
from cnkh_pos.services.catalog import CatalogService, ProductInput
from cnkh_pos.services.entities import EntityInput, EntityService
from cnkh_pos.services.excel_import import ExcelImportService
from cnkh_pos.services.maintenance import AuditMaintenanceService
from cnkh_pos.services.money import rm_to_cents
from cnkh_pos.services.payments import CustomerPaymentService, SupplierPaymentService
from cnkh_pos.services.printing import PrintingService
from cnkh_pos.services.purchases import PurchaseLine, PurchaseService
from cnkh_pos.services.restore import RestoreService
from cnkh_pos.services.sales import ReturnService
from cnkh_pos.services.stocktake import StocktakeService


class PagedTablePage(QWidget):
    def __init__(self, database: Database, title: str, columns: list[str], parent=None):
        super().__init__(parent)
        self.database = database
        self.offset = 0
        self.page_size = 50
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 20)
        heading = QHBoxLayout()
        label = QLabel(title)
        label.setObjectName("PageTitle")
        self.actions = QHBoxLayout()
        heading.addWidget(label)
        heading.addStretch(1)
        heading.addLayout(self.actions)
        root.addLayout(heading)
        self.table = QTableWidget(0, len(columns))
        self.table.setHorizontalHeaderLabels(columns)
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        root.addWidget(self.table, 1)
        pager = QHBoxLayout()
        self.previous = QPushButton("‹ 上一页")
        self.next = QPushButton("下一页 ›")
        self.page_label = QLabel("Page 1")
        self.previous.clicked.connect(self._previous)
        self.next.clicked.connect(self._next)
        pager.addStretch(1)
        pager.addWidget(self.previous)
        pager.addWidget(self.page_label)
        pager.addWidget(self.next)
        root.addLayout(pager)

    def add_action(self, text: str, callback, *, style: str = "") -> QPushButton:
        button = QPushButton(text)
        if style:
            button.setObjectName(style)
        button.clicked.connect(callback)
        self.actions.addWidget(button)
        return button

    def set_rows(self, rows: list[tuple[object, ...]]) -> None:
        self.table.setRowCount(len(rows))
        for r, values in enumerate(rows):
            for c, value in enumerate(values):
                item = QTableWidgetItem("" if value is None else str(value))
                if c == 0:
                    item.setData(Qt.ItemDataRole.UserRole, values[0])
                self.table.setItem(r, c, item)
        self.page_label.setText(f"Page {self.offset // self.page_size + 1}")
        self.previous.setEnabled(self.offset > 0)
        self.next.setEnabled(len(rows) == self.page_size)

    def selected_id(self) -> int | None:
        row = self.table.currentRow()
        return None if row < 0 else int(self.table.item(row, 0).text())

    def _previous(self) -> None:
        self.offset = max(0, self.offset - self.page_size)
        self.refresh()

    def _next(self) -> None:
        self.offset += self.page_size
        self.refresh()

    def refresh(self) -> None:
        raise NotImplementedError


class ProductDialog(QDialog):
    def __init__(
        self,
        database: Database,
        parent=None,
        *,
        product_id: int | None = None,
    ):
        super().__init__(parent)
        self.database = database
        self.product_id = product_id
        self.setWindowTitle("编辑商品" if product_id is not None else "新增商品")
        self.setMinimumWidth(520)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.name = QLineEdit()
        self.aliases = QLineEdit()
        self.category = QComboBox()
        self.category.addItem("未分类 / Uncategorized", None)
        conn = database.connect(readonly=True)
        try:
            for row in conn.execute(
                "SELECT id,name FROM categories WHERE is_deleted=0 ORDER BY name COLLATE NOCASE"
            ):
                self.category.addItem(str(row["name"]), int(row["id"]))
        finally:
            conn.close()
        self.sku = QLineEdit()
        self.barcode = QLineEdit()
        self.cost = QLineEdit("0.00")
        self.price = QLineEdit("0.00")
        self.stock = QLineEdit("0")
        self.unit = QLineEdit("pcs")
        self.location = QLineEdit()
        self.low_stock = QLineEdit("0")
        for label, widget in (
            ("Name *", self.name),
            ("Aliases", self.aliases),
            ("Category", self.category),
            ("SKU", self.sku),
            ("Barcode (blank = EAN-13)", self.barcode),
            ("Cost RM", self.cost),
            ("Selling Price RM", self.price),
            ("Stock", self.stock),
            ("Unit", self.unit),
            ("Location", self.location),
            ("Low Stock Level", self.low_stock),
        ):
            form.addRow(label, widget)
        layout.addLayout(form)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        if product_id is not None:
            self._load_product(product_id)

    def _load_product(self, product_id: int) -> None:
        conn = self.database.connect(readonly=True)
        try:
            row = conn.execute(
                "SELECT * FROM products WHERE id=? AND is_deleted=0", (product_id,)
            ).fetchone()
        finally:
            conn.close()
        if row is None:
            raise LookupError("product not found")
        self.name.setText(str(row["name"]))
        self.aliases.setText(str(row["aliases"]))
        self.sku.setText(str(row["sku"] or ""))
        self.barcode.setText(str(row["barcode"] or ""))
        self.cost.setText(f"{int(row['cost_cents']) / 100:.2f}")
        self.price.setText(f"{int(row['selling_price_cents']) / 100:.2f}")
        self.stock.setText(str(row["stock_decimal"]))
        self.unit.setText(str(row["unit"]))
        self.location.setText(str(row["location"]))
        self.low_stock.setText(str(row["low_stock_decimal"]))
        index = self.category.findData(row["category_id"])
        self.category.setCurrentIndex(max(0, index))

    def value(self) -> ProductInput:
        return ProductInput(
            name=self.name.text(),
            aliases=self.aliases.text(),
            category_id=self.category.currentData(),
            sku=self.sku.text() or None,
            barcode=self.barcode.text() or None,
            cost_cents=rm_to_cents(self.cost.text()),
            selling_price_cents=rm_to_cents(self.price.text()),
            stock=self.stock.text(),
            unit=self.unit.text(),
            location=self.location.text(),
            low_stock=self.low_stock.text(),
        )


class ProductsPage(PagedTablePage):
    def __init__(self, database: Database, user: AuthenticatedUser):
        super().__init__(
            database,
            "商品管理",
            ["ID", "商品", "SKU", "Barcode", "售价", "库存", "单位", "位置"],
        )
        self.user = user
        self.add_action("＋ 新增", self.add_product, style="PrimaryButton")
        self.add_action("编辑", self.edit_product, style="WarningButton")
        self.add_action("Excel 模板", self.export_template)
        self.add_action("Excel 导入", self.import_excel, style="SuccessButton")
        self.add_action("复制 Barcode", self.copy_barcode)
        self.add_action("批量删除", self.delete_selected, style="DangerButton")
        self.add_action("刷新", self.refresh)
        self.refresh()

    def refresh(self) -> None:
        conn = self.database.connect(readonly=True)
        try:
            rows = conn.execute(
                """SELECT id, name, COALESCE(sku,''), COALESCE(barcode,''),
                   printf('RM %.2f', selling_price_cents/100.0), stock_decimal, unit, location
                   FROM products WHERE is_deleted=0 ORDER BY name COLLATE NOCASE LIMIT ? OFFSET ?""",
                (self.page_size, self.offset),
            ).fetchall()
            self.set_rows([tuple(row) for row in rows])
        finally:
            conn.close()

    def add_product(self) -> None:
        dialog = ProductDialog(self.database, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            CatalogService(self.database).add_product(
                dialog.value(), admin_id=self.user.id
            )
            self.refresh()
        except Exception as exc:
            QMessageBox.warning(self, "Product", str(exc))

    def edit_product(self) -> None:
        product_id = self.selected_id()
        if product_id is None:
            QMessageBox.information(self, "Product", "请先选择商品。")
            return
        try:
            dialog = ProductDialog(self.database, self, product_id=product_id)
        except Exception as exc:
            QMessageBox.warning(self, "Product", str(exc))
            return
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            CatalogService(self.database).update_product(
                product_id, dialog.value(), admin_id=self.user.id
            )
            self.refresh()
        except Exception as exc:
            QMessageBox.warning(self, "Product", str(exc))

    def export_template(self) -> None:
        paths = AppPaths.default()
        paths.ensure_directories()
        target, _ = QFileDialog.getSaveFileName(
            self,
            "Save Product Excel Template",
            str(paths.exports / "CNKH_POS_Product_Import_Template.xlsx"),
            "Excel Workbook (*.xlsx)",
            options=QFileDialog.Option.DontUseNativeDialog,
        )
        if not target:
            return
        try:
            result = ExcelImportService.create_template(Path(target))
            QMessageBox.information(self, "Excel Template", f"模板已建立：{result}")
        except Exception as exc:
            QMessageBox.warning(self, "Excel Template", str(exc))

    def import_excel(self) -> None:
        source, _ = QFileDialog.getOpenFileName(
            self,
            "Import Products from Excel",
            "",
            "Excel Workbook (*.xlsx)",
            options=QFileDialog.Option.DontUseNativeDialog,
        )
        if not source:
            return
        service = ExcelImportService(self.database)
        try:
            rows = service.preview(Path(source))
        except Exception as exc:
            QMessageBox.warning(self, "Excel Import", str(exc))
            return
        valid = [row for row in rows if not row.errors]
        invalid = [row for row in rows if row.errors]
        details = "\n".join(
            f"Row {row.row_number}: {', '.join(row.errors)}" for row in invalid[:12]
        )
        prompt = (
            f"可导入：{len(valid)} 行\n有错误：{len(invalid)} 行"
            + (f"\n\n{details}" if details else "")
            + "\n\n只会导入没有错误的行。继续？"
        )
        if QMessageBox.question(self, "Excel Import Preview", prompt) != QMessageBox.StandardButton.Yes:
            return
        summary = service.commit(rows, admin_id=self.user.id)
        self.refresh()
        QMessageBox.information(
            self,
            "Excel Import",
            f"成功：{summary.success}，跳过：{summary.skipped}，预览错误：{summary.errors}",
        )

    def copy_barcode(self) -> None:
        row = self.table.currentRow()
        if row >= 0:
            QApplication.clipboard().setText(self.table.item(row, 3).text())

    def delete_selected(self) -> None:
        ids = sorted(
            {
                int(self.table.item(index.row(), 0).text())
                for index in self.table.selectedIndexes()
            }
        )
        if not ids:
            return
        if (
            QMessageBox.question(
                self, "Danger", f"删除选中的 {len(ids)} 个商品？历史单据会保留快照。"
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        CatalogService(self.database).delete_products(ids, admin_id=self.user.id)
        self.refresh()


class ReturnSaleDialog(QDialog):
    def __init__(self, database: Database, sale_id: int, parent=None):
        super().__init__(parent)
        self.database = database
        self.sale_id = sale_id
        self.setWindowTitle("Sales Return / 销售退货")
        self.setMinimumSize(820, 540)
        root = QVBoxLayout(self)
        root.addWidget(QLabel("输入本次退货数量；退款会按原折扣后的实付金额计算。"))
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["Item ID", "商品", "已售", "已退", "可退", "本次退货"]
        )
        self.table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        root.addWidget(self.table)
        self.reason = QLineEdit()
        root.addWidget(QLabel("Reason / 退货原因"))
        root.addWidget(self.reason)
        self.refund_method = QComboBox()
        self.refund_method.addItem("Original Method / 原付款方式", "ORIGINAL")
        self.refund_method.addItem("Cash / 现金", "CASH")
        self.refund_method.addItem("Card / 卡", "CARD")
        self.refund_method.addItem("DuitNow QR", "DUITNOW_QR")
        root.addWidget(QLabel("Refund Method / 退款方式"))
        root.addWidget(self.refund_method)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._validate)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self._load()

    def _load(self) -> None:
        conn = self.database.connect(readonly=True)
        try:
            rows = conn.execute(
                """SELECT si.id,si.product_name_snapshot,si.quantity_decimal,
                          COALESCE(SUM(CAST(sri.quantity_decimal AS REAL)),0) returned
                   FROM sale_items si
                   LEFT JOIN sale_return_items sri ON sri.sale_item_id=si.id
                   WHERE si.sale_id=? GROUP BY si.id ORDER BY si.id""",
                (self.sale_id,),
            ).fetchall()
        finally:
            conn.close()
        self.table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            sold = Decimal(str(row["quantity_decimal"]))
            returned = Decimal(str(row["returned"]))
            remaining = max(Decimal("0"), sold - returned)
            values = (row["id"], row["product_name_snapshot"], sold, returned, remaining)
            for column, value in enumerate(values):
                self.table.setItem(row_index, column, QTableWidgetItem(str(value)))
            quantity = QDoubleSpinBox()
            quantity.setDecimals(3)
            quantity.setRange(0, float(remaining))
            self.table.setCellWidget(row_index, 5, quantity)

    def _validate(self) -> None:
        if not self.reason.text().strip():
            QMessageBox.warning(self, "Return", "请填写退货原因。")
            return
        if not self.value()[0]:
            QMessageBox.warning(self, "Return", "请至少输入一项退货数量。")
            return
        self.accept()

    def value(self) -> tuple[dict[int, Decimal], str, str]:
        result: dict[int, Decimal] = {}
        for row in range(self.table.rowCount()):
            control = self.table.cellWidget(row, 5)
            quantity = Decimal(str(control.value()))
            if quantity > 0:
                result[int(self.table.item(row, 0).text())] = quantity
        return (
            result,
            self.reason.text().strip(),
            str(self.refund_method.currentData()),
        )


class SalesPage(PagedTablePage):
    def __init__(self, database: Database, user: AuthenticatedUser):
        super().__init__(
            database,
            "销售记录",
            ["ID", "Receipt No", "时间", "总额", "付款方式", "状态"],
        )
        self.user = user
        self.add_action("销售退货", self.return_sale, style="WarningButton")
        self.add_action("重印小票", self.reprint, style="PrimaryButton")
        self.add_action("刷新", self.refresh, style="PrimaryButton")
        self.refresh()

    def refresh(self) -> None:
        conn = self.database.connect(readonly=True)
        try:
            rows = conn.execute(
                "SELECT id, receipt_no, sold_at, printf('RM %.2f', total_cents/100.0), payment_method, CASE is_deleted WHEN 0 THEN 'COMPLETED' ELSE 'DELETED' END FROM sales ORDER BY sold_at DESC LIMIT ? OFFSET ?",
                (self.page_size, self.offset),
            ).fetchall()
            self.set_rows([tuple(row) for row in rows])
        finally:
            conn.close()

    def return_sale(self) -> None:
        sale_id = self.selected_id()
        if sale_id is None:
            QMessageBox.information(self, "Return", "请先选择销售记录。")
            return
        dialog = ReturnSaleDialog(self.database, sale_id, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        quantities, reason, refund_method = dialog.value()
        try:
            number = ReturnService(self.database).create_return(
                sale_id=sale_id,
                quantities_by_sale_item=quantities,
                reason=reason,
                operator_id=self.user.id,
                refund_method=refund_method,
            )
        except Exception as exc:
            QMessageBox.warning(self, "Return", str(exc))
            return
        QMessageBox.information(self, "Return", f"退货已保存：{number}")

    def reprint(self) -> None:
        sale_id = self.selected_id()
        if sale_id is None:
            QMessageBox.information(self, "Receipt", "请先选择销售记录。")
            return
        try:
            service = PrintingService(self.database)
            receipt = service.receipt(sale_id)
            service.print_receipt(receipt)
        except Exception as exc:
            QMessageBox.warning(self, "Receipt", str(exc))
            return
        QMessageBox.information(self, "Receipt", "小票已发送到所选打印机。")


class RecordPaymentDialog(QDialog):
    def __init__(self, *, title: str, balance_cents: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(480)
        layout = QFormLayout(self)
        self.amount = QDoubleSpinBox()
        self.amount.setDecimals(2)
        self.amount.setRange(0.01, balance_cents / 100)
        self.amount.setValue(balance_cents / 100)
        self.method = QComboBox()
        self.method.addItems(["CASH", "CARD", "DUITNOW_QR"])
        self.note = QTextEdit()
        self.note.setPlaceholderText("Optional payment note / 付款备注")
        self.note.setMaximumHeight(100)
        layout.addRow("Amount RM", self.amount)
        layout.addRow("Payment Method", self.method)
        layout.addRow("Note / 备注", self.note)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def value(self) -> tuple[int, str, str]:
        return (
            round(self.amount.value() * 100),
            self.method.currentText(),
            self.note.toPlainText().strip(),
        )


class NewPurchaseDialog(QDialog):
    def __init__(self, database: Database, parent=None):
        super().__init__(parent)
        self.database = database
        self.setWindowTitle("New Purchase / 新建进货")
        self.setMinimumSize(760, 560)
        root = QVBoxLayout(self)
        form = QFormLayout()
        self.supplier = QComboBox()
        conn = database.connect(readonly=True)
        try:
            suppliers = conn.execute(
                "SELECT id,name FROM suppliers WHERE is_deleted=0 ORDER BY name"
            ).fetchall()
        finally:
            conn.close()
        for row in suppliers:
            self.supplier.addItem(str(row["name"]), int(row["id"]))
        self.product = QComboBox()
        self.quantity = QDoubleSpinBox()
        self.quantity.setDecimals(3)
        self.quantity.setRange(0.001, 999999)
        self.quantity.setValue(1)
        self.cost = QDoubleSpinBox()
        self.cost.setDecimals(2)
        self.cost.setRange(0, 999999)
        self.product.currentIndexChanged.connect(self._product_changed)
        add_item = QPushButton("＋ Add Item")
        add_item.setObjectName("PrimaryButton")
        add_item.clicked.connect(self.add_item)
        form.addRow("Supplier", self.supplier)
        form.addRow("Product", self.product)
        form.addRow("Quantity", self.quantity)
        form.addRow("Purchase Cost RM", self.cost)
        form.addRow("", add_item)
        root.addLayout(form)
        self.items = QTableWidget(0, 4)
        self.items.setHorizontalHeaderLabels(
            ["Product ID", "Product", "Quantity", "Purchase Cost RM"]
        )
        self.items.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        root.addWidget(self.items)
        payment_form = QFormLayout()
        self.paid = QDoubleSpinBox()
        self.paid.setDecimals(2)
        self.paid.setMaximum(99999999)
        self.method = QComboBox()
        self.method.addItems(["CASH", "CARD", "DUITNOW_QR"])
        payment_form.addRow("Initial Paid RM", self.paid)
        payment_form.addRow("Payment Method", self.method)
        root.addLayout(payment_form)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.save_button = buttons.button(QDialogButtonBox.StandardButton.Save)
        root.addWidget(buttons)
        self.product_note = QLabel()
        root.insertWidget(0, self.product_note)
        self.supplier.currentIndexChanged.connect(self._supplier_changed)
        self._load_supplier_products()

    def _supplier_changed(self, _index: int) -> None:
        self.items.setRowCount(0)
        self._load_supplier_products()

    def _load_supplier_products(self) -> None:
        self.product.clear()
        supplier_id = self.supplier.currentData()
        if supplier_id is not None:
            conn = self.database.connect(readonly=True)
            try:
                rows = conn.execute(
                    """SELECT p.id,p.name,p.cost_cents FROM supplier_products sp
                       JOIN products p ON p.id=sp.product_id
                       WHERE sp.supplier_id=? AND sp.is_active=1 AND p.is_deleted=0
                       ORDER BY p.name COLLATE NOCASE""",
                    (supplier_id,),
                ).fetchall()
            finally:
                conn.close()
            for row in rows:
                self.product.addItem(
                    str(row["name"]), (int(row["id"]), int(row["cost_cents"]))
                )
        available = self.supplier.count() > 0 and self.product.count() > 0
        self.save_button.setEnabled(available)
        self.product_note.setText(
            ""
            if available
            else "请先在供应商页面建立供应商，并为该供应商登记供货商品。"
        )
        self._product_changed()

    def _product_changed(self) -> None:
        data = self.product.currentData()
        if data:
            self.cost.setValue(data[1] / 100)

    def add_item(self) -> None:
        if self.product.currentIndex() < 0:
            return
        product_id, _ = self.product.currentData()
        for existing_row in range(self.items.rowCount()):
            if int(self.items.item(existing_row, 0).text()) == int(product_id):
                current = Decimal(self.items.item(existing_row, 2).text())
                updated = current + Decimal(str(self.quantity.value()))
                self.items.item(existing_row, 2).setText(str(updated))
                self.items.item(existing_row, 3).setText(f"{self.cost.value():.2f}")
                return
        row = self.items.rowCount()
        self.items.insertRow(row)
        for col, value in enumerate(
            (
                product_id,
                self.product.currentText(),
                self.quantity.value(),
                f"{self.cost.value():.2f}",
            )
        ):
            self.items.setItem(row, col, QTableWidgetItem(str(value)))

    def value(self) -> tuple[int, list[PurchaseLine], int, str]:
        if self.supplier.currentData() is None:
            raise ValueError("supplier is required")
        if self.items.rowCount() == 0:
            raise ValueError("purchase has no items")
        lines = [
            PurchaseLine(
                int(self.items.item(row, 0).text()),
                Decimal(self.items.item(row, 2).text()),
                round(float(self.items.item(row, 3).text()) * 100),
            )
            for row in range(self.items.rowCount())
        ]
        return (
            int(self.supplier.currentData()),
            lines,
            round(self.paid.value() * 100),
            self.method.currentText(),
        )


class PurchasesPage(PagedTablePage):
    def __init__(self, database: Database, user: AuthenticatedUser):
        self.user = user
        super().__init__(
            database,
            "进货管理",
            ["ID", "Purchase No", "供应商", "日期", "总额", "已付", "状态"],
        )
        self.add_action("＋ 新建进货", self.new_purchase, style="PrimaryButton")
        self.add_action("记录供应商付款", self.supplier_payment, style="SuccessButton")
        self.add_action("删除进货", self.delete_purchase, style="DangerButton")
        self.add_action("刷新", self.refresh)
        self.refresh()

    def refresh(self) -> None:
        conn = self.database.connect(readonly=True)
        try:
            rows = conn.execute(
                """SELECT p.id, p.purchase_no, COALESCE(s.name,''), p.purchased_at,
                   printf('RM %.2f',p.total_cents/100.0), printf('RM %.2f',p.paid_cents/100.0), p.status
                   FROM purchases p LEFT JOIN suppliers s ON s.id=p.supplier_id
                   ORDER BY p.purchased_at DESC LIMIT ? OFFSET ?""",
                (self.page_size, self.offset),
            ).fetchall()
            self.set_rows([tuple(row) for row in rows])
        finally:
            conn.close()

    def new_purchase(self) -> None:
        dialog = NewPurchaseDialog(self.database, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            supplier_id, lines, paid, method = dialog.value()
            PurchaseService(self.database).create_purchase(
                supplier_id=supplier_id,
                lines=lines,
                paid_cents=paid,
                payment_method=method,
                operator_id=self.user.id,
            )
            self.refresh()
        except Exception as exc:
            QMessageBox.warning(self, "Purchase", str(exc))

    def delete_purchase(self) -> None:
        purchase_id = self.selected_id()
        if purchase_id is None:
            QMessageBox.information(self, "Purchase", "请先选择进货记录。")
            return
        if (
            QMessageBox.question(
                self,
                "Delete Purchase",
                "删除会反向扣减该进货加入的库存，并保留审计记录。确认继续？",
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        try:
            PurchaseService(self.database).delete_purchase(
                purchase_id=purchase_id, admin_id=self.user.id
            )
            self.refresh()
        except Exception as exc:
            QMessageBox.warning(self, "Delete Purchase", str(exc))

    def supplier_payment(self) -> None:
        purchase_id = self.selected_id()
        if purchase_id is None:
            QMessageBox.information(self, "Payment", "请先选择进货记录。")
            return
        conn = self.database.connect(readonly=True)
        try:
            row = conn.execute(
                """SELECT total_cents-paid_cents balance_cents FROM purchases
                   WHERE id=? AND is_deleted=0""",
                (purchase_id,),
            ).fetchone()
        finally:
            conn.close()
        if row is None or int(row["balance_cents"]) <= 0:
            QMessageBox.information(self, "Payment", "这张进货单没有未结余额。")
            return
        dialog = RecordPaymentDialog(
            title="Supplier Payment / 供应商付款",
            balance_cents=int(row["balance_cents"]),
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        amount_cents, method, note = dialog.value()
        try:
            SupplierPaymentService(self.database).record_payment(
                purchase_id=purchase_id,
                amount_cents=amount_cents,
                payment_method=method,
                note=note,
                operator_id=self.user.id,
            )
            self.refresh()
        except Exception as exc:
            QMessageBox.warning(self, "Supplier Payment", str(exc))


class EntityDialog(QDialog):
    def __init__(self, entity: str, parent=None, *, row=None):
        super().__init__(parent)
        self.entity = entity
        self.setWindowTitle(
            ("Edit" if row is not None else "Add")
            + (" Customer / 客户" if entity == "customers" else " Supplier / 供应商")
        )
        self.setMinimumWidth(520)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.name = QLineEdit()
        self.phone = QLineEdit()
        self.email = QLineEdit()
        self.notes = QTextEdit()
        form.addRow("Name *", self.name)
        form.addRow("Phone / 手机号", self.phone)
        if entity == "suppliers":
            form.addRow("Email", self.email)
        form.addRow("Notes / 备注", self.notes)
        layout.addLayout(form)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._validate)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        if row is not None:
            self.name.setText(str(row["name"]))
            self.phone.setText(str(row["phone"] or ""))
            if entity == "suppliers":
                self.email.setText(str(row["email"] or ""))
            self.notes.setPlainText(str(row["notes"] or ""))

    def _validate(self) -> None:
        if not self.name.text().strip():
            QMessageBox.warning(self, "Record", "Name is required.")
            return
        self.accept()

    def value(self) -> EntityInput:
        return EntityInput(
            name=self.name.text(),
            phone=self.phone.text(),
            email=self.email.text(),
            notes=self.notes.toPlainText(),
        )


class SupplierProductsDialog(QDialog):
    def __init__(
        self,
        database: Database,
        supplier_id: int,
        supplier_name: str,
        parent=None,
    ):
        super().__init__(parent)
        self.database = database
        self.supplier_id = supplier_id
        self.setWindowTitle(f"Supplier Products / {supplier_name}")
        self.setMinimumSize(760, 580)
        root = QVBoxLayout(self)
        root.addWidget(QLabel("勾选此供应商实际供应的商品。一个商品可以属于多个供应商。"))
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["ID", "商品", "SKU", "供应"])
        self.table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        root.addWidget(self.table)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self._load()

    def _load(self) -> None:
        selected = EntityService(
            self.database, "suppliers"
        ).supplier_product_ids(self.supplier_id)
        conn = self.database.connect(readonly=True)
        try:
            rows = conn.execute(
                """SELECT id,name,COALESCE(sku,'') sku FROM products
                   WHERE is_deleted=0 ORDER BY name COLLATE NOCASE"""
            ).fetchall()
        finally:
            conn.close()
        self.table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            self.table.setItem(row_index, 0, QTableWidgetItem(str(row["id"])))
            self.table.setItem(row_index, 1, QTableWidgetItem(str(row["name"])))
            self.table.setItem(row_index, 2, QTableWidgetItem(str(row["sku"])))
            check = QCheckBox()
            check.setChecked(int(row["id"]) in selected)
            self.table.setCellWidget(row_index, 3, check)

    def selected_product_ids(self) -> set[int]:
        return {
            int(self.table.item(row, 0).text())
            for row in range(self.table.rowCount())
            if self.table.cellWidget(row, 3).isChecked()
        }


class EntityPage(PagedTablePage):
    def __init__(self, database: Database, user: AuthenticatedUser, entity: str):
        self.entity = entity
        self.user = user
        title = "客户与欠账" if entity == "customers" else "供应商与付款"
        columns = ["ID", "Name", "Phone", "Email", "Notes", "Balance"]
        super().__init__(database, title, columns)
        self.add_action("＋ 新增", self.add_entity, style="PrimaryButton")
        self.add_action("编辑", self.edit_entity, style="WarningButton")
        if entity == "suppliers":
            self.add_action("供货商品", self.manage_supplier_products, style="PrimaryButton")
        self.add_action(
            "记录还款" if entity == "customers" else "记录付款",
            self.payment,
            style="SuccessButton",
        )
        self.add_action("删除", self.delete_entity, style="DangerButton")
        self.add_action("刷新", self.refresh)
        self.refresh()

    def refresh(self) -> None:
        conn = self.database.connect(readonly=True)
        try:
            if self.entity == "customers":
                rows = conn.execute(
                    """SELECT c.id,c.name,c.phone,'' email,c.notes,
                              printf('RM %.2f',COALESCE(SUM(d.balance_cents),0)/100.0)
                       FROM customers c LEFT JOIN customer_debts d ON d.customer_id=c.id AND d.status='OPEN'
                       WHERE c.is_deleted=0 GROUP BY c.id ORDER BY c.name LIMIT ? OFFSET ?""",
                    (self.page_size, self.offset),
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT s.id,s.name,s.phone,s.email,s.notes,
                              printf('RM %.2f',COALESCE(SUM(p.total_cents-p.paid_cents),0)/100.0)
                       FROM suppliers s LEFT JOIN purchases p ON p.supplier_id=s.id
                       WHERE s.is_deleted=0 GROUP BY s.id ORDER BY s.name LIMIT ? OFFSET ?""",
                    (self.page_size, self.offset),
                ).fetchall()
            self.set_rows([tuple(row) for row in rows])
        finally:
            conn.close()

    def add_entity(self) -> None:
        dialog = EntityDialog(self.entity, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            EntityService(self.database, self.entity).add(
                dialog.value(), admin_id=self.user.id
            )
            self.refresh()
        except Exception as exc:
            QMessageBox.warning(self, "Record", str(exc))

    def edit_entity(self) -> None:
        entity_id = self.selected_id()
        if entity_id is None:
            QMessageBox.information(self, "Record", "请先选择记录。")
            return
        conn = self.database.connect(readonly=True)
        try:
            row = conn.execute(
                f"SELECT * FROM {self.entity} WHERE id=? AND is_deleted=0",
                (entity_id,),
            ).fetchone()
        finally:
            conn.close()
        if row is None:
            return
        dialog = EntityDialog(self.entity, self, row=row)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            EntityService(self.database, self.entity).update(
                entity_id, dialog.value(), admin_id=self.user.id
            )
            self.refresh()
        except Exception as exc:
            QMessageBox.warning(self, "Record", str(exc))

    def delete_entity(self) -> None:
        entity_id = self.selected_id()
        if entity_id is None:
            QMessageBox.information(self, "Record", "请先选择记录。")
            return
        label = "客户" if self.entity == "customers" else "供应商"
        if (
            QMessageBox.question(
                self,
                "Delete",
                f"确认删除所选{label}？历史交易仍会保留。",
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        try:
            EntityService(self.database, self.entity).delete(
                entity_id, admin_id=self.user.id
            )
            self.refresh()
        except Exception as exc:
            QMessageBox.warning(self, "Delete", str(exc))

    def manage_supplier_products(self) -> None:
        if self.entity != "suppliers":
            return
        supplier_id = self.selected_id()
        row = self.table.currentRow()
        if supplier_id is None or row < 0:
            QMessageBox.information(self, "Supplier", "请先选择供应商。")
            return
        dialog = SupplierProductsDialog(
            self.database, supplier_id, self.table.item(row, 1).text(), self
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            EntityService(self.database, "suppliers").set_supplier_products(
                supplier_id,
                dialog.selected_product_ids(),
                admin_id=self.user.id,
            )
        except Exception as exc:
            QMessageBox.warning(self, "Supplier Products", str(exc))
            return
        QMessageBox.information(self, "Supplier Products", "供应商商品目录已保存。")

    def payment(self) -> None:
        entity_id = self.selected_id()
        if entity_id is None:
            QMessageBox.information(self, "Payment", "请先选择记录。")
            return
        conn = self.database.connect(readonly=True)
        try:
            if self.entity == "customers":
                target = conn.execute(
                    "SELECT id,balance_cents FROM customer_debts WHERE customer_id=? AND status='OPEN' ORDER BY opened_at LIMIT 1",
                    (entity_id,),
                ).fetchone()
            else:
                target = conn.execute(
                    "SELECT id,total_cents-paid_cents balance_cents FROM purchases WHERE supplier_id=? AND status<>'PAID' ORDER BY purchased_at LIMIT 1",
                    (entity_id,),
                ).fetchone()
        finally:
            conn.close()
        if target is None:
            QMessageBox.information(self, "Payment", "没有未结余额。")
            return
        dialog = RecordPaymentDialog(
            title=(
                "Customer Payment / 客户还款"
                if self.entity == "customers"
                else "Supplier Payment / 供应商付款"
            ),
            balance_cents=int(target["balance_cents"]),
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        amount_cents, method, note = dialog.value()
        try:
            if self.entity == "customers":
                CustomerPaymentService(self.database).record_payment(
                    debt_id=int(target["id"]),
                    amount_cents=amount_cents,
                    payment_method=method,
                    note=note,
                    operator_id=self.user.id,
                )
            else:
                SupplierPaymentService(self.database).record_payment(
                    purchase_id=int(target["id"]),
                    amount_cents=amount_cents,
                    payment_method=method,
                    note=note,
                    operator_id=self.user.id,
                )
            self.refresh()
        except Exception as exc:
            QMessageBox.warning(self, "Payment", str(exc))


class StocktakeCountDialog(QDialog):
    def __init__(self, database: Database, stocktake_id: int, parent=None):
        super().__init__(parent)
        self.database = database
        self.stocktake_id = stocktake_id
        self.original_counts: dict[int, Decimal] = {}
        self.setWindowTitle("Stock Adjustment / 盘点数量")
        self.setMinimumSize(920, 620)
        root = QVBoxLayout(self)
        title = QLabel("输入实际盘点数量；完成盘点后才会调整库存。")
        title.setObjectName("SectionTitle")
        root.addWidget(title)
        self.table = QTableWidget(0, 7)
        self.table.setObjectName("StocktakeCountTable")
        self.table.setHorizontalHeaderLabels(
            ["Product ID", "商品", "System", "Physical", "Variance", "Unit", "Location"]
        )
        self.table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self.table.verticalHeader().setVisible(False)
        root.addWidget(self.table, 1)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self._load()

    def _load(self) -> None:
        conn = self.database.connect(readonly=True)
        try:
            rows = conn.execute(
                """SELECT product_id,product_name_snapshot,system_stock_decimal,
                          physical_count_decimal,variance_decimal,unit_snapshot,location_snapshot
                   FROM stocktake_items WHERE stocktake_id=?
                   ORDER BY product_name_snapshot COLLATE NOCASE""",
                (self.stocktake_id,),
            ).fetchall()
        finally:
            conn.close()
        self.table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            product_id = int(row["product_id"])
            physical = Decimal(str(row["physical_count_decimal"]))
            self.original_counts[product_id] = physical
            values = (
                product_id,
                row["product_name_snapshot"],
                row["system_stock_decimal"],
                "",
                row["variance_decimal"],
                row["unit_snapshot"],
                row["location_snapshot"],
            )
            for column, value in enumerate(values):
                self.table.setItem(row_index, column, QTableWidgetItem(str(value)))
            control = QDoubleSpinBox()
            control.setObjectName("PhysicalCountInput")
            control.setDecimals(3)
            control.setRange(0, 999999999)
            control.setValue(float(physical))
            control.valueChanged.connect(
                lambda value, row_no=row_index, system=Decimal(
                    str(row["system_stock_decimal"])
                ): self.table.item(row_no, 4).setText(
                    str(Decimal(str(value)) - system)
                )
            )
            self.table.setCellWidget(row_index, 3, control)

    def save(self) -> None:
        service = StocktakeService(self.database)
        for row in range(self.table.rowCount()):
            product_id = int(self.table.item(row, 0).text())
            control = self.table.cellWidget(row, 3)
            physical = Decimal(str(control.value()))
            if physical != self.original_counts[product_id]:
                service.set_physical_count(
                    stocktake_id=self.stocktake_id,
                    product_id=product_id,
                    count=physical,
                )
        self.accept()


class StocktakePage(PagedTablePage):
    def __init__(self, database: Database, user: AuthenticatedUser):
        self.user = user
        super().__init__(
            database,
            "库存盘点",
            ["ID", "Stocktake No", "开始", "完成", "商品数", "差异", "状态"],
        )
        self.add_action("＋ 新建盘点", self.create, style="PrimaryButton")
        self.add_action("盘点数量 / 库存调整", self.edit_counts, style="WarningButton")
        self.add_action("完成盘点", self.complete, style="SuccessButton")
        self.add_action("刷新", self.refresh)
        self.refresh()

    def refresh(self) -> None:
        conn = self.database.connect(readonly=True)
        try:
            rows = conn.execute(
                "SELECT id,stocktake_no,started_at,COALESCE(completed_at,''),product_count,variance_count,status FROM stocktakes ORDER BY started_at DESC LIMIT ? OFFSET ?",
                (self.page_size, self.offset),
            ).fetchall()
            self.set_rows([tuple(row) for row in rows])
        finally:
            conn.close()

    def create(self) -> None:
        StocktakeService(self.database).create_draft(operator_id=self.user.id)
        self.refresh()

    def edit_counts(self) -> None:
        stocktake_id = self.selected_id()
        if stocktake_id is None:
            QMessageBox.information(self, "Stocktake", "请先选择草稿盘点。")
            return
        dialog = StocktakeCountDialog(self.database, stocktake_id, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.refresh()

    def complete(self) -> None:
        stocktake_id = self.selected_id()
        if stocktake_id is None:
            return
        try:
            StocktakeService(self.database).complete(
                stocktake_id=stocktake_id, operator_id=self.user.id
            )
            self.refresh()
        except Exception as exc:
            QMessageBox.warning(self, "Stocktake", str(exc))


class AuditPage(PagedTablePage):
    def __init__(self, database: Database, user: AuthenticatedUser):
        super().__init__(
            database,
            "Audit Log",
            ["ID", "When", "Who", "Action", "Module", "Record", "Before", "After"],
        )
        self.user = user
        self.add_action("清除 Audit Log", self.clear_logs, style="DangerButton")
        self.add_action("刷新", self.refresh, style="PrimaryButton")
        self.refresh()

    def refresh(self) -> None:
        conn = self.database.connect(readonly=True)
        try:
            rows = conn.execute(
                "SELECT id,occurred_at,username_snapshot,action,module,record_type||' #'||record_id,COALESCE(old_value_json,''),COALESCE(new_value_json,'') FROM audit_logs ORDER BY occurred_at DESC,id DESC LIMIT ? OFFSET ?",
                (self.page_size, self.offset),
            ).fetchall()
            self.set_rows([tuple(row) for row in rows])
        finally:
            conn.close()

    def clear_logs(self) -> None:
        if (
            QMessageBox.question(
                self,
                "Clear Audit Log",
                "将清除全部审计记录。系统会先自动备份数据库。确认继续？",
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        password, ok = QInputDialog.getText(
            self,
            "Admin Verification",
            "Current Admin Password",
            QLineEdit.EchoMode.Password,
        )
        if not ok:
            return
        try:
            result = AuditMaintenanceService(
                self.database, AppPaths.default().backups
            ).clear(admin_id=self.user.id, password=password)
        except Exception as exc:
            QMessageBox.warning(self, "Clear Audit Log", str(exc))
            return
        self.refresh()
        QMessageBox.information(
            self,
            "Clear Audit Log",
            f"已清除 {result.removed_count} 条记录，并完成安全备份。",
        )


class MaintenancePage(QWidget):
    def __init__(self, database: Database, user: AuthenticatedUser):
        super().__init__()
        self.database = database
        self.user = user
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 20)
        title = QLabel("数据维护")
        title.setObjectName("PageTitle")
        root.addWidget(title)
        self.info = QLabel()
        self.info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        root.addWidget(self.info)
        buttons = QHBoxLayout()
        self.action_buttons: dict[str, QPushButton] = {}
        for text, callback, style in (
            ("Run Integrity Check", self.integrity, "PrimaryButton"),
            ("Backup", self.backup, "SuccessButton"),
            ("Restore", self.restore, "WarningButton"),
            ("Open Error Log Folder", self.open_log_folder, ""),
        ):
            button = QPushButton(text)
            button.setObjectName(style)
            button.setProperty("acceptanceName", text.replace(" ", ""))
            button.clicked.connect(callback)
            self.action_buttons[text] = button
            buttons.addWidget(button)
        root.addLayout(buttons)
        root.addStretch(1)
        self.refresh()

    def refresh(self) -> None:
        conn = self.database.connect(readonly=True)
        try:
            products = conn.execute(
                "SELECT COUNT(*) FROM products WHERE is_deleted=0"
            ).fetchone()[0]
            sales = conn.execute("SELECT COUNT(*) FROM sales").fetchone()[0]
            version = conn.execute("PRAGMA user_version").fetchone()[0]
        finally:
            conn.close()
        self.info.setText(
            f"App Version: {APP_VERSION}\nDB Schema Version: {version}\nDatabase Path: {self.database.path}\n"
            f"Backup Path: {AppPaths.default().backups}\nLog Path: {AppPaths.default().logs}\n"
            f"Export Path: {AppPaths.default().exports}\nReceipt Path: {AppPaths.default().receipts}\n"
            f"Database Size: {self.database.path.stat().st_size:,} bytes\n"
            f"Product Count: {products}\nSale Count: {sales}"
        )

    def integrity(self) -> None:
        ok, messages = self.database.integrity_check()
        QMessageBox.information(
            self,
            "Integrity",
            "PASS: " + " | ".join(messages) if ok else "FAIL: " + " | ".join(messages),
        )

    def backup(self) -> None:
        service = BackupService(AppPaths.default().backups)
        result = service.create(
            self.database.path, reason="manual"
        )
        service.prune(keep=30)
        QMessageBox.information(self, "Backup", str(result.path))

    def restore(self) -> None:
        backup_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select CNKH POS Backup",
            str(AppPaths.default().backups),
            "SQLite Backup (*.db);;All Files (*)",
            options=QFileDialog.Option.DontUseNativeDialog,
        )
        if not backup_path:
            return
        password, ok = QInputDialog.getText(
            self,
            "Admin Verification",
            "Current Admin Password",
            QLineEdit.EchoMode.Password,
        )
        if not ok:
            return
        try:
            safety = RestoreService(
                self.database, AppPaths.default().backups
            ).restore(
                backup_path,
                admin_id=self.user.id,
                password=password,
            )
        except Exception as exc:
            QMessageBox.warning(self, "Restore", str(exc))
            return
        self.refresh()
        QMessageBox.information(
            self, "Restore", f"恢复成功。替换前安全备份：{safety}"
        )

    def open_log_folder(self) -> None:
        paths = AppPaths.default()
        paths.ensure_directories()
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(paths.logs))):
            QMessageBox.information(self, "Error Log", str(paths.logs))
