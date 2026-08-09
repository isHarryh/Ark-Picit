"""Dialog for editing a painting's name and description."""

from PySide6.QtWidgets import QHBoxLayout

from qfluentwidgets import BodyLabel, LineEdit, MessageBoxBase, SubtitleLabel, SwitchButton

from src.core.storage import StoredPic

_NAME_MAX_LENGTH = 255
_DESCRIPTION_MAX_LENGTH = 255


class RenameDialog(MessageBoxBase):
    """Edit a painting's name and description, optionally refreshing the saved time.

    Args:
        stored: The painting whose metadata is being edited.
        parent: Parent widget.
    """

    def __init__(self, stored: StoredPic, parent=None):
        super().__init__(parent)
        self.widget.setMinimumWidth(420)
        self.viewLayout.setSpacing(12)
        self.viewLayout.addWidget(SubtitleLabel("Rename painting"))

        self.nameEdit = LineEdit(self)
        self.nameEdit.setText(stored.name)
        self.nameEdit.setPlaceholderText("Painting name")
        self.nameEdit.setMaxLength(_NAME_MAX_LENGTH)
        self.descEdit = LineEdit(self)
        self.descEdit.setText(stored.description)
        self.descEdit.setPlaceholderText("Optional description")
        self.descEdit.setMaxLength(_DESCRIPTION_MAX_LENGTH)

        switch_row = QHBoxLayout()
        switch_row.setSpacing(8)
        switch_row.addWidget(BodyLabel("Update last saved time"))
        self.timeSwitch = SwitchButton()
        self.timeSwitch.setChecked(True)
        switch_row.addWidget(self.timeSwitch)
        switch_row.addStretch()

        self.viewLayout.addWidget(BodyLabel("Name:"))
        self.viewLayout.addWidget(self.nameEdit)
        self.viewLayout.addWidget(BodyLabel("Description:"))
        self.viewLayout.addWidget(self.descEdit)
        self.viewLayout.addLayout(switch_row)

        self.yesButton.setText("Save")
        self.cancelButton.setText("Cancel")

    @property
    def new_name(self) -> str:
        """Return the entered name, falling back to ``"Untitled"`` when blank."""
        return self.nameEdit.text().strip() or "Untitled"

    @property
    def new_description(self) -> str:
        """Return the entered description (may be empty)."""
        return self.descEdit.text().strip()

    @property
    def update_time(self) -> bool:
        """Return whether the saved time should be refreshed."""
        return self.timeSwitch.isChecked()
