from __future__ import annotations

import json

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from cnkh_pos.database.connection import Database
from cnkh_pos.services.auth import AuthenticatedUser, AuthService


class NewUserDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Create User / 新增账号")
        self.setMinimumWidth(500)
        root = QVBoxLayout(self)
        form = QFormLayout()
        self.username = QLineEdit()
        self.display_name = QLineEdit()
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.confirm = QLineEdit()
        self.confirm.setEchoMode(QLineEdit.EchoMode.Password)
        self.role = QComboBox()
        self.role.addItem("Staff / 员工", "STAFF")
        self.role.addItem("Administrator / 管理员", "ADMIN")
        self.apply_discount = QCheckBox("Allow line discount / 允许折扣")
        self.manage_quick = QCheckBox("Manage quick amounts / 修改快捷金额")
        self.reprint = QCheckBox("Reprint latest receipt / 重印小票")
        self.reprint.setChecked(True)
        form.addRow("Username", self.username)
        form.addRow("Display Name", self.display_name)
        form.addRow("Password", self.password)
        form.addRow("Confirm", self.confirm)
        form.addRow("Role", self.role)
        form.addRow("Staff Permissions", self.apply_discount)
        form.addRow("", self.manage_quick)
        form.addRow("", self.reprint)
        root.addLayout(form)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._validate)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _validate(self) -> None:
        if not self.username.text().strip() or not self.display_name.text().strip():
            QMessageBox.warning(self, "User", "Username and display name are required.")
            return
        if self.password.text() != self.confirm.text():
            QMessageBox.warning(self, "User", "两次密码不一致。")
            return
        if len(self.password.text()) < 8:
            QMessageBox.warning(self, "User", "密码至少 8 个字符。")
            return
        self.accept()

    def value(self) -> tuple[str, str, str, str, dict[str, bool]]:
        role = str(self.role.currentData())
        permissions = (
            {
                "apply_discount": self.apply_discount.isChecked(),
                "manage_quick_amounts": self.manage_quick.isChecked(),
                "reprint_receipt": self.reprint.isChecked(),
            }
            if role == "STAFF"
            else {}
        )
        return (
            self.username.text().strip(),
            self.display_name.text().strip(),
            self.password.text(),
            role,
            permissions,
        )


class EditUserDialog(QDialog):
    def __init__(self, row, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit User / 编辑账号权限")
        self.setMinimumWidth(500)
        root = QVBoxLayout(self)
        form = QFormLayout()
        username = QLineEdit(str(row["username"]))
        username.setReadOnly(True)
        self.display_name = QLineEdit(str(row["display_name"]))
        self.role = QComboBox()
        self.role.addItem("Staff / 员工", "STAFF")
        self.role.addItem("Administrator / 管理员", "ADMIN")
        self.role.setCurrentIndex(max(0, self.role.findData(str(row["role"]))))
        permissions = json.loads(row["permissions_json"] or "{}")
        self.apply_discount = QCheckBox("Allow line discount / 允许折扣")
        self.manage_quick = QCheckBox("Manage quick amounts / 修改快捷金额")
        self.reprint = QCheckBox("Reprint latest receipt / 重印小票")
        self.apply_discount.setChecked(bool(permissions.get("apply_discount", False)))
        self.manage_quick.setChecked(
            bool(permissions.get("manage_quick_amounts", False))
        )
        self.reprint.setChecked(bool(permissions.get("reprint_receipt", False)))
        form.addRow("Username", username)
        form.addRow("Display Name", self.display_name)
        form.addRow("Role", self.role)
        form.addRow("Staff Permissions", self.apply_discount)
        form.addRow("", self.manage_quick)
        form.addRow("", self.reprint)
        root.addLayout(form)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._validate)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self.role.currentIndexChanged.connect(self._role_changed)
        self._role_changed()

    def _role_changed(self) -> None:
        is_staff = self.role.currentData() == "STAFF"
        for control in (self.apply_discount, self.manage_quick, self.reprint):
            control.setEnabled(is_staff)

    def _validate(self) -> None:
        if not self.display_name.text().strip():
            QMessageBox.warning(self, "User", "Display name is required.")
            return
        self.accept()

    def value(self) -> tuple[str, str, dict[str, bool]]:
        role = str(self.role.currentData())
        permissions = (
            {
                "apply_discount": self.apply_discount.isChecked(),
                "manage_quick_amounts": self.manage_quick.isChecked(),
                "reprint_receipt": self.reprint.isChecked(),
            }
            if role == "STAFF"
            else {}
        )
        return self.display_name.text().strip(), role, permissions


class UsersPage(QWidget):
    def __init__(self, database: Database, current_user: AuthenticatedUser):
        super().__init__()
        self.database = database
        self.current_user = current_user
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 20)
        header = QHBoxLayout()
        title = QLabel("User Accounts / 员工账号")
        title.setObjectName("PageTitle")
        header.addWidget(title)
        header.addStretch(1)
        for text, callback, style in (
            ("＋ 新增账号", self.add_user, "PrimaryButton"),
            ("编辑账号/权限", self.edit_user, "WarningButton"),
            ("重设密码", self.reset_password, "WarningButton"),
            ("启用 / 停用", self.toggle_active, "DangerButton"),
            ("刷新", self.refresh, ""),
        ):
            button = QPushButton(text)
            button.setObjectName(style)
            button.clicked.connect(callback)
            header.addWidget(button)
        root.addLayout(header)
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ["ID", "Username", "Display Name", "Role", "Status", "Permissions", "Updated"]
        )
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        root.addWidget(self.table)
        self.refresh()

    def edit_user(self) -> None:
        user_id = self.selected_id()
        if user_id is None:
            QMessageBox.information(self, "User", "请先选择账号。")
            return
        conn = self.database.connect(readonly=True)
        try:
            row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        finally:
            conn.close()
        if row is None:
            QMessageBox.warning(self, "User", "账号不存在。")
            return
        dialog = EditUserDialog(row, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        display_name, role, permissions = dialog.value()
        try:
            with self.database.transaction() as conn:
                AuthService.update_user(
                    conn,
                    target_id=user_id,
                    display_name=display_name,
                    role=role,
                    permissions=permissions,
                    current_admin_id=self.current_user.id,
                )
        except Exception as exc:
            QMessageBox.warning(self, "User", str(exc))
            return
        self.refresh()

    def selected_id(self) -> int | None:
        row = self.table.currentRow()
        return None if row < 0 else int(self.table.item(row, 0).text())

    def refresh(self) -> None:
        conn = self.database.connect(readonly=True)
        try:
            rows = conn.execute(
                """SELECT id,username,display_name,role,is_active,permissions_json,updated_at
                   FROM users ORDER BY is_active DESC,role,username COLLATE NOCASE"""
            ).fetchall()
        finally:
            conn.close()
        self.table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            permissions = json.loads(row["permissions_json"] or "{}")
            enabled = [key for key, value in permissions.items() if value]
            values = (
                row["id"],
                row["username"],
                row["display_name"],
                row["role"],
                "ACTIVE" if row["is_active"] else "DISABLED",
                ", ".join(enabled) or "—",
                row["updated_at"],
            )
            for column, value in enumerate(values):
                self.table.setItem(row_index, column, QTableWidgetItem(str(value)))

    def add_user(self) -> None:
        dialog = NewUserDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        username, display_name, password, role, permissions = dialog.value()
        try:
            with self.database.transaction() as conn:
                AuthService.create_user(
                    conn,
                    username=username,
                    display_name=display_name,
                    password=password,
                    role=role,
                    permissions=permissions,
                    admin_id=self.current_user.id,
                )
        except Exception as exc:
            QMessageBox.warning(self, "User", str(exc))
            return
        self.refresh()

    def reset_password(self) -> None:
        user_id = self.selected_id()
        if user_id is None:
            QMessageBox.information(self, "User", "请先选择账号。")
            return
        password, ok = self._password_dialog("New Password")
        if not ok:
            return
        try:
            with self.database.transaction() as conn:
                AuthService.reset_password(
                    conn,
                    target_id=user_id,
                    new_password=password,
                    admin_id=self.current_user.id,
                )
        except Exception as exc:
            QMessageBox.warning(self, "User", str(exc))
            return
        QMessageBox.information(self, "User", "密码已更新。")

    def _password_dialog(self, title: str) -> tuple[str, bool]:
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        layout = QFormLayout(dialog)
        first = QLineEdit()
        first.setEchoMode(QLineEdit.EchoMode.Password)
        second = QLineEdit()
        second.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addRow("Password", first)
        layout.addRow("Confirm", second)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return "", False
        if first.text() != second.text() or len(first.text()) < 8:
            QMessageBox.warning(self, "User", "密码不一致或少于 8 个字符。")
            return "", False
        return first.text(), True

    def toggle_active(self) -> None:
        row = self.table.currentRow()
        user_id = self.selected_id()
        if row < 0 or user_id is None:
            QMessageBox.information(self, "User", "请先选择账号。")
            return
        activate = self.table.item(row, 4).text() != "ACTIVE"
        action = "启用" if activate else "停用"
        if (
            QMessageBox.question(self, "User", f"确认{action}所选账号？")
            != QMessageBox.StandardButton.Yes
        ):
            return
        try:
            with self.database.transaction() as conn:
                AuthService.set_active(
                    conn,
                    target_id=user_id,
                    is_active=activate,
                    current_admin_id=self.current_user.id,
                )
        except Exception as exc:
            QMessageBox.warning(self, "User", str(exc))
            return
        self.refresh()
