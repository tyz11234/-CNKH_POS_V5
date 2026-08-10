from __future__ import annotations

import argparse
import os
import tempfile
from datetime import date
from decimal import Decimal
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scale", required=True)
    args = parser.parse_args()
    from PySide6.QtCore import QPoint, QPointF, Qt, QTimer
    from PySide6.QtGui import QShortcut, QWheelEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import (
        QAbstractScrollArea,
        QApplication,
        QComboBox,
        QDialog,
        QDialogButtonBox,
        QDoubleSpinBox,
        QFileDialog,
        QInputDialog,
        QLineEdit,
        QMessageBox,
        QPushButton,
        QTableWidget,
        QTabWidget,
    )

    from cnkh_pos.database.bootstrap import bootstrap_database
    from cnkh_pos.database.connection import Database
    from cnkh_pos.database.migrations import utc_now_text
    from cnkh_pos.services.auth import AuthService
    from cnkh_pos.services.backup import BackupService
    from cnkh_pos.services.catalog import CatalogService, CategoryService, ProductInput
    from cnkh_pos.services.daily_closing import DailyClosingService
    from cnkh_pos.services.payments import (
        CustomerPaymentService,
        SupplierPaymentService,
    )
    from cnkh_pos.services.printing import PrintingService
    from cnkh_pos.services.purchases import PurchaseLine, PurchaseService
    from cnkh_pos.services.sales import SaleLine, SalesService
    from cnkh_pos.services.stocktake import StocktakeService
    from cnkh_pos.ui.admin import AdminWindow
    from cnkh_pos.ui.admin.dashboard import DashboardPage
    from cnkh_pos.ui.admin.data_pages import (
        AuditPage,
        EntityDialog,
        EntityPage,
        MaintenancePage,
        NewPurchaseDialog,
        ProductDialog,
        ProductsPage,
        PurchasesPage,
        RecordPaymentDialog,
        ReturnSaleDialog,
        SalesPage,
        StocktakeCountDialog,
        StocktakePage,
        SupplierProductsDialog,
    )
    from cnkh_pos.ui.admin.settings_pages import (
        CategoryDialog,
        DailyClosingPage,
        DocumentPrefixesWidget,
        QuickAmountsWidget,
        ReceiptSettingsWidget,
        ReportsPage,
    )
    from cnkh_pos.ui.admin.users_page import EditUserDialog, NewUserDialog, UsersPage
    from cnkh_pos.ui.dialogs.checkout import CheckoutDialog, SaleCompletedDialog
    from cnkh_pos.ui.dialogs.discount import DiscountDialog
    from cnkh_pos.ui.staff import StaffWindow
    from cnkh_pos.ui.theme import apply_theme

    artifact = Path("ui-acceptance-artifacts") / f"scale-{args.scale}"
    artifact.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        os.environ["LOCALAPPDATA"] = str(root / "localappdata")
        os.environ["CNKH_POS_TEST_PRINT_PDF"] = "1"
        database = Database(root / "hardware_pos.db")
        bootstrap_database(database.path, root / "backups")
        with database.transaction() as conn:
            admin_id = AuthService.create_user(
                conn,
                username="admin",
                display_name="Admin",
                password="SafePass123!",
                role="ADMIN",
                permissions={},
                admin_id=None,
            )
            staff_id = AuthService.create_user(
                conn,
                username="cashier",
                display_name="Cashier",
                password="SafePass456!",
                role="STAFF",
                permissions={
                    "apply_discount": True,
                    "manage_quick_amounts": True,
                    "reprint_receipt": True,
                },
                admin_id=admin_id,
            )
            admin = AuthService.authenticate(
                conn, "admin", "SafePass123!", required_role="ADMIN"
            )
            staff = AuthService.authenticate(
                conn, "cashier", "SafePass456!", required_role="STAFF"
            )
            now = utc_now_text()
            customer_id = int(
                conn.execute(
                    "INSERT INTO customers(name,phone,created_at,updated_at) VALUES ('Test Customer','0123456789',?,?)",
                    (now, now),
                ).lastrowid
            )
            supplier_id = int(
                conn.execute(
                    "INSERT INTO suppliers(name,created_at,updated_at) VALUES ('Test Supplier',?,?)",
                    (now, now),
                ).lastrowid
            )
        category = CategoryService(database).add("Electrical", admin_id=admin_id)
        CategoryService(database).rename(
            category, "Electrical Cable", admin_id=admin_id
        )
        products = []
        for index in range(120):
            products.append(
                CatalogService(database).add_product(
                    ProductInput(
                        name=f"PVC Cable {index + 1}mm",
                        aliases="电线 kabel",
                        category_id=category,
                        sku=f"PVC{index + 1}",
                        barcode=None,
                        selling_price_cents=280 + index,
                        cost_cents=150,
                        stock="500",
                        unit="meter",
                        location=f"Rack {index % 10}",
                    ),
                    admin_id=admin_id,
                )
            )
        conn = database.connect(readonly=True)
        barcode = str(
            conn.execute(
                "SELECT barcode FROM products WHERE id=?", (products[0],)
            ).fetchone()[0]
        )
        conn.close()
        with database.transaction() as conn:
            now = utc_now_text()
            conn.executemany(
                """INSERT INTO supplier_products(
                    supplier_id,product_id,is_active,created_at,updated_at
                ) VALUES (?,?,1,?,?)""",
                [(supplier_id, product_id, now, now) for product_id in products],
            )

        app = QApplication.instance() or QApplication([])
        apply_theme(app)

        def dismiss_message(dialog: QDialog) -> None:
            assert isinstance(dialog, QMessageBox)
            button = dialog.button(QMessageBox.StandardButton.Ok)
            if button is None:
                button = dialog.defaultButton()
            assert button is not None
            QTest.mouseClick(button, Qt.MouseButton.LeftButton)

        def enter_double(dialog: QDialog, value: float | None = None) -> None:
            assert isinstance(dialog, QInputDialog)
            control = dialog.findChild(QDoubleSpinBox)
            assert control is not None
            control.setValue(control.maximum() if value is None else value)
            dialog.accept()

        def cart_quantity_controls(
            window: StaffWindow, product_id: int
        ) -> tuple[QDoubleSpinBox, QPushButton, QPushButton]:
            """Resolve controls from the current cart tree after every rebuild."""
            for row in range(window.cart.rowCount()):
                item = window.cart.item(row, 0)
                if item is None:
                    continue
                if int(item.data(Qt.ItemDataRole.UserRole)) != product_id:
                    continue
                cell = window.cart.cellWidget(row, 2)
                assert cell is not None
                spin = cell.findChild(QDoubleSpinBox, "CartQuantityValue")
                minus = cell.findChild(QPushButton, "CartQuantityMinus")
                plus = cell.findChild(QPushButton, "CartQuantityPlus")
                assert spin is not None and minus is not None and plus is not None
                return spin, minus, plus
            raise AssertionError(f"cart row not found for product {product_id}")

        admin_window = AdminWindow(database, admin)
        admin_window.resize(1366, 768)
        admin_window.show()
        app.processEvents()
        assert not admin_window.findChildren(QShortcut), (
            "custom POS shortcuts are forbidden"
        )
        sidebar_by_key = {
            str(button.property("pageKey")): button
            for button in admin_window.findChildren(QPushButton)
            if button.objectName() == "SidebarButton"
        }
        sidebar_buttons = [
            sidebar_by_key[key]
            for key, _index in sorted(
                admin_window.page_keys.items(), key=lambda item: item[1]
            )
        ]
        assert len(sidebar_buttons) == admin_window.pages.count()
        for page_index, sidebar_button in enumerate(sidebar_buttons):
            QTest.mouseClick(sidebar_button, Qt.MouseButton.LeftButton)
            app.processEvents()
            assert admin_window.pages.currentIndex() == page_index
            assert_visible_buttons(admin_window, QPushButton, QAbstractScrollArea)
            save_screenshot(
                admin_window, artifact / f"admin-page-{page_index}.png"
            )
            for tabs in admin_window.pages.currentWidget().findChildren(QTabWidget):
                for tab_index in range(tabs.count()):
                    tabs.setCurrentIndex(tab_index)
                    app.processEvents()
                    assert_visible_buttons(
                        admin_window, QPushButton, QAbstractScrollArea
                    )
                    for table in [
                        item
                        for item in tabs.currentWidget().findChildren(QTableWidget)
                        if item.isVisible()
                    ]:
                        send_wheel(
                            table, QWheelEvent, QPointF, QPoint, Qt, QApplication
                        )
                    save_screenshot(
                        admin_window,
                        artifact / f"admin-page-{page_index}-tab-{tab_index}.png",
                    )

        # Native list/table widgets receive a real wheel event without requiring scrollbar dragging.
        tables = [
            table
            for table in admin_window.findChildren(QTableWidget)
            if table.isVisible()
        ]
        for table in tables[:3]:
            send_wheel(table, QWheelEvent, QPointF, QPoint, Qt, QApplication)

        staff_window = StaffWindow(database, staff)
        staff_window.resize(1366, 768)
        staff_window.show()
        app.processEvents()
        assert not staff_window.findChildren(QShortcut), (
            "custom POS shortcuts are forbidden"
        )
        assert_visible_buttons(staff_window, QPushButton, QAbstractScrollArea)
        assert staff_window.discount_button.isEnabled()
        assert staff_window.reprint_button.isEnabled()
        first_page_ids = list(staff_window.visible_product_ids)
        assert staff_window.product_next.isEnabled()
        QTest.mouseClick(staff_window.product_next, Qt.MouseButton.LeftButton)
        app.processEvents()
        assert staff_window.visible_product_ids != first_page_ids
        QTest.mouseClick(staff_window.product_previous, Qt.MouseButton.LeftButton)
        app.processEvents()
        assert staff_window.visible_product_ids == first_page_ids

        # Fuzzy search through the real search button, maximum three suggestions,
        # and mouse selection. This deliberately avoids calling StaffWindow slots
        # directly so disconnected controls fail the release gate.
        staff_window.search.setFocus()
        QTest.keyClicks(staff_window.search, "kabel")
        QTest.mouseClick(staff_window.search_button, Qt.MouseButton.LeftButton)
        app.processEvents()
        assert 0 < staff_window.results.rowCount() <= 3
        QTest.mouseClick(
            staff_window.results.viewport(),
            Qt.MouseButton.LeftButton,
            pos=staff_window.results.visualItemRect(
                staff_window.results.item(0, 1)
            ).center(),
        )
        app.processEvents()
        assert staff_window.cart_quantities
        # Exact barcode auto-add.
        staff_window.search.setText(barcode)
        app.processEvents()
        assert len(staff_window.cart_quantities) >= 1
        # Product-table Add button and the large Add Selected button both work.
        initial_units = sum(staff_window.cart_quantities.values())
        staff_window.products.selectRow(0)
        QTest.mouseClick(
            staff_window.products.cellWidget(0, 5), Qt.MouseButton.LeftButton
        )
        QTest.mouseClick(
            staff_window.add_selected_button, Qt.MouseButton.LeftButton
        )
        app.processEvents()
        assert sum(staff_window.cart_quantities.values()) == initial_units + 2

        # Mouse quantity +/- controls and discount state.
        first_cart_item = staff_window.cart.item(0, 0)
        assert first_cart_item is not None
        cart_product_id = int(first_cart_item.data(Qt.ItemDataRole.UserRole))
        spin, _minus, plus = cart_quantity_controls(staff_window, cart_product_id)
        before_plus = Decimal(str(spin.value()))
        QTest.mouseClick(plus, Qt.MouseButton.LeftButton)
        app.processEvents()
        rebuilt_spin, rebuilt_minus, _rebuilt_plus = cart_quantity_controls(
            staff_window, cart_product_id
        )
        expected_plus = before_plus + Decimal("1")
        assert staff_window.cart_quantities[cart_product_id] == expected_plus
        assert Decimal(str(rebuilt_spin.value())) == expected_plus
        QTest.mouseClick(rebuilt_minus, Qt.MouseButton.LeftButton)
        app.processEvents()
        restored_spin, _restored_minus, _restored_plus = cart_quantity_controls(
            staff_window, cart_product_id
        )
        assert staff_window.cart_quantities[cart_product_id] == before_plus
        assert Decimal(str(restored_spin.value())) == before_plus
        staff_window.cart.selectRow(0)
        total_before_discount = staff_window._cart_total()

        def apply_item_discount(dialog: QDialog) -> None:
            assert isinstance(dialog, DiscountDialog)
            dialog.mode.setCurrentIndex(dialog.mode.findData("FIXED"))
            dialog.value.setValue(0.50)
            dialog.accept()

        schedule_modal(
            app,
            QTimer,
            lambda dialog: isinstance(dialog, DiscountDialog),
            apply_item_discount,
        )
        QTest.mouseClick(staff_window.discount_button, Qt.MouseButton.LeftButton)
        assert 50 in staff_window.cart_discounts.values()
        assert staff_window._cart_total() == total_before_discount - 50

        held_quantities = dict(staff_window.cart_quantities)
        held_discounts = dict(staff_window.cart_discounts)
        schedule_modal(
            app,
            QTimer,
            lambda dialog: isinstance(dialog, QMessageBox),
            dismiss_message,
        )
        QTest.mouseClick(staff_window.hold_button, Qt.MouseButton.LeftButton)
        assert not staff_window.cart_quantities
        QTest.mouseClick(staff_window.retrieve_button, Qt.MouseButton.LeftButton)
        assert staff_window.cart_quantities == held_quantities
        assert staff_window.cart_discounts == held_discounts
        save_screenshot(staff_window, artifact / "staff-pos.png")
        for item_view in (
            staff_window.products,
            staff_window.cart,
            staff_window.category_filter,
        ):
            send_wheel(item_view, QWheelEvent, QPointF, QPoint, Qt, QApplication)

        # Payment and completed dialogs are created as real Qt dialogs at every DPI.
        settings_clicks = []
        payment = CheckoutDialog(
            staff_window._cart_total(),
            [500, 1000, 2000, 5000],
            staff_window,
            customers=[(customer_id, "Test Customer")],
            quick_settings_callback=lambda: settings_clicks.append(True),
        )
        payment.show()
        app.processEvents()
        save_screenshot(payment, artifact / "payment-dialog.png")
        QTest.mouseClick(payment.settings_button, Qt.MouseButton.LeftButton)
        assert settings_clicks == [True]

        # Every payment choice is selected with the mouse. Credit must expose and
        # require the customer selector; the final Cash confirmation is clicked.
        for method in ("CARD", "DUITNOW_QR", "CREDIT", "CASH"):
            button = payment.findChild(QPushButton, f"PaymentMethod{method}")
            assert button is not None
            QTest.mouseClick(button, Qt.MouseButton.LeftButton)
            app.processEvents()
            assert button.isChecked()
            if method == "CREDIT":
                customer_combo = payment.findChild(QComboBox, "CreditCustomer")
                assert customer_combo is not None and customer_combo.isVisible()
                customer_combo.setCurrentIndex(1)
                assert customer_combo.currentData() == customer_id
        payment.paid_input.setText("10000")
        QTest.mouseClick(payment.confirm_button, Qt.MouseButton.LeftButton)
        assert payment.result() == QDialog.DialogCode.Accepted
        completed = SaleCompletedDialog(
            "CNKH20990101-001", 1000, 2000, "CASH", staff_window
        )
        completed.show()
        app.processEvents()
        save_screenshot(completed, artifact / "sale-completed.png")
        completed.close()

        # Complete all four payment methods through the real Staff checkout button,
        # nested payment dialog, and sale-completed dialog.
        def run_staff_sale(
            method: str,
            product_id: int,
            *,
            print_receipt: bool,
            open_settings: bool = False,
        ) -> int:
            staff_window._clear_cart()
            staff_window._add_to_cart(product_id)
            conn = database.connect(readonly=True)
            before_count = int(conn.execute("SELECT COUNT(*) FROM sales").fetchone()[0])
            conn.close()

            def finish_sale(completed_dialog: QDialog) -> None:
                assert isinstance(completed_dialog, SaleCompletedDialog)
                save_screenshot(
                    completed_dialog, artifact / "sale-completed-real.png"
                )
                if print_receipt:
                    schedule_modal(
                        app,
                        QTimer,
                        lambda dialog: isinstance(dialog, QMessageBox),
                        dismiss_message,
                    )
                    QTest.mouseClick(
                        completed_dialog.print_button, Qt.MouseButton.LeftButton
                    )
                else:
                    QTest.mouseClick(
                        completed_dialog.skip_button, Qt.MouseButton.LeftButton
                    )

            def pay(payment_dialog: QDialog) -> None:
                assert isinstance(payment_dialog, CheckoutDialog)
                save_screenshot(payment_dialog, artifact / "payment-dialog-real.png")
                if open_settings:
                    schedule_modal(
                        app,
                        QTimer,
                        lambda dialog: isinstance(dialog, QDialog)
                        and dialog is not payment_dialog,
                        lambda dialog: dialog.accept(),
                    )
                    QTest.mouseClick(
                        payment_dialog.settings_button, Qt.MouseButton.LeftButton
                    )
                method_button = payment_dialog.findChild(
                    QPushButton, f"PaymentMethod{method}"
                )
                assert method_button is not None
                QTest.mouseClick(method_button, Qt.MouseButton.LeftButton)
                if method == "CREDIT":
                    assert payment_dialog.customer.isVisible()
                    payment_dialog.customer.setCurrentIndex(1)
                    assert payment_dialog.customer.currentData() == customer_id
                elif method == "CASH":
                    payment_dialog.paid_input.setText(
                        f"{(payment_dialog.total_cents + 500) / 100:.2f}"
                    )
                schedule_modal(
                    app,
                    QTimer,
                    lambda dialog: isinstance(dialog, SaleCompletedDialog),
                    finish_sale,
                )
                QTest.mouseClick(
                    payment_dialog.confirm_button, Qt.MouseButton.LeftButton
                )

            schedule_modal(
                app,
                QTimer,
                lambda dialog: isinstance(dialog, CheckoutDialog),
                pay,
            )
            QTest.mouseClick(staff_window.checkout_button, Qt.MouseButton.LeftButton)
            app.processEvents()
            conn = database.connect(readonly=True)
            row = conn.execute(
                "SELECT id,payment_method FROM sales ORDER BY id DESC LIMIT 1"
            ).fetchone()
            count = int(conn.execute("SELECT COUNT(*) FROM sales").fetchone()[0])
            conn.close()
            assert count == before_count + 1
            assert row["payment_method"] == method
            return int(row["id"])

        staff_cash_sale_id = run_staff_sale(
            "CASH", products[0], print_receipt=True, open_settings=True
        )
        run_staff_sale("CARD", products[1], print_receipt=False)
        run_staff_sale("DUITNOW_QR", products[2], print_receipt=False)
        staff_credit_sale_id = run_staff_sale(
            "CREDIT", products[3], print_receipt=False
        )

        # Return a completed Cash sale through the Admin sales page and modal.
        QTest.mouseClick(sidebar_buttons[2], Qt.MouseButton.LeftButton)
        sales_page = admin_window.pages.currentWidget()
        assert isinstance(sales_page, SalesPage)
        sales_page.refresh()
        cash_sale_row = next(
            row
            for row in range(sales_page.table.rowCount())
            if int(sales_page.table.item(row, 0).text()) == staff_cash_sale_id
        )
        sales_page.table.selectRow(cash_sale_row)

        def fill_return(dialog: QDialog) -> None:
            assert isinstance(dialog, ReturnSaleDialog)
            quantity = dialog.table.cellWidget(0, 5)
            assert isinstance(quantity, QDoubleSpinBox)
            quantity.setValue(quantity.maximum())
            dialog.reason.setText("UI acceptance return")
            dialog.refund_method.setCurrentIndex(
                dialog.refund_method.findData("CASH")
            )
            schedule_modal(
                app,
                QTimer,
                lambda candidate: isinstance(candidate, QMessageBox),
                dismiss_message,
            )
            buttons = dialog.findChild(QDialogButtonBox)
            assert buttons is not None
            QTest.mouseClick(
                buttons.button(QDialogButtonBox.StandardButton.Save),
                Qt.MouseButton.LeftButton,
            )

        schedule_modal(
            app, QTimer, lambda dialog: isinstance(dialog, ReturnSaleDialog), fill_return
        )
        QTest.mouseClick(
            button_by_text(sales_page, QPushButton, "销售退货"),
            Qt.MouseButton.LeftButton,
        )
        conn = database.connect(readonly=True)
        assert conn.execute(
            "SELECT COUNT(*) FROM sale_returns WHERE sale_id=?", (staff_cash_sale_id,)
        ).fetchone()[0] == 1
        conn.close()

        schedule_modal(
            app,
            QTimer,
            lambda dialog: isinstance(dialog, QMessageBox),
            dismiss_message,
        )
        QTest.mouseClick(staff_window.reprint_button, Qt.MouseButton.LeftButton)

        # Real business flow matrix.
        sales = SalesService(database)
        sales.create_sale(
            lines=[SaleLine(products[0], Decimal("1"), Decimal("1"), 10)],
            payment_method="CASH",
            paid_cents=1000,
            cashier_id=staff_id,
        )
        sales.create_sale(
            lines=[SaleLine(products[1], Decimal("1"), Decimal("1"))],
            payment_method="CARD",
            paid_cents=281,
            cashier_id=staff_id,
        )
        sales.create_sale(
            lines=[SaleLine(products[2], Decimal("1"), Decimal("1"))],
            payment_method="DUITNOW_QR",
            paid_cents=282,
            cashier_id=staff_id,
        )
        credit = sales.create_sale(
            lines=[SaleLine(products[3], Decimal("1"), Decimal("1"))],
            payment_method="CREDIT",
            paid_cents=0,
            cashier_id=staff_id,
            customer_id=customer_id,
        )
        purchase = PurchaseService(database).create_purchase(
            supplier_id=supplier_id,
            lines=[PurchaseLine(products[0], Decimal("5"), 100)],
            paid_cents=100,
            payment_method="CASH",
            operator_id=admin_id,
        )
        SupplierPaymentService(database).record_payment(
            purchase_id=purchase.purchase_id,
            amount_cents=400,
            payment_method="CARD",
            note="settled",
            operator_id=admin_id,
        )
        conn = database.connect(readonly=True)
        debt_id = int(
            conn.execute(
                "SELECT id FROM customer_debts WHERE sale_id=?", (credit.sale_id,)
            ).fetchone()[0]
        )
        conn.close()
        CustomerPaymentService(database).record_payment(
            debt_id=debt_id,
            amount_cents=283,
            payment_method="CASH",
            note="settled",
            operator_id=admin_id,
        )
        DailyClosingService(database).complete(
            business_date=date.today(),
            cashier_id=staff_id,
            actual_cash_cents=270,
            note="UI acceptance",
        )
        stocktake_id, _ = StocktakeService(database).create_draft(operator_id=admin_id)
        StocktakeService(database).set_physical_count(
            stocktake_id=stocktake_id, product_id=products[0], count="499"
        )
        StocktakeService(database).complete(
            stocktake_id=stocktake_id, operator_id=admin_id
        )
        receipt = PrintingService(database).latest_receipt()
        PrintingService(database).render_pdf(receipt, artifact / "reprinted-latest.pdf")
        PrintingService(database).print_receipt(
            receipt, output_pdf=artifact / "qt-80mm-test-print.pdf"
        )
        BackupService(root / "backups").create(database.path, reason="gui_acceptance")
        ok, messages = database.integrity_check()
        assert ok, messages

        # Product creation through the visible Admin action and modal form.
        QTest.mouseClick(sidebar_buttons[1], Qt.MouseButton.LeftButton)
        product_tabs = admin_window.pages.currentWidget()
        assert isinstance(product_tabs, QTabWidget)
        product_tabs.setCurrentIndex(0)
        products_page = product_tabs.currentWidget()
        assert isinstance(products_page, ProductsPage)
        conn = database.connect(readonly=True)
        product_count = int(conn.execute("SELECT COUNT(*) FROM products").fetchone()[0])
        conn.close()

        def fill_product(dialog: QDialog) -> None:
            assert isinstance(dialog, ProductDialog)
            dialog.name.setText("UI Acceptance Test Product")
            dialog.sku.setText("UI-ACCEPT-001")
            dialog.cost.setText("1.25")
            dialog.price.setText("2.50")
            dialog.stock.setText("10")
            dialog.location.setText("QA Rack")
            buttons = dialog.findChild(QDialogButtonBox)
            assert buttons is not None
            QTest.mouseClick(
                buttons.button(QDialogButtonBox.StandardButton.Save),
                Qt.MouseButton.LeftButton,
            )

        schedule_modal(
            app,
            QTimer,
            lambda dialog: isinstance(dialog, ProductDialog),
            fill_product,
        )
        QTest.mouseClick(
            button_by_text(products_page, QPushButton, "＋ 新增"),
            Qt.MouseButton.LeftButton,
        )
        conn = database.connect(readonly=True)
        assert int(conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]) == product_count + 1
        conn.close()

        # Product editing and the Excel import picker are both wired to real actions.
        while products_page.next.isEnabled():
            QTest.mouseClick(products_page.next, Qt.MouseButton.LeftButton)
            app.processEvents()
        edited_row = next(
            row
            for row in range(products_page.table.rowCount())
            if products_page.table.item(row, 1).text() == "UI Acceptance Test Product"
        )
        products_page.table.selectRow(edited_row)

        def edit_product(dialog: QDialog) -> None:
            assert isinstance(dialog, ProductDialog)
            dialog.location.setText("QA Rack Updated")
            buttons = dialog.findChild(QDialogButtonBox)
            assert buttons is not None
            QTest.mouseClick(
                buttons.button(QDialogButtonBox.StandardButton.Save),
                Qt.MouseButton.LeftButton,
            )

        schedule_modal(
            app, QTimer, lambda dialog: isinstance(dialog, ProductDialog), edit_product
        )
        QTest.mouseClick(
            button_by_text(products_page, QPushButton, "编辑"),
            Qt.MouseButton.LeftButton,
        )
        conn = database.connect(readonly=True)
        assert conn.execute(
            "SELECT location FROM products WHERE sku='UI-ACCEPT-001'"
        ).fetchone()[0] == "QA Rack Updated"
        conn.close()
        schedule_modal(
            app,
            QTimer,
            lambda dialog: isinstance(dialog, QFileDialog),
            lambda dialog: dialog.reject(),
        )
        QTest.mouseClick(
            button_by_text(products_page, QPushButton, "Excel 导入"),
            Qt.MouseButton.LeftButton,
        )

        # Stock adjustment is entered in the real count table before completion.
        product_tabs.setCurrentIndex(1)
        stocktake_page = product_tabs.currentWidget()
        assert isinstance(stocktake_page, StocktakePage)
        QTest.mouseClick(
            button_by_text(stocktake_page, QPushButton, "＋ 新建盘点"),
            Qt.MouseButton.LeftButton,
        )
        draft_row = next(
            row
            for row in range(stocktake_page.table.rowCount())
            if stocktake_page.table.item(row, 6).text() == "DRAFT"
        )
        stocktake_page.table.selectRow(draft_row)
        ui_stocktake_id = int(stocktake_page.table.item(draft_row, 0).text())

        def adjust_stock(dialog: QDialog) -> None:
            assert isinstance(dialog, StocktakeCountDialog)
            control = dialog.table.cellWidget(0, 3)
            assert isinstance(control, QDoubleSpinBox)
            control.setValue(max(0, control.value() - 1))
            buttons = dialog.findChild(QDialogButtonBox)
            assert buttons is not None
            QTest.mouseClick(
                buttons.button(QDialogButtonBox.StandardButton.Save),
                Qt.MouseButton.LeftButton,
            )

        schedule_modal(
            app,
            QTimer,
            lambda dialog: isinstance(dialog, StocktakeCountDialog),
            adjust_stock,
        )
        QTest.mouseClick(
            button_by_text(
                stocktake_page, QPushButton, "盘点数量 / 库存调整"
            ),
            Qt.MouseButton.LeftButton,
        )
        for row in range(stocktake_page.table.rowCount()):
            if int(stocktake_page.table.item(row, 0).text()) == ui_stocktake_id:
                stocktake_page.table.selectRow(row)
                break
        QTest.mouseClick(
            button_by_text(stocktake_page, QPushButton, "完成盘点"),
            Qt.MouseButton.LeftButton,
        )
        conn = database.connect(readonly=True)
        assert conn.execute(
            "SELECT status FROM stocktakes WHERE id=?", (ui_stocktake_id,)
        ).fetchone()[0] == "COMPLETED"
        conn.close()

        # Add a full customer and supplier, then configure the supplier catalogue.
        QTest.mouseClick(sidebar_buttons[4], Qt.MouseButton.LeftButton)
        customer_page = admin_window.pages.currentWidget()
        assert isinstance(customer_page, EntityPage)

        def fill_customer(dialog: QDialog) -> None:
            assert isinstance(dialog, EntityDialog)
            dialog.name.setText("UI Full Customer")
            dialog.phone.setText("012-555-0101")
            dialog.notes.setPlainText("Customer note from GUI acceptance")
            buttons = dialog.findChild(QDialogButtonBox)
            assert buttons is not None
            QTest.mouseClick(
                buttons.button(QDialogButtonBox.StandardButton.Save),
                Qt.MouseButton.LeftButton,
            )

        schedule_modal(
            app, QTimer, lambda dialog: isinstance(dialog, EntityDialog), fill_customer
        )
        QTest.mouseClick(
            button_by_text(customer_page, QPushButton, "＋ 新增"),
            Qt.MouseButton.LeftButton,
        )

        QTest.mouseClick(sidebar_buttons[5], Qt.MouseButton.LeftButton)
        supplier_page = admin_window.pages.currentWidget()
        assert isinstance(supplier_page, EntityPage)

        def fill_supplier(dialog: QDialog) -> None:
            assert isinstance(dialog, EntityDialog)
            dialog.name.setText("UI Full Supplier")
            dialog.phone.setText("019-555-0202")
            dialog.email.setText("ui-supplier@example.com")
            dialog.notes.setPlainText("Supplier note from GUI acceptance")
            buttons = dialog.findChild(QDialogButtonBox)
            assert buttons is not None
            QTest.mouseClick(
                buttons.button(QDialogButtonBox.StandardButton.Save),
                Qt.MouseButton.LeftButton,
            )

        schedule_modal(
            app, QTimer, lambda dialog: isinstance(dialog, EntityDialog), fill_supplier
        )
        QTest.mouseClick(
            button_by_text(supplier_page, QPushButton, "＋ 新增"),
            Qt.MouseButton.LeftButton,
        )
        supplier_page.refresh()
        supplier_row = next(
            row
            for row in range(supplier_page.table.rowCount())
            if supplier_page.table.item(row, 1).text() == "UI Full Supplier"
        )
        supplier_page.table.selectRow(supplier_row)

        def choose_supplier_product(dialog: QDialog) -> None:
            assert isinstance(dialog, SupplierProductsDialog)
            dialog.table.cellWidget(0, 3).setChecked(True)
            schedule_modal(
                app,
                QTimer,
                lambda candidate: isinstance(candidate, QMessageBox),
                dismiss_message,
            )
            buttons = dialog.findChild(QDialogButtonBox)
            assert buttons is not None
            QTest.mouseClick(
                buttons.button(QDialogButtonBox.StandardButton.Save),
                Qt.MouseButton.LeftButton,
            )

        schedule_modal(
            app,
            QTimer,
            lambda dialog: isinstance(dialog, SupplierProductsDialog),
            choose_supplier_product,
        )
        QTest.mouseClick(
            button_by_text(supplier_page, QPushButton, "供货商品"),
            Qt.MouseButton.LeftButton,
        )
        conn = database.connect(readonly=True)
        assert conn.execute(
            """SELECT COUNT(*) FROM supplier_products sp
               JOIN suppliers s ON s.id=sp.supplier_id
               WHERE s.name='UI Full Supplier' AND sp.is_active=1"""
        ).fetchone()[0] == 1
        conn.close()

        # New purchase and supplier payment through the Admin page.
        QTest.mouseClick(sidebar_buttons[3], Qt.MouseButton.LeftButton)
        purchases_page = admin_window.pages.currentWidget()
        assert isinstance(purchases_page, PurchasesPage)

        def fill_purchase(dialog: QDialog) -> None:
            assert isinstance(dialog, NewPurchaseDialog)
            dialog.quantity.setValue(2)
            dialog.cost.setValue(2)
            QTest.mouseClick(
                button_by_text(dialog, QPushButton, "＋ Add Item"),
                Qt.MouseButton.LeftButton,
            )
            buttons = dialog.findChild(QDialogButtonBox)
            assert buttons is not None
            QTest.mouseClick(
                buttons.button(QDialogButtonBox.StandardButton.Save),
                Qt.MouseButton.LeftButton,
            )

        schedule_modal(
            app,
            QTimer,
            lambda dialog: isinstance(dialog, NewPurchaseDialog),
            fill_purchase,
        )
        QTest.mouseClick(
            button_by_text(purchases_page, QPushButton, "＋ 新建进货"),
            Qt.MouseButton.LeftButton,
        )
        conn = database.connect(readonly=True)
        ui_purchase_id = int(conn.execute("SELECT MAX(id) FROM purchases").fetchone()[0])
        conn.close()
        for row in range(purchases_page.table.rowCount()):
            if int(purchases_page.table.item(row, 0).text()) == ui_purchase_id:
                purchases_page.table.selectRow(row)
                break

        def supplier_amount(dialog: QDialog) -> None:
            assert isinstance(dialog, RecordPaymentDialog)
            dialog.amount.setValue(1.00)
            dialog.method.setCurrentText("CARD")
            dialog.note.setPlainText("UI supplier payment")
            buttons = dialog.findChild(QDialogButtonBox)
            assert buttons is not None
            QTest.mouseClick(
                buttons.button(QDialogButtonBox.StandardButton.Save),
                Qt.MouseButton.LeftButton,
            )

        schedule_modal(
            app,
            QTimer,
            lambda dialog: isinstance(dialog, RecordPaymentDialog),
            supplier_amount,
        )
        QTest.mouseClick(
            button_by_text(purchases_page, QPushButton, "记录供应商付款"),
            Qt.MouseButton.LeftButton,
        )
        conn = database.connect(readonly=True)
        assert conn.execute(
            "SELECT COUNT(*) FROM supplier_payments WHERE purchase_id=?",
            (ui_purchase_id,),
        ).fetchone()[0] == 1
        conn.close()
        purchases_page.refresh()
        for row in range(purchases_page.table.rowCount()):
            if int(purchases_page.table.item(row, 0).text()) == ui_purchase_id:
                purchases_page.table.selectRow(row)
                break

        def confirm_delete_purchase(dialog: QDialog) -> None:
            assert isinstance(dialog, QMessageBox)
            yes = dialog.button(QMessageBox.StandardButton.Yes)
            assert yes is not None
            QTest.mouseClick(yes, Qt.MouseButton.LeftButton)

        schedule_modal(
            app,
            QTimer,
            lambda dialog: isinstance(dialog, QMessageBox),
            confirm_delete_purchase,
        )
        QTest.mouseClick(
            button_by_text(purchases_page, QPushButton, "删除进货"),
            Qt.MouseButton.LeftButton,
        )
        conn = database.connect(readonly=True)
        assert conn.execute(
            "SELECT COUNT(*) FROM purchases WHERE id=?", (ui_purchase_id,)
        ).fetchone()[0] == 0
        void_payment = conn.execute(
            "SELECT purchase_id,voided_at FROM supplier_payments ORDER BY id DESC LIMIT 1"
        ).fetchone()
        assert void_payment["purchase_id"] is None
        assert void_payment["voided_at"] is not None
        conn.close()

        # Settle the debt created by the real Staff Credit checkout.
        QTest.mouseClick(sidebar_buttons[4], Qt.MouseButton.LeftButton)
        customer_page = admin_window.pages.currentWidget()
        assert isinstance(customer_page, EntityPage)
        customer_page.refresh()
        customer_page.table.selectRow(0)
        def customer_amount(dialog: QDialog) -> None:
            assert isinstance(dialog, RecordPaymentDialog)
            dialog.amount.setValue(dialog.amount.maximum())
            dialog.method.setCurrentText("DUITNOW_QR")
            dialog.note.setPlainText("UI customer payment")
            buttons = dialog.findChild(QDialogButtonBox)
            assert buttons is not None
            QTest.mouseClick(
                buttons.button(QDialogButtonBox.StandardButton.Save),
                Qt.MouseButton.LeftButton,
            )

        schedule_modal(
            app,
            QTimer,
            lambda dialog: isinstance(dialog, RecordPaymentDialog),
            customer_amount,
        )
        QTest.mouseClick(
            button_by_text(customer_page, QPushButton, "记录还款"),
            Qt.MouseButton.LeftButton,
        )
        conn = database.connect(readonly=True)
        assert conn.execute(
            "SELECT status FROM customer_debts WHERE sale_id=?",
            (staff_credit_sale_id,),
        ).fetchone()[0] == "CLOSED"
        conn.close()

        # Create and edit a Staff account with real permission controls.
        QTest.mouseClick(sidebar_buttons[6], Qt.MouseButton.LeftButton)
        users_page = admin_window.pages.currentWidget()
        assert isinstance(users_page, UsersPage)

        def fill_user(dialog: QDialog) -> None:
            assert isinstance(dialog, NewUserDialog)
            dialog.username.setText("ui_staff")
            dialog.display_name.setText("UI Staff")
            dialog.password.setText("SafePass999!")
            dialog.confirm.setText("SafePass999!")
            dialog.apply_discount.setChecked(True)
            dialog.manage_quick.setChecked(True)
            buttons = dialog.findChild(QDialogButtonBox)
            assert buttons is not None
            QTest.mouseClick(
                buttons.button(QDialogButtonBox.StandardButton.Save),
                Qt.MouseButton.LeftButton,
            )

        schedule_modal(
            app, QTimer, lambda dialog: isinstance(dialog, NewUserDialog), fill_user
        )
        QTest.mouseClick(
            button_by_text(users_page, QPushButton, "＋ 新增账号"),
            Qt.MouseButton.LeftButton,
        )
        users_page.refresh()
        ui_staff_row = next(
            row
            for row in range(users_page.table.rowCount())
            if users_page.table.item(row, 1).text() == "ui_staff"
        )
        users_page.table.selectRow(ui_staff_row)

        def edit_user(dialog: QDialog) -> None:
            assert isinstance(dialog, EditUserDialog)
            dialog.display_name.setText("UI Senior Staff")
            dialog.reprint.setChecked(True)
            buttons = dialog.findChild(QDialogButtonBox)
            assert buttons is not None
            QTest.mouseClick(
                buttons.button(QDialogButtonBox.StandardButton.Save),
                Qt.MouseButton.LeftButton,
            )

        schedule_modal(
            app, QTimer, lambda dialog: isinstance(dialog, EditUserDialog), edit_user
        )
        QTest.mouseClick(
            button_by_text(users_page, QPushButton, "编辑账号/权限"),
            Qt.MouseButton.LeftButton,
        )
        conn = database.connect(readonly=True)
        assert conn.execute(
            "SELECT display_name FROM users WHERE username='ui_staff'"
        ).fetchone()[0] == "UI Senior Staff"
        conn.close()

        # Category Add/Rename and every settings tab.
        QTest.mouseClick(sidebar_buttons[8], Qt.MouseButton.LeftButton)
        settings_page = admin_window.pages.currentWidget()
        settings_tabs = settings_page.findChild(QTabWidget)
        assert settings_tabs is not None

        def edit_category(dialog: QDialog) -> None:
            assert isinstance(dialog, CategoryDialog)
            dialog.name.setText("UI Test Category")
            QTest.mouseClick(
                button_by_text(dialog, QPushButton, "新增分类"),
                Qt.MouseButton.LeftButton,
            )
            for row in range(dialog.list.count()):
                if dialog.list.item(row).text() == "UI Test Category":
                    dialog.list.setCurrentRow(row)
                    break
            dialog.name.setText("UI Test Category Renamed")
            QTest.mouseClick(
                button_by_text(dialog, QPushButton, "修改分类"),
                Qt.MouseButton.LeftButton,
            )
            QTest.mouseClick(
                button_by_text(dialog, QPushButton, "关闭"),
                Qt.MouseButton.LeftButton,
            )

        schedule_modal(
            app,
            QTimer,
            lambda dialog: isinstance(dialog, CategoryDialog),
            edit_category,
        )
        QTest.mouseClick(
            button_by_text(
                settings_page, QPushButton, "Category Management / 分类管理"
            ),
            Qt.MouseButton.LeftButton,
        )
        conn = database.connect(readonly=True)
        assert conn.execute(
            "SELECT COUNT(*) FROM categories WHERE name='UI Test Category Renamed'"
        ).fetchone()[0] == 1
        conn.close()

        settings_tabs.setCurrentIndex(0)
        receipt_settings = settings_tabs.currentWidget()
        assert isinstance(receipt_settings, ReceiptSettingsWidget)
        receipt_settings.store.setText("CNKH Hardware UI Acceptance")
        receipt_settings.printer.setCurrentIndex(1)
        schedule_modal(
            app,
            QTimer,
            lambda dialog: isinstance(dialog, QMessageBox),
            dismiss_message,
        )
        QTest.mouseClick(receipt_settings.save_button, Qt.MouseButton.LeftButton)
        schedule_modal(
            app,
            QTimer,
            lambda dialog: isinstance(dialog, QMessageBox),
            dismiss_message,
        )
        QTest.mouseClick(receipt_settings.test_button, Qt.MouseButton.LeftButton)
        export_dir = (
            Path(os.environ["LOCALAPPDATA"])
            / "CNKH Hardware POS"
            / "Exports"
        )
        assert (export_dir / "receipt-settings-test.pdf").exists()

        settings_tabs.setCurrentIndex(1)
        quick_amounts = settings_tabs.currentWidget()
        assert isinstance(quick_amounts, QuickAmountsWidget)
        schedule_modal(
            app,
            QTimer,
            lambda dialog: isinstance(dialog, QInputDialog),
            lambda dialog: enter_double(dialog, 777.77),
        )
        QTest.mouseClick(
            button_by_text(quick_amounts, QPushButton, "＋ 新增"),
            Qt.MouseButton.LeftButton,
        )
        quick_amounts.table.selectRow(quick_amounts.table.rowCount() - 1)
        schedule_modal(
            app,
            QTimer,
            lambda dialog: isinstance(dialog, QInputDialog),
            lambda dialog: enter_double(dialog, 888.88),
        )
        QTest.mouseClick(
            button_by_text(quick_amounts, QPushButton, "修改"),
            Qt.MouseButton.LeftButton,
        )
        QTest.mouseClick(
            button_by_text(quick_amounts, QPushButton, "启用/禁用"),
            Qt.MouseButton.LeftButton,
        )
        QTest.mouseClick(
            button_by_text(quick_amounts, QPushButton, "删除"),
            Qt.MouseButton.LeftButton,
        )
        settings_tabs.setCurrentIndex(2)
        prefixes = settings_tabs.currentWidget()
        assert isinstance(prefixes, DocumentPrefixesWidget)
        prefixes.controls["PURCHASE"].setText("GUI-PI-")
        schedule_modal(
            app,
            QTimer,
            lambda dialog: isinstance(dialog, QMessageBox),
            dismiss_message,
        )
        QTest.mouseClick(prefixes.save_button, Qt.MouseButton.LeftButton)
        settings_tabs.setCurrentIndex(3)
        assert settings_tabs.currentWidget().isVisible()

        # Export a real XLSX and complete Daily Cash Closing with the mouse.
        QTest.mouseClick(sidebar_buttons[7], Qt.MouseButton.LeftButton)
        report_tabs = admin_window.pages.currentWidget()
        assert isinstance(report_tabs, QTabWidget)
        report_tabs.setCurrentIndex(0)
        reports = report_tabs.currentWidget()
        assert isinstance(reports, ReportsPage)
        schedule_modal(
            app,
            QTimer,
            lambda dialog: isinstance(dialog, QMessageBox),
            dismiss_message,
        )
        QTest.mouseClick(reports.export_button, Qt.MouseButton.LeftButton)
        assert list(export_dir.glob("CNKH_POS_Report_*.xlsx"))

        report_tabs.setCurrentIndex(1)
        daily = report_tabs.currentWidget()
        assert isinstance(daily, DailyClosingPage)
        daily.actual.setValue(float(daily.system.text()))
        schedule_modal(
            app,
            QTimer,
            lambda dialog: isinstance(dialog, QMessageBox),
            dismiss_message,
        )
        QTest.mouseClick(
            button_by_text(daily, QPushButton, "完成日结"),
            Qt.MouseButton.LeftButton,
        )
        conn = database.connect(readonly=True)
        assert conn.execute(
            "SELECT COUNT(*) FROM daily_cash_closings WHERE cashier_id=?",
            (admin_id,),
        ).fetchone()[0] == 1
        conn.close()

        # Integrity, backup, and the actual Restore picker (safely cancelled).
        QTest.mouseClick(sidebar_buttons[9], Qt.MouseButton.LeftButton)
        maintenance_tabs = admin_window.pages.currentWidget()
        assert isinstance(maintenance_tabs, QTabWidget)
        maintenance_tabs.setCurrentIndex(0)
        maintenance = maintenance_tabs.currentWidget()
        assert isinstance(maintenance, MaintenancePage)
        for label in ("Run Integrity Check", "Backup"):
            schedule_modal(
                app,
                QTimer,
                lambda dialog: isinstance(dialog, QMessageBox),
                dismiss_message,
            )
            QTest.mouseClick(
                button_by_text(maintenance, QPushButton, label),
                Qt.MouseButton.LeftButton,
            )
        schedule_modal(
            app,
            QTimer,
            lambda dialog: isinstance(dialog, QFileDialog),
            lambda dialog: dialog.reject(),
        )
        QTest.mouseClick(
            button_by_text(maintenance, QPushButton, "Restore"),
            Qt.MouseButton.LeftButton,
        )
        backup_dir = (
            Path(os.environ["LOCALAPPDATA"])
            / "CNKH Hardware POS"
            / "Backups"
        )
        assert list(backup_dir.glob("hardware_pos_*.db"))

        # Audit Log clear is reachable but rejects an incorrect Admin password.
        maintenance_tabs.setCurrentIndex(1)
        audit_page = maintenance_tabs.currentWidget()
        assert isinstance(audit_page, AuditPage)
        conn = database.connect(readonly=True)
        audit_before = int(conn.execute("SELECT COUNT(*) FROM audit_logs").fetchone()[0])
        conn.close()

        def reject_audit_password(dialog: QDialog) -> None:
            assert isinstance(dialog, QInputDialog)
            control = dialog.findChild(QLineEdit)
            assert control is not None
            control.setText("wrong password")
            schedule_modal(
                app,
                QTimer,
                lambda candidate: isinstance(candidate, QMessageBox),
                dismiss_message,
            )
            dialog.accept()

        def confirm_audit_clear(dialog: QDialog) -> None:
            assert isinstance(dialog, QMessageBox)
            schedule_modal(
                app,
                QTimer,
                lambda candidate: isinstance(candidate, QInputDialog),
                reject_audit_password,
            )
            yes = dialog.button(QMessageBox.StandardButton.Yes)
            assert yes is not None
            QTest.mouseClick(yes, Qt.MouseButton.LeftButton)

        schedule_modal(
            app,
            QTimer,
            lambda dialog: isinstance(dialog, QMessageBox),
            confirm_audit_clear,
        )
        QTest.mouseClick(
            button_by_text(audit_page, QPushButton, "清除 Audit Log"),
            Qt.MouseButton.LeftButton,
        )
        conn = database.connect(readonly=True)
        assert int(conn.execute("SELECT COUNT(*) FROM audit_logs").fetchone()[0]) == audit_before
        conn.close()
        ok, messages = database.integrity_check()
        assert ok, messages

        # Refresh the final Dashboard from actual transaction data and preserve it
        # for human screenshot review at every DPI.
        QTest.mouseClick(sidebar_buttons[0], Qt.MouseButton.LeftButton)
        dashboard = admin_window.pages.currentWidget()
        assert isinstance(dashboard, DashboardPage)
        QTest.mouseClick(dashboard.refresh_button, Qt.MouseButton.LeftButton)
        assert dashboard.recent_table.rowCount() >= 4
        save_screenshot(admin_window, artifact / "admin-dashboard-final.png")

        admin_window.close()
        staff_window.close()
        app.processEvents()
    print(f"WINDOWS GUI ACCEPTANCE {args.scale}% PASSED")
    return 0


def save_screenshot(widget, path: Path) -> None:
    pixmap = widget.grab()
    if pixmap.isNull():
        raise AssertionError(f"screenshot is null: {path}")
    if not pixmap.save(str(path)):
        raise AssertionError(f"screenshot could not be saved: {path}")
    if not path.is_file() or path.stat().st_size == 0:
        raise AssertionError(f"screenshot is empty: {path}")


def assert_visible_buttons(window, button_type, scroll_area_type) -> None:
    for button in window.findChildren(button_type):
        if not button.isVisible():
            continue
        ancestor = button.parentWidget()
        clipped_by_scroll_area = False
        while ancestor is not None:
            if isinstance(ancestor, scroll_area_type):
                viewport = ancestor.viewport()
                top_left = button.mapTo(viewport, button.rect().topLeft())
                button_rect = button.rect().translated(top_left)
                if not viewport.rect().intersects(button_rect):
                    clipped_by_scroll_area = True
                    break
            ancestor = ancestor.parentWidget()
        if clipped_by_scroll_area:
            continue
        point = button.mapTo(window, button.rect().topLeft())
        rect = button.rect().translated(point)
        assert window.rect().intersects(rect), f"button outside window: {button.text()}"
        assert button.width() >= 24 and button.height() >= 24, (
            f"button too small: {button.text()}"
        )


def send_wheel(widget, wheel_type, pointf, point, qt, application) -> None:
    local = pointf(widget.rect().center())
    global_pos = pointf(widget.mapToGlobal(widget.rect().center()))
    event = wheel_type(
        local,
        global_pos,
        point(0, 0),
        point(0, -120),
        qt.MouseButton.NoButton,
        qt.KeyboardModifier.NoModifier,
        qt.ScrollPhase.ScrollUpdate,
        False,
    )
    application.sendEvent(widget.viewport(), event)
    application.processEvents()


def button_by_text(parent, button_type, text):
    for button in parent.findChildren(button_type):
        if button.text() == text:
            return button
    raise AssertionError(f"button not found: {text}")


def schedule_modal(application, timer_type, predicate, callback, attempts: int = 200) -> None:
    """Run a real modal interaction inside Qt's nested event loop."""

    def poll(remaining: int) -> None:
        dialog = application.activeModalWidget()
        if dialog is not None and predicate(dialog):
            callback(dialog)
            return
        if remaining <= 0:
            raise AssertionError("expected modal dialog did not appear")
        timer_type.singleShot(10, lambda: poll(remaining - 1))

    timer_type.singleShot(0, lambda: poll(attempts))


if __name__ == "__main__":
    raise SystemExit(main())
