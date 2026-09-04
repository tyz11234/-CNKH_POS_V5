from __future__ import annotations

from PySide6.QtWidgets import (
    QHBoxLayout,
    QMainWindow,
    QStackedWidget,
    QTabWidget,
    QWidget,
)

from cnkh_pos.database.connection import Database
from cnkh_pos.services.auth import AuthenticatedUser
from cnkh_pos.ui.admin.barcode_labels import BarcodeLabelsPage
from cnkh_pos.ui.admin.dashboard import DashboardPage
from cnkh_pos.ui.admin.data_pages import (
    AuditPage,
    EntityPage,
    MaintenancePage,
    PurchasesPage,
    StocktakePage,
)
from cnkh_pos.ui.admin.enhanced_data_pages import (
    ProductsPageEnhanced,
    SalesPageEnhanced,
)
from cnkh_pos.ui.admin.settings_pages import DailyClosingPage, ReportsPage, SettingsPage
from cnkh_pos.ui.admin.users_page import UsersPage
from cnkh_pos.ui.dialogs.sync_pair_dialog import open_sync_pair_dialog
from cnkh_pos.ui.widgets import Sidebar
from cnkh_pos.ui.widgets.sync_toolbar import sync_event_bridge


class AdminWindow(QMainWindow):
    def __init__(self, database: Database, user: AuthenticatedUser):
        super().__init__()
        self.database = database
        self.user = user
        self.setWindowTitle("CNKH POS Admin — V5.0")
        self.setMinimumSize(1080, 720)
        self.resize(1220, 820)

        canvas = QWidget()
        canvas.setObjectName("AppCanvas")
        layout = QHBoxLayout(canvas)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        sidebar = Sidebar(
            [
                ("dashboard", "▣  主页"),
                ("products", "□  商品"),
                ("sales", "▱  销售"),
                ("purchases", "◇  进货"),
                ("customers", "○  客户"),
                ("suppliers", "○  供应商"),
                ("users", "♙  员工账号"),
                ("reports", "▥  报表"),
                ("settings", "⚙  设置"),
                ("maintenance", "▦  数据维护"),
            ],
            display_name=user.display_name,
            role_text="管理员",
            sync_callback=lambda: open_sync_pair_dialog(self, database),
        )
        # Refresh sales page when phone pushes a sale
        self._sales_page = None
        self.pages = QStackedWidget()
        self.page_keys: dict[str, int] = {}
        self._add_page("dashboard", DashboardPage(database))
        catalog_tabs = QTabWidget()
        # Keep the historical Products=0 / Stocktake=1 tab indexes stable because
        # existing Windows GUI acceptance and user muscle-memory depend on them.
        # Barcode labels are additive and therefore live in a new third tab.
        catalog_tabs.addTab(ProductsPageEnhanced(database, user), "Products / 商品")
        catalog_tabs.addTab(StocktakePage(database, user), "Stocktake / 盘点")
        catalog_tabs.addTab(BarcodeLabelsPage(database), "Barcode Labels / 条码标签")
        self._add_page("products", catalog_tabs)
        self._sales_page = SalesPageEnhanced(database, user)
        self._add_page("sales", self._sales_page)
        self._add_page("purchases", PurchasesPage(database, user))
        self._add_page("customers", EntityPage(database, user, "customers"))
        self._add_page("suppliers", EntityPage(database, user, "suppliers"))
        self._add_page("users", UsersPage(database, user))
        report_tabs = QTabWidget()
        report_tabs.addTab(ReportsPage(database), "Reports")
        report_tabs.addTab(DailyClosingPage(database, user), "Daily Cash Closing")
        self._add_page("reports", report_tabs)
        self._add_page("settings", SettingsPage(database, user))
        maintenance_tabs = QTabWidget()
        maintenance_tabs.addTab(MaintenancePage(database, user), "Data Maintenance")
        maintenance_tabs.addTab(AuditPage(database, user), "Audit Log")
        self._add_page("maintenance", maintenance_tabs)
        sidebar.page_selected.connect(self._select_page)
        layout.addWidget(sidebar)
        layout.addWidget(self.pages, 1)
        self.setCentralWidget(canvas)
        sync_event_bridge().sale_event.connect(self._on_sync_event)

    def _add_page(self, key: str, page: QWidget) -> None:
        self.page_keys[key] = self.pages.addWidget(page)

    def _select_page(self, key: str) -> None:
        self.pages.setCurrentIndex(self.page_keys[key])

    def _on_sync_event(self, event: dict) -> None:
        """Refresh sales UI when phone pushes a sale over LAN sync."""
        try:
            page = self._sales_page
            if page is not None and hasattr(page, "reload"):
                page.reload()
            elif page is not None and hasattr(page, "refresh"):
                page.refresh()
        except Exception:
            pass
