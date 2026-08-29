from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtGui import QPainter, QPalette
from PyQt6.QtWidgets import QLabel


class ScrollingLabel(QLabel):
    """Single-line label that scrolls long text inside its available width."""

    def __init__(self, text="", parent=None):
        super().__init__(parent)
        self._full_text = text or ""
        self._offset = 0
        self._pause_ticks = 8
        self.setWordWrap(False)
        super().setText(self._full_text)
        self._timer = QTimer(self)
        self._timer.setInterval(70)
        self._timer.timeout.connect(self._advance)

    def setText(self, text):
        self._full_text = text or ""
        self._offset = 0
        self._pause_ticks = 8
        super().setText(self._full_text)
        self._update_scrolling()
        self.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_scrolling()

    def leaveEvent(self, event):
        self._offset = 0
        self._pause_ticks = 8
        self.update()
        super().leaveEvent(event)

    def _update_scrolling(self):
        if self.fontMetrics().horizontalAdvance(self._full_text) > self.width() - 4:
            self._timer.start()
        else:
            self._timer.stop()

    def _advance(self):
        if self._pause_ticks:
            self._pause_ticks -= 1
            return
        text_width = self.fontMetrics().horizontalAdvance(self._full_text)
        if text_width <= self.width() - 4:
            self._timer.stop()
            return
        self._offset += 2
        if self._offset > text_width + 24:
            self._offset = 0
            self._pause_ticks = 8
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setPen(self.palette().color(QPalette.ColorRole.Text))
        painter.setFont(self.font())
        clip = self.rect().adjusted(2, 0, -2, 0)
        painter.setClipRect(clip)
        metrics = self.fontMetrics()
        baseline = (self.height() + metrics.ascent() - metrics.descent()) // 2
        text_width = metrics.horizontalAdvance(self._full_text)
        if text_width <= clip.width():
            # Use QLabel's normal stylesheet-aware renderer when scrolling is
            # unnecessary. This preserves the configured foreground color.
            super().paintEvent(event)
        else:
            x = clip.left() - self._offset
            painter.drawText(x, baseline, self._full_text)
            painter.drawText(x + text_width + 24, baseline, self._full_text)
