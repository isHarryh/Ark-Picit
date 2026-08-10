"""Create / edit page: the pixel-art painting workspace."""

import logging
import threading

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtGui import QAction, QKeySequence, QShortcut
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    ComboBox,
    InfoBar,
    InfoBarPosition,
    LineEdit,
    MessageBox,
    PrimaryPushButton,
    PrimarySplitPushButton,
    PushButton,
    RoundMenu,
    SplitPushButton,
    StrongBodyLabel,
    ToolButton,
)
from qfluentwidgets import (
    FluentIcon as FIF,
)

from src.app.signal_bus import signalBus
from src.core import ArkPic, ArkPicRule, CodeError, decode, encode, storage
from src.core.rulesets import ALL_RULESETS, RuleCN2026Aug
from src.gui.components.base_page import BasePage
from src.gui.components.color_palette import ColorPalette
from src.gui.components.pixel_canvas import PixelCanvas

logger = logging.getLogger(__name__)


class CreatePage(BasePage):
    """Page for creating, editing, importing and exporting paintings."""

    _canvasImported = Signal(object)  # ArkPic read from the game
    _canvasImportFailed = Signal(str)  # error message

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rule: ArkPicRule = RuleCN2026Aug
        self._pic: ArkPic = ArkPic(self._rule)
        self._stored_id: str | None = None  # None = unsaved new painting
        self._saved_snapshot: list[list[int]] | None = None  # last saved/loaded grid
        self._saved_name: str = ""  # last saved/loaded name
        self._saved_description: str = ""  # last saved/loaded description
        self._canvas: PixelCanvas | None = None
        self._palette: ColorPalette | None = None
        self._build_ui()
        self._connect_signals()
        self._canvasImported.connect(self._apply_imported_canvas)
        self._canvasImportFailed.connect(self._show_import_error)
        self._new_painting()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        # --- Action bar (top) ---
        actions = QHBoxLayout()
        self.btnNew = PushButton(FIF.ADD, "New")
        self.btnSave = PrimarySplitPushButton(FIF.SAVE, "Save", self)
        self._setup_save_menu()
        self.btnExport = PushButton(FIF.SHARE, "Export Code")
        self.btnImport = SplitPushButton(FIF.DOWNLOAD, "Import", self)
        self._setup_import_menu()
        self.btnSmart = PrimaryPushButton(FIF.PHOTO, "Smart Create")
        self.btnGamePaint = PrimaryPushButton(FIF.BRUSH, "Auto Paint in Game")
        actions.addWidget(self.btnNew)
        actions.addWidget(self.btnSmart)
        actions.addWidget(self.btnSave)
        actions.addWidget(self.btnExport)
        actions.addWidget(self.btnImport)
        actions.addStretch()
        actions.addWidget(self.btnGamePaint)
        self.viewLayout.addLayout(actions)

        # --- Form (Name/Description, grid-aligned) ---
        form = QGridLayout()
        form.setHorizontalSpacing(8)
        form.setVerticalSpacing(8)

        lbl_name = BodyLabel("Name:")
        lbl_name.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.nameEdit = LineEdit()
        self.nameEdit.setPlaceholderText("Painting name")
        self.nameEdit.setMaxLength(255)

        lbl_ruleset = BodyLabel("Ruleset:")
        lbl_ruleset.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.ruleCombo = ComboBox()
        for name, rule in ALL_RULESETS.items():
            self.ruleCombo.addItem(f"{name}  ({rule.width}x{rule.height})", userData=name)
        self.ruleCombo.currentIndexChanged.connect(self._on_ruleset_changed)

        lbl_desc = BodyLabel("Description:")
        lbl_desc.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.descEdit = LineEdit()
        self.descEdit.setPlaceholderText("Optional description")
        self.descEdit.setMaxLength(255)

        form.addWidget(lbl_name, 0, 0)
        form.addWidget(self.nameEdit, 0, 1)
        form.addWidget(lbl_ruleset, 0, 2)
        form.addWidget(self.ruleCombo, 0, 3)
        form.addWidget(lbl_desc, 1, 0)
        form.addWidget(self.descEdit, 1, 1, 1, 3)
        form.setColumnStretch(1, 1)
        form.setColumnStretch(3, 0)
        self.viewLayout.addLayout(form)

        # --- Tool panel + Canvas + Palette ---
        middle = QHBoxLayout()

        # Tool panel (left)
        tool_panel = QWidget()
        tool_layout = QVBoxLayout(tool_panel)
        # Match palette's margins/spacing for visual alignment
        tool_layout.setContentsMargins(0, 0, 4, 0)
        tool_layout.setSpacing(8)

        tool_title = StrongBodyLabel("Tools")
        tool_layout.addWidget(tool_title)

        self.toolPaint = ToolButton(FIF.PENCIL_INK)
        self.toolPaint.setCheckable(True)
        self.toolPaint.setChecked(True)

        self.toolFill = ToolButton(FIF.BACKGROUND_FILL)
        self.toolFill.setCheckable(True)

        self.toolUndo = ToolButton(FIF.RETURN)
        self.toolUndo.setEnabled(False)

        self.toolRedo = ToolButton(FIF.RIGHT_ARROW)
        self.toolRedo.setEnabled(False)

        # Icon buttons: 2 per row
        icon_row_1 = QHBoxLayout()
        icon_row_1.setSpacing(4)
        icon_row_1.addWidget(self.toolPaint)
        icon_row_1.addWidget(self.toolFill)
        tool_layout.addLayout(icon_row_1)

        icon_row_2 = QHBoxLayout()
        icon_row_2.setSpacing(4)
        icon_row_2.addWidget(self.toolUndo)
        icon_row_2.addWidget(self.toolRedo)
        tool_layout.addLayout(icon_row_2)

        tool_layout.addSpacing(6)

        self.toolClear = PushButton(FIF.DELETE, "Clear")
        self.toolClear.clicked.connect(self._on_clear)
        tool_layout.addWidget(self.toolClear)

        tool_layout.addStretch()
        middle.addWidget(tool_panel, 0)

        # Canvas (center, fills available space)
        canvas_container = QWidget()
        canvas_layout = QVBoxLayout(canvas_container)
        canvas_layout.setContentsMargins(0, 0, 0, 0)
        self.canvasHolder = canvas_layout
        middle.addWidget(canvas_container, 1)

        # Palette (right)
        self.paletteHolder = QVBoxLayout()
        middle.addLayout(self.paletteHolder, 0)
        self.viewLayout.addLayout(middle, 1)

        self.viewLayout.addStretch()

    def _connect_signals(self) -> None:
        self.btnNew.clicked.connect(self._on_new)
        self.btnSave.clicked.connect(self._on_save)
        self.btnExport.clicked.connect(self._on_export_code)
        self.btnImport.clicked.connect(self._on_import_code)
        self.btnSmart.clicked.connect(self._on_smart_create)
        self.btnGamePaint.clicked.connect(self._on_game_paint)
        self.toolPaint.clicked.connect(self._on_tool_paint)
        self.toolFill.clicked.connect(self._on_tool_fill)
        self.toolUndo.clicked.connect(self._on_undo)
        self.toolRedo.clicked.connect(self._on_redo)
        self.nameEdit.textChanged.connect(self._update_save_state)
        self.descEdit.textChanged.connect(self._update_save_state)

        # Shortcuts
        self.shortcutUndo = QShortcut(QKeySequence("Ctrl+Z"), self)
        self.shortcutUndo.activated.connect(self._on_undo)
        self.shortcutRedo = QShortcut(QKeySequence("Ctrl+Y"), self)
        self.shortcutRedo.activated.connect(self._on_redo)

        signalBus.newPainting.connect(self._new_painting)
        signalBus.editPainting.connect(self._load_by_id)
        signalBus.importCode.connect(self._import_code_text)

    def _setup_save_menu(self) -> None:
        """Attach the Save As action to the Save button's drop-down menu."""
        action = QAction(FIF.SAVE_AS.icon(), "Save As", self)
        action.triggered.connect(self._on_save_as)
        menu = RoundMenu(parent=self)
        menu.addAction(action)
        self.btnSave.setFlyout(menu)

    def _setup_import_menu(self) -> None:
        """Attach the import actions to the Import button's drop-down menu."""
        menu = RoundMenu(parent=self)
        menu.addAction(
            QAction(FIF.CODE.icon(), "Import From Code", self, triggered=self._on_import_code)
        )
        menu.addAction(
            QAction(
                FIF.BRUSH.icon(),
                "Import From Game Canvas",
                self,
                triggered=self._on_import_game_canvas,
            )
        )
        self.btnImport.setFlyout(menu)

    # ------------------------------------------------------------------
    # Canvas / palette lifecycle
    # ------------------------------------------------------------------

    def _rebuild_canvas(self) -> None:
        """Recreate the canvas widget (dynamically sized)."""
        while self.canvasHolder.count():
            item = self.canvasHolder.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self._canvas = PixelCanvas(self._pic)
        self._canvas.contentChanged.connect(self._update_save_state)
        self._canvas.undoAvailabilityChanged.connect(self.toolUndo.setEnabled)
        self._canvas.redoAvailabilityChanged.connect(self.toolRedo.setEnabled)
        self.canvasHolder.addWidget(self._canvas)
        self._update_save_state()

    def _has_unsaved_changes(self) -> bool:
        """Return whether the painting or its metadata differs from the last
        saved/loaded version.

        A never-saved painting counts as having unsaved changes, except for
        a blank canvas: empty name/description with every cell at the
        default color is treated as a pristine, saved state.
        """
        if self._saved_snapshot is None:
            if (
                not self.nameEdit.text().strip()
                and not self.descEdit.text().strip()
                and all(c == self._rule.default_color_id for c in self._pic.flat)
            ):
                return False
            return True
        grid_changed = self._pic.grid != self._saved_snapshot
        meta_changed = (
            self.nameEdit.text().strip() != self._saved_name
            or self.descEdit.text().strip() != self._saved_description
        )
        return grid_changed or meta_changed

    def _update_save_state(self) -> None:
        """Disable Save when there are no unsaved changes; Save As stays available."""
        self.btnSave.button.setEnabled(self._has_unsaved_changes())

    def _rebuild_palette(self) -> None:
        # Remove old palette
        while self.paletteHolder.count():
            item = self.paletteHolder.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._palette = ColorPalette(self._rule)
        self._palette.colorSelected.connect(self._on_color_selected)
        self.paletteHolder.addWidget(self._palette)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _new_painting(self) -> None:
        self._stored_id = None
        self._saved_snapshot = None
        self._saved_name = ""
        self._saved_description = ""
        self._pic = ArkPic(self._rule)
        self.nameEdit.clear()
        self.descEdit.clear()
        self.ruleCombo.setEnabled(True)
        self._rebuild_canvas()
        self._rebuild_palette()
        self._on_color_selected(self._rule.default_color_id)

    def _on_new(self) -> None:
        """Start a fresh painting, asking for confirmation when unsaved work exists."""
        if self._has_unsaved_changes():
            box = MessageBox(
                "New painting?",
                "The current painting has unsaved changes. "
                "Start a new painting anyway?",
                self.window(),
            )
            box.yesButton.setText("New")
            box.cancelButton.setText("Cancel")
            if not box.exec():
                return
        self._new_painting()

    def _load_by_id(self, pic_id: str) -> None:
        if not self._confirm_overwrite_current():
            return
        stored = storage.load(pic_id)
        if stored is None:
            InfoBar.error("Load failed", f"Painting {pic_id} not found.",
                          parent=self, duration=3000)
            return
        self._stored_id = stored.id
        pic, rule = stored.to_ark_pic()
        self._rule = rule
        self._pic = pic
        self._saved_snapshot = pic.snapshot()
        self._saved_name = stored.name
        self._saved_description = stored.description
        self.nameEdit.setText(stored.name)
        self.descEdit.setText(stored.description)
        # Lock ruleset selector
        self.ruleCombo.setEnabled(False)
        self._rebuild_canvas()
        self._rebuild_palette()
        self._on_color_selected(rule.default_color_id)

    def _on_ruleset_changed(self, index: int) -> None:
        if self._stored_id is not None:
            return  # Can't change ruleset when editing existing
        name = self.ruleCombo.itemData(index)
        if name and name in ALL_RULESETS:
            self._rule = ALL_RULESETS[name]
            self._pic = ArkPic(self._rule)
            self._saved_snapshot = None
            self._rebuild_canvas()
            self._rebuild_palette()
            self._on_color_selected(self._rule.default_color_id)

    def _on_color_selected(self, cid: int) -> None:
        if self._canvas:
            self._canvas.set_tool("paint")
            self._canvas.set_color_id(cid)

    def _on_tool_paint(self) -> None:
        self.toolFill.setChecked(False)
        if self._canvas:
            self._canvas.set_tool("paint")

    def _on_tool_fill(self) -> None:
        self.toolPaint.setChecked(False)
        if self._canvas:
            self._canvas.set_tool("fill")

    def _on_clear(self) -> None:
        if self._canvas:
            self._canvas.clear()

    def _on_undo(self) -> None:
        if self._canvas:
            self._canvas.undo()

    def _on_redo(self) -> None:
        if self._canvas:
            self._canvas.redo()

    def _do_save(self, force_new: bool) -> None:
        name = self.nameEdit.text().strip()
        if not name:
            InfoBar.warning(
                "Name missing",
                "Please enter a name before saving.",
                parent=self, position=InfoBarPosition.TOP, duration=3000,
            )
            return
        desc = self.descEdit.text().strip()

        if force_new or self._stored_id is None:
            stored = storage.StoredPic.from_ark_pic(name, desc, self._pic, self._rule)
        else:
            stored = storage.load(self._stored_id)
            if stored is None:
                stored = storage.StoredPic.from_ark_pic(name, desc, self._pic, self._rule)
            else:
                stored.name = name
                stored.description = desc
                stored.rule_width = self._rule.width
                stored.rule_height = self._rule.height
                stored.rule_colors = list(self._rule.colors)
                stored.rule_default_color_id = self._rule.default_color_id
                stored.pixels = self._pic.flat
                stored.refresh_preview(self._pic)

        storage.save(stored)
        self._stored_id = stored.id
        self._saved_snapshot = self._pic.snapshot()
        self._saved_name = stored.name
        self._saved_description = stored.description
        self._update_save_state()
        self.ruleCombo.setEnabled(False)
        signalBus.paintingSaved.emit()
        InfoBar.success("Saved", f"'{stored.name}' saved to gallery.",
                        parent=self, position=InfoBarPosition.TOP, duration=2000)

    def _on_save(self) -> None:
        self._do_save(force_new=False)

    def _on_save_as(self) -> None:
        self._do_save(force_new=True)

    # ------------------------------------------------------------------
    # Export / Import via ArkPicCode text
    # ------------------------------------------------------------------

    def _on_export_code(self) -> None:
        """Export painting as ArkPicCode text via a dialog."""
        from src.gui.dialogs.code_dialog import CodeDialog

        name = self.nameEdit.text().strip()
        desc = self.descEdit.text().strip()

        try:
            # Generate code without metadata first (checkbox controls inclusion)
            code_with_meta = encode(self._pic, name, desc)
            code_without_meta = encode(self._pic)
        except CodeError as e:
            InfoBar.error("Export failed", str(e), parent=self, duration=3000)
            return

        # Show with metadata by default
        dialog = CodeDialog(code_with_meta, self.window(), readonly=True,
                            include_metadata_default=True)

        # Live-update the text when checkbox toggles
        if dialog.metaCheckbox:
            def _on_toggle(checked: bool):
                dialog.textEdit.setText(code_with_meta if checked else code_without_meta)
            dialog.metaCheckbox.toggled.connect(_on_toggle)

        dialog.exec()

    def _on_import_code(self) -> None:
        """Import painting from ArkPicCode text via a dialog."""
        from src.gui.dialogs.code_dialog import CodeDialog

        dialog = CodeDialog("", self.window(), readonly=False)
        if not dialog.exec():
            return
        code = dialog.get_text().strip()
        if not code:
            return
        self._import_code_text(code)

    def _import_code_text(self, code: str) -> None:
        """Decode *code* and load the painting into the editor."""
        try:
            result = decode(code, self._rule)
        except CodeError as e:
            InfoBar.error("Import failed", str(e), parent=self, duration=3000)
            return

        if not self._confirm_overwrite_current():
            return
        self._pic = result.pic
        self._stored_id = None
        self._saved_snapshot = None
        # Restore metadata only when both fields are present; otherwise the
        # import is a fresh instance and the fields stay empty.
        if not result.name and not result.description:
            self.nameEdit.clear()
            self.descEdit.clear()
        else:
            if result.name:
                self.nameEdit.setText(result.name)
            if result.description:
                self.descEdit.setText(result.description)
        self._rebuild_canvas()
        InfoBar.success("Imported", "Painting loaded from code.",
                        parent=self, duration=2000)

    def _confirm_overwrite_current(self) -> bool:
        """Confirm replacing the current canvas when it has unsaved changes.

        Returns True when the current painting is already saved or when the
        user accepts overwriting it.
        """
        if not self._has_unsaved_changes():
            return True
        box = MessageBox(
            "Overwrite current canvas?",
            "The current painting has unsaved changes. Continue anyway?",
            self.window(),
        )
        box.yesButton.setText("Overwrite")
        box.cancelButton.setText("Cancel")
        return box.exec()

    def _on_import_game_canvas(self) -> None:
        """Read the current in-game canvas and load it into the editor."""
        from src.app.device_manager import deviceManager
        from src.gui.dialogs.device_dialog import browse_and_connect

        device = deviceManager.device
        if device is None:
            browse_and_connect(self.window(), on_connected=self._import_canvas_with)
            return
        self._import_canvas_with(device)

    def _import_canvas_with(self, device) -> None:
        """Start the canvas import in a worker thread."""
        InfoBar.info(
            "Importing", "Reading the in-game canvas...",
            parent=self, position=InfoBarPosition.TOP, duration=2000,
        )
        self.btnImport.button.setEnabled(False)
        threading.Thread(target=self._import_canvas_worker, args=(device,), daemon=True).start()

    def _import_canvas_worker(self, device) -> None:
        from src.auto import Automator
        from src.core.tasks import GameTaskError, read_game_canvas

        try:
            automator = Automator(device)
            pic = read_game_canvas(automator, self._rule)
            self._canvasImported.emit(pic)
        except GameTaskError as exc:
            self._canvasImportFailed.emit(str(exc))
        except Exception as exc:
            logger.exception("In-game canvas import failed")
            self._canvasImportFailed.emit(str(exc))

    @Slot(object)
    def _apply_imported_canvas(self, pic: ArkPic) -> None:
        self.btnImport.button.setEnabled(True)
        if not self._confirm_overwrite_current():
            return
        self._pic = pic
        self._stored_id = None
        self._saved_snapshot = None
        # A canvas read from the game is a fresh instance: clear any metadata.
        self.nameEdit.clear()
        self.descEdit.clear()
        self._rebuild_canvas()
        InfoBar.success("Imported", "Canvas loaded from the game.",
                        parent=self, duration=3000)

    @Slot(str)
    def _show_import_error(self, message: str) -> None:
        self.btnImport.button.setEnabled(True)
        InfoBar.error("Import failed", message, parent=self, duration=5000)

    def _on_smart_create(self) -> None:
        from src.gui.dialogs.smart_create_dialog import SmartCreateDialog

        dialog = SmartCreateDialog(self._rule, self.window())
        if dialog.exec():
            result = dialog.result_pic
            if result is not None:
                self._pic = result
                self._stored_id = None
                self._saved_snapshot = None
                self._rebuild_canvas()
                InfoBar.success(
                    "Smart Create",
                    "Pixel art generated. Adjust as needed, then Save.",
                    parent=self, position=InfoBarPosition.TOP, duration=3000,
                )

    def _on_game_paint(self) -> None:
        """Start the in-game auto painting task and switch to the home page.

        When no device is connected, the browse dialog opens first so the
        user can connect one; the task starts automatically after the
        connection succeeds. The task status is displayed on the home page.
        """
        from src.app.device_manager import deviceManager
        from src.gui.dialogs.device_dialog import browse_and_connect

        device = deviceManager.device
        if device is None:
            browse_and_connect(self.window(), on_connected=self._start_game_paint)
            return
        self._start_game_paint(device)

    def _start_game_paint(self, device) -> None:
        """Switch to the home page and start the paint task on *device*."""
        from src.core.tasks import gameTask

        window = self.window()
        window.switchTo(window.homePage)
        gameTask.start(device, self._rule, self._pic)
