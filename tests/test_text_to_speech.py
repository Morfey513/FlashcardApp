from src.utils import text_to_speech as tts_module


class Signal:
    def __init__(self):
        self.callback = None

    def connect(self, callback):
        self.callback = callback


class FakeSpeech:
    engines = ["sapi"]
    initial_state = "ready"

    class State:
        Error = "error"
        Speaking = "speaking"
        Ready = "ready"

    @classmethod
    def availableEngines(cls):
        return list(cls.engines)

    def __init__(self, engine, parent=None):
        self.engine = engine
        self.parent = parent
        self.current_state = self.initial_state
        self.stateChanged = Signal()
        self.said = []
        self.stop_calls = 0

    def state(self):
        return self.current_state

    def errorString(self):
        return "engine failed"

    def say(self, text):
        self.said.append(text)

    def stop(self):
        self.stop_calls += 1
        self.current_state = self.State.Ready


class ImmediateTimer:
    calls = []

    @classmethod
    def singleShot(cls, delay, callback):
        cls.calls.append(delay)
        callback()


def install_fakes(monkeypatch, engines=None, state="ready"):
    FakeSpeech.engines = ["sapi"] if engines is None else engines
    FakeSpeech.initial_state = state
    ImmediateTimer.calls = []
    monkeypatch.setattr(tts_module, "QTextToSpeech", FakeSpeech)
    monkeypatch.setattr(tts_module, "QTimer", ImmediateTimer)


def test_tts_reports_unavailable_and_failed_engines(monkeypatch):
    install_fakes(monkeypatch, engines=[])
    unavailable = tts_module.TextToSpeech()
    assert unavailable.is_available is False
    assert unavailable.engine_name == ""
    assert unavailable.speak("hello") is False
    assert unavailable.speak_sequence(["hello"]) is False

    install_fakes(monkeypatch, state=FakeSpeech.State.Error)
    failed = tts_module.TextToSpeech()
    assert failed.is_available is False
    assert failed.engine_name == ""


def test_tts_normalizes_single_text_and_stops_active_speech(monkeypatch):
    install_fakes(monkeypatch)
    tts = tts_module.TextToSpeech()
    callback = lambda: None

    assert tts.speak("  hello\n   world  ", on_finished=callback) is True
    assert tts._speech.said == ["hello world"]
    assert tts._completion_callback is callback
    assert tts.speak("   ") is False

    tts._speech.current_state = FakeSpeech.State.Speaking
    sequence_id = tts._sequence_id
    tts.stop()
    assert tts._speech.stop_calls == 1
    assert tts._sequence_id == sequence_id + 1
    assert tts._pending_utterances == []
    assert tts._completion_callback is None


def test_tts_sequence_pauses_completes_and_ignores_stale_work(monkeypatch):
    install_fakes(monkeypatch)
    tts = tts_module.TextToSpeech()
    completed = []

    assert tts.speak_sequence([" first ", "", "second"], pause_ms=-10) is True
    sequence_id = tts._sequence_id
    assert tts._speech.said == ["first"]
    assert tts._pause_ms == 0

    tts._continue_sequence(FakeSpeech.State.Speaking)
    assert tts._speech.said == ["first"]
    tts._continue_sequence(FakeSpeech.State.Ready)
    assert tts._speech.said == ["first", "second"]

    tts._completion_callback = lambda: completed.append(True)
    tts._continue_sequence(FakeSpeech.State.Ready)
    assert completed == [True]
    assert ImmediateTimer.calls == [0, 0]

    tts._speak_next(sequence_id - 1)
    assert tts._speech.said == ["first", "second"]
    assert tts.speak_sequence(["", "   "]) is False
