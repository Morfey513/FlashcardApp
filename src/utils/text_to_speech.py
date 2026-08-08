"""Small wrapper around Qt's local text-to-speech engine."""

import logging

from PyQt6.QtCore import QTimer
from PyQt6.QtTextToSpeech import QTextToSpeech


logger = logging.getLogger(__name__)


class TextToSpeech:
    """Provide offline speech without coupling UI widgets to a platform engine."""

    def __init__(self, parent=None):
        engines = QTextToSpeech.availableEngines()
        # SAPI is Windows' built-in offline engine. The mock engine is useful
        # for Qt testing, but is not presented as usable speech to learners.
        engine = next((name for name in ("sapi", "winrt") if name in engines), None)
        self._speech = QTextToSpeech(engine, parent) if engine else None
        self.engine_name = engine or ""
        self._pending_utterances = []
        self._pause_ms = 0
        self._sequence_id = 0
        self._completion_callback = None

        if self._speech and self._speech.state() == QTextToSpeech.State.Error:
            logger.warning(
                "Text-to-speech engine '%s' failed to initialize: %s",
                engine,
                self._speech.errorString(),
            )
            self._speech = None
            self.engine_name = ""
        elif self._speech:
            self._speech.stateChanged.connect(self._continue_sequence)
            logger.info("Text-to-speech engine '%s' is ready", engine)
        else:
            logger.warning("No usable local text-to-speech engine is available")

    @property
    def is_available(self):
        return self._speech is not None

    def speak(self, text, on_finished=None):
        """Stop any prior utterance and read normalized visible-card text."""
        normalized = " ".join(str(text or "").split())
        if not normalized:
            logger.debug("Skipped speech request for empty text")
            return False
        if not self._speech:
            logger.warning("Skipped speech request because TTS is unavailable")
            return False

        self.stop()
        self._completion_callback = on_finished
        self._speech.say(normalized)
        logger.info("Requested TTS using '%s' for %d characters", self.engine_name, len(normalized))
        return True

    def speak_sequence(self, texts, pause_ms=500):
        """Read non-empty utterances sequentially with a pause between them."""
        utterances = [" ".join(str(text or "").split()) for text in texts]
        utterances = [text for text in utterances if text]
        if not utterances:
            return False
        if not self._speech:
            logger.warning("Skipped speech sequence because TTS is unavailable")
            return False

        self.stop()
        self._sequence_id += 1
        self._pending_utterances = utterances
        self._pause_ms = max(0, pause_ms)
        self._speak_next(self._sequence_id)
        logger.info(
            "Requested %d-part TTS sequence using '%s'", len(utterances), self.engine_name
        )
        return True

    def stop(self):
        self._sequence_id += 1
        self._pending_utterances = []
        self._completion_callback = None
        if self._speech and self._speech.state() == QTextToSpeech.State.Speaking:
            self._speech.stop()

    def _speak_next(self, sequence_id):
        if sequence_id != self._sequence_id or not self._pending_utterances:
            return
        self._speech.say(self._pending_utterances.pop(0))

    def _continue_sequence(self, state):
        if state != QTextToSpeech.State.Ready or self._speech.state() != QTextToSpeech.State.Ready:
            return
        if not self._pending_utterances:
            callback = self._completion_callback
            self._completion_callback = None
            if callback:
                QTimer.singleShot(0, callback)
            return
        sequence_id = self._sequence_id
        QTimer.singleShot(
            self._pause_ms,
            lambda: self._speak_next(sequence_id),
        )
