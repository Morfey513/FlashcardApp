"""Configuration for the opt-in, visible Windows GUI regression runner."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final


@dataclass(frozen=True)
class Iterations:
    flashcard_audio: int
    flashcard_tts: int
    quiz: int
    editor: int
    authentication: int
    admin: int


PROFILES: Final[dict[str, Iterations]] = {
    "smoke": Iterations(2, 2, 2, 2, 2, 1),
    "phase7": Iterations(20, 20, 20, 20, 10, 10),
    # Diagnostic deliberately runs only the selected scenario once by default.
    "diagnostic": Iterations(1, 1, 1, 1, 1, 1),
}


@dataclass(frozen=True)
class RunConfig:
    profile: str
    artifact_root: Path
    scenario: str | None = None
    keep_runtime: bool = False
    procdump_path: Path | None = None
    action_timeout_seconds: float = 15.0
    startup_timeout_seconds: float = 30.0
    validation: str | None = None
    repetitions: int = 1
    hold_seconds: float = 30.0

    @property
    def iterations(self) -> Iterations:
        return PROFILES[self.profile]
