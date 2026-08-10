from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from cnkh_pos.config import AppPaths
from cnkh_pos.database.connection import Database
from cnkh_pos.services.barcode_labels import (
    LABEL_PROFILES,
    get_label_profile,
    list_label_products,
    load_product_label,
    print_product_labels,
    render_product_label_pdf,
)
from cnkh_pos.services.money import format_myr


class BarcodeLabelsPage(QWidget):
    def __init__(self, database: Database, parent: QWidget | None = None):
        super().__init__(parent)
        self.database = database
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 18)
        root.setSpacing(12)

        title = QLabel("商品条码标签打印")
        title.setObjectName("PageTitle")
        root.addWidget(title)

        hint = QLabel(
            "选择商品、标签尺寸和打印张数。默认 50×30 mm；打印时可在 Windows 对话框选择实际标签打印机。"
        )
        hint.setWordWrap(True)
        root.addWidget(hint)

        search_row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索商品名称 / SKU / Barcode")
        self.search.returnPressed.connect(self.refresh)
        search_button = QPushButton("搜索")
        search_button.clicked.connect(self.refresh)
        refresh_button = QPushButton("刷新")
        refresh_button.clicked.connect(self._reset_search)
        search_row.addWidget(self.search, 1)
        search_row.addWidget(search_button)
        search_row.addWidget(refresh_button)
        root.addLayout(search_row)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["ID", "商品", "SKU", "Barcode", "售价"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        root.addWidget(self.table, 1)

        controls = QFormLayout()
        self.profile = QComboBox()
        for label_profile in LABEL_PROFILES:
            self.profile.addItem(label_profile.label, label_profile.key)
        default_profile_index = self.profile.findData("50x30")
        if default_profile_index >= 0:
            self.profile.setCurrentIndex(default_profile_index)
        self.copies = QSpinBox()
        self.copies.setRange(1, 999)
        self.copies.setValue(1)
        self.copies.setSuffix(" 张")
        controls.addRow("标签尺寸", self.profile)
        controls.addRow("打印张数", self.copies)
        root.addLayout(controls)

        actions = QHBoxLayout()
        actions.addStretch(1)
        preview_button = QPushButton("导出 PDF 预览")
        preview_button.clicked.connect(self.export_pdf)
        print_button = QPushButton("打印条码标签")
        print_button.setObjectName("PrimaryButton")
        print_button.setProperty("acceptanceName", "BarcodeLabelPrintButton")
        print_button.clicked.connect(self.print_labels)
        actions.addWidget(preview_button)
        actions.addWidget(print_button)
        root.addLayout(actions)

        self.refresh()

    def _reset_search(self) -> None:
        self.search.clear()
        self.refresh()

    def refresh(self) -> None:
        try:
            products = list_label_products(self.database, self.search.text())
        except Exception as exc:
            QMessageBox.warning(self, "Barcode Labels", str(exc))
            return
        self.table.setRowCount(len(products))
        for row_index, product in enumerate(products):
            values = (
                product.product_id,
                product.name,
                product.sku,
                product.barcode,
                format_myr(product.price_cents),
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if column in (0, 4):
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.table.setItem(row_index, column, item)
        if products:
            self.table.selectRow(0)

    def _selected_product_id(self) -> int | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        return None if item is None else int(item.text())

    def _selected_label(self):
        product_id = self._selected_product_id()
        if product_id is None:
            raise ValueError("请先选择一个商品。")
        return load_product_label(self.database, product_id)

    def export_pdf(self) -> None:
        try:
            label = self._selected_label()
            profile = get_label_profile(str(self.profile.currentData()))
        except Exception as exc:
            QMessageBox.warning(self, "Barcode Labels", str(exc))
            return

        paths = AppPaths.default()
        paths.ensure_directories()
        target, _ = QFileDialog.getSaveFileName(
            self,
            "Export Barcode Label PDF",
            str(paths.exports / f"barcode_{label.barcode}_{profile.key}.pdf"),
            "PDF (*.pdf)",
            options=QFileDialog.Option.DontUseNativeDialog,
        )
        if not target:
            return
        try:
            result = render_product_label_pdf(
                label,
                profile,
                self.copies.value(),
                Path(target),
            )
            QMessageBox.information(
                self,
                "Barcode Labels",
                f"PDF 已建立：\n{result}\n\n页数：{self.copies.value()} 张",
            )
        except Exception as exc:
            QMessageBox.warning(self, "Barcode Labels", str(exc))

    def print_labels(self) -> None:
        try:
            label = self._selected_label()
            profile = get_label_profile(str(self.profile.currentData()))
            copies = self.copies.value()
            printed = print_product_labels(
                label,
                profile,
                copies,
                parent=self,
            )
        except Exception as exc:
            QMessageBox.warning(self, "Barcode Labels", str(exc))
            return
        if printed:
            QMessageBox.information(
                self,
                "Barcode Labels",
                f"已发送 {copies} 张 {profile.width_mm:g}×{profile.height_mm:g} mm 条码标签到打印机。",
            )
