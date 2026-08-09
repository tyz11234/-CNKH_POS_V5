from __future__ import annotations

from decimal import Decimal

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
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
    QVBoxLayout,
    QWidget,
)

from cnkh_pos.config import APP_VERSION, AppPaths
from cnkh_pos.database.connection import Database
from cnkh_pos.database.migrations import utc_now_text
from cnkh_pos.services.auth import AuthenticatedUser
from cnkh_pos.services.backup import BackupService
from cnkh_pos.services.catalog import CatalogService, ProductInput
from cnkh_pos.services.money import rm_to_cents
from cnkh_pos.services.restore import RestoreService
from cnkh_pos.services.stocktake import StocktakeService
from cnkh_pos.services.purchases import PurchaseLine, PurchaseService
from cnkh_pos.services.payments import CustomerPaymentService, SupplierPaymentService


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
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("新增商品")
        self.setMinimumWidth(520)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.name = QLineEdit()
        self.aliases = QLineEdit()
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

    def value(self) -> ProductInput:
        return ProductInput(
            name=self.name.text(),
            aliases=self.aliases.text(),
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
        dialog = ProductDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            CatalogService(self.database).add_product(
                dialog.value(), admin_id=self.user.id
            )
            self.refresh()
        except Exception as exc:
            QMessageBox.warning(self, "Product", str(exc))

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


class SalesPage(PagedTablePage):
    def __init__(self, database: Database):
        super().__init__(
            database,
            "销售记录",
            ["ID", "Receipt No", "时间", "总额", "付款方式", "状态"],
        )
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
            products = conn.execute(
                "SELECT id,name,cost_cents FROM products WHERE is_deleted=0 ORDER BY name"
            ).fetchall()
        finally:
            conn.close()
        for row in suppliers:
            self.supplier.addItem(str(row["name"]), int(row["id"]))
        self.product = QComboBox()
        for row in products:
            self.product.addItem(
                str(row["name"]), (int(row["id"]), int(row["cost_cents"]))
            )
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
        root.addWidget(buttons)
        self._product_changed()

    def _product_changed(self) -> None:
        data = self.product.currentData()
        if data:
            self.cost.setValue(data[1] / 100)

    def add_item(self) -> None:
        if self.product.currentIndex() < 0:
            return
        product_id, _ = self.product.currentData()
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
        supplier_id, lines, paid, method = dialog.value()
        try:
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

    def supplier_payment(self) -> None:
        purchase_id = self.selected_id()
        if purchase_id is None:
            QMessageBox.information(self, "Payment", "请先选择进货记录。")
            return
        amount, ok = QInputDialog.getDouble(
            self, "Supplier Payment", "Amount RM", 0, 0.01, 99999999, 2
        )
        if not ok:
            return
        method, ok = QInputDialog.getItem(
            self, "Payment Method", "Method", ["CASH", "CARD", "DUITNOW_QR"], 0, False
        )
        if not ok:
            return
        try:
            SupplierPaymentService(self.database).record_payment(
                purchase_id=purchase_id,
                amount_cents=round(amount * 100),
                payment_method=method,
                note="Admin payment dialog",
                operator_id=self.user.id,
            )
            self.refresh()
        except Exception as exc:
            QMessageBox.warning(self, "Supplier Payment", str(exc))


class EntityPage(PagedTablePage):
    def __init__(self, database: Database, user: AuthenticatedUser, entity: str):
        self.entity = entity
        self.user = user
        title = "客户与欠账" if entity == "customers" else "供应商与付款"
        columns = ["ID", "Name", "Phone", "Email / Notes", "Balance"]
        super().__init__(database, title, columns)
        self.add_action("＋ 新增", self.add_entity, style="PrimaryButton")
        self.add_action(
            "记录还款" if entity == "customers" else "记录付款",
            self.payment,
            style="SuccessButton",
        )
        self.add_action("刷新", self.refresh)
        self.refresh()

    def refresh(self) -> None:
        conn = self.database.connect(readonly=True)
        try:
            if self.entity == "customers":
                rows = conn.execute(
                    """SELECT c.id,c.name,c.phone,c.notes,printf('RM %.2f',COALESCE(SUM(d.balance_cents),0)/100.0)
                       FROM customers c LEFT JOIN customer_debts d ON d.customer_id=c.id AND d.status='OPEN'
                       WHERE c.is_deleted=0 GROUP BY c.id ORDER BY c.name LIMIT ? OFFSET ?""",
                    (self.page_size, self.offset),
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT s.id,s.name,s.phone,s.email,printf('RM %.2f',COALESCE(SUM(p.total_cents-p.paid_cents),0)/100.0)
                       FROM suppliers s LEFT JOIN purchases p ON p.supplier_id=s.id
                       WHERE s.is_deleted=0 GROUP BY s.id ORDER BY s.name LIMIT ? OFFSET ?""",
                    (self.page_size, self.offset),
                ).fetchall()
            self.set_rows([tuple(row) for row in rows])
        finally:
            conn.close()

    def add_entity(self) -> None:
        name, ok = QInputDialog.getText(self, "Add", "Name")
        if not ok or not name.strip():
            return
        now = utc_now_text()
        with self.database.transaction() as conn:
            conn.execute(
                f"INSERT INTO {self.entity}(name, created_at, updated_at) VALUES (?, ?, ?)",
                (name.strip(), now, now),
            )
        self.refresh()

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
        amount, ok = QInputDialog.getDouble(
            self,
            "Payment",
            "Amount RM",
            target["balance_cents"] / 100,
            0.01,
            target["balance_cents"] / 100,
            2,
        )
        if not ok:
            return
        try:
            if self.entity == "customers":
                CustomerPaymentService(self.database).record_payment(
                    debt_id=int(target["id"]),
                    amount_cents=round(amount * 100),
                    payment_method="CASH",
                    note="Admin payment dialog",
                    operator_id=self.user.id,
                )
            else:
                SupplierPaymentService(self.database).record_payment(
                    purchase_id=int(target["id"]),
                    amount_cents=round(amount * 100),
                    payment_method="CASH",
                    note="Admin payment dialog",
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
    def __init__(self, database: Database):
        super().__init__(
            database,
            "Audit Log",
            ["ID", "When", "Who", "Action", "Module", "Record", "Before", "After"],
        )
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
            f"Database Size: {self.database.path.stat().st_size:,} bytes\nProduct Count: {products}\nSale Count: {sales}"
        )

    def integrity(self) -> None:
        ok, messages = self.database.integrity_check()
        QMessageBox.information(
            self,
            "Integrity",
            "PASS: " + " | ".join(messages) if ok else "FAIL: " + " | ".join(messages),
        )

    def backup(self) -> None:
        result = BackupService(AppPaths.default().backups).create(
            self.database.path, reason="manual"
        )
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
