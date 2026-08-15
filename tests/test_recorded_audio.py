from src.utils import recorded_audio as audio_module


class Signal:
    def __init__(self):
        self.callback = None

    def connect(self, callback):
        self.callback = callback


class FakeAudioOutput:
    def __init__(self, parent=None):
        self.parent = parent


class FakePlayer:
    class MediaStatus:
        EndOfMedia = "end"

    class Error:
        NoError = "none"
        ResourceError = "resource"

    def __init__(self, parent=None):
        self.parent = parent
        self.mediaStatusChanged = Signal()
        self.errorOccurred = Signal()
        self.output = None
        self.source = None
        self.play_calls = 0
        self.stop_calls = 0

    def setAudioOutput(self, output):
        self.output = output

    def setSource(self, source):
        self.source = source

    def play(self):
        self.play_calls += 1

    def stop(self):
        self.stop_calls += 1


class FakeUrl:
    @staticmethod
    def fromLocalFile(path):
        return f"local:{path}"


class ImmediateTimer:
    calls = []

    @classmethod
    def singleShot(cls, delay, callback):
        cls.calls.append(delay)
        callback()


class FakeTTS:
    def __init__(self, available=True):
        self.is_available = available
        self.spoken = []
        self.stop_calls = 0
        self.callback = None

    def speak(self, text, on_finished=None):
        self.spoken.append(text)
        self.callback = on_finished
        return True

    def stop(self):
        self.stop_calls += 1


def make_player(monkeypatch, tts):
    ImmediateTimer.calls = []
    monkeypatch.setattr(audio_module, "QAudioOutput", FakeAudioOutput)
    monkeypatch.setattr(audio_module, "QMediaPlayer", FakePlayer)
    monkeypatch.setattr(audio_module, "QUrl", FakeUrl)
    monkeypatch.setattr(audio_module, "QTimer", ImmediateTimer)
    return audio_module.RecordedAudioPlayer(tts)


def test_recorded_audio_uses_recording_then_continues_after_completion(tmp_path, monkeypatch):
    recording = tmp_path / "front.mp3"
    recording.write_bytes(b"audio")
    tts = FakeTTS()
    player = make_player(monkeypatch, tts)

    player.play_sequence([(recording, "front"), (None, "back")], pause_ms=250)
    assert player.player.source == f"local:{recording}"
    assert player.player.play_calls == 1
    assert tts.spoken == []

    player._on_media_status_changed(FakePlayer.MediaStatus.EndOfMedia)
    assert ImmediateTimer.calls == [250]
    assert tts.spoken == ["back"]
    tts.callback()
    assert player.player.stop_calls >= 2


def test_recorded_audio_skips_empty_fields_handles_errors_and_stops(monkeypatch):
    tts = FakeTTS(available=False)
    player = make_player(monkeypatch, tts)

    player.play_sequence([(None, ""), ("missing.mp3", "fallback")], pause_ms=-5)
    assert player._pause_ms == 0
    assert player.player.play_calls == 0
    assert tts.spoken == []

    initial_stops = player.player.stop_calls
    player._on_error(FakePlayer.Error.NoError, "ignored")
    assert player.player.stop_calls == initial_stops
    player._on_error(FakePlayer.Error.ResourceError, "missing codec")
    assert ImmediateTimer.calls == [0]

    player.stop()
    assert player._items == []
    assert tts.stop_calls >= 2
