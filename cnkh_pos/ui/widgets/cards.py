from __future__ import annotations

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QLabel,
    QVBoxLayout,
    QWidget,
)


class Card(QFrame):
    def __init__(self, parent: QWidget | None = None, *, shadow: bool = True):
        super().__init__(parent)
        self.setObjectName("Card")
        if shadow:
            effect = QGraphicsDropShadowEffect(self)
            effect.setBlurRadius(22)
            effect.setOffset(0, 5)
            effect.setColor(QColor(20, 42, 70, 24))
            self.setGraphicsEffect(effect)


class StatCard(Card):
    def __init__(
        self,
        title: str,
        value: str,
        detail: str,
        *,
        tone: str = "primary",
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setObjectName("StatCard")
        self.setMinimumHeight(112)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 13)
        layout.setSpacing(4)
        title_label = QLabel(title)
        title_label.setObjectName("StatLabel")
        self.value_label = QLabel(value)
        self.value_label.setObjectName(
            {
                "success": "StatValueSuccess",
                "warning": "StatValueWarning",
                "danger": "StatValueDanger",
            }.get(tone, "StatValue")
        )
        self.detail_label = QLabel(detail)
        self.detail_label.setObjectName("Muted")
        layout.addWidget(title_label)
        layout.addWidget(self.value_label)
        layout.addWidget(self.detail_label)
