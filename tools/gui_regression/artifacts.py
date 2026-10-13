"""Failure-safe, secret-redacted GUI run artifacts."""
from __future__ import annotations

import csv
import json
import os
import platform
import re
import subprocess
import sys
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

_SECRET_KEY = re.compile(r"(password|token|authorization|database_url|secret)", re.I)
_URL_CREDENTIALS = re.compile(r"(postgres(?:ql)?(?:\+[a-z0-9_]+)?://)[^@/\s]+@", re.I)
_BEARER = re.compile(r"(Bearer\s+)[^\s'\"]+", re.I)
_JSON_SECRET = re.compile(r'("(?:password|access_token|refresh_token|authorization)"\s*:\s*")[^"]*', re.I)


def redact(value: Any, key: str = "") -> Any:
    if _SECRET_KEY.search(key):
        return "<redacted>"
    if isinstance(value, dict):
        return {str(k): redact(v, str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value]
    if isinstance(value, str):
        value = _URL_CREDENTIALS.sub(r"\1<redacted>@", value)
        value = _BEARER.sub(r"\1<redacted>", value)
        return _JSON_SECRET.sub(r"\1<redacted>", value)
    return value


@dataclass
class Step:
    timestamp: str
    scenario: str
    action: str
    outcome: str
    detail: str = ""


class Artifacts:
    def __init__(self, root: Path, profile: str):
        self.run_id = f"gui-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
        self.path = root / self.run_id
        self.path.mkdir(parents=True, exist_ok=False)
        self.steps: list[Step] = []
        self.profile = profile

    def record(self, scenario: str, action: str, outcome: str = "PASS", detail: str = "") -> None:
        self.steps.append(Step(time.strftime("%Y-%m-%dT%H:%M:%S%z"), scenario, action, outcome, str(redact(detail))))

    def write_json(self, name: str, value: Any) -> Path:
        target = self.path / name
        target.write_text(json.dumps(redact(value), indent=2, sort_keys=True, default=str), encoding="utf-8")
        return target

    def write_text(self, name: str, value: str) -> Path:
        target = self.path / name
        target.write_text(str(redact(value)), encoding="utf-8")
        return target

    def screenshot(self, window, name: str) -> None:
        try:
            wrapper = window.wrapper_object() if hasattr(window, "wrapper_object") else window
            wrapper.capture_as_image().save(self.path / name)
        except Exception as exc:
            self.record("artifacts", "screenshot", "LIMITED", type(exc).__name__)

    def desktop_screenshot(self, name: str) -> None:
        try:
            from PIL import ImageGrab
            ImageGrab.grab(all_screens=True).save(self.path / name)
        except Exception as exc:
            self.record("artifacts", "desktop_screenshot", "LIMITED", type(exc).__name__)

    def sanitize_file(self, path: Path) -> None:
        if not path.exists():
            return
        try:
            path.write_text(str(redact(path.read_text(encoding="utf-8", errors="replace"))), encoding="utf-8")
        except Exception as exc:
            self.record("artifacts", "sanitize_file", "LIMITED", type(exc).__name__)

    def uia_tree(self, window, name: str) -> None:
        try:
            import io
            from contextlib import redirect_stdout
            stream = io.StringIO()
            with redirect_stdout(stream):
                printable = window if hasattr(window, "print_control_identifiers") else window.wrapper_object()
                printable.print_control_identifiers(depth=8)
            self.write_text(name, stream.getvalue())
        except Exception as exc:
            self.record("artifacts", "uia_tree", "LIMITED", type(exc).__name__)

    def environment(self) -> dict[str, str]:
        return {
            "platform": platform.platform(),
            "python": sys.version,
            "profile": self.profile,
            "run_id": self.run_id,
        }

    def finalize(self, result: str, extra: dict[str, Any] | None = None) -> None:
        self.write_json("run.json", {"result": result, "environment": self.environment(), "extra": extra or {}, "steps": [asdict(item) for item in self.steps]})
        with (self.path / "steps.csv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["timestamp", "scenario", "action", "outcome", "detail"])
            writer.writeheader()
            writer.writerows(asdict(item) for item in self.steps)

    def capture_windows_events(self, started: float, ended: float, process_id: int | None, runtime_path: Path) -> bool:
        """Capture only crash events attributable to this process and run interval."""
        if os.name != "nt":
            return False
        start = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(started - 1))
        end = time.strftime("%Y-%m-%dT%H:%M:%S.999Z", time.gmtime(ended + 1))
        query = "*[System[(EventID=1000 or EventID=1001) and TimeCreated[@SystemTime >= '" + start + "' and @SystemTime <= '" + end + "']]]"
        command = ["wevtutil", "qe", "Application", "/q:" + query, "/f:text", "/rd:false"]
        try:
            completed = subprocess.run(command, capture_output=True, text=True, timeout=20, check=False)
            pid_hex = f"0x{process_id:X}" if process_id is not None else ""
            runtime = str(runtime_path).casefold()
            blocks = (completed.stdout or "").split("Event[")
            matched = ["Event[" + block for block in blocks[1:] if pid_hex.casefold() in block.casefold() or runtime in block.casefold()]
            has_match = bool(matched)
            content = "\n\n".join(matched) if matched else "No matching Application Error/WER event for this process and run interval.\n"
            if completed.returncode not in (0, 1):
                # Some locked-down workstations deny wevtutil.  Fall back to the
                # same bounded XPath through PowerShell rather than querying a
                # global recent-events window.
                powershell = [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    "$q=$args[0]; Get-WinEvent -LogName Application -FilterXPath $q -ErrorAction Stop | Format-List * | Out-String",
                    query,
                ]
                fallback = subprocess.run(powershell, capture_output=True, text=True, timeout=20, check=False)
                fallback_blocks = (fallback.stdout or "").split("TimeCreated")
                fallback_matches = ["TimeCreated" + block for block in fallback_blocks[1:] if pid_hex.casefold() in block.casefold() or runtime in block.casefold()]
                if fallback_matches:
                    has_match = True
                    content = "\n\n".join(fallback_matches)
                else:
                    content += "\nwevtutil stderr:\n" + completed.stderr
                    content += "\nGet-WinEvent fallback stderr:\n" + fallback.stderr
            self.write_text("windows-events.txt", content)
            return has_match
        except Exception as exc:
            self.record("artifacts", "windows_events", "LIMITED", type(exc).__name__)
            return False
