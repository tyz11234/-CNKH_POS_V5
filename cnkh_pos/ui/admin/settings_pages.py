from __future__ import annotations

import json
import os
from datetime import date, datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from cnkh_pos.database.connection import Database
from cnkh_pos.database.migrations import utc_now_text
from cnkh_pos.config import AppPaths
from cnkh_pos.services.auth import AuthenticatedUser
from cnkh_pos.services.catalog import CategoryService
from cnkh_pos.services.daily_closing import DailyClosingService
from cnkh_pos.services.money import format_myr


class CategoryDialog(QDialog):
    def __init__(self, database: Database, user: AuthenticatedUser, parent=None):
        super().__init__(parent)
        self.database = database
        self.user = user
        self.setWindowTitle("Category Management / 分类管理")
        self.setMinimumSize(680, 500)
        root = QVBoxLayout(self)
        title = QLabel("分类管理")
        title.setObjectName("PageTitle")
        root.addWidget(title)
        body = QHBoxLayout()
        self.list = QListWidget()
        body.addWidget(self.list, 2)
        detail = QVBoxLayout()
        detail.addWidget(QLabel("Category Name"))
        self.name = QLineEdit()
        detail.addWidget(self.name)
        self.count = QLabel("Product Count: 0")
        detail.addWidget(self.count)
        detail.addStretch(1)
        body.addLayout(detail, 3)
        root.addLayout(body, 1)
        actions = QHBoxLayout()
        for text, callback, style in (
            ("新增分类", self.add, "PrimaryButton"),
            ("修改分类", self.rename, "WarningButton"),
            ("删除分类", self.delete, "DangerButton"),
            ("关闭", self.accept, ""),
        ):
            button = QPushButton(text)
            button.setObjectName(style)
            button.clicked.connect(callback)
            actions.addWidget(button)
        root.addLayout(actions)
        self.list.currentItemChanged.connect(self._selected)
        self.refresh()

    def refresh(self) -> None:
        self.list.clear()
        conn = self.database.connect(readonly=True)
        try:
            rows = conn.execute(
                """SELECT c.id,c.name,COUNT(p.id) count FROM categories c
                   LEFT JOIN products p ON p.category_id=c.id AND p.is_deleted=0
                   GROUP BY c.id ORDER BY c.name"""
            ).fetchall()
            for row in rows:
                from PySide6.QtWidgets import QListWidgetItem

                item = QListWidgetItem(str(row["name"]))
                item.setData(
                    Qt.ItemDataRole.UserRole, (int(row["id"]), int(row["count"]))
                )
                self.list.addItem(item)
        finally:
            conn.close()

    def _selected(self, current, previous) -> None:
        del previous
        if current:
            category_id, count = current.data(Qt.ItemDataRole.UserRole)
            self.name.setText(current.text())
            self.count.setText(f"Product Count: {count}")

    def add(self) -> None:
        name = self.name.text().strip()
        if name:
            CategoryService(self.database).add(name, admin_id=self.user.id)
            self.refresh()

    def rename(self) -> None:
        item = self.list.currentItem()
        if item and self.name.text().strip():
            CategoryService(self.database).rename(
                item.data(Qt.ItemDataRole.UserRole)[0],
                self.name.text(),
                admin_id=self.user.id,
            )
            self.refresh()

    def delete(self) -> None:
        item = self.list.currentItem()
        if not item:
            return
        category_id, count = item.data(Qt.ItemDataRole.UserRole)
        if (
            QMessageBox.question(
                self, "Delete Category", f"删除后 {count} 个商品会转为未分类。继续？"
            )
            == QMessageBox.StandardButton.Yes
        ):
            CategoryService(self.database).delete(category_id, admin_id=self.user.id)
            self.refresh()


class QuickAmountsWidget(QWidget):
    def __init__(self, database: Database):
        super().__init__()
        self.database = database
        root = QVBoxLayout(self)
        heading = QHBoxLayout()
        title = QLabel("金额快捷按钮设置")
        title.setObjectName("SectionTitle")
        heading.addWidget(title)
        heading.addStretch(1)
        for text, callback, style in (
            ("＋ 新增", self.add, "PrimaryButton"),
            ("修改", self.edit, "WarningButton"),
            ("启用/禁用", self.toggle, ""),
            ("↑", lambda: self.move(-1), ""),
            ("↓", lambda: self.move(1), ""),
            ("删除", self.delete, "DangerButton"),
        ):
            button = QPushButton(text)
            button.setObjectName(style)
            button.clicked.connect(callback)
            heading.addWidget(button)
        root.addLayout(heading)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["#", "按钮金额 (RM)", "状态", "顺序"])
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.table.verticalHeader().setVisible(False)
        root.addWidget(self.table)
        self.refresh()

    def refresh(self) -> None:
        conn = self.database.connect(readonly=True)
        try:
            rows = conn.execute(
                "SELECT id,amount_cents,is_enabled,sort_order FROM quick_amounts ORDER BY sort_order,id"
            ).fetchall()
        finally:
            conn.close()
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, value in enumerate(
                (
                    row["id"],
                    f"{row['amount_cents'] / 100:.2f}",
                    "启用" if row["is_enabled"] else "禁用",
                    row["sort_order"],
                )
            ):
                self.table.setItem(r, c, QTableWidgetItem(str(value)))

    def selected_id(self) -> int | None:
        row = self.table.currentRow()
        return None if row < 0 else int(self.table.item(row, 0).text())

    def add(self) -> None:
        amount, ok = QInputDialog.getDouble(
            self, "Quick Amount", "Amount RM", 10, 0.01, 100000, 2
        )
        if ok:
            with self.database.transaction() as conn:
                order = int(
                    conn.execute(
                        "SELECT COALESCE(MAX(sort_order),0)+10 FROM quick_amounts"
                    ).fetchone()[0]
                )
                conn.execute(
                    "INSERT INTO quick_amounts(amount_cents,is_enabled,sort_order) VALUES (?,1,?)",
                    (round(amount * 100), order),
                )
            self.refresh()

    def edit(self) -> None:
        item_id = self.selected_id()
        if item_id is None:
            return
        amount, ok = QInputDialog.getDouble(
            self, "Quick Amount", "Amount RM", 10, 0.01, 100000, 2
        )
        if ok:
            with self.database.transaction() as conn:
                conn.execute(
                    "UPDATE quick_amounts SET amount_cents=? WHERE id=?",
                    (round(amount * 100), item_id),
                )
            self.refresh()

    def toggle(self) -> None:
        item_id = self.selected_id()
        if item_id is not None:
            with self.database.transaction() as conn:
                conn.execute(
                    "UPDATE quick_amounts SET is_enabled=1-is_enabled WHERE id=?",
                    (item_id,),
                )
            self.refresh()

    def delete(self) -> None:
        item_id = self.selected_id()
        if item_id is not None:
            with self.database.transaction() as conn:
                conn.execute("DELETE FROM quick_amounts WHERE id=?", (item_id,))
            self.refresh()

    def move(self, direction: int) -> None:
        row = self.table.currentRow()
        if row < 0:
            return
        target_row = row + direction
        if target_row < 0 or target_row >= self.table.rowCount():
            return
        current_id = int(self.table.item(row, 0).text())
        target_id = int(self.table.item(target_row, 0).text())
        current_order = int(self.table.item(row, 3).text())
        target_order = int(self.table.item(target_row, 3).text())
        with self.database.transaction() as conn:
            conn.execute(
                "UPDATE quick_amounts SET sort_order=? WHERE id=?",
                (target_order, current_id),
            )
            conn.execute(
                "UPDATE quick_amounts SET sort_order=? WHERE id=?",
                (current_order, target_id),
            )
        self.refresh()
        self.table.selectRow(target_row)


class ReceiptSettingsWidget(QWidget):
    def __init__(self, database: Database, user: AuthenticatedUser):
        super().__init__()
        self.database = database
        self.user = user
        root = QHBoxLayout(self)
        form = QFormLayout()
        self.store = QLineEdit("CNKH Hardware")
        self.address = QTextEdit()
        self.phone = QLineEdit()
        self.footer = QTextEdit("Thank you / 谢谢光临")
        self.notes = QTextEdit()
        for label, widget in (
            ("Store Name", self.store),
            ("Address", self.address),
            ("Phone", self.phone),
            ("Footer", self.footer),
            ("Notes", self.notes),
        ):
            form.addRow(label, widget)
            if hasattr(widget, "textChanged"):
                widget.textChanged.connect(self.update_preview)
        save = QPushButton("保存 Receipt Settings")
        save.setObjectName("SuccessButton")
        save.clicked.connect(self.save)
        self.save_button = save
        test = QPushButton("Test Print")
        test.setObjectName("PrimaryButton")
        test.clicked.connect(self.test_print)
        self.test_button = test
        form.addRow(save, test)
        root.addLayout(form, 3)
        preview_box = QVBoxLayout()
        preview_box.addWidget(QLabel("80mm Receipt Live Preview"))
        self.preview = QTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setMinimumWidth(310)
        self.preview.setStyleSheet(
            "font-family:Consolas; background:white; border:1px solid #DCE3EC;"
        )
        preview_box.addWidget(self.preview)
        root.addLayout(preview_box, 2)
        self.update_preview()

    def update_preview(self) -> None:
        self.preview.setPlainText(
            f"{self.store.text():^32}\n{self.address.toPlainText():^32}\n{self.phone.text():^32}\n"
            f"{'-' * 32}\nReceipt: CNKH20260809-001\nCashier: Admin\n{'-' * 32}\n"
            f"PVC Pipe 20mm      RM 9.00\nHammer 2lb         RM 15.90\n{'-' * 32}\n"
            f"TOTAL              RM 24.90\n{'-' * 32}\n{self.footer.toPlainText():^32}\n{self.notes.toPlainText():^32}"
        )

    def save(self) -> None:
        value = {
            "store_name": self.store.text(),
            "address": self.address.toPlainText(),
            "phone": self.phone.text(),
            "footer": self.footer.toPlainText(),
            "notes": self.notes.toPlainText(),
        }
        with self.database.transaction() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO settings(key,value_json,updated_at,updated_by) VALUES ('receipt',?,?,?)",
                (json.dumps(value, ensure_ascii=False), utc_now_text(), self.user.id),
            )

    def test_print(self) -> None:
        from PySide6.QtCore import QSizeF
        from PySide6.QtGui import QPageSize, QTextDocument
        from PySide6.QtPrintSupport import QPrinter

        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        printer.setPageSize(
            QPageSize(QSizeF(80, 297), QPageSize.Unit.Millimeter, "80mm")
        )
        test_pdf = os.environ.get("CNKH_POS_TEST_PRINT_PDF")
        output_path = None
        if test_pdf:
            paths = AppPaths.default()
            paths.ensure_directories()
            output_path = paths.exports / "receipt-settings-test.pdf"
            printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
            printer.setOutputFileName(str(output_path))
        document = QTextDocument()
        document.setPlainText(self.preview.toPlainText())
        document.print_(printer)
        QMessageBox.information(
            self,
            "Test Print",
            f"测试小票已输出：{output_path}" if output_path else "测试小票已发送到默认打印机。",
        )


class SettingsPage(QWidget):
    def __init__(self, database: Database, user: AuthenticatedUser):
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 20)
        header = QHBoxLayout()
        title = QLabel("系统设置")
        title.setObjectName("PageTitle")
        categories = QPushButton("Category Management / 分类管理")
        categories.setObjectName("PrimaryButton")
        categories.clicked.connect(lambda: CategoryDialog(database, user, self).exec())
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(categories)
        root.addLayout(header)
        tabs = QTabWidget()
        tabs.addTab(ReceiptSettingsWidget(database, user), "Receipt Settings")
        tabs.addTab(QuickAmountsWidget(database), "Quick Amount Settings")
        general = QWidget()
        form = QFormLayout(general)
        form.addRow("UI Language", QLineEdit("中文 / English"))
        form.addRow("Receipt Language", QLineEdit("English"))
        form.addRow("Sale Success Sound", QCheckBox())
        form.addRow("Windows Startup Auto Launch Staff POS", QCheckBox())
        tabs.addTab(general, "General")
        root.addWidget(tabs)


class DailyClosingPage(QWidget):
    def __init__(self, database: Database, user: AuthenticatedUser):
        super().__init__()
        self.database = database
        self.user = user
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 24)
        title = QLabel("Daily Cash Closing / 每日收银结算")
        title.setObjectName("PageTitle")
        root.addWidget(title)
        form = QFormLayout()
        self.system = QLineEdit("0.00")
        self.system.setReadOnly(True)
        self.actual = QLineEdit("0.00")
        self.variance = QLabel("RM 0.00")
        self.note = QTextEdit()
        self.actual.textChanged.connect(self.update_variance)
        form.addRow("System Cash", self.system)
        form.addRow("Actual Cash", self.actual)
        form.addRow("Variance", self.variance)
        form.addRow("Notes", self.note)
        root.addLayout(form)
        complete = QPushButton("完成日结")
        complete.setObjectName("CheckoutButton")
        complete.clicked.connect(self.complete)
        root.addWidget(complete)
        root.addStretch(1)
        self.load_system_cash()

    def load_system_cash(self) -> None:
        cents = DailyClosingService(self.database).system_cash(
            business_date=date.today()
        )
        self.system.setText(f"{cents / 100:.2f}")
        self.update_variance()

    def update_variance(self) -> None:
        try:
            system = round(float(self.system.text()) * 100)
            actual = round(float(self.actual.text()) * 100)
            self.variance.setText(format_myr(actual - system))
        except ValueError:
            self.variance.setText("—")

    def complete(self) -> None:
        actual = round(float(self.actual.text()) * 100)
        DailyClosingService(self.database).complete(
            business_date=date.today(),
            cashier_id=self.user.id,
            actual_cash_cents=actual,
            note=self.note.toPlainText(),
        )
        QMessageBox.information(self, "Daily Closing", "日结已保存。")


class ReportsPage(QWidget):
    def __init__(self, database: Database):
        super().__init__()
        self.database = database
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 20)
        title = QLabel("Reports / Monthly Summary")
        title.setObjectName("PageTitle")
        root.addWidget(title)
        self.summary = QLabel()
        self.summary.setStyleSheet("font-size:17px; line-height:1.5;")
        root.addWidget(self.summary)
        export = QPushButton("Export Excel")
        export.setObjectName("PrimaryButton")
        export.clicked.connect(self.export_excel)
        self.export_button = export
        root.addWidget(export, alignment=Qt.AlignmentFlag.AlignLeft)
        root.addStretch(1)
        conn = database.connect(readonly=True)
        try:
            sales, profit, count = conn.execute(
                "SELECT COALESCE(SUM(total_cents),0),COALESCE(SUM((si.unit_price_cents-si.unit_cost_cents_snapshot)*CAST(si.quantity_decimal AS REAL)),0),COUNT(DISTINCT s.id) FROM sales s LEFT JOIN sale_items si ON si.sale_id=s.id"
            ).fetchone()
            purchases = conn.execute(
                "SELECT COALESCE(SUM(total_cents),0) FROM purchases"
            ).fetchone()[0]
            receivable = conn.execute(
                "SELECT COALESCE(SUM(balance_cents),0) FROM customer_debts WHERE status='OPEN'"
            ).fetchone()[0]
            payable = conn.execute(
                "SELECT COALESCE(SUM(total_cents-paid_cents),0) FROM purchases"
            ).fetchone()[0]
        finally:
            conn.close()
        self.summary.setText(
            f"Sales: {format_myr(int(sales))}\nGross Profit: {format_myr(int(profit))}\nTransaction Count: {count}\nPurchases: {format_myr(int(purchases))}\nCustomer Receivables: {format_myr(int(receivable))}\nSupplier Payables: {format_myr(int(payable))}"
        )

    def export_excel(self) -> None:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill

        paths = AppPaths.default()
        paths.ensure_directories()
        target = paths.exports / f"CNKH_POS_Report_{datetime.now():%Y%m%d_%H%M%S}.xlsx"
        workbook = Workbook()
        summary = workbook.active
        summary.title = "Summary"
        summary.append(["CNKH Hardware POS V5", "Monthly Summary"])
        for line in self.summary.text().splitlines():
            label, _, value = line.partition(":")
            summary.append([label, value.strip()])
        summary["A1"].font = Font(bold=True, color="FFFFFF")
        summary["B1"].font = Font(bold=True, color="FFFFFF")
        summary["A1"].fill = PatternFill("solid", fgColor="0B2A53")
        summary["B1"].fill = PatternFill("solid", fgColor="0B2A53")
        summary.column_dimensions["A"].width = 28
        summary.column_dimensions["B"].width = 24

        conn = self.database.connect(readonly=True)
        try:
            datasets = (
                (
                    "Sales",
                    ["Receipt No", "Sold At", "Total (sen)", "Payment", "Customer"],
                    """SELECT s.receipt_no,s.sold_at,s.total_cents,s.payment_method,
                              COALESCE(c.name,'Walk-In Customer')
                       FROM sales s LEFT JOIN customers c ON c.id=s.customer_id
                       WHERE s.is_deleted=0 ORDER BY s.sold_at DESC""",
                ),
                (
                    "Purchases",
                    ["Purchase No", "Purchased At", "Total (sen)", "Paid (sen)", "Status"],
                    """SELECT purchase_no,purchased_at,total_cents,paid_cents,status
                       FROM purchases WHERE is_deleted=0 ORDER BY purchased_at DESC""",
                ),
                (
                    "Customer Debts",
                    ["Customer", "Original (sen)", "Balance (sen)", "Status", "Opened At"],
                    """SELECT c.name,d.original_cents,d.balance_cents,d.status,d.opened_at
                       FROM customer_debts d JOIN customers c ON c.id=d.customer_id
                       ORDER BY d.opened_at DESC""",
                ),
            )
            for name, headers, query in datasets:
                sheet = workbook.create_sheet(name)
                sheet.append(headers)
                for cell in sheet[1]:
                    cell.font = Font(bold=True, color="FFFFFF")
                    cell.fill = PatternFill("solid", fgColor="1769E0")
                for row in conn.execute(query):
                    sheet.append(list(row))
                sheet.freeze_panes = "A2"
                sheet.auto_filter.ref = sheet.dimensions
                for column in sheet.columns:
                    width = min(42, max(12, max(len(str(cell.value or "")) for cell in column) + 2))
                    sheet.column_dimensions[column[0].column_letter].width = width
        finally:
            conn.close()
        workbook.save(target)
        QMessageBox.information(self, "Export Excel", f"报表已导出：{target}")
