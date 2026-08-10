from __future__ import annotations

import json
import os
import sys
import tempfile
import traceback
from datetime import datetime
from pathlib import Path

REPORT_ENV = "CNKH_POS_SELF_TEST_REPORT"


def _write_report(path: Path | None, payload: dict[str, object]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _safe_console(message: str) -> None:
    """Windowed PyInstaller executables may expose no stdout or stderr."""
    for stream in (getattr(sys, "stdout", None), getattr(sys, "stderr", None)):
        if stream is None:
            continue
        try:
            stream.write(message + "\n")
            stream.flush()
            return
        except (AttributeError, OSError, ValueError):
            continue


def _run_checks(mode: str) -> dict[str, object]:
    if mode not in {"admin", "staff"}:
        raise ValueError(f"unsupported self-test mode: {mode}")
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
            raise RuntimeError("application window did not become visible")
        window.close()
        app.processEvents()
        ok, _ = database.integrity_check()
        if not ok or result.schema_after <= 0:
            raise RuntimeError("temporary self-test database failed validation")
        return {
            "mode": mode,
            "schema": result.schema_after,
            "window_minimum_width": window.minimumWidth(),
        }


def run(mode: str) -> int:
    configured_report = os.environ.get(REPORT_ENV, "").strip()
    report_path = Path(configured_report) if configured_report else None
    started_at = datetime.now().astimezone().isoformat(timespec="seconds")
    try:
        details = _run_checks(mode)
    except BaseException as exc:
        payload = {
            "status": "FAIL",
            "mode": mode,
            "started_at": started_at,
            "finished_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "exception_type": type(exc).__name__,
            "error": str(exc),
            "traceback": "".join(
                traceback.format_exception(type(exc), exc, exc.__traceback__)
            ),
        }
        try:
            _write_report(report_path, payload)
        except (OSError, ValueError):
            pass
        _safe_console(f"PACKAGED {mode.upper()} SELF-TEST FAILED: {exc}")
        return 1

    payload = {
        "status": "PASS",
        "started_at": started_at,
        "finished_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        **details,
    }
    try:
        _write_report(report_path, payload)
    except (OSError, ValueError) as exc:
        _safe_console(f"PACKAGED {mode.upper()} SELF-TEST REPORT FAILED: {exc}")
        return 2
    _safe_console(f"PACKAGED {mode.upper()} SELF-TEST PASSED")
    return 0
