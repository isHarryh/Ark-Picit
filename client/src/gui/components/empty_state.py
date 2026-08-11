"""Centered empty/error state widget for pages.

Shows a large icon, a title, an optional small hint and an optional action
button, vertically centered in the available space. Used for gallery /
explore empty states and explore error states.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QSizePolicy, QVBoxLayout, QWidget
from qfluentwidgets import (
    CaptionLabel,
    IconWidget,
    PrimaryPushButton,
    SubtitleLabel,
)
from qfluentwidgets import FluentIcon as FIF


class EmptyStateWidget(QWidget):
    """Vertical centered empty-state content: icon, title, hint, button."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.addStretch(1)

        self.iconWidget = IconWidget(FIF.ALBUM, self)
        self.iconWidget.setFixedSize(80, 80)
        layout.addWidget(self.iconWidget, 0, Qt.AlignmentFlag.AlignHCenter)

        layout.addSpacing(12)

        self.titleLabel = SubtitleLabel(self)
        self.titleLabel.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.titleLabel)

        self.hintLabel = CaptionLabel(self)
        self.hintLabel.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hintLabel.setVisible(False)
        layout.addWidget(self.hintLabel)

        layout.addSpacing(12)

        self.actionBtn = PrimaryPushButton(self)
        self.actionBtn.setVisible(False)
        layout.addWidget(self.actionBtn, 0, Qt.AlignmentFlag.AlignHCenter)

        layout.addStretch(1)

    def set_state(
        self,
        icon,
        title: str,
        hint: str = "",
        button_text: str = "",
        button_icon=None,
    ) -> None:
        """Configure the widget content; empty strings hide the optional parts."""
        self.iconWidget.setIcon(icon)
        self.titleLabel.setText(title)
        self.hintLabel.setText(hint)
        self.hintLabel.setVisible(bool(hint))
        self.actionBtn.setText(button_text)
        self.actionBtn.setIcon(button_icon or FIF.EDIT)
        self.actionBtn.setVisible(bool(button_text))
