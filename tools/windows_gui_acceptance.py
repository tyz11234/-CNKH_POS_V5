from __future__ import annotations

import argparse
import tempfile
from datetime import date
from decimal import Decimal
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scale", required=True)
    args = parser.parse_args()
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QShortcut, QWheelEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import (
        QAbstractScrollArea,
        QApplication,
        QDialog,
        QDoubleSpinBox,
        QPushButton,
        QTabWidget,
        QTableWidget,
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
    from cnkh_pos.ui.dialogs.checkout import CheckoutDialog, SaleCompletedDialog
    from cnkh_pos.ui.staff import StaffWindow
    from cnkh_pos.ui.theme import apply_theme

    artifact = Path("ui-acceptance-artifacts") / f"scale-{args.scale}"
    artifact.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
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
                permissions={"apply_discount": True},
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

        app = QApplication.instance() or QApplication([])
        apply_theme(app)
        admin_window = AdminWindow(database, admin)
        admin_window.resize(1366, 768)
        admin_window.show()
        app.processEvents()
        assert not admin_window.findChildren(QShortcut), (
            "custom POS shortcuts are forbidden"
        )
        for page_index in range(admin_window.pages.count()):
            admin_window.pages.setCurrentIndex(page_index)
            app.processEvents()
            assert_visible_buttons(admin_window, QPushButton, QAbstractScrollArea)
            admin_window.grab().save(str(artifact / f"admin-page-{page_index}.png"))
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
                    admin_window.grab().save(
                        str(artifact / f"admin-page-{page_index}-tab-{tab_index}.png")
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

        # Fuzzy search, maximum three suggestions, mouse selection.
        staff_window.search.setFocus()
        QTest.keyClicks(staff_window.search, "kabel")
        app.processEvents()
        assert 0 < staff_window.results.rowCount() <= 3
        staff_window._result_clicked(0, 0)
        assert staff_window.cart_quantities
        # Exact barcode auto-add.
        staff_window.search.setText(barcode)
        app.processEvents()
        assert len(staff_window.cart_quantities) >= 1
        # Mouse quantity control and discount state.
        spin = staff_window.cart.findChild(QDoubleSpinBox)
        assert spin is not None
        spin.setValue(2.5)
        spin.editingFinished.emit()
        first_product = next(iter(staff_window.cart_quantities))
        staff_window.cart_discounts[first_product] = 50
        staff_window._rebuild_cart()
        staff_window.grab().save(str(artifact / "staff-pos.png"))
        send_wheel(
            staff_window.products, QWheelEvent, QPointF, QPoint, Qt, QApplication
        )

        # Payment and completed dialogs are created as real Qt dialogs at every DPI.
        payment = CheckoutDialog(
            staff_window._cart_total(), [500, 1000, 2000, 5000], staff_window
        )
        payment.show()
        app.processEvents()
        payment.grab().save(str(artifact / "payment-dialog.png"))
        payment.paid_input.setText("10000")
        payment._confirm()
        assert payment.result() == QDialog.DialogCode.Accepted
        completed = SaleCompletedDialog(
            "CNKH20990101-001", 1000, 2000, "CASH", staff_window
        )
        completed.show()
        app.processEvents()
        completed.grab().save(str(artifact / "sale-completed.png"))
        completed.close()

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
        admin_window.close()
        staff_window.close()
        app.processEvents()
    print(f"WINDOWS GUI ACCEPTANCE {args.scale}% PASSED")
    return 0


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


if __name__ == "__main__":
    raise SystemExit(main())
