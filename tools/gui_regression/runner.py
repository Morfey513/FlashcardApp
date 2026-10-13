"""CLI orchestration for the opt-in visible Windows GUI regression runner."""
from __future__ import annotations

import os
import shutil
import sys
import time
from pathlib import Path

from .artifacts import Artifacts
from .configuration import RunConfig
from .fixtures import GuiFixtures
from .processes import (
    ManagedProcess,
    ProcDumpMonitor,
    TopLevelWindow,
    assert_window_responsive,
    close_process_windows_normally,
    classify_windows_diagnostics,
    free_loopback_port,
    native_exit_name,
    wait_for_responsive_window,
    wait_ready,
)
from .runtime import RuntimeCopy
from .uia import UIA
from .workflows import Workflows


ROOT = Path(__file__).resolve().parents[2]
_DATABASE_ENVIRONMENT_KEYS = (
    "DATABASE_URL", "STUDY_BUDDY_DATABASE_URL", "STUDY_BUDDY_TEST_DATABASE_URL",
    "PGHOST", "PGPORT", "PGDATABASE", "PGUSER", "PGPASSWORD",
)


def _environment(runtime: Path, *, api_url: str | None = None, database_url: str | None = None) -> dict[str, str]:
    """Create a role-specific environment without DB access in the GUI process."""
    env = dict(os.environ)
    for key in _DATABASE_ENVIRONMENT_KEYS:
        env.pop(key, None)
    env.pop("QT_QPA_PLATFORM", None)
    env["PYTHONFAULTHANDLER"] = "1"
    env["PYTHONUNBUFFERED"] = "1"
    env["APPDATA"] = str(runtime / "appdata")
    env["LOCALAPPDATA"] = str(runtime / "localappdata")
    env["STUDY_BUDDY_MEDIA_ROOT"] = str(runtime / "managed-media")
    if api_url:
        env["STUDY_BUDDY_STORAGE"] = "api"
        env["STUDY_BUDDY_API_URL"] = api_url
    if database_url:
        env["STUDY_BUDDY_STORAGE"] = "postgresql"
        env["STUDY_BUDDY_DATABASE_URL"] = database_url
    return env


def _copy_log(runtime: Path, artifacts: Artifacts) -> None:
    source = runtime / "logs" / "quiz_app.log"
    if source.exists():
        target = artifacts.path / "application.log"
        shutil.copy2(source, target)
        artifacts.sanitize_file(target)


def _start_desktop(runtime_path: Path, base_url: str, artifacts: Artifacts, config: RunConfig) -> tuple[ManagedProcess, TopLevelWindow]:
    desktop = ManagedProcess(
        "desktop", [sys.executable, "-u", "-X", "faulthandler", "-m", "src.main"], runtime_path,
        _environment(runtime_path, api_url=base_url), artifacts.path,
    )
    desktop.start()
    if not hasattr(artifacts, "desktop_pids"):
        artifacts.desktop_pids = []
    artifacts.desktop_pids.append(desktop.pid)
    try:
        window = wait_for_responsive_window(desktop, config.startup_timeout_seconds)
    except Exception:
        # The HWND gate is pre-UIA.  A gate failure must not leak the real app
        # or be mistaken later for a process exit caused by the application.
        desktop.terminate()
        desktop.close_streams()
        raise
    artifacts.record("launcher", "hwnd ready", "PASS", f"launcher_pid={desktop.pid}; window_pid={window.process_id}; hwnd=0x{window.hwnd:X}; title={window.title!r}")
    artifacts.desktop_screenshot(f"launcher-hwnd-{desktop.pid}.png")
    return desktop, window


def _start_optional_procdump(
    desktop: ManagedProcess,
    window: TopLevelWindow,
    artifacts: Artifacts,
    config: RunConfig,
) -> ProcDumpMonitor | None:
    if config.procdump_path is None:
        return None
    if not config.procdump_path.is_file():
        raise FileNotFoundError(f"ProcDump executable was not found: {config.procdump_path}")
    # The Windows Python launcher can own a child Qt process.  A dump from the
    # launcher is not useful when the HWND belongs to that child.
    artifacts.record(
        "diagnostics", "ProcDump monitor", "PASS",
        f"{config.procdump_path.name}; target_pid={window.process_id}",
    )
    return ProcDumpMonitor(config.procdump_path, window.process_id, artifacts.path)


def _attach_uia(desktop: ManagedProcess, window: TopLevelWindow, artifacts: Artifacts, config: RunConfig):
    """Use UIA only after the independent Win32 readiness gate has passed."""
    desktop.assert_alive()
    assert_window_responsive(window.hwnd)
    ui = UIA(desktop, artifacts, config.action_timeout_seconds)
    launcher = ui.attach_to_hwnd(window.hwnd)
    info = launcher.element_info
    identity = {
        "launcher_pid": desktop.pid, "window_pid": window.process_id, "hwnd": f"0x{window.hwnd:X}", "win32_title": window.title,
        "uia_name": getattr(info, "name", None), "uia_control_type": getattr(info, "control_type", None),
        "uia_class_name": getattr(info, "class_name", None), "uia_automation_id": getattr(info, "automation_id", None),
    }
    artifacts.write_json(f"uia-top-level-{desktop.pid}.json", identity)
    artifacts.record("launcher", "UIA attach", "PASS", str(identity))
    artifacts.screenshot(launcher, f"launcher-uia-{desktop.pid}.png")
    artifacts.uia_tree(launcher, f"launcher-uia-{desktop.pid}.txt")
    return ui, launcher


def _hold_healthy(desktop: ManagedProcess, window: TopLevelWindow, seconds: float) -> TopLevelWindow:
    current_window = window
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        desktop.assert_alive()
        try:
            assert_window_responsive(current_window.hwnd)
        except RuntimeError:
            # A legitimate viewer/dialog transition can hide the launcher.
            # Re-discover a responsive top-level window without invoking UIA.
            current_window = wait_for_responsive_window(desktop, 2.0)
        time.sleep(0.2)
    return current_window


def _desktop_outcome(desktop: ManagedProcess, window: TopLevelWindow | None, artifacts: Artifacts, timeout: float) -> dict[str, object]:
    """Keep natural exit, graceful close, and runner-forced shutdown distinct."""
    before_cleanup = desktop.poll()
    if before_cleanup is None and window is not None:
        try:
            closed = close_process_windows_normally(desktop, timeout)
        except Exception as exc:
            closed = False
            artifacts.record("shutdown", "normal close", "LIMITED", f"{type(exc).__name__}: {exc}")
        if not closed:
            artifacts.record("shutdown", "normal close", "FAIL", "window/process did not exit within timeout")
            desktop.terminate()
    elif before_cleanup is None:
        desktop.terminate()
    code = desktop.poll()
    outcome = {
        "pid": desktop.pid,
        "window_pid": window.process_id if window else None,
        "diagnostic_pid": window.process_id if window else desktop.pid,
        "exit_code": code,
        "exit_classification": native_exit_name(code) or "non_native",
        "observed_before_cleanup": before_cleanup,
        "termination_method": desktop.termination_method,
        "runner_forced": desktop.termination_method in {"terminate", "kill"},
    }
    if not hasattr(artifacts, "desktop_outcomes"):
        artifacts.desktop_outcomes = []
    artifacts.desktop_outcomes.append(outcome)
    return outcome


def _run_launcher_validation(base_url: str, runtime_path: Path, artifacts: Artifacts, config: RunConfig) -> list[dict[str, object]]:
    if config.validation not in {"no-uia", "uia"}:
        raise ValueError(f"unknown validation mode {config.validation!r}")
    outcomes: list[dict[str, object]] = []
    for iteration in range(1, config.repetitions + 1):
        desktop = None
        window = None
        procdump = None
        try:
            artifacts.record("launcher_validation", f"iteration {iteration} start ({config.validation})")
            desktop, window = _start_desktop(runtime_path, base_url, artifacts, config)
            procdump = _start_optional_procdump(desktop, window, artifacts, config)
            if config.validation == "uia":
                _attach_uia(desktop, window, artifacts, config)
            window = _hold_healthy(desktop, window, config.hold_seconds)
            artifacts.record("launcher_validation", f"iteration {iteration} healthy")
        finally:
            if desktop:
                outcome = _desktop_outcome(desktop, window, artifacts, config.action_timeout_seconds)
                outcomes.append(outcome)
                artifacts.record("launcher_validation", f"iteration {iteration} exit", "PASS", str(outcome))
                desktop.close_streams()
            if procdump:
                procdump.stop()
    return outcomes


def _run_minimal_milestone(base_url: str, runtime_path: Path, artifacts: Artifacts, config: RunConfig, accounts, fixture_names) -> list[dict[str, object]]:
    desktop = None
    window = None
    procdump = None
    try:
        desktop, window = _start_desktop(runtime_path, base_url, artifacts, config)
        procdump = _start_optional_procdump(desktop, window, artifacts, config)
        ui, _launcher = _attach_uia(desktop, window, artifacts, config)
        workflows = Workflows(ui, accounts, artifacts, fixture_names)
        scenario = getattr(workflows, config.scenario or "", None)
        if config.scenario not in {"minimal_milestone", "authentication_milestone", "ordering_value_capability", "ordering_validation", "ordering_duplicate_validation", "matching_validation", "matching_duplicate_validation", "ordering_answer_change_validation", "preview_answers_validation", "score_results_validation"} or not callable(scenario):
            raise ValueError(f"unsupported bounded GUI scenario: {config.scenario!r}")
        scenario()
        desktop.assert_alive()
        assert_window_responsive(window.hwnd)
        artifacts.record(config.scenario or "bounded_scenario", "complete")
    finally:
        outcomes = []
        if desktop:
            outcomes.append(_desktop_outcome(desktop, window, artifacts, config.action_timeout_seconds))
            desktop.close_streams()
        if procdump:
            procdump.stop()
    return outcomes


def _run_profile_matrix(base_url: str, runtime_path: Path, artifacts: Artifacts, config: RunConfig, accounts, fixture_names) -> list[dict[str, object]]:
    """Run the visible, role-scoped smoke/Phase 7 matrix in one QApplication."""
    desktop = window = procdump = None
    try:
        desktop, window = _start_desktop(runtime_path, base_url, artifacts, config)
        procdump = _start_optional_procdump(desktop, window, artifacts, config)
        ui, _launcher = _attach_uia(desktop, window, artifacts, config)
        workflows = Workflows(ui, accounts, artifacts, fixture_names)
        iterations = config.iterations
        for index in range(iterations.quiz):
            artifacts.record("matrix", f"guest quiz iteration {index + 1}")
            workflows.quiz_navigation()
        for index in range(iterations.flashcard_audio):
            workflows.flashcard_audio_cycle(use_tts=False)
        for index in range(iterations.flashcard_tts):
            workflows.flashcard_audio_cycle(use_tts=True)
        for index in range(iterations.authentication):
            artifacts.record("matrix", f"student workflow iteration {index + 1}")
            workflows.student_workflow()
        for index in range(iterations.editor):
            artifacts.record("matrix", f"teacher workflow iteration {index + 1}")
            workflows.teacher_workflow()
        for index in range(iterations.admin):
            artifacts.record("matrix", f"admin workflow iteration {index + 1}")
            workflows.admin_workflow()
        desktop.assert_alive()
        assert_window_responsive(window.hwnd)
        artifacts.record("matrix", "complete")
    finally:
        outcomes = []
        if desktop:
            outcomes.append(_desktop_outcome(desktop, window, artifacts, config.action_timeout_seconds))
            desktop.close_streams()
        if procdump:
            procdump.stop()
    return outcomes


def run(config: RunConfig) -> int:
    if os.name != "nt":
        raise RuntimeError("the visible GUI runner is supported only on an unlocked Windows desktop")
    from src.runtime_config import load_runtime_environment

    load_runtime_environment()
    database_url = os.environ.get("STUDY_BUDDY_TEST_DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError("STUDY_BUDDY_TEST_DATABASE_URL must be set; GUI runner refuses other databases")
    artifacts = Artifacts(config.artifact_root, config.profile)
    runtime = RuntimeCopy(
        ROOT,
        artifacts.run_id,
        config.keep_runtime,
        preview_only=config.scenario == "preview_answers_validation",
    )
    fixtures = api = None
    started = time.time()
    desktop_outcomes: list[dict[str, object]] = []
    result = "FAIL"
    try:
        runtime_path = runtime.prepare()
        fixtures = GuiFixtures(database_url, artifacts.run_id)
        accounts = fixtures.seed()
        fixture_names = {
            "guest_quiz": runtime.guest_quiz_name,
            "guest_deck": runtime.guest_deck_name,
            "student_quiz": fixtures.public_quiz_name,
            "student_deck": fixtures.public_deck_name,
        }
        artifacts.write_json("fixture-identities.json", fixture_names)
        port = free_loopback_port()
        base_url = f"http://127.0.0.1:{port}"
        api = ManagedProcess(
            "api", [sys.executable, "-u", "-m", "uvicorn", "src.api.main:app", "--host", "127.0.0.1", "--port", str(port)],
            runtime_path, _environment(runtime_path, database_url=database_url), artifacts.path,
        )
        api.start()
        wait_ready(base_url, api, config.startup_timeout_seconds)
        if config.validation:
            desktop_outcomes = _run_launcher_validation(base_url, runtime_path, artifacts, config)
        elif config.scenario in {"minimal_milestone", "authentication_milestone", "ordering_value_capability", "ordering_validation", "ordering_duplicate_validation", "matching_validation", "matching_duplicate_validation", "ordering_answer_change_validation", "preview_answers_validation", "score_results_validation"}:
            desktop_outcomes = _run_minimal_milestone(base_url, runtime_path, artifacts, config, accounts, fixture_names)
        else:
            desktop_outcomes = _run_profile_matrix(base_url, runtime_path, artifacts, config, accounts, fixture_names)
        if any(item["observed_before_cleanup"] is not None for item in desktop_outcomes):
            raise RuntimeError("desktop exited before requested graceful shutdown")
        if any(item["exit_classification"] != "non_native" for item in desktop_outcomes):
            raise RuntimeError("desktop had a native crash exit")
        result = "PASS"
    except Exception as exc:
        artifacts.record("runner", "exception", "FAIL", f"{type(exc).__name__}: {exc}")
        artifacts.desktop_screenshot("failure-desktop.png")
    finally:
        ended = time.time()
        if api:
            api.terminate()
            api.close_streams()
        _copy_log(runtime.path, artifacts)
        desktop_stderr = artifacts.path / "desktop.stderr.log"
        stderr_text = desktop_stderr.read_text(encoding="utf-8", errors="replace") if desktop_stderr.exists() else ""
        for name in ("desktop.stdout.log", "desktop.stderr.log", "api.stdout.log", "api.stderr.log", "procdump.stdout.log", "procdump.stderr.log"):
            artifacts.sanitize_file(artifacts.path / name)
        recorded_outcomes = desktop_outcomes or getattr(artifacts, "desktop_outcomes", [])
        desktop_pid = recorded_outcomes[-1].get("window_pid") if recorded_outcomes else (getattr(artifacts, "desktop_pids", []) or [None])[-1]
        matching_wer_event = artifacts.capture_windows_events(
            started, ended, int(desktop_pid) if desktop_pid else None, runtime.path,
        )
        latest_outcome = recorded_outcomes[-1] if recorded_outcomes else {}
        diagnostics = classify_windows_diagnostics(
            stderr_text,
            exit_code=latest_outcome.get("exit_code"),
            was_responsive=(result == "PASS" and latest_outcome.get("observed_before_cleanup") is None),
            matching_wer_event=matching_wer_event,
        )
        for diagnostic in diagnostics:
            artifacts.record(
                "diagnostics", "desktop Windows exception",
                "LIMITED" if diagnostic["classification"] == "non_fatal_diagnostic" else "FAIL",
                str(diagnostic),
            )
        if any(item["classification"] != "non_fatal_diagnostic" for item in diagnostics):
            result = "FAIL"
        if fixtures:
            try:
                fixtures.cleanup()
                artifacts.record("cleanup", "database fixtures")
            except Exception as exc:
                artifacts.record("cleanup", "database fixtures", "FAIL", type(exc).__name__)
                result = "FAIL"
        runtime.cleanup()
        artifacts.finalize(result, {
                "desktop_outcomes": recorded_outcomes,
            "desktop_diagnostics": diagnostics,
            "matching_windows_event": matching_wer_event,
            "api_exit_code": api.poll() if api else None,
            "api_termination_method": api.termination_method if api else None,
            "runtime_preserved": config.keep_runtime,
        })
    return 0 if result == "PASS" else 1
