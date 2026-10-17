"""Run tests with coverage and append the console output to the test log."""

from datetime import datetime
from pathlib import Path
from subprocess import run
import sys
from uuid import uuid4

from src.config import TEST_LOG_FILE


def main():
    project_root = Path(__file__).resolve().parent
    test_output_root = project_root / ".temp"
    # A prior native Qt crash can leave pytest's fixed basetemp locked on
    # Windows. Give each run a fresh directory so the next run can start.
    pytest_temp = test_output_root / f"pytest-{uuid4().hex}"
    test_result = run(
        [
            sys.executable,
            "-m",
            "pytest",
            str(project_root / "tests"),
            "-q",
            f"--basetemp={pytest_temp}",
            f"-o=cache_dir={pytest_temp / 'cache'}",
            "--cov=src",
            f"--cov-config={project_root / '.coveragerc'}",
            "--cov-report=term-missing",
            "--cov-report=html",
            "--cov-report=xml",
        ],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
    )
    output = test_result.stdout + test_result.stderr
    if test_result.returncode != 0:
        status = f"0x{test_result.returncode & 0xFFFFFFFF:08X}"
        output += (
            f"\nPytest exited with code {test_result.returncode} ({status}). "
            "Coverage gates did not run; any HTML/XML report from this run "
            "may be incomplete.\n"
        )
    controller_result = None
    quiz_controller_result = None
    utility_result = None
    if test_result.returncode == 0:
        controller_result = run(
            [
                sys.executable,
                "-m",
                "coverage",
                "report",
                "--format=total",
                "--include=src/controllers/*.py",
                "--fail-under=80",
            ],
            cwd=project_root,
            capture_output=True,
            text=True,
            check=False,
        )
        output += "\nController coverage gate (minimum 80%):\n"
        output += controller_result.stdout + controller_result.stderr
        quiz_controller_result = run(
            [
                sys.executable,
                "-m",
                "coverage",
                "report",
                "--format=total",
                "--include=src/controllers/quiz_controller.py",
                "--fail-under=80",
            ],
            cwd=project_root,
            capture_output=True,
            text=True,
            check=False,
        )
        output += "\nQuiz/Test Mode controller coverage gate (minimum 80%):\n"
        output += quiz_controller_result.stdout + quiz_controller_result.stderr
        utility_result = run(
            [
                sys.executable,
                "-m",
                "coverage",
                "report",
                "--format=total",
                "--include=src/utils/*.py",
                "--fail-under=90",
            ],
            cwd=project_root,
            capture_output=True,
            text=True,
            check=False,
        )
        output += "\nUtility coverage gate (minimum 90%):\n"
        output += utility_result.stdout + utility_result.stderr
    TEST_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with TEST_LOG_FILE.open("a", encoding="utf-8") as log:
        log.write(f"\n[{datetime.now().isoformat(timespec='seconds')}]\n")
        log.write(output)
    print(output, end="")
    if test_result.returncode != 0:
        return test_result.returncode
    if controller_result and controller_result.returncode != 0:
        return controller_result.returncode
    if quiz_controller_result and quiz_controller_result.returncode != 0:
        return quiz_controller_result.returncode
    return utility_result.returncode if utility_result else 0


if __name__ == "__main__":
    raise SystemExit(main())
