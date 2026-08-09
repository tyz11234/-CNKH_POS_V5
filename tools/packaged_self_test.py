from __future__ import annotations

import os
import tempfile
from pathlib import Path


def run(mode: str) -> int:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from cnkh_pos.database.bootstrap import bootstrap_database
    from cnkh_pos.database.connection import Database
    from cnkh_pos.services.auth import AuthService
    from cnkh_pos.services.catalog import CatalogService, ProductInput
    from cnkh_pos.ui.theme import apply_theme

    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        database = Database(root / "hardware_pos.db")
        result = bootstrap_database(database.path, root / "backups")
        with database.transaction() as conn:
            user_id = AuthService.create_user(
                conn,
                username="selftest",
                display_name="Self Test",
                password="SelfTest123!",
                role="ADMIN" if mode == "admin" else "STAFF",
                permissions={},
                admin_id=None,
            )
            user = AuthService.authenticate(
                conn,
                "selftest",
                "SelfTest123!",
                required_role="ADMIN" if mode == "admin" else "STAFF",
            )
        CatalogService(database).add_product(
            ProductInput(
                name="Self Test Product",
                sku="SELFTEST",
                selling_price_cents=100,
                stock="10",
            ),
            admin_id=user_id,
        )
        app = QApplication.instance() or QApplication([])
        apply_theme(app)
        if mode == "admin":
            from cnkh_pos.ui.admin import AdminWindow

            window = AdminWindow(database, user)
        else:
            from cnkh_pos.ui.staff import StaffWindow

            window = StaffWindow(database, user)
        window.show()
        app.processEvents()
        if not window.isVisible() or window.minimumWidth() <= 0:
            return 3
        window.close()
        ok, _ = database.integrity_check()
        if not ok or result.schema_after <= 0:
            return 4
    print(f"PACKAGED {mode.upper()} SELF-TEST PASSED")
    return 0
