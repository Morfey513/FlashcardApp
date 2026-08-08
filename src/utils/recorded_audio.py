"""Sequential playback of optional recorded flashcard audio."""

import logging
from pathlib import Path

from PyQt6.QtCore import QObject, QTimer, QUrl
from PyQt6.QtMultimedia import QAudioOutput, QMediaPlayer


logger = logging.getLogger(__name__)


class RecordedAudioPlayer(QObject):
    """Play recorded fields in order and fall back to local TTS per field."""

    def __init__(self, text_to_speech, parent=None):
        super().__init__(parent)
        self.text_to_speech = text_to_speech
        self.audio_output = QAudioOutput(self)
        self.player = QMediaPlayer(self)
        self.player.setAudioOutput(self.audio_output)
        self.player.mediaStatusChanged.connect(self._on_media_status_changed)
        self.player.errorOccurred.connect(self._on_error)
        self._items = []
        self._pause_ms = 0

    def play_sequence(self, items, pause_ms=500):
        """Play ``(path, text)`` fields, using TTS if a recording is missing."""
        self.stop()
        self._items = list(items)
        self._pause_ms = max(0, pause_ms)
        self._play_next()

    def stop(self):
        self._items = []
        self.player.stop()
        self.text_to_speech.stop()

    def _play_next(self):
        while self._items:
            path_value, text = self._items.pop(0)
            path = Path(path_value) if path_value else None
            if path and path.is_file():
                logger.info("Playing recorded flashcard audio: %s", path.name)
                self.player.setSource(QUrl.fromLocalFile(str(path)))
                self.player.play()
                return
            if str(text or "").strip() and self.text_to_speech.is_available:
                logger.debug("No recorded audio for flashcard field; using TTS")
                self.text_to_speech.speak(text, on_finished=self._continue_after_pause)
                return
        self.player.stop()

    def _continue_after_pause(self):
        QTimer.singleShot(self._pause_ms, self._play_next)

    def _on_media_status_changed(self, status):
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self._continue_after_pause()

    def _on_error(self, error, error_string):
        if error != QMediaPlayer.Error.NoError:
            logger.warning("Recorded audio playback failed: %s", error_string)
            self._continue_after_pause()
