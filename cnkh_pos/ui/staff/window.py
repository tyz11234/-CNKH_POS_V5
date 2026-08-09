from __future__ import annotations

import os
from decimal import Decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QDoubleSpinBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from cnkh_pos.database.connection import Database
from cnkh_pos.services.auth import AuthenticatedUser
from cnkh_pos.services.money import format_myr
from cnkh_pos.services.product_search import search_products
from cnkh_pos.services.sales import SaleLine, SalesService
from cnkh_pos.services.held_orders import HeldOrderService
from cnkh_pos.services.printing import PrintingService
from cnkh_pos.config import AppPaths
from cnkh_pos.ui.dialogs.checkout import CheckoutDialog, SaleCompletedDialog
from cnkh_pos.ui.widgets import Card


PRODUCTS = [
    ("PVC Cable 1.5mm", "PVC1.5", "955501010001", "RM 2.10", "150", "roll"),
    ("PVC Cable 2.5mm", "PVC2.5", "955501010002", "RM 2.80", "120", "roll"),
    ("PVC Cable 4.0mm", "PVC4.0", "955501010003", "RM 4.60", "85", "roll"),
    ("Hammer 2lb", "HAM2LB", "955501020001", "RM 15.90", "65", "pcs"),
    ("Screwdriver Set 6pcs", "SDR6PCS", "955501030001", "RM 18.90", "40", "set"),
    ("Pipe 20mm", "PIPE20", "955501040020", "RM 4.50", "80", "meter"),
    ("Pipe 25mm", "PIPE25", "955501040025", "RM 6.20", "60", "meter"),
    ("PVC Glue 500ml", "GLUE500", "955501050500", "RM 12.50", "35", "pcs"),
]


class StaffWindow(QMainWindow):
    def __init__(self, database: Database, user: AuthenticatedUser):
        super().__init__()
        self.database = database
        self.user = user
        self.cart_quantities: dict[int, Decimal] = {}
        self.cart_discounts: dict[int, int] = {}
        self.visible_product_ids: list[int] = []
        self.setWindowTitle("CNKH POS Staff — V5.0")
        self.setMinimumSize(1120, 720)
        self.resize(1360, 850)
        canvas = QWidget()
        canvas.setObjectName("AppCanvas")
        root = QVBoxLayout(canvas)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._top_bar())

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(18, 16, 18, 18)
        body_layout.setSpacing(12)
        body_layout.addLayout(self._search_bar())
        body_layout.addWidget(self._search_results())

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self._product_panel())
        splitter.addWidget(self._cart_panel())
        splitter.setSizes([680, 520])
        body_layout.addWidget(splitter, 1)
        root.addWidget(body, 1)
        self.setCentralWidget(canvas)
        self._load_product_table()
        self._filter_results("")

    def _top_bar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("TopBar")
        bar.setFixedHeight(58)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(20, 0, 20, 0)
        title = QLabel("☰    收银台 (POS)")
        title.setObjectName("TopBarTitle")
        user = QLabel(f"● 收银员：{self.user.display_name}")
        user.setObjectName("TopBarMeta")
        layout.addWidget(title)
        layout.addStretch(1)
        layout.addWidget(user)
        return bar

    def _search_bar(self) -> QHBoxLayout:
        layout = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setObjectName("SearchInput")
        self.search.setPlaceholderText(
            "扫描 / 输入条码、商品名称、SKU、Alias、Category、Location"
        )
        self.search.textChanged.connect(self._filter_results)
        button = QPushButton("搜索商品")
        button.setObjectName("PrimaryButton")
        button.setMinimumHeight(50)
        layout.addWidget(self.search, 1)
        layout.addWidget(button)
        return layout

    def _search_results(self) -> QTableWidget:
        self.results = QTableWidget(0, 6)
        self.results.setHorizontalHeaderLabels(
            ["商品名称", "SKU", "Barcode", "售价", "库存", "单位"]
        )
        self.results.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        for column in range(1, 6):
            self.results.horizontalHeader().setSectionResizeMode(
                column, QHeaderView.ResizeMode.ResizeToContents
            )
        self.results.verticalHeader().setVisible(False)
        self.results.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.results.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.results.setMaximumHeight(146)
        self.results.cellClicked.connect(self._result_clicked)
        return self.results

    def _product_panel(self) -> Card:
        panel = Card(shadow=False)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 12, 12, 12)
        title = QLabel("商品列表")
        title.setObjectName("SectionTitle")
        layout.addWidget(title)
        self.products = QTableWidget(0, 6)
        self.products.setHorizontalHeaderLabels(
            ["商品名称", "SKU", "售价", "库存", "单位", "加入"]
        )
        self.products.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self.products.verticalHeader().setVisible(False)
        self.products.setAlternatingRowColors(True)
        self.products.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.products.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        layout.addWidget(self.products, 1)
        pager = QLabel("共 58 项商品        1    2    3    4    5    …    8    ›")
        pager.setObjectName("Muted")
        layout.addWidget(pager)
        return panel

    def _cart_panel(self) -> Card:
        panel = Card(shadow=False)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 12, 12, 12)
        header = QHBoxLayout()
        self.cart_title = QLabel("购物车 (0)")
        self.cart_title.setObjectName("SectionTitle")
        clear = QPushButton("清空")
        clear.setObjectName("DangerButton")
        clear.clicked.connect(self._clear_cart)
        header.addWidget(self.cart_title)
        header.addStretch(1)
        header.addWidget(clear)
        layout.addLayout(header)

        self.cart = QTableWidget(0, 6)
        self.cart.setHorizontalHeaderLabels(
            ["商品", "单价", "数量", "Discount", "小计", "删除"]
        )
        self.cart.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self.cart.verticalHeader().setVisible(False)
        self.cart.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        layout.addWidget(self.cart, 1)

        total = QHBoxLayout()
        total.addWidget(QLabel("总计金额"))
        total.addStretch(1)
        self.total_label = QLabel("RM 0.00")
        self.total_label.setObjectName("MoneyHero")
        total.addWidget(self.total_label)
        layout.addLayout(total)

        secondary = QGridLayout()
        for index, (text, name) in enumerate(
            (
                ("加入购物车", "PrimaryButton"),
                ("挂单", "WarningButton"),
                ("恢复挂单", "PrimaryButton"),
                ("取消订单", "DangerButton"),
            )
        ):
            button = QPushButton(text)
            button.setObjectName(name)
            if text == "挂单":
                self.hold_button = button
            elif text == "恢复挂单":
                self.retrieve_button = button
            elif text == "取消订单":
                button.clicked.connect(self._clear_cart)
            secondary.addWidget(button, index // 2, index % 2)
        layout.addLayout(secondary)
        discount = QPushButton("修改所选商品 Discount")
        discount.setObjectName("WarningButton")
        discount.clicked.connect(self._edit_discount)
        layout.addWidget(discount)
        self.hold_button.clicked.connect(self._hold_order)
        self.retrieve_button.clicked.connect(self._retrieve_order)
        reprint = QPushButton("重新打印上一张小票")
        reprint.clicked.connect(self._reprint_latest)
        layout.addWidget(reprint)
        checkout = QPushButton("结账   →")
        checkout.setObjectName("CheckoutButton")
        checkout.clicked.connect(self._checkout)
        layout.addWidget(checkout)
        return panel

    def _populate_table(self, table: QTableWidget, rows: list[tuple[str, ...]]) -> None:
        table.setRowCount(len(rows))
        for row, product in enumerate(rows):
            for col, value in enumerate(product):
                table.setItem(row, col, QTableWidgetItem(value))

    def _filter_results(self, query: str) -> None:
        self.results.setRowCount(0)
        if not query.strip():
            return
        conn = self.database.connect(readonly=True)
        try:
            matches = search_products(conn, query, limit=3)
        finally:
            conn.close()
        for result in matches:
            row = self.results.rowCount()
            self.results.insertRow(row)
            values = (
                result.name,
                result.sku,
                result.barcode,
                format_myr(result.price_cents),
                result.stock,
                result.unit,
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.ItemDataRole.UserRole, result.product_id)
                self.results.setItem(row, column, item)
        if len(matches) == 1 and matches[0].exact_barcode:
            self._add_to_cart(matches[0].product_id)
            self.search.clear()

    def _result_clicked(self, row: int, column: int) -> None:
        del column
        product_id = int(self.results.item(row, 0).data(Qt.ItemDataRole.UserRole))
        self._add_to_cart(product_id)
        self.search.clear()

    def _add_to_cart(self, product_id: int) -> None:
        self.cart_quantities[product_id] = self.cart_quantities.get(
            product_id, Decimal("0")
        ) + Decimal("1")
        self._rebuild_cart()

    def _checkout(self) -> None:
        total = self._cart_total()
        if not self.cart_quantities:
            QMessageBox.information(self, "Cart", "购物车是空的。")
            return
        dialog = CheckoutDialog(total, self._quick_amounts(), self)
        if dialog.exec() != CheckoutDialog.DialogCode.Accepted:
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
            result = SalesService(self.database).create_sale(
                lines=lines,
                payment_method=dialog.payment_method,
                paid_cents=dialog.paid_cents,
                cashier_id=self.user.id,
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

    def _load_product_table(self) -> None:
        conn = self.database.connect(readonly=True)
        try:
            rows = conn.execute(
                "SELECT id, name, COALESCE(sku,'') AS sku, selling_price_cents, stock_decimal, unit FROM products WHERE is_deleted=0 ORDER BY name COLLATE NOCASE LIMIT 100"
            ).fetchall()
        finally:
            conn.close()
        self.products.setRowCount(len(rows))
        self.visible_product_ids = []
        for row_index, product in enumerate(rows):
            product_id = int(product["id"])
            self.visible_product_ids.append(product_id)
            values = (
                product["name"],
                product["sku"],
                format_myr(product["selling_price_cents"]),
                product["stock_decimal"],
                product["unit"],
            )
            for column, value in enumerate(values):
                self.products.setItem(row_index, column, QTableWidgetItem(str(value)))
            add = QPushButton("＋")
            add.setObjectName("PrimaryButton")
            add.clicked.connect(
                lambda checked=False, pid=product_id: self._add_to_cart(pid)
            )
            self.products.setCellWidget(row_index, 5, add)

    def _rebuild_cart(self) -> None:
        self.cart.setRowCount(0)
        conn = self.database.connect(readonly=True)
        try:
            for product_id, quantity in self.cart_quantities.items():
                product = conn.execute(
                    "SELECT name, selling_price_cents FROM products WHERE id=?",
                    (product_id,),
                ).fetchone()
                if product is None:
                    continue
                row = self.cart.rowCount()
                self.cart.insertRow(row)
                discount_cents = self.cart_discounts.get(product_id, 0)
                subtotal = (
                    int(
                        (Decimal(product["selling_price_cents"]) * quantity).quantize(
                            Decimal("1")
                        )
                    )
                    - discount_cents
                )
                values = (
                    product["name"],
                    format_myr(product["selling_price_cents"]),
                    "",
                    format_myr(discount_cents),
                    format_myr(subtotal),
                )
                for column, value in enumerate(values):
                    item = QTableWidgetItem(str(value))
                    item.setData(Qt.ItemDataRole.UserRole, product_id)
                    self.cart.setItem(row, column, item)
                quantity_widget = QWidget()
                quantity_layout = QHBoxLayout(quantity_widget)
                quantity_layout.setContentsMargins(0, 0, 0, 0)
                minus = QPushButton("−")
                plus = QPushButton("+")
                spin = QDoubleSpinBox()
                spin.setDecimals(3)
                spin.setRange(0, 999999)
                spin.setValue(float(quantity))
                minus.clicked.connect(
                    lambda checked=False, pid=product_id, control=spin: (
                        self._set_quantity(pid, max(0, control.value() - 1))
                    )
                )
                plus.clicked.connect(
                    lambda checked=False, pid=product_id, control=spin: (
                        self._set_quantity(pid, control.value() + 1)
                    )
                )
                spin.editingFinished.connect(
                    lambda pid=product_id, control=spin: self._set_quantity(
                        pid, control.value()
                    )
                )
                quantity_layout.addWidget(minus)
                quantity_layout.addWidget(spin)
                quantity_layout.addWidget(plus)
                self.cart.setCellWidget(row, 2, quantity_widget)
                remove = QPushButton("×")
                remove.setObjectName("DangerButton")
                remove.clicked.connect(
                    lambda checked=False, pid=product_id: self._remove_cart(pid)
                )
                self.cart.setCellWidget(row, 5, remove)
        finally:
            conn.close()
        self.cart_title.setText(f"购物车 ({len(self.cart_quantities)})")
        self.total_label.setText(format_myr(self._cart_total()))

    def _remove_cart(self, product_id: int) -> None:
        self.cart_quantities.pop(product_id, None)
        self.cart_discounts.pop(product_id, None)
        self._rebuild_cart()

    def _clear_cart(self) -> None:
        self.cart_quantities.clear()
        self.cart_discounts.clear()
        self._rebuild_cart()

    def _cart_total(self) -> int:
        if not self.cart_quantities:
            return 0
        conn = self.database.connect(readonly=True)
        try:
            total = Decimal("0")
            for product_id, quantity in self.cart_quantities.items():
                row = conn.execute(
                    "SELECT selling_price_cents FROM products WHERE id=?", (product_id,)
                ).fetchone()
                if row:
                    total += Decimal(
                        row["selling_price_cents"]
                    ) * quantity - self.cart_discounts.get(product_id, 0)
            return int(total.quantize(Decimal("1")))
        finally:
            conn.close()

    def _set_quantity(self, product_id: int, value: float) -> None:
        quantity = Decimal(str(value))
        if quantity <= 0:
            self._remove_cart(product_id)
        else:
            self.cart_quantities[product_id] = quantity
            self._rebuild_cart()

    def _edit_discount(self) -> None:
        row = self.cart.currentRow()
        if row < 0:
            QMessageBox.information(self, "Discount", "请先选择购物车商品。")
            return
        product_id = int(self.cart.item(row, 0).data(Qt.ItemDataRole.UserRole))
        from PySide6.QtWidgets import QInputDialog

        amount, ok = QInputDialog.getDouble(
            self,
            "Discount",
            "Discount RM",
            self.cart_discounts.get(product_id, 0) / 100,
            0,
            100000,
            2,
        )
        if ok:
            self.cart_discounts[product_id] = round(amount * 100)
            self._rebuild_cart()

    def _quick_amounts(self) -> list[int]:
        conn = self.database.connect(readonly=True)
        try:
            return [
                int(row[0])
                for row in conn.execute(
                    "SELECT amount_cents FROM quick_amounts WHERE is_enabled=1 ORDER BY sort_order, id"
                )
            ]
        finally:
            conn.close()

    def _hold_order(self) -> None:
        payload = {
            "items": [
                {
                    "product_id": product_id,
                    "quantity": str(quantity),
                    "discount_cents": self.cart_discounts.get(product_id, 0),
                }
                for product_id, quantity in self.cart_quantities.items()
            ]
        }
        try:
            held = HeldOrderService(self.database).hold(
                payload, cashier_id=self.user.id
            )
        except Exception as exc:
            QMessageBox.warning(self, "Hold Order", str(exc))
            return
        self._clear_cart()
        QMessageBox.information(self, "Hold Order", f"已挂单：{held.hold_no}")

    def _retrieve_order(self) -> None:
        try:
            held = HeldOrderService(self.database).retrieve_latest(
                cashier_id=self.user.id
            )
        except Exception as exc:
            QMessageBox.warning(self, "Retrieve Order", str(exc))
            return
        self.cart_quantities = {
            int(item["product_id"]): Decimal(str(item["quantity"]))
            for item in held.payload["items"]
        }
        self.cart_discounts = {
            int(item["product_id"]): int(item.get("discount_cents", 0))
            for item in held.payload["items"]
        }
        self._rebuild_cart()

    def _print_sale(self, sale_id: int) -> None:
        service = PrintingService(self.database)
        receipt = service.receipt(sale_id)
        paths = AppPaths.default()
        paths.ensure_directories()
        target = paths.exports / f"{receipt.receipt_no}.pdf"
        test_pdf = target if os.environ.get("CNKH_POS_TEST_PRINT_PDF") else None
        service.print_receipt(receipt, output_pdf=test_pdf)
        QMessageBox.information(self, "Receipt", "小票已发送到默认 80mm 打印机。")

    def _reprint_latest(self) -> None:
        try:
            receipt = PrintingService(self.database).latest_receipt()
            self._print_sale(receipt.sale_id)
        except Exception as exc:
            QMessageBox.warning(self, "Reprint", str(exc))
