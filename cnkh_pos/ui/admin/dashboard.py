from __future__ import annotations

from datetime import date

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from cnkh_pos.database.connection import Database
from cnkh_pos.services.money import format_myr
from cnkh_pos.ui.widgets import Card, StatCard


class DashboardPage(QWidget):
    def __init__(self, database: Database, parent: QWidget | None = None):
        super().__init__(parent)
        self.database = database
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 20)
        root.setSpacing(14)

        heading = QHBoxLayout()
        title = QLabel("管理员仪表盘")
        title.setObjectName("PageTitle")
        refresh = QPushButton("↻  Refresh / 刷新")
        refresh.setObjectName("PrimaryButton")
        refresh.setProperty("acceptanceName", "DashboardRefreshButton")
        refresh.clicked.connect(self.refresh)
        self.refresh_button = refresh
        heading.addWidget(title)
        heading.addStretch(1)
        heading.addWidget(refresh)
        root.addLayout(heading)

        stats = QGridLayout()
        stats.setHorizontalSpacing(12)
        stats.setVerticalSpacing(12)
        cards = [
            ("today_sales", "今日营业额", "RM 0.00", "今日实际数据", "success"),
            ("today_count", "今日单数", "0", "今日实际数据", "primary"),
            ("profit", "毛利", "RM 0.00", "按销售成本计算", "primary"),
            ("low_stock", "低库存", "0", "需要及时补货", "warning"),
            ("receivable", "客户欠账", "RM 0.00", "共 0 位客户", "danger"),
            ("payable", "供应商未付款", "RM 0.00", "共 0 笔未付款", "warning"),
        ]
        self.stat_cards: dict[str, StatCard] = {}
        for index, (key, title_text, value, detail, tone) in enumerate(cards):
            card = StatCard(title_text, value, detail, tone=tone)
            self.stat_cards[key] = card
            stats.addWidget(card, index // 2, index % 2)
        root.addLayout(stats)

        notifications = Card()
        note_layout = QVBoxLayout(notifications)
        note_layout.setContentsMargins(16, 14, 16, 14)
        note_title = QLabel("最新通知")
        note_title.setObjectName("SectionTitle")
        note_layout.addWidget(note_title)
        self.notification_labels: list[QLabel] = []
        for _ in range(4):
            row = QLabel("—")
            row.setStyleSheet("color:#68768A; padding:4px 0;")
            self.notification_labels.append(row)
            note_layout.addWidget(row)
        root.addWidget(notifications)

        recent = Card()
        recent_layout = QVBoxLayout(recent)
        recent_layout.setContentsMargins(16, 14, 16, 14)
        recent_title = QLabel("最近销售单据")
        recent_title.setObjectName("SectionTitle")
        recent_layout.addWidget(recent_title)
        self.recent_table = QTableWidget(0, 5)
        self.recent_table.setHorizontalHeaderLabels(
            ["单据号", "时间", "客户", "金额 (RM)", "状态"]
        )
        self.recent_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.recent_table.verticalHeader().setVisible(False)
        self.recent_table.setAlternatingRowColors(True)
        self.recent_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        recent_layout.addWidget(self.recent_table)
        root.addWidget(recent, 1)
        self.refresh()

    def refresh(self) -> None:
        business_date = date.today().isoformat()
        conn = self.database.connect(readonly=True)
        try:
            today_sales, today_count = conn.execute(
                """SELECT COALESCE(SUM(total_cents),0), COUNT(*) FROM sales
                   WHERE is_deleted=0 AND substr(sold_at,1,10)=?""",
                (business_date,),
            ).fetchone()
            profit = conn.execute(
                """SELECT COALESCE(SUM(
                       (si.unit_price_cents-si.unit_cost_cents_snapshot)
                       * CAST(si.quantity_decimal AS REAL)-si.discount_cents),0)
                   FROM sale_items si JOIN sales s ON s.id=si.sale_id
                   WHERE s.is_deleted=0 AND substr(s.sold_at,1,10)=?""",
                (business_date,),
            ).fetchone()[0]
            low_stock = conn.execute(
                """SELECT COUNT(*) FROM products WHERE is_deleted=0
                   AND CAST(low_stock_decimal AS REAL)>0
                   AND CAST(stock_decimal AS REAL)<=CAST(low_stock_decimal AS REAL)"""
            ).fetchone()[0]
            receivable, customer_count = conn.execute(
                """SELECT COALESCE(SUM(balance_cents),0),COUNT(DISTINCT customer_id)
                   FROM customer_debts WHERE status='OPEN'"""
            ).fetchone()
            payable, payable_count = conn.execute(
                """SELECT COALESCE(SUM(total_cents-paid_cents),0),COUNT(*)
                   FROM purchases WHERE is_deleted=0 AND status<>'PAID'"""
            ).fetchone()
            recent = conn.execute(
                """SELECT s.receipt_no,s.sold_at,COALESCE(c.name,'Walk-In Customer'),
                          s.total_cents,CASE s.is_deleted WHEN 0 THEN '已完成' ELSE '已删除' END
                   FROM sales s LEFT JOIN customers c ON c.id=s.customer_id
                   ORDER BY s.sold_at DESC,s.id DESC LIMIT 5"""
            ).fetchall()
            low_item = conn.execute(
                """SELECT name,stock_decimal FROM products WHERE is_deleted=0
                   AND CAST(low_stock_decimal AS REAL)>0
                   AND CAST(stock_decimal AS REAL)<=CAST(low_stock_decimal AS REAL)
                   ORDER BY CAST(stock_decimal AS REAL) LIMIT 1"""
            ).fetchone()
            debt = conn.execute(
                """SELECT c.name,d.balance_cents FROM customer_debts d
                   JOIN customers c ON c.id=d.customer_id WHERE d.status='OPEN'
                   ORDER BY d.opened_at DESC LIMIT 1"""
            ).fetchone()
            unpaid = conn.execute(
                """SELECT COALESCE(s.name,'未指定供应商'),p.total_cents-p.paid_cents
                   FROM purchases p LEFT JOIN suppliers s ON s.id=p.supplier_id
                   WHERE p.is_deleted=0 AND p.status<>'PAID'
                   ORDER BY p.purchased_at DESC LIMIT 1"""
            ).fetchone()
            purchase = conn.execute(
                """SELECT purchase_no FROM purchases WHERE is_deleted=0
                   ORDER BY purchased_at DESC,id DESC LIMIT 1"""
            ).fetchone()
        finally:
            conn.close()

        values = {
            "today_sales": (format_myr(int(today_sales)), "今日实际数据"),
            "today_count": (str(int(today_count)), "今日实际数据"),
            "profit": (format_myr(round(float(profit))), "按销售成本计算"),
            "low_stock": (str(int(low_stock)), "需要及时补货"),
            "receivable": (
                format_myr(int(receivable)),
                f"共 {int(customer_count)} 位客户",
            ),
            "payable": (
                format_myr(int(payable)),
                f"共 {int(payable_count)} 笔未付款",
            ),
        }
        for key, (value, detail) in values.items():
            self.stat_cards[key].value_label.setText(value)
            self.stat_cards[key].detail_label.setText(detail)

        notifications = [
            (
                f"⚠ 商品 [{low_item['name']}] 库存不足，当前库存：{low_item['stock_decimal']}"
                if low_item
                else "✓ 当前没有低库存商品",
                "#D92D3C" if low_item else "#168A3F",
            ),
            (
                f"♙ 客户 [{debt['name']}] 未结欠款 {format_myr(int(debt['balance_cents']))}"
                if debt
                else "✓ 当前没有客户欠账",
                "#D97706" if debt else "#168A3F",
            ),
            (
                f"▣ 供应商 [{unpaid[0]}] 未付款 {format_myr(int(unpaid[1]))}"
                if unpaid
                else "✓ 当前没有供应商未付款",
                "#D97706" if unpaid else "#168A3F",
            ),
            (
                f"● 最新进货单 [{purchase['purchase_no']}] 已入库"
                if purchase
                else "● 尚无进货记录",
                "#168A3F",
            ),
        ]
        for label, (text, color) in zip(self.notification_labels, notifications):
            label.setText(text)
            label.setStyleSheet(f"color:{color}; padding:4px 0;")

        self.recent_table.setRowCount(len(recent))
        for row_index, row in enumerate(recent):
            values = (
                row["receipt_no"],
                str(row["sold_at"])[11:16],
                row[2],
                f"{int(row['total_cents']) / 100:,.2f}",
                row[4],
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if column in (1, 3, 4):
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.recent_table.setItem(row_index, column, item)
