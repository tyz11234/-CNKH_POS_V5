from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


class Sidebar(QFrame):
    page_selected = Signal(str)

    def __init__(
        self,
        items: list[tuple[str, str]],
        parent: QWidget | None = None,
        *,
        display_name: str = "Admin",
        role_text: str = "管理员",
    ):
        super().__init__(parent)
        self.setObjectName("Sidebar")
        self.setFixedWidth(188)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 24, 16, 18)
        layout.setSpacing(7)

        brand = QVBoxLayout()
        brand.setContentsMargins(8, 0, 4, 20)
        title = QLabel("◆ CNKH")
        title.setObjectName("BrandTitle")
        subtitle = QLabel("HARDWARE POS")
        subtitle.setObjectName("BrandSubtitle")
        version = QLabel("V5.0")
        version.setObjectName("BrandVersion")
        version.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        brand.addWidget(title)
        brand.addWidget(subtitle)
        brand.addWidget(version)
        layout.addLayout(brand)

        group = QButtonGroup(self)
        group.setExclusive(True)
        for index, (key, text) in enumerate(items):
            button = QPushButton(f"  {text}")
            button.setObjectName("SidebarButton")
            button.setProperty("pageKey", key)
            button.setCheckable(True)
            button.clicked.connect(
                lambda checked=False, page=key: self.page_selected.emit(page)
            )
            group.addButton(button)
            layout.addWidget(button)
            if index == 0:
                button.setChecked(True)
        layout.addStretch(1)

        user = QFrame()
        user_layout = QHBoxLayout(user)
        user_layout.setContentsMargins(6, 12, 2, 0)
        avatar = QLabel("●")
        avatar.setStyleSheet("color: white; font-size: 26px;")
        labels = QVBoxLayout()
        name = QLabel(display_name)
        name.setStyleSheet("color: white; font-weight: 700;")
        role = QLabel(f"● {role_text}")
        role.setStyleSheet("color: #52D273; font-size: 11px;")
        labels.addWidget(name)
        labels.addWidget(role)
        user_layout.addWidget(avatar)
        user_layout.addLayout(labels)
        layout.addWidget(user)
