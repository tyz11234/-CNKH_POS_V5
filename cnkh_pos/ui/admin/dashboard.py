from __future__ import annotations

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

from cnkh_pos.ui.widgets import Card, StatCard


class DashboardPage(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 20)
        root.setSpacing(14)

        heading = QHBoxLayout()
        title = QLabel("管理员仪表盘")
        title.setObjectName("PageTitle")
        refresh = QPushButton("↻  Refresh / 刷新")
        refresh.setObjectName("PrimaryButton")
        heading.addWidget(title)
        heading.addStretch(1)
        heading.addWidget(refresh)
        root.addLayout(heading)

        stats = QGridLayout()
        stats.setHorizontalSpacing(12)
        stats.setVerticalSpacing(12)
        cards = [
            ("今日营业额", "RM 12,450.80", "较昨日  +18.6%", "success"),
            ("今日单数", "128", "较昨日  +15.2%", "primary"),
            ("毛利", "RM 3,265.40", "毛利率  26.26%", "primary"),
            ("低库存", "23", "需要及时补货", "warning"),
            ("客户欠账", "RM 8,760.50", "共 12 位客户", "danger"),
            ("供应商未付款", "RM 15,230.00", "共 8 笔未付款", "warning"),
        ]
        for index, values in enumerate(cards):
            stats.addWidget(
                StatCard(*values[:3], tone=values[3]), index // 2, index % 2
            )
        root.addLayout(stats)

        notifications = Card()
        note_layout = QVBoxLayout(notifications)
        note_layout.setContentsMargins(16, 14, 16, 14)
        note_title = QLabel("最新通知")
        note_title.setObjectName("SectionTitle")
        note_layout.addWidget(note_title)
        for text, color in (
            ("⚠ 商品 [PVC Cable 2.5mm] 库存不足，当前库存：18", "#D92D3C"),
            ("♙ 客户 [德强工程] 有新的欠款 RM 560.00", "#D97706"),
            ("▣ 供应商 [安达五金] 发票到期未付款 RM 2,350.00", "#D97706"),
            ("● 新进货单 [PI-20250809-003] 已入库", "#168A3F"),
        ):
            row = QLabel(text)
            row.setStyleSheet(f"color: {color}; padding: 4px 0;")
            note_layout.addWidget(row)
        root.addWidget(notifications)

        recent = Card()
        recent_layout = QVBoxLayout(recent)
        recent_layout.setContentsMargins(16, 14, 16, 14)
        recent_title = QLabel("最近销售单据")
        recent_title.setObjectName("SectionTitle")
        recent_layout.addWidget(recent_title)
        table = QTableWidget(5, 5)
        table.setHorizontalHeaderLabels(["单据号", "时间", "客户", "金额 (RM)", "状态"])
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        table.verticalHeader().setVisible(False)
        table.setAlternatingRowColors(True)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        rows = [
            ("CNKH20260809-128", "10:29", "Walk-In Customer", "158.50", "已完成"),
            ("CNKH20260809-127", "10:21", "伟强工程", "2,345.00", "已完成"),
            ("CNKH20260809-126", "10:05", "联兴电器", "780.00", "已完成"),
            ("CNKH20260809-125", "09:52", "Walk-In Customer", "96.90", "已完成"),
            ("CNKH20260809-124", "09:41", "安发装修", "1,230.00", "已完成"),
        ]
        for r, values in enumerate(rows):
            for c, value in enumerate(values):
                item = QTableWidgetItem(value)
                if c in (1, 3, 4):
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                table.setItem(r, c, item)
        recent_layout.addWidget(table)
        root.addWidget(recent, 1)
