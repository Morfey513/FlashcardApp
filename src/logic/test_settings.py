"""Validation and defaults for Class-Only quiz assessment rules."""

DEFAULT_TEST_SETTINGS = {
    "time_limit_minutes": 0,
    "passing_grade_percent": 80,
    "attempt_limit": 1,
    "due_at": None,
    "answer_review_policy": "immediate",
}

ANSWER_REVIEW_POLICIES = ("immediate", "after_due_date", "never")


def normalize_test_settings(value=None):
    """Return a safe, complete settings mapping for persisted quiz data."""
    source = value if isinstance(value, dict) else {}

    def bounded_int(key, default, minimum, maximum):
        try:
            number = int(source.get(key, default))
        except (TypeError, ValueError):
            number = default
        return max(minimum, min(maximum, number))

    review_policy = source.get("answer_review_policy", "immediate")
    if review_policy not in ANSWER_REVIEW_POLICIES:
        review_policy = "immediate"
    return {
        "time_limit_minutes": bounded_int("time_limit_minutes", 0, 0, 1440),
        "passing_grade_percent": bounded_int("passing_grade_percent", 80, 1, 100),
        "attempt_limit": bounded_int("attempt_limit", 1, 0, 100),
        "due_at": source.get("due_at") or None,
        "answer_review_policy": review_policy,
    }
