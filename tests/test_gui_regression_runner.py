"""Unit coverage for the opt-in Windows GUI runner; no desktop is launched."""

from pathlib import Path

from tools.gui_regression.configuration import RunConfig
from tools.gui_regression.processes import TopLevelWindow, classify_windows_diagnostics
from tools.gui_regression import runner
from tools.gui_regression.workflows import Workflows
from tools.gui_regression.uia import AutomationLimitation, Locator, UIA
from pywinauto.timings import wait_until


def test_uia_com_diagnostic_is_nonfatal_only_after_a_clean_responsive_exit():
    stderr = "Windows fatal exception: code 0x8001010d\n"

    assert classify_windows_diagnostics(
        stderr, exit_code=0, was_responsive=True, matching_wer_event=False,
    ) == [{
        "code": "0x8001010D",
        "name": "uia_com_reentrancy",
        "classification": "non_fatal_diagnostic",
    }]

    assert classify_windows_diagnostics(
        stderr, exit_code=0, was_responsive=True, matching_wer_event=True,
    )[0]["classification"] == "requires_review"
    assert classify_windows_diagnostics(
        stderr, exit_code=-1073740791, was_responsive=False, matching_wer_event=False,
    )[0]["classification"] == "requires_review"


def test_unknown_or_terminating_windows_exception_requires_review():
    stderr = (
        "Windows fatal exception: code 0xC0000409\n"
        "Windows fatal exception: code 0xDEADBEEF\n"
    )

    diagnostics = classify_windows_diagnostics(
        stderr, exit_code=-1073740791, was_responsive=False, matching_wer_event=False,
    )

    assert [item["classification"] for item in diagnostics] == [
        "requires_review", "requires_review",
    ]


def test_procdump_targets_the_hwnd_owning_process(monkeypatch, tmp_path):
    captured = {}

    class FakeProcDump:
        def __init__(self, executable, process_id, artifact_dir):
            captured.update(executable=executable, process_id=process_id, artifact_dir=artifact_dir)

    class FakeArtifacts:
        path = tmp_path

        def record(self, *args):
            captured["record"] = args

    procdump = tmp_path / "procdump.exe"
    procdump.write_bytes(b"")
    monkeypatch.setattr(runner, "ProcDumpMonitor", FakeProcDump)
    desktop = type("Desktop", (), {"pid": 100})()
    window = TopLevelWindow(hwnd=123, title="Learning App", process_id=200)
    config = RunConfig("diagnostic", tmp_path, procdump_path=procdump)

    monitor = runner._start_optional_procdump(desktop, window, FakeArtifacts(), config)

    assert isinstance(monitor, FakeProcDump)
    assert captured["process_id"] == 200
    assert "target_pid=200" in captured["record"][3]


def test_uia_state_wait_polls_false_until_true():
    ui = object.__new__(UIA)
    ui.timeout = 0.2
    ui._wait_until = wait_until
    calls = []

    def condition():
        calls.append(True)
        return len(calls) == 3

    assert ui.wait_for_state(condition, "eventual state") is True
    assert len(calls) == 3


def test_uia_state_wait_times_out_when_predicate_stays_false():
    ui = object.__new__(UIA)
    ui.timeout = 0.01
    ui._wait_until = wait_until

    try:
        ui.wait_for_state(lambda: False, "never true")
    except AutomationLimitation as exc:
        assert "never true" in str(exc)
    else:
        raise AssertionError("false predicate must time out")


def test_uia_semantic_invoke_delivers_the_resolved_submit_control():
    class Artifacts:
        def __init__(self):
            self.actions = []

        def record(self, *_args):
            self.actions.append(_args)

    class Control:
        invoked = False

        def invoke(self):
            self.invoked = True

    control = Control()
    ui = object.__new__(UIA)
    ui.artifacts = Artifacts()
    ui.child = lambda _parent, _locator: control
    ui._process = type("Process", (), {"assert_alive": staticmethod(lambda: None)})()

    ui.invoke(object(), Locator("submit answer"), "ordering", "submit ordering answer")

    assert control.invoked is True
    assert ui.artifacts.actions[-1][1] == "submit ordering answer"


def test_uia_available_distinguishes_visible_semantic_completion_controls():
    class Process:
        @staticmethod
        def assert_alive():
            return None

    class Spec:
        @staticmethod
        def exists(**_kwargs):
            return True

        @staticmethod
        def is_visible():
            return True

        @staticmethod
        def is_enabled():
            return True

    class Parent:
        @staticmethod
        def child_window(**criteria):
            assert criteria["title"] == "Finalize Results"
            return Spec()

    ui = object.__new__(UIA)
    ui._process = Process()
    from tools.gui_regression.uia import QUIZ_FINALIZE
    assert ui.available(Parent(), QUIZ_FINALIZE) is True


def test_combo_terminal_completion_uses_finalize_then_direct_results_when_submit_is_not_rendered():
    from tools.gui_regression.uia import QUIZ_FINALIZE, QUIZ_RESULTS, QUIZ_SUBMIT

    class UI:
        def __init__(self):
            self.invoked = []

        @staticmethod
        def available(_viewer, locator):
            return locator in {QUIZ_FINALIZE, QUIZ_RESULTS}

        def invoke(self, _viewer, locator, _scenario, _action):
            self.invoked.append(locator)

        @staticmethod
        def assert_panel(_viewer, locator, _scenario, _state):
            assert locator is QUIZ_RESULTS

        @staticmethod
        def wait_for_state(predicate, _state):
            assert predicate() is True

    class Artifacts:
        def record(self, *_args, **_kwargs):
            return None

    ui = UI()
    result = Workflows(ui, {}, Artifacts())._submit_combo_answer_and_assert_advances(
        object(), "ordering question", "ordering",
    )

    assert result == "results"
    assert ui.invoked == [QUIZ_FINALIZE]
    assert QUIZ_SUBMIT not in ui.invoked


def test_combo_terminal_completion_confirms_unfinished_before_results():
    from tools.gui_regression.uia import CONFIRM_YES, QUIZ_FINALIZE, QUIZ_RESULTS, UNFINISHED_QUIZ

    class UI:
        def __init__(self):
            self.stage = "question"
            self.actions = []

        def available(self, _viewer, locator):
            return (
                (locator is QUIZ_FINALIZE and self.stage == "question")
                or (locator is CONFIRM_YES and self.stage == "confirm")
                or (locator is QUIZ_RESULTS and self.stage == "results")
            )

        def invoke(self, _viewer, locator, _scenario, _action):
            assert locator is QUIZ_FINALIZE
            self.stage = "confirm"
            self.actions.append("finalize")

        def click(self, _viewer, locator, _scenario, _action):
            assert locator is CONFIRM_YES
            self.stage = "results"
            self.actions.append("yes")

        def assert_panel(self, _viewer, locator, _scenario, _state):
            assert locator is (UNFINISHED_QUIZ if self.stage == "confirm" else QUIZ_RESULTS)

        @staticmethod
        def wait_for_state(predicate, _state):
            assert predicate() is True

    class Artifacts:
        def record(self, *_args, **_kwargs):
            return None

    ui = UI()
    result = Workflows(ui, {}, Artifacts())._submit_combo_answer_and_assert_advances(
        object(), "matching question", "matching",
    )
    assert result == "results"
    assert ui.actions == ["finalize", "yes"]


def test_uia_combo_value_selection_uses_exact_value_and_real_polling():
    class Artifacts:
        def record(self, *_args, **_kwargs):
            return None

        def uia_tree(self, *_args, **_kwargs):
            return None

    class Combo:
        selected = "-- Select --"

        def select(self, value):
            assert value == "one"
            self.selected = value

        def selected_text(self):
            return self.selected

    ui = object.__new__(UIA)
    ui.timeout = 0.2
    ui._wait_until = wait_until
    ui.artifacts = Artifacts()
    ui._application = object()
    combo = Combo()

    ui.select_combo_value(combo, "one", "value-test")

    assert combo.selected_text() == "one"


def test_uia_combo_value_popup_fallback_uses_exact_named_list_item():
    class Artifacts:
        def record(self, *_args, **_kwargs):
            return None

        def uia_tree(self, *_args, **_kwargs):
            return None

        def write_json(self, *_args, **_kwargs):
            return None

    class Info:
        runtime_id = (1, 2, 3)
        control_type = "ListItem"
        automation_id = "popup"
        class_name = ""

    class Combo:
        selected = "-- Select --"

        def select(self, _value):
            raise IndexError("not exposed while collapsed")

        def expand(self):
            return None

        def click_input(self):
            return None

        def selected_text(self):
            return self.selected

        def descendants(self, *, control_type):
            return []

    combo = Combo()

    class Item:
        element_info = Info()

        @staticmethod
        def window_text():
            return "one"

        @staticmethod
        def click_input():
            combo.selected = "one"

    class Surface:
        @staticmethod
        def descendants(*, control_type):
            assert control_type == "ListItem"
            return [Item()]

    class Application:
        @staticmethod
        def windows():
            return [Surface()]

    ui = object.__new__(UIA)
    ui.timeout = 0.2
    ui._wait_until = wait_until
    ui.artifacts = Artifacts()
    ui._application = Application()
    ui.capture_state = lambda *_args: None

    ui.select_combo_value(combo, "one", "value-test")

    assert combo.selected_text() == "one"


def test_combo_answer_intent_requires_exact_readback_for_matching_and_ordering_duplicates():
    class Combo:
        def __init__(self):
            self.selected = "-- Select --"

        def selected_text(self):
            return self.selected

    class Viewer:
        def __init__(self):
            self.combos = [Combo(), Combo()]

        def descendants(self, *, control_type):
            return self.combos if control_type == "ComboBox" else []

    class UI:
        @staticmethod
        def select_combo_value(combo, expected, _scenario):
            combo.selected = expected

        @staticmethod
        def wait_for_state(predicate, _state):
            assert predicate() is True

        @staticmethod
        def capture_state(*_args):
            raise AssertionError("exact value selection should not fail")

    class Artifacts:
        def record(self, *_args, **_kwargs):
            return None

    viewer = Viewer()
    workflows = Workflows(UI(), {}, Artifacts())
    workflows._select_combo_answers(viewer, ["one", "two"], "ordering")
    assert [combo.selected_text() for combo in viewer.combos] == ["one", "two"]

    workflows._select_combo_answers(viewer, ["one", "one"], "ordering")
    assert [combo.selected_text() for combo in viewer.combos] == ["one", "one"]

    workflows._select_combo_answers(viewer, ["1", "2"], "matching")
    assert [combo.selected_text() for combo in viewer.combos] == ["1", "2"]


def test_combo_answer_intent_rejects_placeholder_readback():
    class Combo:
        def selected_text(self):
            return "-- Select --"

    class Viewer:
        def descendants(self, *, control_type):
            return [Combo(), Combo()] if control_type == "ComboBox" else []

    class UI:
        @staticmethod
        def select_combo_value(*_args):
            return None

        @staticmethod
        def wait_for_state(predicate, _state):
            if not predicate():
                raise AutomationLimitation("selection remained placeholder")

        @staticmethod
        def capture_state(*_args):
            return None

    class Artifacts:
        def record(self, *_args, **_kwargs):
            return None

    try:
        Workflows(UI(), {}, Artifacts())._select_combo_answers(Viewer(), ["one", "two"], "ordering")
    except AssertionError as exc:
        assert "was not rendered" in str(exc)
    else:
        raise AssertionError("placeholder must block an ordering submission")


def test_duplicate_matching_and_ordering_mark_qt_controls_invalid_and_grade_incorrect(qt_application):
    from PyQt6.QtWidgets import QComboBox
    from src.controllers.quiz_controller import QuizController
    from src.ui.quiz_view import QuizViewer

    first, second = QComboBox(), QComboBox()
    for combo in (first, second):
        combo.addItems(["-- Select --", "one", "two"])
        combo.setCurrentText("one")
    viewer = type("OrderingView", (), {"combos": [first, second]})()

    QuizViewer.validate_unique_selection(viewer)

    assert first.property("invalid") is True
    assert second.property("invalid") is True
    controller = object.__new__(QuizController)
    assert controller._check_logic({
        "type": "ordering", "user_answer": ["one", "one"],
        "correct_answer": ["one", "two"],
    }) is False
    assert controller._check_logic({
        "type": "matching",
        "user_answer": [
            {"prompt": "one", "answer": "1"},
            {"prompt": "two", "answer": "1"},
        ],
        "correct_answer": [
            {"prompt": "one", "answer": "1"},
            {"prompt": "two", "answer": "2"},
        ],
    }) is False
    assert qt_application is not None


def test_quiz_navigation_requires_semantic_submit_to_advance():
    """The workflow's success criterion is rendered next-question state."""
    class UI:
        def __init__(self):
            self.submitted = False
            self.calls = []

        def click(self, _parent, locator, _scenario, _action):
            self.calls.append(locator)
            if locator.name == "submit answer":
                self.submitted = True

        def assert_panel(self, _parent, locator, _scenario, _state):
            if locator.name == "next quiz question":
                assert self.submitted is True
            return object()

    class Artifacts:
        def record(self, *_args, **_kwargs):
            return None

    ui = UI()
    workflows = Workflows(ui, {}, Artifacts())
    viewer = object()
    workflows.open_quiz = lambda _scenario: viewer
    workflows._select_isolated_fixture = lambda *_args: None
    workflows._answer_rendered_question = lambda *_args: None
    workflows.close_quiz_to_launcher = lambda *_args: None

    workflows.quiz_navigation()

    assert any(locator.name == "submit answer" for locator in ui.calls)


def test_fixture_selection_requires_one_isolated_visible_fixture():
    class Item:
        def __init__(self):
            self.clicked = False

        def window_text(self):
            return ""

        def descendants(self):
            return []

        def click_input(self):
            self.clicked = True

    class Listing:
        def __init__(self):
            self.public = Item()

        def descendants(self, *, control_type):
            assert control_type == "ListItem"
            return [self.public]

    class UI:
        def __init__(self, listing):
            self.listing = listing

        def assert_panel(self, *_args):
            return self.listing

        def capture_state(self, *_args):
            raise AssertionError("the configured fixture exists exactly once")

    class Artifacts:
        def record(self, *_args, **_kwargs):
            return None

    listing = Listing()
    workflows = Workflows(
        UI(listing), {}, Artifacts(), {"student_quiz": "run Public Quiz"},
    )

    workflows._select_isolated_fixture(
        object(), Locator("quiz list"), "student", "quiz", "student_quiz",
    )

    assert listing.public.clicked is True


def test_fixture_selection_rejects_ambiguous_anonymous_rows():
    class Item:
        def click_input(self):
            raise AssertionError("ambiguous rows must not be clicked")

    class Listing:
        def descendants(self, *, control_type):
            assert control_type == "ListItem"
            return [Item(), Item()]

    class UI:
        def assert_panel(self, *_args):
            return Listing()

        def capture_state(self, *_args):
            return None

    class Artifacts:
        def record(self, *_args, **_kwargs):
            return None

    workflows = Workflows(UI(), {}, Artifacts(), {"student_quiz": "run Public Quiz"})

    try:
        workflows._select_isolated_fixture(
            object(), Locator("quiz list"), "student", "quiz", "student_quiz",
        )
    except Exception as exc:
        assert "expected exactly one isolated quiz fixture" in str(exc)
    else:
        raise AssertionError("ambiguous anonymous fixture rows must fail")


def test_rendered_combo_answer_state_changes_to_latest_value():
    class Combo:
        def __init__(self):
            self.value = "-- Select --"

        def selected_text(self):
            return self.value

    class Viewer:
        def __init__(self):
            self.combo = Combo()

        def descendants(self, *, control_type):
            return [self.combo] if control_type == "ComboBox" else []

    viewer = Viewer()
    workflows = Workflows(object(), {}, object())
    viewer.combo.value = "one"
    initial = workflows._rendered_answer_state(viewer)
    viewer.combo.value = "two"
    final = workflows._rendered_answer_state(viewer)

    assert initial == ("one",)
    assert final == ("two",)
    assert initial != final


def test_preview_review_requires_current_question_and_answered_status_for_selected_input():
    captured = []

    class Text:
        def __init__(self, value):
            self.value = value

        def window_text(self):
            return self.value

    class Viewer:
        def descendants(self, *, control_type):
            assert control_type == "Text"
            return [Text("Q1: GUI preview true false"), Text("✅ Answered")]

    class UI:
        @staticmethod
        def capture_state(*args):
            captured.append(args)

        @staticmethod
        def available(*_args):
            return False

    class Artifacts:
        @staticmethod
        def record(*_args, **_kwargs):
            return None

    Workflows(UI(), {}, Artifacts())._assert_preview_review(
        Viewer(), "preview", "GUI preview true false", "✅ Answered",
    )
    assert captured == []


def test_preview_review_requires_unanswered_status_for_unselected_input():
    class Text:
        def window_text(self):
            return "Q1: GUI preview true false"

    class Status:
        def window_text(self):
            return "⚠️ Unanswered"

    class Viewer:
        @staticmethod
        def descendants(*, control_type):
            assert control_type == "Text"
            return [Text(), Status()]

    class UI:
        @staticmethod
        def capture_state(*_args):
            return None

        @staticmethod
        def available(*_args):
            return False

    class Artifacts:
        @staticmethod
        def record(*_args, **_kwargs):
            return None

    Workflows(UI(), {}, Artifacts())._assert_preview_review(
        Viewer(), "preview", "GUI preview true false", "⚠️ Unanswered",
    )


def test_preview_review_rejects_wrong_status_for_selected_input():
    class Text:
        def __init__(self, value):
            self.value = value

        def window_text(self):
            return self.value

    class Viewer:
        @staticmethod
        def descendants(*, control_type):
            assert control_type == "Text"
            return [Text("Q1: GUI preview true false"), Text("⚠️ Unanswered")]

    class UI:
        @staticmethod
        def capture_state(*_args):
            return None

        @staticmethod
        def available(*_args):
            return False

    class Artifacts:
        @staticmethod
        def record(*_args, **_kwargs):
            return None

    try:
        Workflows(UI(), {}, Artifacts())._assert_preview_review(
            Viewer(), "preview", "GUI preview true false", "✅ Answered",
        )
    except AssertionError as exc:
        assert "status" in str(exc)
    else:
        raise AssertionError("selected Preview must reject an unanswered current row")


def test_score_result_summary_requires_exact_score_and_correct_wrong_rows():
    class Text:
        def __init__(self, value):
            self.value = value

        def window_text(self):
            return self.value

    class Viewer:
        @staticmethod
        def descendants(*, control_type):
            assert control_type == "Text"
            return [
                Text("Score: 3/6 (50.0%)"),
                Text("GUI fixture matching\nYour answer: one -> 1, two -> 2\nCorrect: one -> 1, two -> 2\nAttempts: 1 correct, 0 wrong"),
                Text("GUI fixture multiple choice\nYour answer: two\nCorrect: one\nAttempts: 0 correct, 1 wrong"),
                Text("GUI fixture short answer\nYour answer: one\nCorrect: one\nAttempts: 1 correct, 0 wrong"),
                Text("GUI fixture ordering\nYour answer: one, one\nCorrect: one, two\nAttempts: 0 correct, 1 wrong"),
                Text("GUI fixture single choice\nYour answer: one\nCorrect: one\nAttempts: 1 correct, 0 wrong"),
                Text("GUI fixture true false\nYour answer: False\nCorrect: True\nAttempts: 0 correct, 1 wrong"),
            ]

    class UI:
        @staticmethod
        def wait_for_state(predicate, _state):
            assert predicate() is True

        @staticmethod
        def capture_state(*_args):
            return None

    class Artifacts:
        def __init__(self):
            self.records = []

        def record(self, *args, **kwargs):
            self.records.append((args, kwargs))

    artifacts = Artifacts()
    Workflows(UI(), {}, artifacts)._assert_result_summary(Viewer(), "score", score=3, total=6)
    assert artifacts.records[-1][1]["detail"] == "Score: 3/6 (50.0%)"


def test_score_fixture_plan_is_stable_under_shuffled_question_presentation():
    expected = {
        "GUI fixture matching": True,
        "GUI fixture multiple choice": False,
        "GUI fixture short answer": True,
        "GUI fixture ordering": False,
        "GUI fixture single choice": True,
        "GUI fixture true false": False,
    }

    workflows = Workflows(object(), {}, object())
    shuffled = [
        "GUI fixture ordering", "GUI fixture short answer", "GUI fixture true false",
        "GUI fixture matching", "GUI fixture single choice", "GUI fixture multiple choice",
    ]

    assert [workflows._score_fixture_plan(question) for question in shuffled] == [
        expected[question] for question in shuffled
    ]
    assert sum(workflows._score_fixture_plan(question) for question in shuffled) == 3


def test_changed_ordering_result_requires_the_latest_submitted_values():
    class Text:
        def __init__(self, value):
            self.value = value

        def window_text(self):
            return self.value

    class Viewer:
        @staticmethod
        def descendants(*, control_type):
            assert control_type == "Text"
            return [Text(
                "GUI fixture ordering\nYour answer: two, one\nCorrect: one, two\n"
                "Attempts: 0 correct, 1 wrong"
            )]

    class UI:
        @staticmethod
        def wait_for_state(predicate, _state):
            assert predicate() is True

        @staticmethod
        def capture_state(*_args):
            return None

    class Artifacts:
        @staticmethod
        def record(*_args, **_kwargs):
            return None

    Workflows(UI(), {}, Artifacts())._assert_question_result_entry(
        Viewer(), "ordering", "GUI fixture ordering", "two, one", "one, two",
    )


def test_results_done_navigates_to_quiz_menu_then_launcher():
    from tools.gui_regression.uia import LAUNCHER_QUIZ, QUIZ_DONE, QUIZ_MENU, RETURN_TO_LAUNCHER

    class UI:
        def __init__(self):
            self.actions = []

        def click(self, _parent, locator, _scenario, _action):
            self.actions.append(locator)

        @staticmethod
        def assert_panel(_viewer, locator, _scenario, _state):
            assert locator is QUIZ_MENU

        @staticmethod
        def child(_launcher, locator):
            assert locator is LAUNCHER_QUIZ
            return object()

    class Artifacts:
        @staticmethod
        def record(*_args, **_kwargs):
            return None

    ui = UI()
    workflows = Workflows(ui, {}, Artifacts())
    workflows.launcher = lambda: object()
    workflows._results_to_launcher(object(), "results")

    assert ui.actions == [QUIZ_DONE, RETURN_TO_LAUNCHER]
