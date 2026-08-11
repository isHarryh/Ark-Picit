"""Dialog for displaying and entering ArkPicCode text."""

from PySide6.QtGui import QGuiApplication
from qfluentwidgets import (
    CheckBox,
    MessageBoxBase,
    SubtitleLabel,
    TextEdit,
)


class CodeDialog(MessageBoxBase):
    """Dialog for copy/export or paste/import of ArkPicCode text.

    Args:
        code: The code string (empty in import mode).
        parent: Parent widget.
        readonly: True for export mode (show code + copy button),
                  False for import mode (editable text + import button).
        include_metadata_default: In export mode, whether the
            "include name & description" checkbox is checked by default.
    """

    def __init__(
        self,
        code: str,
        parent=None,
        readonly: bool = True,
        include_metadata_default: bool = True,
    ):
        self._readonly = readonly
        super().__init__(parent)
        self._build_ui(code, include_metadata_default)

    def _build_ui(self, code: str, include_meta: bool) -> None:
        self.widget.setMinimumWidth(520)

        # Use MessageBoxBase's native viewLayout (no custom margin overrides)
        layout = self.viewLayout
        layout.setSpacing(12)

        # Title — use SubtitleLabel for proper native sizing
        if self._readonly:
            layout.addWidget(SubtitleLabel(self.tr("CopyCodeTitle")))
        else:
            layout.addWidget(SubtitleLabel(self.tr("InputCodeTitle")))

        # Text area
        self.textEdit = TextEdit()
        self.textEdit.setText(code)
        self.textEdit.setReadOnly(self._readonly)
        self.textEdit.setMinimumHeight(140)
        if not self._readonly:
            self.textEdit.setPlaceholderText(self.tr("PasteCodePlaceholder"))
        layout.addWidget(self.textEdit)

        # Export mode: checkbox to include metadata
        self.metaCheckbox: CheckBox | None = None
        if self._readonly:
            self.metaCheckbox = CheckBox(self.tr("IncludeMetadataLabel"))
            self.metaCheckbox.setChecked(include_meta)
            layout.addWidget(self.metaCheckbox)
            self.yesButton.setText(self.tr("CopyButton"))
            self.cancelButton.setText(self.tr("CloseButton"))
        else:
            self.yesButton.setText(self.tr("ImportButton"))
            self.cancelButton.setText(self.tr("CancelButton"))

    def accept(self) -> None:
        """In export mode, copy to clipboard before accepting."""
        if self._readonly:
            self._copy()
        super().accept()

    def _copy(self) -> None:
        clipboard = QGuiApplication.clipboard()
        clipboard.setText(self.textEdit.toPlainText().strip())

    @property
    def include_metadata(self) -> bool:
        """Whether the user checked 'include name and description'."""
        return self.metaCheckbox is not None and self.metaCheckbox.isChecked()

    def get_text(self) -> str:
        return self.textEdit.toPlainText().strip()
