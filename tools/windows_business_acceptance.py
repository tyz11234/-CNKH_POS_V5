from __future__ import annotations

import json
import os
import re
import tempfile
import traceback
from datetime import date
from decimal import Decimal
from pathlib import Path

from openpyxl import load_workbook
from PySide6.QtWidgets import QApplication

from cnkh_pos.database.bootstrap import bootstrap_database
from cnkh_pos.database.connection import Database
from cnkh_pos.services.auth import AuthService
from cnkh_pos.services.backup import BackupService
from cnkh_pos.services.barcode_labels import (
    get_label_profile,
    load_product_label,
    render_product_label_pdf,
)
from cnkh_pos.services.catalog import (
    CatalogService,
    CategoryService,
    ProductInput,
    is_valid_ean13,
)
from cnkh_pos.services.checkout_rounding import (
    RoundedReturnService,
    RoundedSalesService,
)
from cnkh_pos.services.daily_closing import DailyClosingService
from cnkh_pos.services.discounts import (
    allocate_order_discount,
    discount_cents_from_value,
)
from cnkh_pos.services.entities import EntityInput, EntityService
from cnkh_pos.services.excel_import import ExcelImportService
from cnkh_pos.services.held_orders import HeldOrderService
from cnkh_pos.services.payments import CustomerPaymentService, SupplierPaymentService
from cnkh_pos.services.printing import PrintingService
from cnkh_pos.services.purchases import PurchaseLine, PurchaseService
from cnkh_pos.services.reports import ReportService
from cnkh_pos.services.restore import RestoreService
from cnkh_pos.services.sales import SaleLine, SalesService
from cnkh_pos.services.stocktake import StocktakeService
from cnkh_pos.ui.admin import AdminWindow
from cnkh_pos.ui.staff import StaffWindow

ADMIN_PASSWORD = "LifecycleAdmin123!"
STAFF_PASSWORD = "LifecycleStaff123!"


def _assert(condition: object, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _stock(database: Database, product_id: int) -> Decimal:
    conn = database.connect(readonly=True)
    try:
        row = conn.execute(
            "SELECT stock_decimal FROM products WHERE id=?", (product_id,)
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        raise LookupError(f"product {product_id} is missing")
    return Decimal(str(row[0]))


def _product_barcode(database: Database, product_id: int) -> str:
    conn = database.connect(readonly=True)
    try:
        row = conn.execute(
            "SELECT barcode FROM products WHERE id=?", (product_id,)
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        raise LookupError(f"product {product_id} is missing")
    return str(row[0] or "")


def _write_report(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    temporary.replace(path)


def run() -> int:
    artifact_dir = Path(
        os.environ.get("CNKH_POS_BUSINESS_ACCEPTANCE_DIR", "business-acceptance-artifacts")
    ).resolve()
    artifact_dir.mkdir(parents=True, exist_ok=True)
    report_path = artifact_dir / "business-lifecycle.json"
    steps: list[dict[str, object]] = []
    current_step = "startup"

    def passed(name: str, detail: str = "") -> None:
        steps.append({"name": name, "status": "PASS", "detail": detail})

    try:
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory(prefix="cnkh_business_lifecycle_") as temp_name:
            root = Path(temp_name)
            database = Database(root / "hardware_pos.db")
            backups = root / "backups"

            current_step = "database bootstrap and users"
            bootstrap_database(database.path, backups)
            with database.transaction() as conn:
                admin_id = AuthService.create_user(
                    conn,
                    username="lifecycle-admin",
                    display_name="Lifecycle Admin",
                    password=ADMIN_PASSWORD,
                    role="ADMIN",
                    permissions={
                        "apply_discount": True,
                        "manage_quick_amounts": True,
                        "reprint_receipt": True,
                    },
                    admin_id=None,
                )
                staff_id = AuthService.create_user(
                    conn,
                    username="lifecycle-staff",
                    display_name="Lifecycle Staff",
                    password=STAFF_PASSWORD,
                    role="STAFF",
                    permissions={
                        "apply_discount": True,
                        "manage_quick_amounts": True,
                        "reprint_receipt": True,
                    },
                    admin_id=admin_id,
                )
            with database.transaction() as conn:
                admin_user = AuthService.authenticate(
                    conn,
                    "lifecycle-admin",
                    ADMIN_PASSWORD,
                    required_role="ADMIN",
                )
                staff_user = AuthService.authenticate(
                    conn,
                    "lifecycle-staff",
                    STAFF_PASSWORD,
                    required_role="STAFF",
                )
            _assert(admin_user.id == admin_id, "admin authentication mismatch")
            _assert(staff_user.id == staff_id, "staff authentication mismatch")
            passed(current_step, "fresh schema, admin and staff authentication")

            current_step = "category and product create/update/barcodes"
            category_service = CategoryService(database)
            category_id = category_service.add("Lifecycle Hardware", admin_id=admin_id)
            catalog = CatalogService(database)
            auto_product = catalog.add_product(
                ProductInput(
                    name="Lifecycle Auto Cable",
                    category_id=category_id,
                    sku="LIFE-AUTO",
                    cost_cents=500,
                    selling_price_cents=1067,
                    stock="10",
                    unit="pcs",
                    location="A1",
                ),
                admin_id=admin_id,
            )
            manual_product = catalog.add_product(
                ProductInput(
                    name="Lifecycle Manual Plug",
                    category_id=category_id,
                    sku="LIFE-MANUAL",
                    cost_cents=300,
                    selling_price_cents=700,
                    stock="5",
                    unit="pcs",
                    location="A2",
                    barcode="CNKH-LIFE-MANUAL-001",
                ),
                admin_id=admin_id,
            )
            auto_barcode = _product_barcode(database, auto_product)
            _assert(is_valid_ean13(auto_barcode), "auto barcode is not valid EAN-13")
            _assert(
                _product_barcode(database, manual_product) == "CNKH-LIFE-MANUAL-001",
                "manual barcode was not preserved",
            )
            try:
                catalog.add_product(
                    ProductInput(
                        name="Duplicate Barcode",
                        barcode="CNKH-LIFE-MANUAL-001",
                    ),
                    admin_id=admin_id,
                )
            except ValueError as exc:
                _assert("duplicate barcode" in str(exc), "unexpected duplicate error")
            else:
                raise AssertionError("duplicate barcode was accepted")
            catalog.update_product(
                auto_product,
                ProductInput(
                    name="Lifecycle Auto Cable",
                    aliases="cable;wire",
                    category_id=category_id,
                    sku="LIFE-AUTO",
                    cost_cents=500,
                    selling_price_cents=1067,
                    stock="10",
                    unit="pcs",
                    location="RACK-A1",
                    low_stock="2",
                    barcode=auto_barcode,
                ),
                admin_id=admin_id,
            )
            passed(current_step, f"auto={auto_barcode}; manual barcode preserved")

            current_step = "customer supplier and supplier catalogue"
            customers = EntityService(database, "customers")
            suppliers = EntityService(database, "suppliers")
            customer_id = customers.add(
                EntityInput("Lifecycle Customer", "0123456789", notes="acceptance"),
                admin_id=admin_id,
            )
            supplier_id = suppliers.add(
                EntityInput(
                    "Lifecycle Supplier",
                    "0198765432",
                    "supplier@example.com",
                    "acceptance",
                ),
                admin_id=admin_id,
            )
            customers.update(
                customer_id,
                EntityInput("Lifecycle Customer Updated", "0111111111", notes="updated"),
                admin_id=admin_id,
            )
            suppliers.set_supplier_products(
                supplier_id,
                {auto_product, manual_product},
                admin_id=admin_id,
            )
            _assert(
                suppliers.supplier_product_ids(supplier_id)
                == {auto_product, manual_product},
                "supplier catalogue mismatch",
            )
            passed(current_step)

            current_step = "purchase create partial payment and settlement"
            purchase = PurchaseService(database).create_purchase(
                supplier_id=supplier_id,
                lines=[
                    PurchaseLine(auto_product, Decimal("5"), 450),
                    PurchaseLine(manual_product, Decimal("2"), 280),
                ],
                paid_cents=1000,
                payment_method="CARD",
                operator_id=admin_id,
            )
            _assert(purchase.total_cents == 2810, "purchase total mismatch")
            _assert(purchase.status == "PARTIAL", "purchase should be partial")
            SupplierPaymentService(database).record_payment(
                purchase_id=purchase.purchase_id,
                amount_cents=1810,
                payment_method="CARD",
                note="settled in lifecycle acceptance",
                operator_id=admin_id,
            )
            _assert(_stock(database, auto_product) == Decimal("15"), "purchase stock A")
            _assert(_stock(database, manual_product) == Decimal("7"), "purchase stock B")
            passed(current_step, purchase.purchase_no)

            current_step = "held order round trip"
            held_service = HeldOrderService(database)
            held = held_service.hold(
                {
                    "items": [
                        {
                            "product_id": auto_product,
                            "quantity": "1",
                            "discount_cents": 50,
                        }
                    ]
                },
                cashier_id=staff_id,
            )
            retrieved = held_service.retrieve(held.id, cashier_id=staff_id)
            _assert(
                int(retrieved.payload["items"][0]["product_id"]) == auto_product,
                "held order product mismatch",
            )
            passed(current_step, held.hold_no)

            current_step = "discounted cash checkout and settlement rounding"
            auto_gross = 1067 * 2
            auto_discount = discount_cents_from_value(
                auto_gross, mode="PERCENT", value="10"
            )
            manual_discount = discount_cents_from_value(
                700, mode="FIXED", value="0.50"
            )
            line_net = [
                (auto_product, auto_gross - auto_discount),
                (manual_product, 700 - manual_discount),
            ]
            order_discount = discount_cents_from_value(
                sum(net for _product_id, net in line_net),
                mode="FIXED",
                value="1.04",
            )
            allocated = allocate_order_discount(line_net, order_discount)
            checkout = RoundedSalesService(database).create_sale(
                lines=[
                    SaleLine(
                        auto_product,
                        Decimal("2"),
                        Decimal("2"),
                        discount_cents=auto_discount + allocated[auto_product],
                    ),
                    SaleLine(
                        manual_product,
                        Decimal("1"),
                        Decimal("1"),
                        discount_cents=manual_discount + allocated[manual_product],
                    ),
                ],
                payment_method="CASH",
                paid_cents=3000,
                cashier_id=staff_id,
            )
            _assert(checkout.total_cents == 2470, "rounded checkout total should be RM24.70")
            _assert(checkout.change_cents == 530, "checkout change should be RM5.30")
            conn = database.connect(readonly=True)
            try:
                stored_sale = conn.execute(
                    """SELECT subtotal_cents,discount_cents,total_cents,paid_cents,change_cents
                       FROM sales WHERE id=?""",
                    (checkout.sale_id,),
                ).fetchone()
                sale_items = conn.execute(
                    "SELECT id,product_id,quantity_decimal FROM sale_items WHERE sale_id=? ORDER BY id",
                    (checkout.sale_id,),
                ).fetchall()
            finally:
                conn.close()
            _assert(
                tuple(stored_sale) == (2834, 367, 2470, 3000, 530),
                "stored discounted checkout amounts mismatch",
            )
            passed(current_step, checkout.receipt_no)

            current_step = "80mm receipt text reportlab PDF and Qt PDF"
            printing = PrintingService(database)
            receipt = printing.receipt(checkout.sale_id)
            receipt_text = printing.render_text(receipt)
            _assert("TOTAL" in receipt_text and "RM 24.70" in receipt_text, "receipt total")
            _assert("DISCOUNT" in receipt_text and "RM 3.67" in receipt_text, "receipt discount")
            reportlab_pdf = printing.render_pdf(
                receipt, artifact_dir / "business-receipt-reportlab.pdf"
            )
            qt_pdf = artifact_dir / "business-receipt-qt-80mm.pdf"
            printing.print_receipt(receipt, output_pdf=qt_pdf)
            _assert(reportlab_pdf.stat().st_size > 500, "ReportLab receipt PDF is empty")
            _assert(qt_pdf.stat().st_size > 500, "Qt 80mm receipt PDF is empty")
            passed(current_step)

            current_step = "full sale return with rounding reversal"
            return_service = RoundedReturnService(database)
            first_item = sale_items[0]
            second_item = sale_items[1]
            return_service.create_return(
                sale_id=checkout.sale_id,
                quantities_by_sale_item={int(first_item["id"]): Decimal("2")},
                reason="Lifecycle first return",
                operator_id=admin_id,
                refund_method="CASH",
            )
            return_service.create_return(
                sale_id=checkout.sale_id,
                quantities_by_sale_item={int(second_item["id"]): Decimal("1")},
                reason="Lifecycle final return",
                operator_id=admin_id,
                refund_method="CASH",
            )
            conn = database.connect(readonly=True)
            try:
                total_refund = int(
                    conn.execute(
                        "SELECT COALESCE(SUM(total_cents),0) FROM sale_returns WHERE sale_id=?",
                        (checkout.sale_id,),
                    ).fetchone()[0]
                )
            finally:
                conn.close()
            _assert(total_refund == 2470, "full return did not reverse rounded total")
            _assert(_stock(database, auto_product) == Decimal("15"), "returned stock A")
            _assert(_stock(database, manual_product) == Decimal("7"), "returned stock B")
            passed(current_step)

            current_step = "credit sale customer payment and safe customer delete"
            credit = RoundedSalesService(database).create_sale(
                lines=[
                    SaleLine(
                        manual_product,
                        Decimal("1"),
                        Decimal("1"),
                        discount_cents=50,
                    )
                ],
                payment_method="CREDIT",
                paid_cents=0,
                cashier_id=staff_id,
                customer_id=customer_id,
            )
            _assert(credit.total_cents == 650, "credit sale total mismatch")
            conn = database.connect(readonly=True)
            try:
                debt_id = int(
                    conn.execute(
                        "SELECT id FROM customer_debts WHERE sale_id=?", (credit.sale_id,)
                    ).fetchone()[0]
                )
            finally:
                conn.close()
            CustomerPaymentService(database).record_payment(
                debt_id=debt_id,
                amount_cents=250,
                payment_method="CASH",
                note="partial lifecycle payment",
                operator_id=admin_id,
            )
            try:
                customers.delete(customer_id, admin_id=admin_id)
            except ValueError as exc:
                _assert("open debt" in str(exc), "unexpected customer delete error")
            else:
                raise AssertionError("customer with open debt was deletable")
            CustomerPaymentService(database).record_payment(
                debt_id=debt_id,
                amount_cents=400,
                payment_method="CARD",
                note="final lifecycle payment",
                operator_id=admin_id,
            )
            passed(current_step)

            current_step = "cash sale for reports and daily closing"
            cash_sale = RoundedSalesService(database).create_sale(
                lines=[
                    SaleLine(
                        auto_product,
                        Decimal("1"),
                        Decimal("1"),
                        price_override_cents=333,
                    )
                ],
                payment_method="CASH",
                paid_cents=500,
                cashier_id=staff_id,
            )
            _assert(cash_sale.total_cents == 330, "cash sale rounding mismatch")
            passed(current_step, cash_sale.receipt_no)

            current_step = "stocktake draft count and completion"
            stocktake = StocktakeService(database)
            stocktake_id, stocktake_no = stocktake.create_draft(
                operator_id=admin_id, notes="lifecycle acceptance"
            )
            _assert(_stock(database, auto_product) == Decimal("14"), "pre-stocktake stock")
            stocktake.set_physical_count(
                stocktake_id=stocktake_id,
                product_id=auto_product,
                count=Decimal("15"),
            )
            stocktake.complete(stocktake_id=stocktake_id, operator_id=admin_id)
            _assert(_stock(database, auto_product) == Decimal("15"), "stocktake adjustment")
            passed(current_step, stocktake_no)

            current_step = "purchase delete stock reversal and sale delete stock reversal"
            disposable_category = category_service.add("Disposable", admin_id=admin_id)
            disposable = catalog.add_product(
                ProductInput(
                    name="Disposable Lifecycle Product",
                    category_id=disposable_category,
                    selling_price_cents=100,
                    stock="3",
                ),
                admin_id=admin_id,
            )
            suppliers.set_supplier_products(
                supplier_id,
                {auto_product, manual_product, disposable},
                admin_id=admin_id,
            )
            disposable_purchase = PurchaseService(database).create_purchase(
                supplier_id=supplier_id,
                lines=[PurchaseLine(disposable, Decimal("2"), 100)],
                paid_cents=200,
                payment_method="CARD",
                operator_id=admin_id,
            )
            _assert(_stock(database, disposable) == Decimal("5"), "disposable purchase stock")
            PurchaseService(database).delete_purchase(
                purchase_id=disposable_purchase.purchase_id,
                admin_id=admin_id,
            )
            _assert(_stock(database, disposable) == Decimal("3"), "purchase delete reversal")
            disposable_sale = RoundedSalesService(database).create_sale(
                lines=[SaleLine(disposable, Decimal("1"), Decimal("1"))],
                payment_method="CASH",
                paid_cents=100,
                cashier_id=staff_id,
            )
            _assert(_stock(database, disposable) == Decimal("2"), "disposable sale stock")
            SalesService(database).delete_sale(
                sale_id=disposable_sale.sale_id,
                admin_id=admin_id,
            )
            _assert(_stock(database, disposable) == Decimal("3"), "sale delete reversal")
            catalog.delete_products([disposable], admin_id=admin_id)
            conn = database.connect(readonly=True)
            try:
                deleted = conn.execute(
                    "SELECT is_deleted,barcode FROM products WHERE id=?", (disposable,)
                ).fetchone()
            finally:
                conn.close()
            _assert(tuple(deleted) == (1, None), "product delete tombstone mismatch")
            category_service.delete(disposable_category, admin_id=admin_id)
            passed(current_step)

            current_step = "Excel template preview and import"
            template = artifact_dir / "business-product-import.xlsx"
            ExcelImportService.create_template(template)
            workbook = load_workbook(template)
            try:
                sheet = workbook.active
                sheet["A2"] = "Lifecycle Excel Item"
                sheet["B2"] = "excel;import"
                sheet["C2"] = "Lifecycle Import"
                sheet["D2"] = "LIFE-EXCEL"
                sheet["E2"] = 1.25
                sheet["F2"] = 2.5
                sheet["G2"] = 8
                sheet["H2"] = "pcs"
                sheet["I2"] = "E1"
                sheet["J2"] = 2
                sheet["K2"] = ""
                workbook.save(template)
            finally:
                workbook.close()
            import_service = ExcelImportService(database)
            preview = import_service.preview(template)
            _assert(len(preview) == 1 and not preview[0].errors, "Excel preview failed")
            summary = import_service.commit(preview, admin_id=admin_id)
            _assert(summary.success == 1 and summary.errors == 0, "Excel import failed")
            conn = database.connect(readonly=True)
            try:
                excel_row = conn.execute(
                    "SELECT id,barcode FROM products WHERE sku='LIFE-EXCEL' AND is_deleted=0"
                ).fetchone()
            finally:
                conn.close()
            _assert(excel_row is not None, "Excel product is missing")
            _assert(is_valid_ean13(str(excel_row["barcode"])), "Excel auto barcode invalid")
            passed(current_step)

            current_step = "barcode label PDF copies"
            label = load_product_label(database, auto_product)
            label_pdf = render_product_label_pdf(
                label,
                get_label_profile("40x30"),
                3,
                artifact_dir / "business-barcode-labels-40x30-3copies.pdf",
            )
            label_bytes = label_pdf.read_bytes()
            page_count = len(re.findall(rb"/Type\s*/Page\b", label_bytes))
            _assert(page_count == 3, "barcode label copy count mismatch")
            _assert(label_pdf.stat().st_size > 1000, "barcode label PDF is empty")
            passed(current_step, "40x30 mm, 3 pages")

            current_step = "reports and daily cash closing"
            today = date.today().isoformat()
            report = ReportService(database).summary(start_date=today, end_date=today)
            _assert(report.sales_cents == 980, "report net sales mismatch")
            _assert(report.transaction_count == 3, "report transaction count mismatch")
            _assert(report.purchases_cents == 2810, "report purchases mismatch")
            _assert(report.current_receivable_cents == 0, "receivable should be settled")
            _assert(report.current_payable_cents == 0, "payable should be settled")
            system_cash = DailyClosingService(database).system_cash(
                business_date=date.today()
            )
            _assert(system_cash == 580, f"daily cash mismatch: {system_cash}")
            closing = DailyClosingService(database).complete(
                business_date=date.today(),
                cashier_id=admin_id,
                actual_cash_cents=system_cash,
                note="lifecycle acceptance exact count",
            )
            _assert(closing.variance_cents == 0, "daily closing variance should be zero")
            passed(current_step, f"system cash={system_cash} cents")

            current_step = "safe entity delete after balances settle"
            customers.delete(customer_id, admin_id=admin_id)
            suppliers.delete(supplier_id, admin_id=admin_id)
            conn = database.connect(readonly=True)
            try:
                flags = tuple(
                    conn.execute(
                        """SELECT
                           (SELECT is_deleted FROM customers WHERE id=?),
                           (SELECT is_deleted FROM suppliers WHERE id=?)""",
                        (customer_id, supplier_id),
                    ).fetchone()
                )
            finally:
                conn.close()
            _assert(flags == (1, 1), "entity soft-delete flags mismatch")
            passed(current_step)

            current_step = "backup restore and database integrity"
            checkpoint = BackupService(backups).create(
                database.path, reason="business_acceptance_checkpoint"
            ).path
            temporary_product = catalog.add_product(
                ProductInput(name="Temporary After Backup"), admin_id=admin_id
            )
            _assert(temporary_product > 0, "temporary product creation failed")
            RestoreService(database, backups).restore(
                checkpoint,
                admin_id=admin_id,
                password=ADMIN_PASSWORD,
            )
            conn = database.connect(readonly=True)
            try:
                temporary_count = int(
                    conn.execute(
                        "SELECT COUNT(*) FROM products WHERE name='Temporary After Backup'"
                    ).fetchone()[0]
                )
                integrity = str(conn.execute("PRAGMA integrity_check").fetchone()[0])
                foreign_keys = conn.execute("PRAGMA foreign_key_check").fetchall()
            finally:
                conn.close()
            _assert(temporary_count == 0, "restore did not remove post-backup product")
            _assert(integrity == "ok", "restored database integrity failed")
            _assert(not foreign_keys, "restored database has foreign-key violations")
            passed(current_step)

            current_step = "populated Admin and Staff window construction"
            with database.transaction() as conn:
                admin_user = AuthService.authenticate(
                    conn,
                    "lifecycle-admin",
                    ADMIN_PASSWORD,
                    required_role="ADMIN",
                )
                staff_user = AuthService.authenticate(
                    conn,
                    "lifecycle-staff",
                    STAFF_PASSWORD,
                    required_role="STAFF",
                )
            admin_window = AdminWindow(database, admin_user)
            staff_window = StaffWindow(database, staff_user)
            admin_window.show()
            staff_window.show()
            app.processEvents()
            _assert(admin_window.isVisible(), "Admin populated window is not visible")
            _assert(staff_window.isVisible(), "Staff populated window is not visible")
            _assert(staff_window.discount_button.isEnabled(), "Staff discount permission lost")
            admin_window.close()
            staff_window.close()
            app.processEvents()
            passed(current_step, "both populated windows opened and closed")

        payload = {
            "status": "PASS",
            "platform": os.name,
            "step_count": len(steps),
            "steps": steps,
        }
        _write_report(report_path, payload)
        print(f"BUSINESS LIFECYCLE ACCEPTANCE PASSED: {len(steps)} steps")
        print(f"Report: {report_path}")
        return 0
    except BaseException as exc:
        steps.append(
            {
                "name": current_step,
                "status": "FAIL",
                "detail": f"{type(exc).__name__}: {exc}",
            }
        )
        payload = {
            "status": "FAIL",
            "platform": os.name,
            "step_count": len(steps),
            "steps": steps,
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
        }
        _write_report(report_path, payload)
        print(payload["traceback"])
        print(f"Report: {report_path}")
        return 1


if __name__ == "__main__":
    raise SystemExit(run())
