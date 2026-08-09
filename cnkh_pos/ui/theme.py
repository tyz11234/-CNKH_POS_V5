from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QFile, QIODevice, QTextStream
from PySide6.QtWidgets import QApplication


def project_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parents[2]


def load_stylesheet() -> str:
    resource = QFile(":/cnkh/styles/app.qss")
    if resource.exists() and resource.open(QIODevice.OpenModeFlag.ReadOnly):
        stream = QTextStream(resource)
        return stream.readAll()
    return (project_root() / "resources" / "styles" / "app.qss").read_text(
        encoding="utf-8"
    )


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    app.setStyleSheet(load_stylesheet())
