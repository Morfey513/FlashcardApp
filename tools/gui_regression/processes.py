"""Subprocess supervision for the isolated API and one visible Qt process."""
from __future__ import annotations

import socket
import subprocess
import time
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.request import urlopen

import psutil
import win32con
import win32gui
import win32process


NATIVE_EXIT_CODES = {0xC0000005: "access_violation", 0xC0000409: "stack_buffer_overrun"}
# Qt's Windows accessibility provider can surface this COM first-chance
# exception while UI Automation is attached.  It is only non-fatal when the
# observed desktop process remains healthy and exits normally; callers must
# retain it as a diagnostic rather than suppressing it.
NON_FATAL_DIAGNOSTIC_CODES = {0x8001010D: "uia_com_reentrancy"}
_WINDOWS_EXCEPTION = re.compile(r"Windows fatal exception: code 0x([0-9a-fA-F]+)")


def native_exit_name(code: int | None) -> str | None:
    if code is None:
        return None
    return NATIVE_EXIT_CODES.get(code & 0xFFFFFFFF)


def classify_windows_diagnostics(
    stderr: str,
    *,
    exit_code: int | None,
    was_responsive: bool,
    matching_wer_event: bool,
) -> list[dict[str, object]]:
    """Classify faulthandler Windows diagnostics without hiding their output."""
    seen: set[int] = set()
    diagnostics: list[dict[str, object]] = []
    for match in _WINDOWS_EXCEPTION.finditer(stderr or ""):
        code = int(match.group(1), 16)
        if code in seen:
            continue
        seen.add(code)
        known_nonfatal = code in NON_FATAL_DIAGNOSTIC_CODES
        nonfatal = (
            known_nonfatal
            and exit_code == 0
            and was_responsive
            and not matching_wer_event
        )
        diagnostics.append({
            "code": f"0x{code:08X}",
            "name": NON_FATAL_DIAGNOSTIC_CODES.get(code, "unclassified"),
            "classification": "non_fatal_diagnostic" if nonfatal else "requires_review",
        })
    return diagnostics


def free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


@dataclass(frozen=True)
class TopLevelWindow:
    hwnd: int
    title: str
    process_id: int


def visible_windows_for_pid(pid: int) -> list[TopLevelWindow]:
    """Return visible top-level HWNDs without calling the UI Automation provider."""
    result: list[TopLevelWindow] = []

    def collect(hwnd: int, _unused) -> bool:
        _thread_id, owner_pid = win32process.GetWindowThreadProcessId(hwnd)
        if owner_pid == pid and win32gui.IsWindowVisible(hwnd):
            result.append(TopLevelWindow(hwnd, win32gui.GetWindowText(hwnd), owner_pid))
        return True

    try:
        win32gui.EnumWindows(collect, None)
    except win32gui.error as exc:
        raise RuntimeError("cannot enumerate the interactive Windows desktop") from exc
    return result


def visible_windows_for_process_tree(pid: int) -> list[TopLevelWindow]:
    """Include child processes created by a Python/Qt launcher on Windows."""
    process_ids = {pid}
    try:
        process_ids.update(child.pid for child in psutil.Process(pid).children(recursive=True))
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass
    windows: list[TopLevelWindow] = []
    for process_id in process_ids:
        windows.extend(visible_windows_for_pid(process_id))
    return windows


def wait_for_responsive_window(process: "ManagedProcess", timeout: float) -> TopLevelWindow:
    """Wait for a visible, responsive HWND before any pywinauto/UIA operation."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        process.assert_alive()
        for window in visible_windows_for_process_tree(process.pid or -1):
            try:
                # WM_NULL with ABORTIFHUNG confirms that this window can process messages.
                win32gui.SendMessageTimeout(window.hwnd, win32con.WM_NULL, 0, 0, win32con.SMTO_ABORTIFHUNG, 1500)
                return window
            except win32gui.error:
                continue
        time.sleep(0.1)
    raise TimeoutError(f"{process.name} did not create a visible responsive top-level window")


def assert_window_responsive(hwnd: int) -> None:
    """Confirm a specific HWND still belongs to a responsive message loop."""
    if not win32gui.IsWindow(hwnd) or not win32gui.IsWindowVisible(hwnd):
        raise RuntimeError(f"top-level window 0x{hwnd:X} is no longer visible")
    try:
        win32gui.SendMessageTimeout(hwnd, win32con.WM_NULL, 0, 0, win32con.SMTO_ABORTIFHUNG, 1500)
    except win32gui.error as exc:
        raise RuntimeError(f"top-level window 0x{hwnd:X} is unresponsive") from exc


def close_window_normally(hwnd: int, process: "ManagedProcess", timeout: float) -> bool:
    """Request the normal Qt close path first; report rather than hide a forced fallback."""
    process.termination_method = "graceful_wm_close_requested"
    win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
    deadline = time.monotonic() + timeout
    while process.poll() is None and time.monotonic() < deadline:
        time.sleep(0.1)
    return process.poll() is not None


def close_process_windows_normally(process: "ManagedProcess", timeout: float) -> bool:
    """Close every currently visible window owned by this isolated app tree."""
    process.termination_method = "graceful_wm_close_requested"
    for window in visible_windows_for_process_tree(process.pid or -1):
        try:
            win32gui.PostMessage(window.hwnd, win32con.WM_CLOSE, 0, 0)
        except win32gui.error:
            continue
    deadline = time.monotonic() + timeout
    while process.poll() is None and time.monotonic() < deadline:
        time.sleep(0.1)
    return process.poll() is not None


class ManagedProcess:
    def __init__(self, name: str, command: list[str], cwd: Path, environment: dict[str, str], log_dir: Path):
        self.name, self.command, self.cwd, self.environment = name, command, cwd, environment
        self.stdout_path, self.stderr_path = log_dir / f"{name}.stdout.log", log_dir / f"{name}.stderr.log"
        self._stdout = self._stderr = None
        self.process: subprocess.Popen | None = None
        self.observed_exit_code: int | None = None
        self.termination_method = "not_requested"

    def start(self) -> int:
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        self._stdout = self.stdout_path.open("w", encoding="utf-8")
        self._stderr = self.stderr_path.open("w", encoding="utf-8")
        self.process = subprocess.Popen(self.command, cwd=self.cwd, env=self.environment, stdout=self._stdout, stderr=self._stderr, creationflags=creationflags)
        return self.process.pid

    @property
    def pid(self) -> int | None:
        return self.process.pid if self.process else None

    def poll(self) -> int | None:
        code = self.process.poll() if self.process else None
        if code is not None and self.observed_exit_code is None:
            self.observed_exit_code = code
        return code

    def assert_alive(self) -> None:
        code = self.poll()
        if code is not None:
            name = native_exit_name(code)
            suffix = f" ({name}, 0x{code & 0xFFFFFFFF:08X})" if name else f" (exit {code})"
            raise RuntimeError(f"{self.name} terminated unexpectedly{suffix}")

    def terminate(self, timeout: float = 10.0) -> int | None:
        if not self.process:
            return None
        if self.process.poll() is None:
            self.termination_method = "terminate"
            children = self._children()
            self.process.terminate()
            try:
                self.process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                self.kill(timeout)
            self._terminate_children(children)
        return self.poll()

    def kill(self, timeout: float = 10.0) -> int | None:
        if not self.process:
            return None
        if self.process.poll() is None:
            self.termination_method = "kill"
            children = self._children()
            self.process.kill()
            self.process.wait(timeout=timeout)
            self._terminate_children(children)
        return self.poll()

    def _children(self) -> list[psutil.Process]:
        """Avoid leaking an application child after a documented runner-forced stop."""
        if not self.pid:
            return []
        try:
            return psutil.Process(self.pid).children(recursive=True)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return []

    def _terminate_children(self, children: list[psutil.Process]) -> None:
        for child in children:
            try:
                child.terminate()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

    def close_streams(self) -> None:
        for stream in (self._stdout, self._stderr):
            if stream:
                stream.close()


class ProcDumpMonitor:
    """Optional, external crash dumper; it never restarts the desktop app."""
    def __init__(self, executable: Path, process_id: int, artifact_dir: Path):
        self.process_id = process_id
        self.stdout_path = artifact_dir / "procdump.stdout.log"
        self.stderr_path = artifact_dir / "procdump.stderr.log"
        self._stdout = self.stdout_path.open("w", encoding="utf-8")
        self._stderr = self.stderr_path.open("w", encoding="utf-8")
        self.process = subprocess.Popen(
            [str(executable), "-accepteula", "-e", "-ma", "-x", str(artifact_dir), str(process_id)],
            stdout=self._stdout, stderr=self._stderr,
        )

    def stop(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
        self._stdout.close()
        self._stderr.close()


def wait_ready(base_url: str, server: ManagedProcess, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        server.assert_alive()
        try:
            with urlopen(base_url + "/ready", timeout=2) as response:
                if response.status == 200:
                    return
        except Exception:
            time.sleep(0.2)
    raise TimeoutError("API did not become ready")


def is_hung(pid: int) -> bool:
    """Process-only fallback; HWND responsiveness is checked by wait_for_responsive_window."""
    try:
        return psutil.Process(pid).status() == psutil.STATUS_ZOMBIE
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return True
