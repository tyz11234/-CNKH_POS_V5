from __future__ import annotations

import html
import os
from decimal import Decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from cnkh_pos.config import AppPaths
from cnkh_pos.database.connection import Database
from cnkh_pos.services.auth import AuthenticatedUser
from cnkh_pos.services.held_orders import HeldOrderService, cart_state_from_held_payload
from cnkh_pos.services.lan_sync_server import publish_sync_event
from cnkh_pos.services.money import (
    clamp_discount_cents,
    format_myr,
    line_amount_cents,
    rm_to_cents,
)
from cnkh_pos.services.printing import PrintingService
from cnkh_pos.services.product_search import search_products
from cnkh_pos.services.sales import SaleLine, SalesService
from cnkh_pos.ui.dialogs.checkout import CheckoutDialog, SaleCompletedDialog
from cnkh_pos.ui.dialogs.e_receipt_dialog import send_e_receipt_for_sale
from cnkh_pos.ui.widgets import Card
from cnkh_pos.ui.widgets.sync_toolbar import (
    make_sync_pair_button,
    make_sync_status_label,
    sync_event_bridge,
)


class StaffWindow(QMainWindow):
    def __init__(self, database: Database, user: AuthenticatedUser):
        super().__init__()
        self.database = database
        self.user = user
        self.cart_quantities: dict[int, Decimal] = {}
        self.cart_discounts: dict[int, int] = {}
        self.visible_product_ids: list[int] = []
        self.product_offset = 0
        self.product_page_size = 50
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
        layout.addWidget(make_sync_status_label())
        layout.addWidget(make_sync_pair_button(self, self.database))
        self.hold_overdue_label = QLabel("")
        self.hold_overdue_label.setStyleSheet("color:#B26A00;font-weight:800;")
        layout.addWidget(self.hold_overdue_label)
        layout.addWidget(user)
        from PySide6.QtCore import QTimer
        self._hold_timer = QTimer(self)
        self._hold_timer.timeout.connect(self._refresh_hold_overdue)
        self._hold_timer.start(60000)
        self._refresh_hold_overdue()
        # Live refresh when phone pushes a sale
        sync_event_bridge().sale_event.connect(self._on_sync_event)
        return bar

    def _on_sync_event(self, event: dict) -> None:
        if str(event.get("type") or "") != "sale":
            return
        # Soft refresh product stock after remote sale
        try:
            self._load_product_table()
        except Exception:
            pass

    def _hold_timeout_minutes(self) -> int:
        try:
            conn = self.database.connect(readonly=True)
            row = conn.execute(
                "SELECT value_json FROM settings WHERE key='hold_timeout_minutes'"
            ).fetchone()
            conn.close()
            if row and row[0]:
                import json as _json
                try:
                    return int(_json.loads(row[0]))
                except Exception:
                    return int(str(row[0]).strip('"') or 30)
        except Exception:
            pass
        return 30

    def _refresh_hold_overdue(self) -> None:
        try:
            from datetime import datetime, timedelta

            from cnkh_pos.services.held_orders import HeldOrderService
            mins = self._hold_timeout_minutes()
            cutoff = datetime.utcnow() - timedelta(minutes=mins)
            held = HeldOrderService(self.database).list_held(cashier_id=self.user.id)
            overdue = 0
            for h in held:
                try:
                    ts = datetime.fromisoformat(str(h.held_at).replace("Z", ""))
                    if ts < cutoff:
                        overdue += 1
                except Exception:
                    pass
            if overdue:
                self.hold_overdue_label.setText(f"⚠挂单超时 {overdue}")
            else:
                self.hold_overdue_label.setText("")
        except Exception:
            self.hold_overdue_label.setText("")

    def _search_bar(self) -> QHBoxLayout:
        layout = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setObjectName("SearchInput")
        self.search.setPlaceholderText(
            "扫描 / 输入条码、商品名称、SKU、Alias、Category、Location"
        )
        self.search.textChanged.connect(self._filter_results)
        self.search_button = QPushButton("搜索商品")
        self.search_button.setObjectName("PrimaryButton")
        self.search_button.setMinimumHeight(50)
        self.search_button.clicked.connect(
            lambda: self._filter_results(self.search.text())
        )
        layout.addWidget(self.search, 1)
        layout.addWidget(self.search_button)
        return layout

    def _search_results(self) -> QTableWidget:
        self.results = QTableWidget(0, 6)
        self.results.setObjectName("SearchSuggestions")
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
        self.results.setMaximumHeight(190)
        self.results.setVisible(False)
        self.results.cellClicked.connect(self._result_clicked)
        return self.results

    def _product_panel(self) -> Card:
        panel = Card(shadow=False)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 12, 12, 12)
        title = QLabel("商品列表")
        title.setObjectName("SectionTitle")
        layout.addWidget(title)
        product_body = QHBoxLayout()
        self.category_filter = QListWidget()
        self.category_filter.setObjectName("ProductCategoryFilter")
        self.category_filter.setMaximumWidth(145)
        self.category_filter.setMinimumWidth(105)
        self.category_filter.currentRowChanged.connect(self._category_changed)
        product_body.addWidget(self.category_filter)
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
        product_body.addWidget(self.products, 1)
        layout.addLayout(product_body, 1)
        pager = QHBoxLayout()
        self.product_previous = QPushButton("‹ 上一页")
        self.product_next = QPushButton("下一页 ›")
        self.product_page_label = QLabel("第 1 页")
        self.product_page_label.setObjectName("Muted")
        self.product_previous.clicked.connect(self._previous_product_page)
        self.product_next.clicked.connect(self._next_product_page)
        pager.addStretch(1)
        pager.addWidget(self.product_previous)
        pager.addWidget(self.product_page_label)
        pager.addWidget(self.product_next)
        layout.addLayout(pager)
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
        self.cart.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Fixed
        )
        self.cart.horizontalHeader().resizeSection(2, 116)
        for column in (1, 3, 4, 5):
            self.cart.horizontalHeader().setSectionResizeMode(
                column, QHeaderView.ResizeMode.ResizeToContents
            )
        self.cart.verticalHeader().setVisible(False)
        self.cart.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        layout.addWidget(self.cart, 1)

        total = QHBoxLayout()
        total.addWidget(QLabel("总计金额"))
        total.addStretch(1)
        self.total_label = QLabel("RM 0.00")
        self.total_label.setObjectName("MoneyHero")
        self.total_label.setMinimumWidth(220)
        self.total_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
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
            if text == "加入购物车":
                self.add_selected_button = button
                button.clicked.connect(self._add_selected_product)
            elif text == "挂单":
                self.hold_button = button
            elif text == "恢复挂单":
                self.retrieve_button = button
            elif text == "取消订单":
                button.clicked.connect(self._clear_cart)
            secondary.addWidget(button, index // 2, index % 2)
        layout.addLayout(secondary)
        discount = QPushButton("修改所选商品 Discount")
        discount.setObjectName("WarningButton")
        self.discount_button = discount
        discount.clicked.connect(self._edit_discount)
        discount.setEnabled(bool(self.user.permissions.get("apply_discount", False)))
        discount.setToolTip(
            "需要管理员授予折扣权限" if not discount.isEnabled() else ""
        )
        layout.addWidget(discount)
        self.hold_button.clicked.connect(self._hold_order)
        self.retrieve_button.clicked.connect(self._retrieve_order)
        reprint = QPushButton("重新打印上一张小票")
        self.reprint_button = reprint
        reprint.clicked.connect(self._reprint_latest)
        reprint.setEnabled(bool(self.user.permissions.get("reprint_receipt", False)))
        layout.addWidget(reprint)
        checkout = QPushButton("结账   →")
        checkout.setObjectName("CheckoutButton")
        self.checkout_button = checkout
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
            self.results.setVisible(False)
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
            highlighted = QLabel(self._highlight(result.name, query))
            highlighted.setTextFormat(Qt.TextFormat.RichText)
            highlighted.setContentsMargins(8, 0, 8, 0)
            self.results.setCellWidget(row, 0, highlighted)
            self.results.setRowHeight(row, 46)
        self.results.setVisible(bool(matches))
        if len(matches) == 1 and matches[0].exact_barcode:
            self._add_to_cart(matches[0].product_id)
            self.search.clear()

    def _result_clicked(self, row: int, column: int) -> None:
        del column
        product_id = int(self.results.item(row, 0).data(Qt.ItemDataRole.UserRole))
        self._add_to_cart(product_id)
        self.search.clear()

    @staticmethod
    def _highlight(value: str, query: str) -> str:
        safe = html.escape(value)
        term = query.strip()
        if not term:
            return safe
        lower_value = value.casefold()
        lower_term = term.casefold()
        start = lower_value.find(lower_term)
        if start < 0:
            return safe
        before = html.escape(value[:start])
        match = html.escape(value[start : start + len(term)])
        after = html.escape(value[start + len(term) :])
        return (
            f"{before}<span style='color:#E5484D;font-weight:800;"
            f"background:#FFF0F1'>{match}</span>{after}"
        )

    def _add_selected_product(self) -> None:
        row = self.products.currentRow()
        if 0 <= row < len(self.visible_product_ids):
            self._add_to_cart(self.visible_product_ids[row])
            return
        result_row = self.results.currentRow()
        if result_row >= 0 and self.results.item(result_row, 0) is not None:
            self._result_clicked(result_row, 0)
            return
        QMessageBox.information(self, "Cart", "请先选择一个商品。")

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
        dialog = CheckoutDialog(
            total,
            self._quick_amounts(),
            self,
            customers=self._customers(),
            quick_settings_callback=self._open_quick_amount_settings,
            paths=AppPaths.default(),
            is_admin=self.user.role == "ADMIN",
        )
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
            sale_id=result.sale_id,
            database=self.database,
        )
        completed.exec()
        if completed.print_requested:
            self._print_sale(result.sale_id)
        if getattr(completed, "ereceipt_requested", False):
            send_e_receipt_for_sale(self, self.database, result.sale_id)
        try:
            publish_sync_event(
                "sale",
                source="pc",
                receipt_no=result.receipt_no,
                sale_id=result.sale_id,
            )
        except Exception:
            pass

    def _load_product_table(self) -> None:
        if not hasattr(self, "category_filter"):
            return
        if self.category_filter.count() == 0:
            self._load_categories()
        current_category = self.category_filter.currentItem()
        category_id = (
            current_category.data(Qt.ItemDataRole.UserRole)
            if current_category is not None
            else None
        )
        conn = self.database.connect(readonly=True)
        try:
            if category_id is None:
                total_count = int(
                    conn.execute(
                        "SELECT COUNT(*) FROM products WHERE is_deleted=0"
                    ).fetchone()[0]
                )
                rows = conn.execute(
                    """SELECT id,name,COALESCE(sku,'') AS sku,selling_price_cents,
                              stock_decimal,unit FROM products WHERE is_deleted=0
                       ORDER BY name COLLATE NOCASE LIMIT ? OFFSET ?""",
                    (self.product_page_size, self.product_offset),
                ).fetchall()
            else:
                total_count = int(
                    conn.execute(
                        """SELECT COUNT(*) FROM products
                           WHERE is_deleted=0 AND category_id=?""",
                        (category_id,),
                    ).fetchone()[0]
                )
                rows = conn.execute(
                    """SELECT id,name,COALESCE(sku,'') AS sku,selling_price_cents,
                              stock_decimal,unit FROM products
                       WHERE is_deleted=0 AND category_id=?
                       ORDER BY name COLLATE NOCASE LIMIT ? OFFSET ?""",
                    (category_id, self.product_page_size, self.product_offset),
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
        page = self.product_offset // self.product_page_size + 1
        pages = max(1, (total_count + self.product_page_size - 1) // self.product_page_size)
        self.product_page_label.setText(f"共 {total_count} 项　　第 {page} / {pages} 页")
        self.product_previous.setEnabled(self.product_offset > 0)
        self.product_next.setEnabled(self.product_offset + len(rows) < total_count)

    def _category_changed(self, _row: int) -> None:
        self.product_offset = 0
        self._load_product_table()

    def _previous_product_page(self) -> None:
        self.product_offset = max(0, self.product_offset - self.product_page_size)
        self._load_product_table()

    def _next_product_page(self) -> None:
        self.product_offset += self.product_page_size
        self._load_product_table()

    def _load_categories(self) -> None:
        self.category_filter.blockSignals(True)
        self.category_filter.clear()
        all_item = QListWidgetItem("全部")
        all_item.setData(Qt.ItemDataRole.UserRole, None)
        self.category_filter.addItem(all_item)
        conn = self.database.connect(readonly=True)
        try:
            rows = conn.execute(
                "SELECT id,name FROM categories WHERE is_deleted=0 ORDER BY name COLLATE NOCASE"
            ).fetchall()
        finally:
            conn.close()
        for row in rows:
            item = QListWidgetItem(str(row["name"]))
            item.setData(Qt.ItemDataRole.UserRole, int(row["id"]))
            self.category_filter.addItem(item)
        self.category_filter.setCurrentRow(0)
        self.category_filter.blockSignals(False)

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
                gross_cents = line_amount_cents(
                    int(product["selling_price_cents"]), quantity
                )
                discount_cents = clamp_discount_cents(
                    self.cart_discounts.get(product_id, 0), gross_cents
                )
                if discount_cents:
                    self.cart_discounts[product_id] = discount_cents
                else:
                    self.cart_discounts.pop(product_id, None)
                subtotal = gross_cents - discount_cents
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
                quantity_widget.setObjectName("CartQuantityCell")
                quantity_widget.setProperty("productId", product_id)
                quantity_layout = QHBoxLayout(quantity_widget)
                quantity_layout.setContentsMargins(0, 0, 0, 0)
                quantity_layout.setSpacing(2)
                minus = QPushButton("−")
                minus.setObjectName("CartQuantityMinus")
                minus.setProperty("productId", product_id)
                minus.setFixedWidth(22)
                plus = QPushButton("+")
                plus.setObjectName("CartQuantityPlus")
                plus.setProperty("productId", product_id)
                plus.setFixedWidth(22)
                spin = QDoubleSpinBox()
                spin.setObjectName("CartQuantityValue")
                spin.setProperty("productId", product_id)
                spin.setDecimals(3)
                spin.setRange(0, 999999)
                spin.setFixedWidth(66)
                spin.setValue(float(quantity))
                minus.clicked.connect(
                    lambda checked=False, pid=product_id: self._change_quantity(
                        pid, Decimal("-1")
                    )
                )
                plus.clicked.connect(
                    lambda checked=False, pid=product_id: self._change_quantity(
                        pid, Decimal("1")
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
                self.cart.setRowHeight(row, 44)
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
            total = 0
            for product_id, quantity in self.cart_quantities.items():
                row = conn.execute(
                    "SELECT selling_price_cents FROM products WHERE id=?", (product_id,)
                ).fetchone()
                if row:
                    gross = line_amount_cents(
                        int(row["selling_price_cents"]), quantity
                    )
                    total += gross - clamp_discount_cents(
                        self.cart_discounts.get(product_id, 0), gross
                    )
            return total
        finally:
            conn.close()

    def _change_quantity(self, product_id: int, delta: Decimal) -> None:
        current = self.cart_quantities.get(product_id, Decimal("0"))
        self._set_quantity(product_id, current + delta)

    def _set_quantity(self, product_id: int, value: float | Decimal) -> None:
        quantity = Decimal(str(value))
        if quantity <= 0:
            self._remove_cart(product_id)
        else:
            self.cart_quantities[product_id] = quantity
            maximum = self._maximum_discount(product_id)
            if self.cart_discounts.get(product_id, 0) > maximum:
                self.cart_discounts[product_id] = maximum
            self._rebuild_cart()

    def _maximum_discount(self, product_id: int) -> int:
        quantity = self.cart_quantities.get(product_id, Decimal("0"))
        conn = self.database.connect(readonly=True)
        try:
            row = conn.execute(
                "SELECT selling_price_cents FROM products WHERE id=? AND is_deleted=0",
                (product_id,),
            ).fetchone()
        finally:
            conn.close()
        if row is None:
            return 0
        return line_amount_cents(int(row["selling_price_cents"]), quantity)

    def _edit_discount(self) -> None:
        row = self.cart.currentRow()
        if row < 0:
            QMessageBox.information(self, "Discount", "请先选择购物车商品。")
            return
        product_id = int(self.cart.item(row, 0).data(Qt.ItemDataRole.UserRole))
        from PySide6.QtWidgets import QInputDialog

        maximum = self._maximum_discount(product_id)
        amount, ok = QInputDialog.getDouble(
            self,
            "Discount",
            "Discount RM",
            min(self.cart_discounts.get(product_id, 0), maximum) / 100,
            0,
            maximum / 100,
            2,
        )
        if ok:
            self.cart_discounts[product_id] = rm_to_cents(amount)
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

    def _customers(self) -> list[tuple[int, str]]:
        conn = self.database.connect(readonly=True)
        try:
            return [
                (int(row["id"]), str(row["name"]))
                for row in conn.execute(
                    "SELECT id,name FROM customers WHERE is_deleted=0 ORDER BY name COLLATE NOCASE"
                )
            ]
        finally:
            conn.close()

    def _open_quick_amount_settings(self) -> None:
        if not self.user.permissions.get("manage_quick_amounts", False):
            QMessageBox.information(self, "Settings", "此账号没有修改快捷金额的权限。")
            return
        from PySide6.QtWidgets import QDialog, QVBoxLayout

        from cnkh_pos.ui.admin.settings_pages import QuickAmountsWidget

        dialog = QDialog(self)
        dialog.setWindowTitle("金额快捷按钮设置")
        dialog.setMinimumSize(680, 460)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QuickAmountsWidget(self.database))
        dialog.exec()

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
        if self.cart_quantities and (
            QMessageBox.question(
                self, "Retrieve Order", "恢复挂单会替换当前购物车。继续？"
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        service = HeldOrderService(self.database)
        try:
            choices = service.list_held(cashier_id=self.user.id)
            if not choices:
                raise LookupError("no held order")
            held = choices[0]
            if len(choices) > 1:
                labels = [item.hold_no for item in choices]
                selected, ok = QInputDialog.getItem(
                    self, "Retrieve Order", "选择挂单", labels, 0, False
                )
                if not ok:
                    return
                held = choices[labels.index(selected)]
            held = service.retrieve(held.id, cashier_id=self.user.id)
        except Exception as exc:
            QMessageBox.warning(self, "Retrieve Order", str(exc))
            return
        self.cart_quantities, self.cart_discounts = cart_state_from_held_payload(
            held.payload
        )
        self._rebuild_cart()

    def _print_sale(self, sale_id: int) -> None:
        service = PrintingService(self.database)
        receipt = service.receipt(sale_id)
        paths = AppPaths.default()
        paths.ensure_directories()
        target = paths.receipts / f"{receipt.receipt_no}.pdf"
        test_pdf = target if os.environ.get("CNKH_POS_TEST_PRINT_PDF") else None
        try:
            service.print_receipt(receipt, output_pdf=test_pdf)
        except Exception as exc:
            QMessageBox.warning(self, "Receipt", f"打印失败：{exc}")
            return
        printer_name = str(receipt.settings.get("printer_name", "")).strip()
        destination = (
            printer_name
            if printer_name
            else (
                "Windows default printer"
                if str(receipt.settings.get("printer_mode", "")).upper() == "DEFAULT"
                else "PDF test output"
            )
        )
        QMessageBox.information(self, "Receipt", f"小票已发送到：{destination}")

    def _reprint_latest(self) -> None:
        if not self.user.permissions.get("reprint_receipt", False):
            QMessageBox.information(self, "Reprint", "此账号没有重印权限。")
            return
        try:
            receipt = PrintingService(self.database).latest_receipt()
            self._print_sale(receipt.sale_id)
        except Exception as exc:
            QMessageBox.warning(self, "Reprint", str(exc))
