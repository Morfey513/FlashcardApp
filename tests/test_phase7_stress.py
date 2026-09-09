"""Focused no-PostgreSQL coverage for the bounded Phase 7 harness."""
from __future__ import annotations

import pytest

from tools.phase7_stress import (
    Observation, PROFILES, RunConfig, aggregate, selected_profiles,
    public_config, validate_database_url, worker_start_delay, write_results,
    cleanup_plan,
)


def test_dry_run_accepts_missing_database_but_live_run_refuses_it():
    RunConfig(dry_run=True).validate()
    with pytest.raises(ValueError, match="must be set"):
        RunConfig().validate()


@pytest.mark.parametrize("url", ["sqlite:///study_buddy_test.db", "postgresql://u:p@localhost/study_buddy"])
def test_database_guard_refuses_non_dedicated_postgresql(url):
    with pytest.raises(ValueError, match="study_buddy_test"):
        validate_database_url(url)


def test_profile_definitions_cover_required_stress_categories():
    assert set(PROFILES) == {
        "multi-account", "same-account-sessions", "assessment-cohort",
        "assessment-different-students", "assessment-terminal-submit", "hot-row",
    }
    assert any(item.name == "session_b_stays_valid" for item in PROFILES["same-account-sessions"].operations)
    assert any(409 in item.expected_statuses for item in PROFILES["assessment-cohort"].operations)
    assert len(selected_profiles("all")) == 6


def test_aggregation_separates_expected_contention_from_failure():
    metrics = aggregate([
        Observation("start", 200, 4, True), Observation("start", 409, 8, True),
        Observation("start", 500, 12, False, "server"),
    ], 1.0)[0]
    assert (metrics.successful, metrics.expected_non_success, metrics.unexpected) == (1, 1, 1)
    assert metrics.statuses == {"200": 1, "409": 1, "500": 1}
    assert metrics.latency_p95_ms == 8


def test_ramp_delays_workers_but_burst_does_not():
    config = RunConfig(dry_run=True, shape="ramp", concurrency=5, ramp_seconds=4)
    assert worker_start_delay(0, config) == 0
    assert worker_start_delay(4, config) == 4
    assert worker_start_delay(2, RunConfig(dry_run=True, shape="burst")) == 0


def test_report_configuration_and_artifacts_never_include_database_credentials(tmp_path):
    config = RunConfig(database_url="postgresql://user:secret@host/study_buddy_test", dry_run=True)
    assert "database_url" not in public_config(config)
    path = tmp_path / "result.json"
    csv_path = tmp_path / "result.csv"
    write_results(aggregate([Observation("read", 200, 1, True)], 1), path, csv_path)
    assert path.exists() and csv_path.exists()
    assert "secret" not in path.read_text(encoding="utf-8")


def test_cleanup_plan_is_explicit_and_dependency_safe():
    plan = cleanup_plan()
    assert plan.index("user_sessions") < plan.index("users")
    assert plan.index("quiz_attempt_answers") < plan.index("quiz_attempts") < plan.index("quizzes")
    assert plan.index("class_members") < plan.index("classes")
    assert "media" in plan and plan.index("media") < plan.index("users")
