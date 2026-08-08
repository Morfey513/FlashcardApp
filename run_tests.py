"""Run the test suite and append its complete console output to the test log."""

from datetime import datetime
from subprocess import run
import sys

from src.config import TEST_LOG_FILE


def main():
    result = run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            f"--basetemp={TEST_LOG_FILE.parent / 'pytest-temp'}",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    output = result.stdout + result.stderr
    TEST_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with TEST_LOG_FILE.open("a", encoding="utf-8") as log:
        log.write(f"\n[{datetime.now().isoformat(timespec='seconds')}]\n")
        log.write(output)
    print(output, end="")
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
