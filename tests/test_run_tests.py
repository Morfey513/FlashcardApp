"""Regression coverage for the test runner's native-crash reporting."""

from pathlib import Path
from types import SimpleNamespace

import run_tests


def test_native_pytest_exit_is_logged_and_next_run_uses_fresh_temp(monkeypatch, tmp_path):
    log_file = tmp_path / "test_results.log"
    commands = []

    def crashed_pytest(command, **_kwargs):
        commands.append(command)
        return SimpleNamespace(returncode=-1073740791, stdout="........\n", stderr="")

    monkeypatch.setattr(run_tests, "TEST_LOG_FILE", log_file)
    monkeypatch.setattr(run_tests, "run", crashed_pytest)

    assert run_tests.main() == -1073740791
    assert run_tests.main() == -1073740791

    assert len(commands) == 2  # No coverage gate runs after a native crash.
    basetemps = [next(arg for arg in command if arg.startswith("--basetemp=")) for command in commands]
    assert basetemps[0] != basetemps[1]
    assert all(
        f"-o=cache_dir={Path(base.split('=', 1)[1]) / 'cache'}" in command
        for base, command in zip(basetemps, commands)
    )
    assert log_file.read_text(encoding="utf-8").count("Pytest exited with code") == 2
    assert "0xC0000409" in log_file.read_text(encoding="utf-8")
    assert "Coverage gates did not run" in log_file.read_text(encoding="utf-8")
