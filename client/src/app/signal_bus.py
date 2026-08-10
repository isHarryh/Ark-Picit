"""Global signal bus for cross-component communication."""

from PySide6.QtCore import QObject, Signal


class SignalBus(QObject):
    """Application-wide signal hub."""

    # Painting
    newPainting = Signal()  # start a fresh canvas
    editPainting = Signal(str)  # edit a stored painting by id
    paintingSaved = Signal()  # gallery should refresh
    importCode = Signal(str)  # load an ArkPicCode text into the editor


signalBus = SignalBus()
