"""Top-bar sync/pair control shared by Staff + Admin."""

from __future__ import annotations

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import QLabel, QPushButton

from cnkh_pos.database.connection import Database
from cnkh_pos.services.lan_sync_server import get_active_server, get_event_hub
from cnkh_pos.ui.dialogs.sync_pair_dialog import open_sync_pair_dialog


class SyncEventBridge(QObject):
    """Marshal EventHub callbacks onto the Qt GUI thread."""

    sale_event = Signal(dict)


_BRIDGE: SyncEventBridge | None = None


def sync_event_bridge() -> SyncEventBridge:
    global _BRIDGE
    if _BRIDGE is None:
        _BRIDGE = SyncEventBridge()

        def _forward(event: dict) -> None:
            try:
                _BRIDGE.sale_event.emit(event)  # type: ignore[union-attr]
            except Exception:
                pass

        get_event_hub().add_listener(_forward)
    return _BRIDGE


def make_sync_pair_button(parent, database: Database) -> QPushButton:
    btn = QPushButton("同步/配对")
    btn.setObjectName("SyncPairButton")
    btn.setToolTip("局域网同步 · 显示配对二维码给手机扫描")
    btn.setMinimumHeight(32)
    btn.clicked.connect(lambda: open_sync_pair_dialog(parent, database))
    return btn


def make_sync_status_label() -> QLabel:
    label = QLabel("○ Sync")
    label.setObjectName("SyncStatusLabel")
    label.setStyleSheet("color:#888;font-size:12px;font-weight:700;")

    def _tick() -> None:
        srv = get_active_server()
        if srv is not None and srv.running:
            label.setText("● Sync")
            label.setStyleSheet("color:#168A3F;font-size:12px;font-weight:700;")
        else:
            label.setText("○ Sync")
            label.setStyleSheet("color:#888;font-size:12px;font-weight:700;")

    timer = QTimer(label)
    timer.timeout.connect(_tick)
    timer.start(1500)
    _tick()
    return label
