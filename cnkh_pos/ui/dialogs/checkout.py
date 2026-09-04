from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from cnkh_pos.config import AppPaths
from cnkh_pos.services.money import format_myr, rm_to_cents
from cnkh_pos.services.printing import resolve_checkout_qr_path

CHECKOUT_QR_PREVIEW_SIZE = 220
STAFF_MISSING_QR_MESSAGE = "尚未设置 DuitNow 收款码，请管理员在设置中上传"
ADMIN_MISSING_QR_HINT = "尚未设置 DuitNow 收款码 → 请到「收据设置 / Receipt Settings」上传"


class CheckoutDialog(QDialog):
    """Large mouse-first payment dialog. Committing a sale belongs to SalesService."""

    def __init__(
        self,
        total_cents: int,
        quick_amounts: list[int] | None = None,
        parent=None,
        *,
        customers: list[tuple[int, str]] | None = None,
        quick_settings_callback=None,
        paths: AppPaths | Path | None = None,
        is_admin: bool = False,
    ):
        super().__init__(parent)
        self.total_cents = total_cents
        self.paid_cents = 0
        self.payment_method = "CASH"
        self.deposit_method: str | None = None
        self.customer_id: int | None = None
        self._paths = self._normalize_paths(paths)
        self._is_admin = bool(is_admin)
        self.setWindowTitle("结账 / 收款")
        self.setModal(True)
        self.setMinimumSize(430, 620)
        self.resize(470, 720)
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(12)

        title = QLabel("结账 / 收款")
        title.setObjectName("PageTitle")
        root.addWidget(title)
        root.addWidget(self._caption("应收金额"))
        total = QLabel(format_myr(total_cents))
        total.setObjectName("MoneyHero")
        total.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(total)

        root.addWidget(self._caption("实收金额"))
        self.paid_input = QLineEdit()
        self.paid_input.setObjectName("PaymentInput")
        self.paid_input.setPlaceholderText("RM 0.00")
        self.paid_input.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.paid_input.textChanged.connect(self._update_change)
        root.addWidget(self.paid_input)

        root.addWidget(self._caption("付款方式"))
        methods = QHBoxLayout()
        self.method_group = QButtonGroup(self)
        self.method_group.setExclusive(True)
        for index, (label, value) in enumerate(
            (
                ("Cash", "CASH"),
                ("Card", "CARD"),
                ("DuitNow QR", "DUITNOW_QR"),
                ("Credit", "CREDIT"),
            )
        ):
            button = QPushButton(label)
            button.setObjectName(f"PaymentMethod{value}")
            button.setCheckable(True)
            button.setProperty("paymentMethod", value)
            self.method_group.addButton(button)
            methods.addWidget(button)
            if index == 0:
                button.setChecked(True)
        root.addLayout(methods)

        self.customer_caption = self._caption("Credit Customer / 欠账客户")
        self.customer = QComboBox()
        self.customer.setObjectName("CreditCustomer")
        self.customer.addItem("请选择客户", None)
        for customer_id, name in customers or []:
            self.customer.addItem(name, customer_id)
        self.customer_caption.hide()
        self.customer.hide()
        root.addWidget(self.customer_caption)
        root.addWidget(self.customer)

        self.deposit_caption = self._caption("定金付款方式 / Deposit Method")
        self.deposit_caption.hide()
        root.addWidget(self.deposit_caption)
        deposit_row = QHBoxLayout()
        self.deposit_group = QButtonGroup(self)
        self.deposit_group.setExclusive(True)
        for index, (label, value) in enumerate(
            (
                ("Cash", "CASH"),
                ("Card", "CARD"),
                ("DuitNow QR", "DUITNOW_QR"),
            )
        ):
            button = QPushButton(label)
            button.setObjectName(f"DepositMethod{value}")
            button.setCheckable(True)
            button.setProperty("depositMethod", value)
            self.deposit_group.addButton(button)
            deposit_row.addWidget(button)
            if index == 0:
                button.setChecked(True)
        self.deposit_buttons_host = QWidget()
        self.deposit_buttons_host.setLayout(deposit_row)
        self.deposit_buttons_host.hide()
        root.addWidget(self.deposit_buttons_host)
        self.paid_input.textChanged.connect(self._refresh_deposit_visibility)
        self.method_group.buttonToggled.connect(self._method_changed)
        self.deposit_group.buttonToggled.connect(self._deposit_changed)

        root.addWidget(self._build_duitnow_qr_panel())

        quick_header = QHBoxLayout()
        quick_header.addWidget(self._caption("快捷金额"))
        quick_header.addStretch(1)
        settings = QPushButton("⚙ 设置")
        settings.setObjectName("QuickAmountSettingsButton")
        self.settings_button = settings
        if quick_settings_callback is not None:
            settings.clicked.connect(quick_settings_callback)
        quick_header.addWidget(settings)
        root.addLayout(quick_header)
        quick_grid = QGridLayout()
        for index, cents in enumerate(
            quick_amounts or [1000, 2000, 5000, 10000, 20000]
        ):
            button = QPushButton(format_myr(cents).replace(".00", ""))
            button.setObjectName("QuickAmountButton")
            button.clicked.connect(
                lambda checked=False, amount=cents: self._set_paid(amount)
            )
            quick_grid.addWidget(button, index // 3, index % 3)
        root.addLayout(quick_grid)

        change_row = QHBoxLayout()
        change_row.addWidget(self._caption("找零金额"))
        change_row.addStretch(1)
        self.change_label = QLabel("RM 0.00")
        self.change_label.setStyleSheet(
            "color:#168A3F; font-size:22px; font-weight:800;"
        )
        change_row.addWidget(self.change_label)
        root.addLayout(change_row)
        root.addStretch(1)

        actions = QHBoxLayout()
        cancel = QPushButton("取消")
        cancel.setObjectName("PaymentCancelButton")
        cancel.clicked.connect(self.reject)
        confirm = QPushButton("确认收款")
        confirm.setObjectName("SuccessButton")
        confirm.setProperty("acceptanceName", "PaymentConfirmButton")
        self.confirm_button = confirm
        confirm.setMinimumHeight(54)
        confirm.clicked.connect(self._confirm)
        actions.addWidget(cancel)
        actions.addWidget(confirm, 2)
        root.addLayout(actions)
        self._refresh_duitnow_qr_panel()

    @staticmethod
    def _normalize_paths(paths: AppPaths | Path | None) -> AppPaths:
        if paths is None:
            return AppPaths.default()
        if isinstance(paths, AppPaths):
            return paths
        # Resolved assets Path or Assets folder Path.
        path = Path(paths)
        if path.name.lower() in {"receipt_qr.png", "receipt_qr.jpg"}:
            assets = path.parent
            root = assets.parent
        elif path.name == "Assets":
            assets = path
            root = assets.parent
        else:
            # Treat as AppPaths.root
            root = path
            assets = root / "Assets"
        return AppPaths(
            root=root,
            data=root / "Data",
            database=root / "Data" / "hardware_pos.db",
            backups=root / "Backups",
            logs=root / "Logs",
            exports=root / "Exports",
            receipts=root / "Receipts",
            assets=assets,
        )

    def _build_duitnow_qr_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("CheckoutDuitNowQrPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(8)
        caption = self._caption("DuitNow 收款码 / Payment QR")
        caption.setObjectName("CheckoutDuitNowQrCaption")
        layout.addWidget(caption)
        preview = QLabel()
        preview.setObjectName("CheckoutDuitNowQrPreview")
        preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        preview.setFixedSize(CHECKOUT_QR_PREVIEW_SIZE, CHECKOUT_QR_PREVIEW_SIZE)
        preview.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
        )
        preview.setStyleSheet(
            "background:#F7FAFC; border:1px solid #DCE3EC; border-radius:12px;"
        )
        preview.setScaledContents(False)
        layout.addWidget(preview, 0, Qt.AlignmentFlag.AlignHCenter)
        message = QLabel()
        message.setObjectName("CheckoutDuitNowQrMessage")
        message.setWordWrap(True)
        message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        message.setStyleSheet("color:#5B6B7C; font-size:13px;")
        layout.addWidget(message)
        panel.hide()
        self.duitnow_qr_panel = panel
        self.duitnow_qr_preview = preview
        self.duitnow_qr_message = message
        return panel

    def _duitnow_qr_should_show(self) -> bool:
        selected = self.method_group.checkedButton()
        method = (
            str(selected.property("paymentMethod")) if selected else "CASH"
        )
        if method == "DUITNOW_QR":
            return True
        if method == "CREDIT" and not self.deposit_buttons_host.isHidden():
            deposit = self.deposit_group.checkedButton()
            if deposit is not None and str(deposit.property("depositMethod")) == (
                "DUITNOW_QR"
            ):
                return True
        return False

    def _refresh_duitnow_qr_panel(self) -> None:
        show = self._duitnow_qr_should_show()
        self.duitnow_qr_panel.setVisible(show)
        if not show:
            return
        qr_path = resolve_checkout_qr_path(paths=self._paths)
        if qr_path is not None:
            pixmap = QPixmap(str(qr_path))
            if not pixmap.isNull():
                self.duitnow_qr_preview.setText("")
                self.duitnow_qr_preview.setPixmap(
                    pixmap.scaled(
                        self.duitnow_qr_preview.size(),
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
                self.duitnow_qr_preview.show()
                self.duitnow_qr_message.hide()
                return
        self.duitnow_qr_preview.setPixmap(QPixmap())
        self.duitnow_qr_preview.setText("")
        self.duitnow_qr_preview.hide()
        if self._is_admin:
            self.duitnow_qr_message.setText(ADMIN_MISSING_QR_HINT)
            self.duitnow_qr_message.setStyleSheet(
                "color:#0B6BCB; font-size:13px; text-decoration:underline;"
            )
        else:
            self.duitnow_qr_message.setText(STAFF_MISSING_QR_MESSAGE)
            self.duitnow_qr_message.setStyleSheet(
                "color:#B54708; font-size:13px; font-weight:600;"
            )
        self.duitnow_qr_message.show()

    @staticmethod
    def _caption(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("SectionTitle")
        return label

    def _set_paid(self, cents: int) -> None:
        self.paid_input.setText(f"{cents / 100:.2f}")

    def _method_changed(self, button: QPushButton, checked: bool) -> None:
        if not checked:
            return
        method = str(button.property("paymentMethod"))
        is_credit = method == "CREDIT"
        self.customer_caption.setVisible(is_credit)
        self.customer.setVisible(is_credit)
        if method in {"CARD", "DUITNOW_QR"}:
            self._set_paid(self.total_cents)
        elif is_credit:
            self.paid_input.setText("0.00")
        self._refresh_deposit_visibility()
        self._refresh_duitnow_qr_panel()

    def _deposit_changed(self, button: QPushButton, checked: bool) -> None:
        if not checked:
            return
        self._refresh_duitnow_qr_panel()

    def _refresh_deposit_visibility(self, *_args) -> None:
        selected = self.method_group.checkedButton()
        method = (
            str(selected.property("paymentMethod")) if selected else "CASH"
        )
        show = False
        if method == "CREDIT":
            cleaned = (
                self.paid_input.text()
                .upper()
                .replace("RM", "")
                .replace(",", "")
                .strip()
            )
            try:
                paid = rm_to_cents(cleaned or "0")
            except ValueError:
                paid = 0
            show = paid > 0
        self.deposit_caption.setVisible(show)
        self.deposit_buttons_host.setVisible(show)
        self._refresh_duitnow_qr_panel()

    def _update_change(self, value: str) -> None:
        cleaned = value.upper().replace("RM", "").replace(",", "").strip()
        try:
            paid = rm_to_cents(cleaned or "0")
        except ValueError:
            self.change_label.setText("—")
            return
        self.change_label.setText(format_myr(max(0, paid - self.total_cents)))

    def _confirm(self) -> None:
        selected = self.method_group.checkedButton()
        self.payment_method = (
            str(selected.property("paymentMethod")) if selected else "CASH"
        )
        self.customer_id = (
            int(self.customer.currentData())
            if self.payment_method == "CREDIT"
            and self.customer.currentData() is not None
            else None
        )
        if self.payment_method == "CREDIT" and self.customer_id is None:
            self.customer.setFocus()
            self.customer.setStyleSheet("border:2px solid #E5484D;")
            return
        cleaned = (
            self.paid_input.text().upper().replace("RM", "").replace(",", "").strip()
        )
        if self.payment_method in {"CARD", "DUITNOW_QR"} and not cleaned:
            self.paid_cents = self.total_cents
        else:
            try:
                self.paid_cents = rm_to_cents(cleaned or "0")
            except ValueError:
                self.paid_input.setFocus()
                return
        if self.payment_method != "CREDIT" and self.paid_cents < self.total_cents:
            self.paid_input.setStyleSheet("border:2px solid #E5484D;")
            self.paid_input.setFocus()
            return
        self.deposit_method = None
        if self.payment_method == "CREDIT" and self.paid_cents > 0:
            deposit_button = self.deposit_group.checkedButton()
            if deposit_button is None:
                self.deposit_buttons_host.setStyleSheet("border:2px solid #E5484D;")
                return
            self.deposit_method = str(deposit_button.property("depositMethod"))
            self.deposit_buttons_host.setStyleSheet("")
        self.accept()


class SaleCompletedDialog(QDialog):
    def __init__(
        self,
        receipt_no: str,
        total_cents: int,
        paid_cents: int,
        method: str,
        parent=None,
    ):
        super().__init__(parent)
        self.print_requested = False
        self.setWindowTitle("Sale Completed / 销售完成")
        self.setMinimumWidth(520)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 26, 28, 26)
        title = QLabel("✓  Sale Completed / 销售完成")
        title.setStyleSheet("color:#168A3F; font-size:22px; font-weight:800;")
        layout.addWidget(title)
        for key, value in (
            ("Receipt No", receipt_no),
            ("Total", format_myr(total_cents)),
            ("Paid", format_myr(paid_cents)),
            ("Change", format_myr(max(0, paid_cents - total_cents))),
            ("Payment Method", method),
        ):
            row = QHBoxLayout()
            row.addWidget(QLabel(key))
            row.addStretch(1)
            result = QLabel(value)
            result.setStyleSheet("font-weight:700;")
            row.addWidget(result)
            layout.addLayout(row)
        actions = QHBoxLayout()
        print_button = QPushButton("打印小票")
        print_button.setObjectName("SuccessButton")
        print_button.setProperty("acceptanceName", "PrintReceiptButton")
        print_button.clicked.connect(self._request_print)
        self.print_button = print_button
        skip = QPushButton("暂不打印")
        skip.setObjectName("SkipPrintButton")
        skip.clicked.connect(self.accept)
        self.skip_button = skip
        actions.addWidget(print_button)
        actions.addWidget(skip)
        layout.addLayout(actions)

    def _request_print(self) -> None:
        self.print_requested = True
        self.accept()
