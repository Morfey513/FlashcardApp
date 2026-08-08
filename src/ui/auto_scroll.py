"""Browser-style middle-click auto-scroll for scrollable PyQt content."""

from PyQt6.QtCore import QEvent, QTimer, Qt
from PyQt6.QtWidgets import QScrollArea, QTextBrowser, QWidget


class _AutoScrollSupport:
    """Shared event handling for scroll areas whose child widgets eat clicks."""

    def _init_auto_scroll(self):
        self._origin = self._position = None
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._scroll_step)
        self.viewport().setMouseTracking(True)
        self.viewport().installEventFilter(self)

    def track_auto_scroll_content(self, content: QWidget):
        """Track a content widget and its rows/buttons after each re-render."""
        content.setMouseTracking(True)
        content.installEventFilter(self)
        for child in content.findChildren(QWidget):
            child.setMouseTracking(True)
            child.installEventFilter(self)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.MiddleButton:
            if self._timer.isActive():
                self.stop_auto_scroll()
            else:
                self._origin = self._position = event.globalPosition().toPoint()
                self._timer.start()
                self.viewport().setCursor(Qt.CursorShape.SizeVerCursor)
            return True
        if event.type() == QEvent.Type.MouseMove and self._timer.isActive():
            self._position = event.globalPosition().toPoint()
            return True
        if event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape and self._timer.isActive():
            self.stop_auto_scroll()
            return True
        return super().eventFilter(watched, event)

    def stop_auto_scroll(self):
        self._timer.stop()
        self._origin = self._position = None
        self.viewport().unsetCursor()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape and self._timer.isActive():
            self.stop_auto_scroll()
            event.accept()
            return
        super().keyPressEvent(event)

    def _scroll_step(self):
        if not self._origin or not self._position:
            return
        distance = self._position.y() - self._origin.y()
        if abs(distance) >= 8:
            bar = self.verticalScrollBar()
            bar.setValue(bar.value() + max(-30, min(30, distance // 10)))


class AutoScrollArea(_AutoScrollSupport, QScrollArea):
    """QScrollArea with browser-style middle-click auto-scroll."""

    def __init__(self, parent=None):
        QScrollArea.__init__(self, parent)
        self._init_auto_scroll()


class AutoScrollTextBrowser(_AutoScrollSupport, QTextBrowser):
    """QTextBrowser with the same middle-click auto-scroll behaviour."""

    def __init__(self, parent=None):
        QTextBrowser.__init__(self, parent)
        self._init_auto_scroll()
