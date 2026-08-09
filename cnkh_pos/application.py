from __future__ import annotations

import sys
from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox, QMainWindow

from cnkh_pos.config import APP_VERSION, AppPaths
from cnkh_pos.database import Database, DatabaseStartupError, bootstrap_database
from cnkh_pos.services.error_log import write_error_log
from cnkh_pos.services.auth import AuthenticatedUser
from cnkh_pos.ui.dialogs.login import FirstAdminDialog, LoginDialog
from cnkh_pos.ui.theme import apply_theme


def run_application(
    mode: str,
    window_factory: Callable[[Database, AuthenticatedUser], QMainWindow],
) -> int:
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setApplicationName(f"CNKH POS {mode.title()}")
    app.setApplicationVersion(APP_VERSION)
    app.setOrganizationName("CNKH Hardware")
    apply_theme(app)
    paths = AppPaths.default()
    paths.ensure_directories()
    try:
        bootstrap_database(paths.database, paths.backups)
        database = Database(paths.database)
        conn = database.connect(readonly=True)
        try:
            user_count = int(
                conn.execute("SELECT COUNT(*) FROM users WHERE is_active=1").fetchone()[
                    0
                ]
            )
        finally:
            conn.close()
        if user_count == 0:
            if mode.lower() != "admin":
                QMessageBox.information(
                    None, "CNKH POS", "请先从 Admin 程序建立第一个管理员账号。"
                )
                return 1
            setup = FirstAdminDialog(database)
            if (
                setup.exec() != FirstAdminDialog.DialogCode.Accepted
                or setup.created_user is None
            ):
                return 0
            user = setup.created_user
        else:
            login = LoginDialog(database, mode.upper())
            if login.exec() != LoginDialog.DialogCode.Accepted or login.user is None:
                return 0
            user = login.user
        window = window_factory(database, user)
        window.show()
        return app.exec()
    except DatabaseStartupError as exc:
        write_error_log(paths.logs, exc, app_mode=mode)
        QMessageBox.critical(
            None,
            "Database safety lock / 数据库安全锁",
            f"{exc}\n\nV5 has not opened the database for normal writing.",
        )
        return 2
    except BaseException as exc:
        write_error_log(paths.logs, exc, app_mode=mode)
        QMessageBox.critical(None, "CNKH POS", f"Unexpected startup error:\n{exc}")
        return 3
