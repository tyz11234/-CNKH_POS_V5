from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from cnkh_pos.database.connection import Database
from cnkh_pos.services.auth import AuthService, AuthenticatedUser


class FirstAdminDialog(QDialog):
    def __init__(self, database: Database, parent=None):
        super().__init__(parent)
        self.database = database
        self.created_user: AuthenticatedUser | None = None
        self.setWindowTitle("CNKH POS V5 — First Administrator")
        self.setMinimumWidth(480)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        title = QLabel("建立第一个管理员 / Create First Admin")
        title.setObjectName("PageTitle")
        layout.addWidget(title)
        form = QFormLayout()
        self.username = QLineEdit("admin")
        self.display_name = QLineEdit("Administrator")
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.confirm = QLineEdit()
        self.confirm.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("Username", self.username)
        form.addRow("Display Name", self.display_name)
        form.addRow("Password", self.password)
        form.addRow("Confirm Password", self.confirm)
        layout.addLayout(form)
        note = QLabel("密码至少 8 个字符。密码与 Hash 永远不会写入 Audit/Error Log。")
        note.setObjectName("Muted")
        layout.addWidget(note)
        button = QPushButton("建立管理员并继续")
        button.setObjectName("PrimaryButton")
        button.clicked.connect(self._create)
        layout.addWidget(button)

    def _create(self) -> None:
        if self.password.text() != self.confirm.text():
            QMessageBox.warning(self, "Password", "两次密码不一致。")
            return
        try:
            with self.database.transaction() as conn:
                AuthService.create_user(
                    conn,
                    username=self.username.text(),
                    display_name=self.display_name.text(),
                    password=self.password.text(),
                    role="ADMIN",
                    permissions={},
                    admin_id=None,
                )
                self.created_user = AuthService.authenticate(
                    conn,
                    self.username.text(),
                    self.password.text(),
                    required_role="ADMIN",
                )
        except Exception as exc:
            QMessageBox.warning(self, "Create Admin", str(exc))
            return
        self.accept()


class LoginDialog(QDialog):
    def __init__(self, database: Database, role: str, parent=None):
        super().__init__(parent)
        self.database = database
        self.role = role
        self.user: AuthenticatedUser | None = None
        self.setWindowTitle(f"CNKH POS {role.title()} Login")
        self.setMinimumWidth(430)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 28, 30, 28)
        brand = QLabel("◆ CNKH Hardware POS")
        brand.setStyleSheet("color:#102E64; font-size:22px; font-weight:900;")
        title = QLabel("管理员登录" if role == "ADMIN" else "员工 / Cashier 登录")
        title.setObjectName("PageTitle")
        self.username = QLineEdit()
        self.username.setPlaceholderText("Username")
        self.password = QLineEdit()
        self.password.setPlaceholderText("Password")
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.password.returnPressed.connect(self._login)
        login = QPushButton("登录 / Login")
        login.setObjectName("PrimaryButton")
        login.setMinimumHeight(48)
        login.clicked.connect(self._login)
        layout.addWidget(brand)
        layout.addWidget(title)
        layout.addWidget(self.username)
        layout.addWidget(self.password)
        layout.addWidget(login)

    def _login(self) -> None:
        try:
            with self.database.transaction() as conn:
                self.user = AuthService.authenticate(
                    conn,
                    self.username.text(),
                    self.password.text(),
                    required_role=self.role,
                )
        except PermissionError:
            QMessageBox.warning(self, "Login", "账号、密码或入口角色不正确。")
            return
        self.accept()
