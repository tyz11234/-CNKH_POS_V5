"""Prominent LAN sync / pairing QR dialog for Staff + Admin top bars."""

from __future__ import annotations

import secrets

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from cnkh_pos.database.connection import Database
from cnkh_pos.services.lan_sync_server import (
    DEFAULT_PORT,
    detect_lan_ip,
    get_active_server,
    pairing_payload,
    start_global_server,
    stop_global_server,
)


def _qr_pixmap(text: str, *, modules: int = 9) -> QPixmap:
    """Render QR via qrcode matrix → QImage (no Pillow required)."""
    try:
        import qrcode
    except ImportError:
        # Fallback: blank with text note
        pix = QPixmap(280, 280)
        pix.fill(QColor("white"))
        painter = QPainter(pix)
        painter.drawText(pix.rect(), Qt.AlignmentFlag.AlignCenter, "install qrcode\nfor QR")
        painter.end()
        return pix
    qr = qrcode.QRCode(border=2, box_size=modules)
    qr.add_data(text)
    qr.make(fit=True)
    matrix = qr.get_matrix()
    size = len(matrix)
    img = QImage(size, size, QImage.Format.Format_RGB32)
    img.fill(QColor("white"))
    for y, row in enumerate(matrix):
        for x, cell in enumerate(row):
            if cell:
                img.setPixel(x, y, QColor("black").rgb())
    return QPixmap.fromImage(
        img.scaled(280, 280, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.FastTransformation)
    )


class SyncPairDialog(QDialog):
    """Start/stop sync server and show pairing QR for phone scan."""

    def __init__(self, database: Database, parent=None):
        super().__init__(parent)
        self.database = database
        self.setWindowTitle("同步 / 配对 · LAN Sync")
        self.setMinimumWidth(420)
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        title = QLabel("手机扫码配对 / Scan to pair")
        title.setStyleSheet("font-size:18px;font-weight:800;")
        root.addWidget(title)
        self.status = QLabel("Stopped")
        root.addWidget(self.status)
        self.endpoint = QLabel("—")
        self.endpoint.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.endpoint.setStyleSheet("font-size:15px;font-weight:700;color:#1769E0;")
        root.addWidget(self.endpoint)
        self.qr_label = QLabel()
        self.qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.qr_label.setMinimumHeight(290)
        root.addWidget(self.qr_label)
        self.payload = QLabel("")
        self.payload.setWordWrap(True)
        self.payload.setStyleSheet("color:#667;font-size:11px;")
        self.payload.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        root.addWidget(self.payload)

        token_row = QHBoxLayout()
        token_row.addWidget(QLabel("Token"))
        self.token = QLineEdit()
        self.token.setPlaceholderText("可选 / optional")
        token_row.addWidget(self.token, 1)
        root.addLayout(token_row)

        port_row = QHBoxLayout()
        port_row.addWidget(QLabel("Port"))
        self.port = QLineEdit(str(DEFAULT_PORT))
        port_row.addWidget(self.port)
        root.addLayout(port_row)

        ttl_row = QHBoxLayout()
        ttl_row.addWidget(QLabel("有效分钟 5–10"))
        self.ttl = QLineEdit("7")
        ttl_row.addWidget(self.ttl)
        root.addLayout(ttl_row)

        actions = QHBoxLayout()
        start = QPushButton("启动并显示二维码 / Start")
        start.setObjectName("SuccessButton")
        start.clicked.connect(self.start_server)
        refresh = QPushButton("刷新配对码 / Refresh QR")
        refresh.setObjectName("PrimaryButton")
        refresh.clicked.connect(self.refresh_qr)
        stop = QPushButton("停止 / Stop")
        stop.setObjectName("DangerButton")
        stop.clicked.connect(self.stop_server)
        close = QPushButton("关闭")
        close.clicked.connect(self.accept)
        actions.addWidget(start)
        actions.addWidget(refresh)
        actions.addWidget(stop)
        actions.addWidget(close)
        root.addLayout(actions)
        tip = QLabel(
            "同一 Wi‑Fi · 手机点顶栏「扫码配对」扫此码。\n"
            "格式 cnkh-sync:v1|{baseUrl,token,name,exp} · 默认约7分钟过期"
        )
        tip.setWordWrap(True)
        tip.setStyleSheet("color:#667;font-size:12px;")
        root.addWidget(tip)
        self._refresh()

    def _refresh(self) -> None:
        srv = get_active_server()
        if srv is not None and srv.running:
            self.status.setText("● Running / 同步中")
            self.status.setStyleSheet("color:#168A3F;font-weight:700;")
            self.endpoint.setText(srv.endpoint)
            self.port.setText(str(srv.port))
            if srv.token:
                self.token.setText(srv.token)
            payload = srv.pairing_qr_text
            self.payload.setText(payload)
            self.qr_label.setPixmap(_qr_pixmap(payload))
        else:
            self.status.setText("○ Stopped")
            self.status.setStyleSheet("color:#888;font-weight:700;")
            preview = f"http://{detect_lan_ip()}:{self.port.text().strip() or DEFAULT_PORT}"
            self.endpoint.setText(preview)
            payload = pairing_payload(
                base_url=preview,
                token=self.token.text().strip(),
                name="CNKH-PC",
                ttl_seconds=self._ttl_seconds() if hasattr(self, "ttl") else 420,
            )
            self.payload.setText(payload + "\n(启动后可扫)")
            self.qr_label.setPixmap(_qr_pixmap(payload))

    def start_server(self) -> None:
        try:
            port = int(self.port.text().strip() or DEFAULT_PORT)
        except ValueError:
            QMessageBox.warning(self, "LAN Sync", "无效端口")
            return
        token = self.token.text().strip()
        if not token:
            token = secrets.token_hex(3)  # short optional default
            self.token.setText(token)
        try:
            srv = start_global_server(self.database, port=port, token=token, name="CNKH-PC")
            srv.refresh_pairing_qr(ttl_seconds=self._ttl_seconds())
            self._refresh()
        except Exception as exc:
            QMessageBox.critical(self, "LAN Sync", str(exc))

    def _ttl_seconds(self) -> int:
        try:
            mins = int(float(self.ttl.text().strip() or "7"))
        except ValueError:
            mins = 7
        mins = max(5, min(10, mins))
        return mins * 60

    def refresh_qr(self) -> None:
        srv = get_active_server()
        if srv is None or not srv.running:
            QMessageBox.information(self, "LAN Sync", "请先启动同步服务")
            return
        payload = srv.refresh_pairing_qr(ttl_seconds=self._ttl_seconds())
        self.payload.setText(payload)
        self.qr_label.setPixmap(_qr_pixmap(payload))

    def stop_server(self) -> None:
        stop_global_server()
        self._refresh()


def open_sync_pair_dialog(parent, database: Database) -> None:
    SyncPairDialog(database, parent).exec()
