"""Rendered-user workflows.  Each action is followed by a visible-state assertion."""
from __future__ import annotations

from .fixtures import Account
from .uia import (FLASHCARD_VIEWER, GUEST_GREETING, LAUNCHER, LOGIN, LOGIN_OPEN,
                  LOGIN_SUBMIT, LOGOUT_CONFIRM, LOGOUT_OPEN, LOGOUT_YES,
                  MODERATION, PROFILE, QUIZ_EDITOR, QUIZ_VIEWER,
                  LAUNCHER_CLASSES, LAUNCHER_FLASHCARDS, LAUNCHER_FLASHCARD_EDITOR,
                  LAUNCHER_MODERATION, LAUNCHER_PROGRESS, LAUNCHER_QUIZ,
                  LAUNCHER_QUIZ_EDITOR,
                  FLASHCARD_AUDIO, FLASHCARD_EXIT, FLASHCARD_MENU, FLASHCARD_RETURN_TO_LAUNCHER, FLASHCARD_STUDY,
                  PRACTICE, QUIT_QUIZ, QUIZ_DONE, QUIZ_FINALIZE, QUIZ_MENU, QUIZ_NEXT_PROGRESS,
                  QUIZ_QUESTION, QUIZ_RESULTS, QUIZ_SUBMIT, QUIZ_PREVIEW, QUIZ_REVIEW, QUIZ_BACK_TO_QUIZ,
                  RETURN_TO_LAUNCHER, START_STUDY, CONFIRM_YES, UNFINISHED_QUIZ,
                  AutomationLimitation, Locator, UIA, button)


class Workflows:
    def __init__(self, ui: UIA, accounts: dict[str, Account], artifacts, fixture_names=None):
        self.ui, self.accounts, self.artifacts = ui, accounts, artifacts
        self.fixture_names = fixture_names or {}

    def launcher(self):
        return self.ui.launcher()

    @staticmethod
    def _button_by_text(parent, text: str) -> Locator:
        return button(text)

    def login(self, account: Account, scenario: str = "authentication") -> None:
        launcher = self.launcher()
        self.ui.click(launcher, LOGIN_OPEN, scenario, "open login")
        self.artifacts.uia_tree(launcher, f"{scenario}-launcher-after-login-click.txt")
        dialog = self.ui.child(launcher, LOGIN)
        self.artifacts.uia_tree(dialog, f"{scenario}-login-dialog.txt")
        edits = dialog.descendants(control_type="Edit")
        if len(edits) != 2:
            raise AutomationLimitation(f"login dialog must expose exactly two Edit controls; found {len(edits)}")
        self.artifacts.record(scenario, f"enter credentials for {account.role}")
        # Structural semantic contract: the visible Email label precedes Password.
        edits[0].set_focus(); edits[0].type_keys("^a{BACKSPACE}"); edits[0].type_keys(account.login, with_spaces=True)
        edits[1].set_focus(); edits[1].type_keys(account.password, with_spaces=True)
        self.ui.click(dialog, LOGIN_SUBMIT, scenario, "submit login")
        self.ui.wait_child_gone(launcher, LOGIN)
        launcher = self.launcher()
        self.ui.child(launcher, Locator("logged-in greeting", control_type="Text", title=f"Welcome, GUI {account.role}!"))
        self.ui.child(launcher, LOGOUT_OPEN)

    def logout(self, scenario: str = "authentication") -> None:
        launcher = self.launcher()
        self.ui.click(launcher, LOGOUT_OPEN, scenario, "request logout")
        confirmation = self.ui.child(launcher, LOGOUT_CONFIRM)
        self.artifacts.uia_tree(confirmation, f"{scenario}-logout-confirmation.txt")
        self.ui.click(confirmation, LOGOUT_YES, scenario, "confirm logout")
        self.ui.wait_child_gone(launcher, LOGOUT_CONFIRM)
        # The visible login control is the postcondition for guest mode.
        launcher = self.launcher()
        self.ui.child(launcher, GUEST_GREETING)
        self.ui.child(launcher, LOGIN_OPEN)

    def authentication_milestone(self) -> None:
        """Bounded guest -> student -> guest workflow; no viewer/matrix actions."""
        launcher = self.launcher()
        self.ui.child(launcher, GUEST_GREETING)
        self.login(self.accounts["student"], "authentication_milestone")
        self.logout("authentication_milestone")

    def open_quiz(self, scenario: str = "quiz"):
        launcher = self.launcher()
        self.ui.click(launcher, LAUNCHER_QUIZ, scenario, "open quiz viewer")
        viewer = self.ui.window(QUIZ_VIEWER)
        self.ui.assert_panel(viewer, QUIZ_MENU, scenario, "quiz menu")
        return viewer

    def open_flashcards(self, scenario: str = "flashcards"):
        launcher = self.launcher()
        self.ui.click(launcher, LAUNCHER_FLASHCARDS, scenario, "open flashcard viewer")
        viewer = self.ui.window(FLASHCARD_VIEWER)
        self.ui.assert_panel(viewer, FLASHCARD_MENU, scenario, "flashcard selection")
        return viewer

    def close_quiz_to_launcher(self, viewer, scenario: str) -> None:
        # Managed study windows deliberately expose this command.  Using it
        # exercises the product's close/return lifecycle instead of asking the
        # UIA provider to destroy a native Qt window behind its controller.
        # This workflow always enters an active practice session, so exit in
        # two asserted product transitions: question -> menu -> launcher.
        self.ui.click(viewer, QUIT_QUIZ, scenario, "quit active quiz")
        viewer = self.ui.window(QUIZ_VIEWER)
        self.ui.assert_panel(viewer, QUIZ_MENU, scenario, "quiz menu after quit")
        self.ui.click(viewer, RETURN_TO_LAUNCHER, scenario, "return to launcher")
        self.ui.child(self.launcher(), LAUNCHER_QUIZ)

    def close_flashcards_to_launcher(self, viewer, scenario: str) -> None:
        """Flashcard study uses its own visible exit, never quiz fallbacks."""
        self.ui.click(viewer, FLASHCARD_EXIT, scenario, "return to flashcard selection")
        viewer = self.ui.window(FLASHCARD_VIEWER)
        self.ui.assert_panel(viewer, FLASHCARD_MENU, scenario, "flashcard selection after exit")
        self.ui.click(viewer, FLASHCARD_RETURN_TO_LAUNCHER, scenario, "return to launcher")
        self.ui.child(self.launcher(), LAUNCHER_FLASHCARDS)

    def _select_isolated_fixture(self, panel, list_anchor: Locator, scenario: str, kind: str, fixture_key: str) -> None:
        listing = self.ui.assert_panel(panel, list_anchor, scenario, f"{kind} fixture list")
        items = listing.descendants(control_type="ListItem")
        expected_name = self.fixture_names.get(fixture_key)
        if not expected_name:
            raise AutomationLimitation(f"missing configured fixture identity for {fixture_key!r}")
        # Qt's QListWidget currently publishes rows as anonymous UIA
        # ListItems (no Name or child Text), so an accessible-name lookup is
        # not available without changing product accessibility metadata.  The
        # isolated runtime instead guarantees exactly one visible fixture for
        # each smoke workflow.  Refuse ambiguity before interacting; this is
        # not a positional/first-item fallback.
        if len(items) != 1:
            self.ui.capture_state(panel, scenario, f"unexpected-{kind}-fixture-cardinality")
            raise AutomationLimitation(
                f"expected exactly one isolated {kind} fixture for {fixture_key!r} "
                f"({expected_name!r}); found {len(items)}"
            )
        self.artifacts.record(scenario, f"select isolated {kind} fixture", detail=expected_name)
        items[0].click_input()

    def quiz_navigation(self, role: str = "guest") -> None:
        scenario = "quiz_navigation"
        viewer = self.open_quiz(scenario)
        self._select_isolated_fixture(viewer, QUIZ_MENU, scenario, "quiz", f"{role}_quiz")
        self.ui.click(viewer, PRACTICE, scenario, "start selected practice quiz")
        self.ui.assert_panel(viewer, QUIZ_QUESTION, scenario, "active quiz question")
        self._answer_rendered_question(viewer, scenario)
        self.ui.click(viewer, QUIZ_SUBMIT, scenario, "submit answer")
        self.ui.assert_panel(viewer, QUIZ_NEXT_PROGRESS, scenario, "next active quiz question")
        self.close_quiz_to_launcher(viewer, scenario)

    def _answer_rendered_question(self, viewer, scenario: str) -> None:
        """Interact through the actual Qt-rendered answer control families."""
        edits = viewer.descendants(control_type="Edit")
        if edits:
            answer = edits[0]
            answer.set_focus(); answer.type_keys("^a{BACKSPACE}"); answer.type_keys("one", with_spaces=True)
            if answer.get_value() != "one":
                raise AssertionError("short-answer value did not persist")
            self.artifacts.record(scenario, "enter short answer")
            return
        combos = viewer.descendants(control_type="ComboBox")
        if combos:
            # The general fixture's matching choices are value-addressable as
            # well. Do not revive the historical index/Down-key workaround.
            expected_values = [str(index) for index in range(1, len(combos) + 1)]
            self._select_combo_answers(viewer, expected_values, scenario)
            self.artifacts.record(scenario, "select matching or ordering values")
            return
        excluded = {"Quit Quiz", "Submit Answer", "Skip", "Preview Answers", "Finalize Results"}
        candidates = []
        for control_type in ("CheckBox", "RadioButton", "Button"):
            candidates.extend(
                item for item in viewer.descendants(control_type=control_type)
                if item.window_text() not in excluded
            )
        for candidate in candidates:
            try:
                candidate.click_input()
                if candidate.get_toggle_state():
                    self.artifacts.record(scenario, "select checkable answer")
                    return
            except Exception:
                continue
        self.ui.capture_state(viewer, scenario, "no-answer-control")
        raise AutomationLimitation("no selectable rendered answer control was found")

    def _select_combo_answer(self, combo, expected_answer: str, viewer, scenario: str) -> None:
        """Select and prove one specific rendered ComboBox answer value.

        Matching and ordering share the same anonymous Qt ComboBox UIA
        behavior.  Callers supply a value intent; UIA resolves that value
        through its semantic selection path or exact-name popup item.
        """
        try:
            self.ui.select_combo_value(combo, expected_answer, scenario)
            self.ui.wait_for_state(
                lambda: str(combo.selected_text() or "") == expected_answer,
                f"ComboBox renders intended answer {expected_answer!r}",
            )
        except Exception as exc:
            self.artifacts.record(
                scenario,
                "ComboBox answer selection failure",
                "FAIL",
                f"expected={expected_answer!r}; {type(exc).__name__}: {exc}",
            )
            self.ui.capture_state(viewer, scenario, "combo-value-not-rendered")
            raise AssertionError(
                f"ComboBox answer {expected_answer!r} was not rendered"
            ) from exc

    def _select_combo_answers(self, viewer, expected_answers: list[str], scenario: str) -> None:
        combos = viewer.descendants(control_type="ComboBox")
        if len(combos) != len(expected_answers):
            self.ui.capture_state(viewer, scenario, "unexpected-ordering-combo-count")
            raise AutomationLimitation(
                f"expected {len(expected_answers)} answer ComboBoxes; found {len(combos)}"
            )
        for combo, expected_answer in zip(combos, expected_answers, strict=True):
            self._select_combo_answer(combo, expected_answer, viewer, scenario)
        self.ui.wait_for_state(
            lambda: [str(combo.selected_text() or "") for combo in combos] == expected_answers,
            "complete intended ComboBox answer state",
        )

    def _complete_final_results(self, viewer, scenario: str) -> None:
        """Complete either normal final transition without assuming a modal.

        A fully answered quiz can move straight to results.  If earlier items
        were skipped, the product correctly renders its ``Unfinished`` modal;
        confirm it semantically before asserting Results.
        """
        self.ui.wait_for_state(
            lambda: self.ui.available(viewer, QUIZ_RESULTS) or self.ui.available(viewer, CONFIRM_YES),
            "Finalize Results renders results or unfinished confirmation",
        )
        if self.ui.available(viewer, CONFIRM_YES):
            self.ui.assert_panel(viewer, UNFINISHED_QUIZ, scenario, "unfinished quiz confirmation")
            self.ui.click(viewer, CONFIRM_YES, scenario, "confirm unfinished finalization")
        self.ui.assert_panel(viewer, QUIZ_RESULTS, scenario, "quiz results")

    def _submit_combo_answer_and_assert_advances(self, viewer, previous_question: str, scenario: str) -> str:
        """Deliver the current matching/ordering completion action.

        The final practice item deliberately replaces ``Submit Answer`` with
        ``Finalize Results``.  Both are semantic completion actions, but they
        lead to different product panels and must not be conflated.
        """
        if self.ui.available(viewer, QUIZ_SUBMIT):
            self.ui.invoke(viewer, QUIZ_SUBMIT, scenario, "submit ComboBox answer")
            terminal = False
        elif self.ui.available(viewer, QUIZ_FINALIZE):
            self.ui.invoke(viewer, QUIZ_FINALIZE, scenario, "finalize ComboBox results")
            terminal = True
        else:
            self.ui.capture_state(viewer, scenario, "combo-completion-control-unavailable")
            raise AutomationLimitation("neither Submit Answer nor Finalize Results is rendered for ComboBox answer")

        if terminal:
            self._complete_final_results(viewer, scenario)
            return "results"

        def question_or_results_advanced():
            changed_question = self._question_text(viewer) not in {"", previous_question}
            result_buttons = viewer.descendants(control_type="Button", title="Finalize Results")
            review_buttons = viewer.descendants(control_type="Button", title="Back to Quiz")
            return changed_question or bool(result_buttons) or bool(review_buttons)

        self.ui.wait_for_state(
            question_or_results_advanced,
            "ComboBox Submit advances to next question or review/results",
        )
        return "question" if self._question_text(viewer) != previous_question else "review"

    def _results_to_launcher(self, viewer, scenario: str) -> None:
        """Close an asserted results panel via its own product transition."""
        self.ui.click(viewer, QUIZ_DONE, scenario, "finish ordering results")
        self.ui.assert_panel(viewer, QUIZ_MENU, scenario, "quiz menu after results")
        self.ui.click(viewer, RETURN_TO_LAUNCHER, scenario, "return to launcher after results")
        self.ui.child(self.launcher(), LAUNCHER_QUIZ)

    def _assert_duplicate_combo_result(self, viewer, scenario: str, submitted: str, correct: str) -> None:
        """Prove the real result view reports a duplicate ComboBox answer incorrect."""
        def result_contains_duplicate_and_correct_value() -> bool:
            texts = [str(item.window_text() or "") for item in viewer.descendants(control_type="Text")]
            return any(submitted in text for text in texts) and any(correct in text for text in texts)

        self.ui.wait_for_state(
            result_contains_duplicate_and_correct_value,
            "results render duplicate submitted and correct values",
        )
        self.ui.capture_state(viewer, scenario, "duplicate-combo-results")
        self.artifacts.record(scenario, "duplicate ComboBox answer graded incorrect", detail=f"{submitted} != {correct}")

    def _assert_question_result_entry(
        self, viewer, scenario: str, question: str, submitted: str, correct: str,
    ) -> None:
        """Prove one result row belongs to its question and has its submitted value."""
        def intended_row_visible() -> bool:
            rows = [
                str(item.window_text() or "")
                for item in viewer.descendants(control_type="Text")
                if question in str(item.window_text() or "")
            ]
            return len(rows) == 1 and all(fragment in rows[0] for fragment in (
                f"Your answer: {submitted}", f"Correct: {correct}",
            ))

        self.ui.wait_for_state(
            intended_row_visible,
            f"results row for {question!r} contains changed submitted answer",
        )
        self.ui.capture_state(viewer, scenario, "changed-answer-results")
        self.artifacts.record(
            scenario,
            "result row proves changed ComboBox values were submitted",
            detail=f"{question}; submitted={submitted}; correct={correct}",
        )

    def _assert_result_summary(self, viewer, scenario: str, score: int, total: int) -> None:
        """Assert the rendered aggregate and fixture-specific review rows."""
        percentage = score * 100 / total
        expected_score = f"Score: {score}/{total} ({percentage:.1f}%)"
        # This scenario submits a deterministic correct/wrong pattern against
        # the isolated six-question fixture.  Require actual result entries,
        # including the user's submitted value and the correct value, rather
        # than treating a score title alone as a Results-window pass.
        expected_rows = (
            "GUI fixture matching\nYour answer: one -> 1, two -> 2\nCorrect: one -> 1, two -> 2\nAttempts: 1 correct, 0 wrong",
            "GUI fixture multiple choice\nYour answer: two\nCorrect: one\nAttempts: 0 correct, 1 wrong",
            "GUI fixture short answer\nYour answer: one\nCorrect: one\nAttempts: 1 correct, 0 wrong",
            "GUI fixture ordering\nYour answer: one, one\nCorrect: one, two\nAttempts: 0 correct, 1 wrong",
            "GUI fixture single choice\nYour answer: one\nCorrect: one\nAttempts: 1 correct, 0 wrong",
            "GUI fixture true false\nYour answer: False\nCorrect: True\nAttempts: 0 correct, 1 wrong",
        )

        def result_summary_visible() -> bool:
            texts = [str(item.window_text() or "") for item in viewer.descendants(control_type="Text")]
            return (
                any(expected_score in text for text in texts)
                and all(any(row in text for text in texts) for row in expected_rows)
            )

        # Persist the full rendered result view before evaluating it.  This is
        # particularly useful if an off-screen row is not exposed by the Qt
        # UIA provider and the semantic assertion must fail.
        self.ui.capture_state(viewer, scenario, "score-results-pre-assertion")
        self.ui.wait_for_state(result_summary_visible, "score, percentage, correct, and incorrect result evidence")
        self.ui.capture_state(viewer, scenario, "score-results")
        self.artifacts.record(scenario, "score/results summary verified", detail=expected_score)

    def _rendered_answer_state(self, viewer) -> tuple[str, ...]:
        """Return the current rendered answer state without submitting it.

        Preview Answers is deliberately non-committing in the product.  This
        compact state read lets the GUI scenario prove that returning from the
        preview did not replace the user's visible in-progress answer.
        """
        combos = viewer.descendants(control_type="ComboBox")
        if combos:
            return tuple(str(combo.selected_text() or "") for combo in combos)

        edits = viewer.descendants(control_type="Edit")
        if edits:
            return tuple(str(edit.get_value() or "") for edit in edits)

        values = []
        for control_type in ("CheckBox", "RadioButton", "Button"):
            for control in viewer.descendants(control_type=control_type):
                try:
                    if control.get_toggle_state():
                        values.append(str(control.window_text() or ""))
                except Exception:
                    continue
        return tuple(values)

    def _assert_preview_review(
        self, viewer, scenario: str, current_question: str, expected_status: str,
    ) -> None:
        """Verify the Review Summary status associated with the current question."""
        review_texts = [str(item.window_text() or "") for item in viewer.descendants(control_type="Text")]
        current_index = next((
            index for index, text in enumerate(review_texts) if current_question in text
        ), None)
        if current_index is None:
            self.ui.capture_state(viewer, scenario, "preview-current-question-missing")
            raise AssertionError("Preview Answers did not render the current question in its review summary")
        status = next((
            text for text in review_texts[current_index + 1:current_index + 4]
            if "Answered" in text or "Unanswered" in text
        ), "")
        if status != expected_status:
            self.ui.capture_state(viewer, scenario, "preview-current-status-mismatch")
            raise AssertionError(
                f"Preview Answers status for {current_question!r} was {status!r}; "
                f"expected {expected_status!r}"
            )
        if self.ui.available(viewer, QUIZ_RESULTS):
            self.ui.capture_state(viewer, scenario, "preview-unexpected-results")
            raise AssertionError("Preview Answers finalized the quiz into Results")
        self.artifacts.record(
            scenario,
            "preview review summary verified",
            detail=f"current question visible; status={expected_status}",
        )

    def _select_checkable_button_answer(self, viewer, answer: str, scenario: str) -> None:
        """Select a named rendered checkable answer and prove its checked state."""
        controls = []
        for control_type in ("CheckBox", "RadioButton", "Button"):
            controls.extend(
                control for control in viewer.descendants(control_type=control_type)
                if str(control.window_text() or "") == answer
            )
        if len(controls) != 1:
            self.ui.capture_state(viewer, scenario, f"checkable-answer-{answer}-unavailable")
            raise AutomationLimitation(
                f"expected exactly one rendered checkable answer {answer!r}; found {len(controls)}"
            )
        control = controls[0]
        self.artifacts.record(scenario, "select checkable fixture answer", detail=answer)
        control.click_input()
        self.ui.wait_for_state(
            lambda: bool(control.get_toggle_state()),
            f"checkable fixture answer {answer!r} is selected",
        )
        return control

    def _record_checkable_control_diagnostic(self, control, scenario: str, name: str) -> None:
        """Persist UIA state for the Preview input without inspecting app internals."""
        info = getattr(control, "element_info", None)
        state = {
            "name": str(control.window_text() or ""),
            "toggle_state": bool(control.get_toggle_state()),
            "control_type": getattr(info, "control_type", None),
            "automation_id": getattr(info, "automation_id", None),
            "class_name": getattr(info, "class_name", None),
        }
        self.artifacts.write_json(f"{scenario}-{name}-uia-state.json", state)
        self.artifacts.record(scenario, "record selected checkable control diagnostic", detail=str(state))

    def _answer_known_fixture_question(self, viewer, scenario: str, correct: bool) -> None:
        """Answer one deterministic GUI fixture item with a known correct/wrong value."""
        question = self._question_text(viewer).casefold()
        if "matching" in question:
            self._select_combo_answers(viewer, ["1", "2"] if correct else ["1", "1"], scenario)
        elif "ordering" in question:
            self._select_combo_answers(viewer, ["one", "two"] if correct else ["one", "one"], scenario)
        elif "short" in question:
            edits = viewer.descendants(control_type="Edit")
            if len(edits) != 1:
                raise AutomationLimitation(f"fixture short answer must expose one Edit; found {len(edits)}")
            value = "one" if correct else "two"
            edits[0].set_focus()
            edits[0].type_keys("^a{BACKSPACE}")
            edits[0].type_keys(value, with_spaces=True)
            self.ui.wait_for_state(lambda: str(edits[0].get_value() or "") == value, "short fixture answer renders")
            self.artifacts.record(scenario, "enter short fixture answer", detail=value)
        elif "true false" in question:
            self._select_checkable_button_answer(viewer, "True" if correct else "False", scenario)
        elif "single choice" in question or "multiple choice" in question:
            self._select_checkable_button_answer(viewer, "one" if correct else "two", scenario)
        else:
            self.ui.capture_state(viewer, scenario, "unknown-fixture-question")
            raise AutomationLimitation(f"unknown deterministic fixture question: {question!r}")

    @staticmethod
    def _score_fixture_plan(question: str) -> bool:
        """Fixed 3/6 outcome plan keyed by stable fixture identity, not order."""
        normalized = question.casefold()
        plan = {
            "matching": True,
            "multiple choice": False,
            "short answer": True,
            "ordering": False,
            "single choice": True,
            "true false": False,
        }
        matches = [expected for identity, expected in plan.items() if identity in normalized]
        if len(matches) != 1:
            raise AutomationLimitation(f"unknown or ambiguous score fixture question: {question!r}")
        return matches[0]

    def _advance_to_final_question(self, viewer, scenario: str) -> str:
        """Use real Skip controls until the final-question controls are rendered."""
        for position in range(1, 7):
            if self.ui.available(viewer, QUIZ_FINALIZE):
                return self._question_text(viewer)
            previous = self._question_text(viewer)
            self.ui.click(viewer, button("Skip"), scenario, f"skip to final question {position}")
            self.ui.wait_for_state(
                lambda: self._question_text(viewer) != previous,
                f"advance toward final question {position}",
            )
        self.ui.capture_state(viewer, scenario, "final-question-not-reached")
        raise AutomationLimitation("could not reach final deterministic fixture question")

    def _finish_remaining_questions_to_results(self, viewer, scenario: str) -> None:
        """Reach results through normal visible quiz controls after a mid-quiz assertion.

        The diagnostic fixture shuffles questions, so ordering can occur before
        the final position.  We retain its real submitted answer, skip only
        later unrelated questions, and confirm the product's explicit
        unfinished-quiz dialog before results are rendered.
        """
        for position in range(1, 7):
            if self.ui.available(viewer, QUIZ_FINALIZE):
                self.ui.invoke(viewer, QUIZ_FINALIZE, scenario, "finalize incomplete ComboBox quiz")
                self._complete_final_results(viewer, scenario)
                return
            previous_question = self._question_text(viewer)
            self.ui.click(viewer, button("Skip"), scenario, f"skip remaining question {position}")
            self.ui.wait_for_state(
                lambda: self._question_text(viewer) != previous_question,
                f"remaining question advance after skip {position}",
            )
        self.ui.capture_state(viewer, scenario, "ordering-results-not-reached")
        raise AutomationLimitation("could not reach Finalize Results after bounded ordering continuation")

    def _question_text(self, viewer) -> str:
        """Read the rendered question anchor, rather than runner bookkeeping."""
        question = self.ui.child(viewer, QUIZ_QUESTION)
        return str(question.window_text() or "")

    def _open_combo_question(self, question_type: str, scenario: str):
        """Open the deterministic fixture and advance only until one question type."""
        viewer = self.open_quiz(scenario)
        self._select_isolated_fixture(viewer, QUIZ_MENU, scenario, "quiz", "guest_quiz")
        self.ui.click(viewer, PRACTICE, scenario, "start selected practice quiz")
        self.ui.assert_panel(viewer, QUIZ_QUESTION, scenario, "active quiz question")

        current_question = self._question_text(viewer)
        for position in range(1, 7):
            if question_type.casefold() in current_question.casefold():
                return viewer, current_question
            if position == 6:
                self.ui.capture_state(viewer, scenario, f"{question_type}-question-not-reached")
                raise AutomationLimitation(f"{question_type} question was not rendered in the six-question fixture")
            self.ui.click(viewer, button("Skip"), scenario, f"skip non-{question_type} question {position}")
            previous_question = current_question
            self.ui.wait_for_state(
                lambda: self._question_text(viewer) != previous_question,
                f"question advance after {question_type} skip {position}",
            )
            current_question = self._question_text(viewer)
        raise AssertionError("ordering search loop did not terminate")

    def ordering_value_capability(self) -> None:
        """Bounded probe for exact-value Qt ComboBox UIA selection."""
        scenario = "ordering_value_capability"
        viewer, _question = self._open_combo_question("ordering", scenario)
        combos = viewer.descendants(control_type="ComboBox")
        if len(combos) != 2:
            self.ui.capture_state(viewer, scenario, "unexpected-combo-count")
            raise AutomationLimitation(f"ordering fixture must expose two ComboBoxes; found {len(combos)}")
        self.ui.select_combo_value(combos[0], "one", scenario, capture_popup=True)
        self.ui.wait_for_state(
            lambda: str(combos[0].selected_text() or "") == "one",
            "first ordering ComboBox renders 'one'",
        )
        self.artifacts.record(scenario, "exact-value capability confirmed", detail="one")
        self.close_quiz_to_launcher(viewer, scenario)

    def ordering_validation(self) -> None:
        """Bounded real-GUI check of a distinct ordering submission.

        Practice deliberately randomizes question order.  Skips are product
        actions used only to reach the ordering item; the actual assertion is
        that its real rendered submit advances to another panel/state.
        """
        scenario = "ordering_validation"
        viewer, current_question = self._open_combo_question("ordering", scenario)

        self.artifacts.record(scenario, "ordering question reached", detail=current_question)
        self._select_combo_answers(viewer, ["one", "two"], scenario)
        # Preserve the concrete rendered state immediately before semantic
        # Submit, including every anonymous QComboBox readback.
        self.ui.capture_state(viewer, scenario, "ordering-pre-submit")
        outcome = self._submit_combo_answer_and_assert_advances(viewer, current_question, scenario)
        self.artifacts.record(scenario, "ordering submit advanced")
        if outcome == "question":
            self.close_quiz_to_launcher(viewer, scenario)
        elif outcome == "results":
            self._results_to_launcher(viewer, scenario)

    def ordering_duplicate_validation(self) -> None:
        """Exercise duplicate selection feedback and its non-blocking submit contract."""
        scenario = "ordering_duplicate_validation"
        viewer, current_question = self._open_combo_question("ordering", scenario)
        self._select_combo_answers(viewer, ["one", "one"], scenario)
        self.ui.capture_state(viewer, scenario, "duplicate-ordering-pre-submit")
        self.artifacts.record(
            scenario,
            "duplicate ordering values rendered",
            detail="one, one; visual invalid state captured in screenshot",
        )
        outcome = self._submit_combo_answer_and_assert_advances(viewer, current_question, scenario)
        if outcome == "question":
            self._finish_remaining_questions_to_results(viewer, scenario)
        self._assert_duplicate_combo_result(viewer, scenario, "one, one", "one, two")
        self.artifacts.record(scenario, "duplicate ordering submit advanced")
        if outcome in {"question", "results"}:
            self._results_to_launcher(viewer, scenario)

    def matching_validation(self) -> None:
        """Bounded valid matching path using prompt-independent answer intents."""
        scenario = "matching_validation"
        viewer, current_question = self._open_combo_question("matching", scenario)
        self.artifacts.record(scenario, "matching question reached", detail=current_question)
        self._select_combo_answers(viewer, ["1", "2"], scenario)
        self.ui.capture_state(viewer, scenario, "matching-pre-submit")
        outcome = self._submit_combo_answer_and_assert_advances(viewer, current_question, scenario)
        self.artifacts.record(scenario, "matching valid submit advanced")
        if outcome == "question":
            self.close_quiz_to_launcher(viewer, scenario)
        elif outcome == "results":
            self._results_to_launcher(viewer, scenario)

    def matching_duplicate_validation(self) -> None:
        """Bounded duplicate matching path and incorrect-results contract."""
        scenario = "matching_duplicate_validation"
        viewer, current_question = self._open_combo_question("matching", scenario)
        self._select_combo_answers(viewer, ["1", "1"], scenario)
        self.ui.capture_state(viewer, scenario, "duplicate-matching-pre-submit")
        self.artifacts.record(scenario, "duplicate matching values rendered", detail="1, 1; visual invalid state captured")
        outcome = self._submit_combo_answer_and_assert_advances(viewer, current_question, scenario)
        if outcome == "question":
            self._finish_remaining_questions_to_results(viewer, scenario)
        self._assert_duplicate_combo_result(viewer, scenario, "one -> 1, two -> 1", "one -> 1, two -> 2")
        self.artifacts.record(scenario, "duplicate matching submit advanced")
        if outcome in {"question", "results"}:
            self._results_to_launcher(viewer, scenario)

    def ordering_answer_change_validation(self) -> None:
        """Prove both ordering controls commit their most recently selected value."""
        scenario = "ordering_answer_change_validation"
        viewer, current_question = self._open_combo_question("ordering", scenario)
        combos = viewer.descendants(control_type="ComboBox")
        if len(combos) != 2:
            raise AutomationLimitation(f"ordering fixture must expose two ComboBoxes; found {len(combos)}")
        for index, (initial, final) in enumerate((("one", "two"), ("two", "one")), start=1):
            self._select_combo_answer(combos[index - 1], initial, viewer, scenario)
            self.ui.wait_for_state(
                lambda combo=combos[index - 1], value=initial: str(combo.selected_text() or "") == value,
                f"ordering control {index} initial value {initial!r}",
            )
            self._select_combo_answer(combos[index - 1], final, viewer, scenario)
            self.ui.wait_for_state(
                lambda combo=combos[index - 1], value=final: str(combo.selected_text() or "") == value,
                f"ordering control {index} changed value {final!r}",
            )
            self.artifacts.record(scenario, "ordering ComboBox value changed", detail=f"control={index}; {initial}->{final}")
        self.ui.wait_for_state(
            lambda: [str(combo.selected_text() or "") for combo in combos] == ["two", "one"],
            "ordering final changed values",
        )
        self.ui.capture_state(viewer, scenario, "ordering-values-changed-pre-submit")
        outcome = self._submit_combo_answer_and_assert_advances(viewer, current_question, scenario)
        self.artifacts.record(scenario, "ordering changed-answer completion advanced")
        if outcome == "question":
            self._finish_remaining_questions_to_results(viewer, scenario)
        self._assert_question_result_entry(
            viewer, scenario, "GUI fixture ordering", "two, one", "one, two",
        )
        self._results_to_launcher(viewer, scenario)

    def preview_answers_validation(self) -> None:
        """Exercise selected and unanswered Preview Answers contracts separately."""
        scenario = "preview_answers_validation"
        viewer = self.open_quiz(scenario)
        self._select_isolated_fixture(viewer, QUIZ_MENU, scenario, "quiz", "guest_quiz")
        self.ui.click(viewer, PRACTICE, scenario, "start selected practice quiz")
        self.ui.assert_panel(viewer, QUIZ_QUESTION, scenario, "active quiz question")
        final_question = self._question_text(viewer)
        if "preview true false" not in final_question.casefold():
            self.ui.capture_state(viewer, scenario, "preview-fixture-wrong-question")
            raise AutomationLimitation(f"Preview fixture did not render its true/false question: {final_question!r}")
        selected_control = self._select_checkable_button_answer(viewer, "True", scenario)
        self._record_checkable_control_diagnostic(selected_control, scenario, "selected-true")
        answer_before_preview = self._rendered_answer_state(viewer)
        if answer_before_preview != ("True",):
            self.ui.capture_state(viewer, scenario, "preview-answer-not-rendered")
            raise AssertionError(f"True was not visibly selected before Preview Answers: {answer_before_preview!r}")
        self.ui.capture_state(viewer, scenario, "preview-pre-action")
        self.ui.click(viewer, QUIZ_PREVIEW, scenario, "preview answers")
        self.ui.assert_panel(viewer, QUIZ_REVIEW, scenario, "preview review summary")
        self.ui.capture_state(viewer, scenario, "preview-review")
        self._assert_preview_review(viewer, scenario, final_question, "✅ Answered")
        self.ui.click(viewer, QUIZ_BACK_TO_QUIZ, scenario, "return from preview")
        self.ui.wait_for_state(
            lambda: self._question_text(viewer) == final_question,
            "same question after Preview Answers return",
        )
        answer_after_preview = self._rendered_answer_state(viewer)
        if answer_after_preview != answer_before_preview:
            self.ui.capture_state(viewer, scenario, "preview-answer-not-preserved")
            raise AssertionError(
                "Preview Answers changed the rendered in-progress answer: "
                f"before={answer_before_preview!r}; after={answer_after_preview!r}"
            )
        self.artifacts.record(
            scenario,
            "selected Preview returned without finalizing, advancing, or changing answer",
            detail=f"answer={answer_after_preview!r}",
        )
        self.close_quiz_to_launcher(viewer, scenario)

        # Fresh session in the same isolated fixture: no selected input must
        # remain genuinely unanswered in Review Summary.
        viewer = self.open_quiz(scenario)
        self._select_isolated_fixture(viewer, QUIZ_MENU, scenario, "quiz", "guest_quiz")
        self.ui.click(viewer, PRACTICE, scenario, "start unanswered preview fixture")
        self.ui.assert_panel(viewer, QUIZ_QUESTION, scenario, "active unanswered preview question")
        unanswered_question = self._question_text(viewer)
        self.ui.click(viewer, QUIZ_PREVIEW, scenario, "preview unanswered answer")
        self.ui.assert_panel(viewer, QUIZ_REVIEW, scenario, "unanswered preview review summary")
        self._assert_preview_review(viewer, scenario, unanswered_question, "⚠️ Unanswered")
        self.ui.click(viewer, QUIZ_BACK_TO_QUIZ, scenario, "return from unanswered preview")
        self.ui.wait_for_state(
            lambda: self._question_text(viewer) == unanswered_question,
            "same unanswered question after Preview Answers return",
        )
        self.artifacts.record(scenario, "unselected Preview remained unanswered without advancing")
        self.close_quiz_to_launcher(viewer, scenario)

    def score_results_validation(self) -> None:
        """Complete the six-question fixture with three correct and three wrong answers."""
        scenario = "score_results_validation"
        viewer = self.open_quiz(scenario)
        self._select_isolated_fixture(viewer, QUIZ_MENU, scenario, "quiz", "guest_quiz")
        self.ui.click(viewer, PRACTICE, scenario, "start selected practice quiz")
        self.ui.assert_panel(viewer, QUIZ_QUESTION, scenario, "active quiz question")
        observed_questions = set()
        for position in range(1, 7):
            previous = self._question_text(viewer)
            correct = self._score_fixture_plan(previous)
            if previous in observed_questions:
                self.ui.capture_state(viewer, scenario, "score-question-repeated")
                raise AssertionError(f"shuffled fixture repeated question before Results: {previous!r}")
            observed_questions.add(previous)
            self.artifacts.record(
                scenario, "apply score fixture answer by question identity",
                detail=f"question={previous}; expected_correct={correct}",
            )
            self._answer_known_fixture_question(viewer, scenario, correct=correct)
            if self.ui.available(viewer, QUIZ_SUBMIT):
                self.ui.invoke(viewer, QUIZ_SUBMIT, scenario, f"submit fixture answer {position}")
                self.ui.wait_for_state(
                    lambda: self._question_text(viewer) != previous,
                    f"advance after fixture answer {position}",
                )
            elif self.ui.available(viewer, QUIZ_FINALIZE):
                self.ui.invoke(viewer, QUIZ_FINALIZE, scenario, "finalize deterministic score quiz")
                self._complete_final_results(viewer, scenario)
                break
            else:
                self.ui.capture_state(viewer, scenario, "score-completion-control-unavailable")
                raise AutomationLimitation("fixture question has no visible Submit Answer or Finalize Results control")
        else:
            raise AssertionError("six-question fixture did not reach final results")
        if len(observed_questions) != 6:
            raise AssertionError(f"score fixture did not present six distinct questions: {observed_questions!r}")
        self._assert_result_summary(viewer, scenario, score=3, total=6)
        self._results_to_launcher(viewer, scenario)

    def flashcard_audio_cycle(self, use_tts: bool, role: str = "guest") -> None:
        scenario = "flashcard_tts" if use_tts else "flashcard_audio"
        viewer = self.open_flashcards(scenario)
        self._select_isolated_fixture(viewer, FLASHCARD_MENU, scenario, "flashcard deck", f"{role}_deck")
        self.ui.click(viewer, START_STUDY, scenario, "start study")
        self.ui.assert_panel(viewer, FLASHCARD_STUDY, scenario, "active flashcard")
        self.ui.click(viewer, FLASHCARD_AUDIO, scenario, "invoke audio or TTS")
        if not use_tts:
            self.ui.click(viewer, button("Flip Card"), scenario, "flip card")
            next_buttons = viewer.descendants(control_type="Button", title="Next Card")
            if next_buttons:
                next_buttons[0].click_input()
        self.close_flashcards_to_launcher(viewer, scenario)

    def profile(self) -> None:
        scenario = "student_profile"
        launcher = self.launcher()
        self.ui.click(launcher, LAUNCHER_PROGRESS, scenario, "open progress")
        dialog = self.ui.window(PROFILE)
        self.close_dialog_to_launcher(dialog, scenario)

    def teacher_editor_cycle(self) -> None:
        scenario = "teacher_editor"
        launcher = self.launcher()
        self.ui.click(launcher, LAUNCHER_QUIZ_EDITOR, scenario, "open quiz editor")
        editor = self.ui.window(QUIZ_EDITOR)
        # Open the create dialog, then cancel: verifies dynamic editor construction without mutating content.
        self.ui.click(editor, button("Create Quiz"), scenario, "open create quiz")
        dialogs = editor.descendants(control_type="Window")
        cancel = None
        for item in dialogs:
            found = item.descendants(control_type="Button", title="Cancel")
            if found:
                cancel = found[0]; break
        if cancel is None:
            raise AutomationLimitation("Quiz Editor create dialog lacks a semantic Cancel button")
        cancel.click_input()
        self.close_dialog_to_launcher(editor, scenario)

    def admin_moderation_cycle(self) -> None:
        scenario = "admin_moderation"
        launcher = self.launcher()
        self.ui.click(launcher, LAUNCHER_MODERATION, scenario, "open moderation")
        dialog = self.ui.window(MODERATION)
        # A visible search/filter is a rendered control rebuild smoke assertion.
        self.ui.child(dialog, Locator("class search", control_type="Edit", auto_id="class_search"))
        self.close_dialog_to_launcher(dialog, scenario)

    def close_dialog_to_launcher(self, dialog, scenario: str) -> None:
        """Close a managed dialog and assert the launcher became interactive."""
        self.artifacts.record(scenario, "close managed dialog")
        dialog.close()
        self.ui.child(self.launcher(), LAUNCHER_QUIZ)

    def guest_workflow(self) -> None:
        self.ui.child(self.launcher(), GUEST_GREETING)
        self.quiz_navigation()
        self.flashcard_audio_cycle(use_tts=False)

    def student_workflow(self) -> None:
        self.login(self.accounts["student"], "student")
        self.quiz_navigation("student")
        self.flashcard_audio_cycle(use_tts=True, role="student")
        self.profile()
        self.logout("student")

    def teacher_workflow(self) -> None:
        self.login(self.accounts["teacher"], "teacher")
        self.teacher_editor_cycle()
        launcher = self.launcher()
        self.ui.click(launcher, LAUNCHER_CLASSES, "teacher_classes", "open classes roster")
        dialog = self.ui.window(MODERATION)
        self.ui.child(dialog, Locator("class search", control_type="Edit", auto_id="class_search"))
        self.close_dialog_to_launcher(dialog, "teacher_classes")
        self.logout("teacher")

    def admin_workflow(self) -> None:
        self.login(self.accounts["admin"], "admin")
        self.admin_moderation_cycle()
        self.logout("admin")

    def minimal_milestone(self) -> None:
        self.login(self.accounts["student"], "milestone")
        viewer = self.open_quiz("milestone")
        self._select_isolated_fixture(viewer, QUIZ_MENU, "milestone", "quiz", "student_quiz")
        self.ui.click(viewer, RETURN_TO_LAUNCHER, "milestone", "return to launcher")
        viewer = self.open_quiz("milestone")
        self.ui.click(viewer, RETURN_TO_LAUNCHER, "milestone", "return to launcher")
        self.logout("milestone")
        self.login(self.accounts["teacher"], "milestone")
        viewer = self.open_quiz("milestone")
        self.ui.click(viewer, RETURN_TO_LAUNCHER, "milestone", "return to launcher")
        self.logout("milestone")
