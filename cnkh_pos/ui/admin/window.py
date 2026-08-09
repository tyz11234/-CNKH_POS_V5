from __future__ import annotations

from PySide6.QtWidgets import (
    QHBoxLayout,
    QMainWindow,
    QStackedWidget,
    QTabWidget,
    QWidget,
)

from cnkh_pos.ui.admin.dashboard import DashboardPage
from cnkh_pos.database.connection import Database
from cnkh_pos.services.auth import AuthenticatedUser
from cnkh_pos.ui.widgets import Sidebar
from cnkh_pos.ui.admin.data_pages import (
    AuditPage,
    EntityPage,
    MaintenancePage,
    ProductsPage,
    PurchasesPage,
    SalesPage,
    StocktakePage,
)
from cnkh_pos.ui.admin.settings_pages import DailyClosingPage, ReportsPage, SettingsPage


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
                ("reports", "▥  报表"),
                ("settings", "⚙  设置"),
                ("maintenance", "▦  数据维护"),
            ]
        )
        self.pages = QStackedWidget()
        self.page_keys: dict[str, int] = {}
        self._add_page("dashboard", DashboardPage())
        catalog_tabs = QTabWidget()
        catalog_tabs.addTab(ProductsPage(database, user), "Products / 商品")
        catalog_tabs.addTab(StocktakePage(database, user), "Stocktake / 盘点")
        self._add_page("products", catalog_tabs)
        self._add_page("sales", SalesPage(database))
        self._add_page("purchases", PurchasesPage(database, user))
        self._add_page("customers", EntityPage(database, user, "customers"))
        self._add_page("suppliers", EntityPage(database, user, "suppliers"))
        report_tabs = QTabWidget()
        report_tabs.addTab(ReportsPage(database), "Reports")
        report_tabs.addTab(DailyClosingPage(database, user), "Daily Cash Closing")
        self._add_page("reports", report_tabs)
        self._add_page("settings", SettingsPage(database, user))
        maintenance_tabs = QTabWidget()
        maintenance_tabs.addTab(MaintenancePage(database), "Data Maintenance")
        maintenance_tabs.addTab(AuditPage(database), "Audit Log")
        self._add_page("maintenance", maintenance_tabs)
        sidebar.page_selected.connect(self._select_page)
        layout.addWidget(sidebar)
        layout.addWidget(self.pages, 1)
        self.setCentralWidget(canvas)

    def _add_page(self, key: str, page: QWidget) -> None:
        self.page_keys[key] = self.pages.addWidget(page)

    def _select_page(self, key: str) -> None:
        self.pages.setCurrentIndex(self.page_keys[key])
