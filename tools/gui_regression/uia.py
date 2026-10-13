"""Strict UIA page-object helpers.  No absolute coordinates are permitted."""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any


class AutomationLimitation(RuntimeError):
    """A required rendered control was absent or could not be addressed semantically."""


@dataclass(frozen=True)
class Locator:
    name: str
    control_type: str | None = None
    auto_id: str | None = None
    auto_id_re: str | None = None
    title: str | None = None
    title_re: str | None = None

    def criteria(self) -> dict[str, str]:
        return {key: value for key, value in {
            "control_type": self.control_type, "auto_id": self.auto_id,
            "auto_id_re": self.auto_id_re, "title": self.title,
            "title_re": self.title_re,
        }.items() if value}


# Texts are the English fixture contract.  The runner pins its isolated data to English.
LAUNCHER = Locator("launcher", control_type="Window", title_re=".*Study Buddy.*|.*Learning App.*")
LOGIN = Locator("login", control_type="Window", title_re="(?i).*login.*|.*sign in.*")
LOGOUT_CONFIRM = Locator("logout confirmation", control_type="Window", title_re="(?i).*log out.*")
# Verified on the real Qt 6 Windows UIA provider. Qt prefixes objectName values
# with the complete QObject path, so visible UIA Names are the stable selectors.
LOGIN_OPEN = Locator("login", control_type="Button", title="🔑")
LOGIN_SUBMIT = Locator("sign in", control_type="Button", title="Sign In")
LOGIN_GUEST = Locator("continue as guest", control_type="Button", title="Continue as Guest")
LOGOUT_OPEN = Locator("logout", control_type="Button", title="🚪")
LOGOUT_YES = Locator("confirm logout", control_type="Button", title="Yes")
GUEST_GREETING = Locator("guest greeting", control_type="Text", title="Welcome, Guest!")
QUIZ_VIEWER = Locator("quiz_viewer", control_type="Window", title_re=".*Quiz.*")
FLASHCARD_VIEWER = Locator("flashcard_viewer", control_type="Window", title_re=".*Flashcard.*")
QUIZ_EDITOR = Locator("quiz_editor", control_type="Window", title_re=".*Quiz Editor.*|.*Quiz.*")
MODERATION = Locator("moderation", control_type="Window", title="Moderation")
PROFILE = Locator("profile", control_type="Window", title_re=".*Progress.*|.*Statistics.*")

# The English launcher deliberately uses emoji-prefixed labels.  UIA exposes
# the rendered accessible Name, not the translation key or a shortened label.
# Keep these in the manifest rather than duplicating fragile literals in
# workflows.
LAUNCHER_QUIZ = Locator("quiz mode", control_type="Button", title="📝 Quiz Mode")
LAUNCHER_FLASHCARDS = Locator("flashcard mode", control_type="Button", title="🎴 Flashcard Mode")
LAUNCHER_PROGRESS = Locator("my progress", control_type="Button", title="My Progress")
LAUNCHER_QUIZ_EDITOR = Locator("quiz editor", control_type="Button", title="📝 Quiz Editor")
LAUNCHER_FLASHCARD_EDITOR = Locator("flashcard editor", control_type="Button", title="🎴 Flashcard Editor")
LAUNCHER_CLASSES = Locator("classes roster", control_type="Button", title="🏫 My Classes / Roster")
LAUNCHER_MODERATION = Locator("moderation", control_type="Button", title="🛡️ Moderation")
RETURN_TO_LAUNCHER = Locator("return to launcher", control_type="Button", title="← Return to Launcher")
PRACTICE = Locator("practice", control_type="Button", title="📖 Practice")
TAKE_TEST = Locator("take test", control_type="Button", title="📝 Take Test")
START_STUDY = Locator("start study", control_type="Button", title="Start Study")
QUIT_QUIZ = Locator("quit quiz", control_type="Button", title="Quit Quiz")
QUIZ_MENU = Locator("quiz menu list", control_type="List", auto_id="QApplication.QuizViewer.QFrame.quiz_learning_list")
QUIZ_QUESTION = Locator("active quiz question", control_type="Text", auto_id="QApplication.QuizViewer.QFrame.quiz_scroll_area.qt_scrollarea_viewport.QWidget.question")
QUIZ_NEXT_PROGRESS = Locator("next quiz question", control_type="Text", auto_id="QApplication.QuizViewer.QFrame.quiz_scroll_area.qt_scrollarea_viewport.QWidget.progress", title_re="Practice .* Question [2-6] of 6")
QUIZ_SUBMIT = Locator("submit answer", control_type="Button", title="Submit Answer")
QUIZ_FINALIZE = Locator("finalize results", control_type="Button", title="Finalize Results")
QUIZ_RESULTS = Locator("quiz results", control_type="Text", auto_id="QApplication.QuizViewer.QFrame.result_title", title_re="Score: .*")
QUIZ_DONE = Locator("done with results", control_type="Button", title="Done")
UNFINISHED_QUIZ = Locator("unfinished quiz confirmation", control_type="Window", title="Unfinished")
CONFIRM_YES = Locator("confirm unfinished quiz", control_type="Button", title="Yes")
QUIZ_PREVIEW = Locator("preview answers", control_type="Button", title="Preview Answers")
QUIZ_REVIEW = Locator("review summary", control_type="Text", title="Review Summary")
QUIZ_BACK_TO_QUIZ = Locator("back to quiz", control_type="Button", title="Back to Quiz")
FLASHCARD_MENU = Locator("flashcard deck list", control_type="List", auto_id="QApplication.FlashcardViewer.QFrame.flashcard_deck_list")
FLASHCARD_STUDY = Locator("active flashcard", control_type="Custom", auto_id="QApplication.FlashcardViewer.QFrame.flashcard_card")
FLASHCARD_EXIT = Locator("return to deck menu", control_type="Button", title="← Back")
FLASHCARD_RETURN_TO_LAUNCHER = Locator("return to launcher", control_type="Button", title="← Back to Main Menu")
FLASHCARD_AUDIO = Locator("flashcard audio", control_type="Button", auto_id="QApplication.FlashcardViewer.QFrame.flashcard_card.flashcard_audio_btn")


class UIA:
    def __init__(self, app_process, artifacts, timeout: float):
        try:
            from pywinauto.application import Application
            from pywinauto.timings import wait_until, wait_until_passes
        except ImportError as exc:  # requirements-gui is intentionally opt-in.
            raise RuntimeError("Install requirements-gui.txt before running GUI regression") from exc
        self._application = Application(backend="uia")
        self._process = app_process
        self.artifacts = artifacts
        self.timeout = timeout
        self._wait_until = wait_until
        self._wait_until_passes = wait_until_passes
        self._launcher = None

    def attach_to_hwnd(self, hwnd: int):
        """Attach only after the Win32 readiness gate has observed this HWND."""
        self._process.assert_alive()
        try:
            # Attach to the observed handle: a Windows Python launcher can
            # legitimately host the visible Qt window in a child process.
            self._application.connect(handle=hwnd)
            spec = self._application.window(handle=hwnd)
            spec.wait("exists visible ready", timeout=self.timeout)
            self._launcher = spec
            return self._launcher
        except Exception as exc:
            raise AutomationLimitation(f"UIA could not attach to ready HWND 0x{hwnd:X}") from exc

    def launcher(self):
        if self._launcher is None:
            raise AutomationLimitation("UIA launcher was not attached through the HWND readiness gate")
        self._process.assert_alive()
        return self._launcher

    def window(self, locator: Locator):
        self._process.assert_alive()
        spec = self._application.window(**locator.criteria())
        try:
            spec.wait("exists visible ready", timeout=self.timeout)
            return spec
        except Exception as exc:
            raise AutomationLimitation(f"UIA could not locate {locator.name}: {locator.criteria()}") from exc

    def child(self, parent, locator: Locator):
        self._process.assert_alive()
        spec = parent.child_window(**locator.criteria())
        try:
            spec.wait("exists visible enabled ready", timeout=self.timeout)
            return spec
        except Exception as exc:
            raise AutomationLimitation(f"UIA could not locate {locator.name}: {locator.criteria()}") from exc

    def available(self, parent, locator: Locator) -> bool:
        """Whether a semantic control is currently visible and enabled.

        This is intentionally a bounded state read, rather than a second
        long locator wait.  It lets a workflow distinguish mutually-exclusive
        rendered actions such as ``Submit Answer`` and ``Finalize Results``.
        """
        self._process.assert_alive()
        spec = parent.child_window(**locator.criteria())
        try:
            return bool(spec.exists(timeout=0) and spec.is_visible() and spec.is_enabled())
        except Exception:
            return False

    def click(self, parent, locator: Locator, scenario: str, action: str) -> None:
        control = self.child(parent, locator)
        self.artifacts.record(scenario, action)
        # click_input uses the semantic element rectangle; it never uses a fixed coordinate.
        control.click_input()
        self._process.assert_alive()

    def invoke(self, parent, locator: Locator, scenario: str, action: str) -> None:
        """Invoke a semantic UIA command without mouse-coordinate selection."""
        control = self.child(parent, locator)
        self.artifacts.record(scenario, action)
        try:
            control.invoke()
        except Exception as exc:
            raise AutomationLimitation(f"UIA cannot invoke {locator.name}") from exc
        self._process.assert_alive()

    def assert_panel(self, parent, locator: Locator, scenario: str, state: str):
        """Wait for a rendered panel anchor and preserve its actual state on failure."""
        try:
            control = self.child(parent, locator)
        except Exception as exc:
            self.capture_state(parent, scenario, f"failed-{state}")
            raise exc
        self.artifacts.record(scenario, f"state: {state}")
        return control

    def wait_for_state(self, condition, state: str):
        """Poll a boolean UI state until it is true or the action timeout elapses."""
        try:
            return self._wait_until(self.timeout, 0.1, condition)
        except Exception as exc:
            raise AutomationLimitation(f"UIA state did not become true: {state}") from exc

    def select_combo_value(self, combo, expected_value: str, scenario: str, *, capture_popup: bool = False) -> None:
        """Select a Qt ComboBox item by its rendered value, never its index.

        Qt's UIA provider sometimes omits a closed ComboBox's item container.
        First use its semantic value selection API; only then inspect an
        expanded popup for one exact-name ListItem.  Both paths are
        value-addressable and element-relative.
        """
        def selected_expected_value() -> bool:
            return str(combo.selected_text() or "") == expected_value

        if capture_popup:
            self.artifacts.uia_tree(combo, f"{scenario}-combo-before-value-selection.txt")
        try:
            combo.select(expected_value)
            self.wait_for_state(
                selected_expected_value,
                f"ComboBox renders requested value {expected_value!r}",
            )
            self.artifacts.record(scenario, "ComboBox semantic value selection", detail=expected_value)
            return
        except Exception as direct_exc:
            self.artifacts.record(
                scenario,
                "ComboBox semantic value selection unavailable",
                "LIMITED",
                f"{type(direct_exc).__name__}: {direct_exc}",
            )

        try:
            combo.expand()
        except Exception:
            pass
        # Qt's ExpandCollapse provider may claim success without presenting a
        # popup. Click the resolved ComboBox itself to request the rendered
        # popup; this remains element-relative rather than positional input.
        combo.click_input()

        if capture_popup:
            self.capture_state(combo, scenario, "combo-popup-expanded")

        def popup_items():
            candidates = []
            popup_options = []
            seen = set()
            surfaces = [combo]
            try:
                surfaces.extend(self._application.windows())
            except Exception as exc:
                raise AutomationLimitation("could not enumerate UIA popup surfaces") from exc
            for surface in surfaces:
                try:
                    for item in surface.descendants(control_type="ListItem"):
                        key = getattr(item.element_info, "runtime_id", None) or id(item)
                        if key in seen:
                            continue
                        seen.add(key)
                        name = str(item.window_text() or "")
                        popup_options.append({
                            "name": name,
                            "control_type": getattr(item.element_info, "control_type", None),
                            "automation_id": getattr(item.element_info, "automation_id", None),
                            "class_name": getattr(item.element_info, "class_name", None),
                        })
                        if name == expected_value:
                            candidates.append(item)
                except Exception:
                    continue
            return candidates, popup_options

        candidates, popup_options = popup_items()
        if not popup_options:
            # Qt can report a successful ExpandCollapse operation while its
            # list has not actually become exposed. A single second activation
            # is a concrete state repair, not an unbounded retry loop.
            combo.click_input()
            candidates, popup_options = popup_items()
        self.artifacts.write_json(
            f"{scenario}-combo-popup-options.json",
            popup_options,
        )
        if len(candidates) != 1:
            raise AutomationLimitation(
                f"expanded ComboBox exposes {len(candidates)} exact-name UIA items for {expected_value!r}"
            )
        try:
            # Qt's ListItem Selection pattern is exposed but does not commit
            # the popup choice. Click the exact named UIA element instead.
            # ``click_input`` derives its point from that item's bounding
            # rectangle; it is not a fixed screen-coordinate fallback.
            candidates[0].click_input()
        except Exception as exc:
            raise AutomationLimitation(
                f"exact-name popup item {expected_value!r} cannot be invoked"
            ) from exc
        self.wait_for_state(
            selected_expected_value,
            f"ComboBox popup selection renders requested value {expected_value!r}",
        )
        self.artifacts.record(scenario, "ComboBox popup value selection", detail=expected_value)

    def capture_state(self, window, scenario: str, state: str) -> None:
        self.artifacts.screenshot(window, f"{scenario}-{state}.png")
        self.artifacts.uia_tree(window, f"{scenario}-{state}.txt")
        try:
            for index, top_level in enumerate(self._application.windows()):
                self.artifacts.uia_tree(top_level, f"{scenario}-{state}-top-{index}.txt")
        except Exception as exc:
            self.artifacts.record(scenario, "top-level UIA capture", "LIMITED", type(exc).__name__)

    def set_text(self, parent, locator: Locator, text: str, scenario: str, action: str) -> None:
        control = self.child(parent, locator)
        self.artifacts.record(scenario, action)
        control.set_focus()
        control.type_keys("^a{BACKSPACE}")
        control.type_keys(text, with_spaces=True)
        self._process.assert_alive()

    def wait_gone(self, locator: Locator) -> None:
        spec = self._application.window(**locator.criteria())
        try:
            spec.wait_not("exists", timeout=self.timeout)
        except Exception as exc:
            raise AssertionError(f"{locator.name} did not close") from exc

    def wait_child_gone(self, parent, locator: Locator) -> None:
        spec = parent.child_window(**locator.criteria())
        try:
            spec.wait_not("exists visible", timeout=self.timeout)
        except Exception as exc:
            raise AssertionError(f"{locator.name} did not close") from exc

    def capture_failure(self, scenario: str, exc: BaseException, window=None) -> None:
        self.artifacts.record(scenario, "failure", "FAIL", f"{type(exc).__name__}: {exc}")
        if window is not None:
            self.artifacts.screenshot(window, f"{scenario}-failure.png")
            self.artifacts.uia_tree(window, f"{scenario}-uia-tree.txt")


def button(title: str, *, auto_id: str | None = None) -> Locator:
    return Locator(title, control_type="Button", title=title, auto_id=auto_id)


def edit(*, auto_id: str | None = None, title: str | None = None) -> Locator:
    return Locator(title or auto_id or "edit", control_type="Edit", title=title, auto_id=auto_id)
