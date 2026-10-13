"""Unit coverage for isolated Phase 7 fixture and external-client tooling."""
from __future__ import annotations

import json
from contextlib import contextmanager
from urllib.parse import urlsplit

import pytest
import sqlalchemy

import tools.phase7_stress as stress
from tools.phase7_fixture import (
    build_fixture_manifest,
    cleanup_fixture_rows,
    validate_database_url,
    validate_manifest,
)


def seeded_manifest(*, concurrency: int = 2, base_url: str = "http://10.0.0.20:8000") -> dict:
    manifest = build_fixture_manifest(concurrency, base_url)
    manifest["content_ids"]["media"] = f"{manifest['fixture_id']}-media"
    manifest["content_ids"]["content_version"] = 1
    return validate_manifest(manifest)


@pytest.mark.parametrize(
    "url",
    (
        "postgresql://user:password@localhost/study_buddy",
        "postgresql://user:password@localhost/study_buddy_test_extra",
        "sqlite:///study_buddy_test",
    ),
)
def test_fixture_database_guard_requires_exact_test_database(url):
    with pytest.raises(ValueError, match="study_buddy_test"):
        validate_database_url(url)


def test_fixture_ids_and_credentials_are_unique_and_identity_derived():
    first = build_fixture_manifest(4, "http://10.0.0.20:8000")
    second = build_fixture_manifest(4, "http://10.0.0.20:8000")
    assert first["fixture_id"] != second["fixture_id"]
    assert first["accounts"]["password"] != second["accounts"]["password"]
    assert len(first["accounts"]["students"]) == 4
    changed = seeded_manifest()
    changed["content_ids"]["quizzes"]["primary"] = "somebody-elses-quiz"
    with pytest.raises(ValueError, match="identifiers"):
        validate_manifest(changed)


def test_cleanup_statements_are_scoped_and_cleanup_is_repeatable():
    statements = []

    class FakeSession:
        def execute(self, statement):
            statements.append(statement)

    class FakeSessions:
        @contextmanager
        def begin(self):
            yield FakeSession()

    manifest = seeded_manifest()
    cleanup_fixture_rows(FakeSessions(), manifest)
    first_count = len(statements)
    cleanup_fixture_rows(FakeSessions(), manifest)
    assert len(statements) == first_count * 2
    assert first_count > 0
    assert all(" WHERE " in f" {statement} " for statement in statements)
    rendered = "\n".join(str(statement) for statement in statements)
    assert "LIKE" not in rendered.upper()


class FakeResponse:
    def __init__(self, status=200, payload=None):
        self.status = status
        self.payload = payload if payload is not None else {}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def test_external_mode_is_http_only_uses_manifest_credentials_and_base_url(monkeypatch):
    manifest = seeded_manifest()
    requests = []

    def fake_urlopen(request, timeout):
        url = request if isinstance(request, str) else request.full_url
        requests.append((url, None if isinstance(request, str) else request.data))
        path = urlsplit(url).path
        if path == "/api/v1/auth/login":
            body = json.loads(request.data)
            assert body["password"] == manifest["accounts"]["password"]
            assert body["login"] in {item["username"] for item in manifest["accounts"]["students"]}
            return FakeResponse(payload={"access_token": f"token-{body['login']}"})
        return FakeResponse()

    monkeypatch.setattr(stress, "urlopen", fake_urlopen)
    monkeypatch.setattr(stress, "_start_server", lambda _app: pytest.fail("external mode started FastAPI"))
    monkeypatch.setattr(sqlalchemy, "create_engine", lambda *_args, **_kwargs: pytest.fail("external mode accessed PostgreSQL"))
    config = stress.RunConfig(
        profile="multi-account", shape="burst", concurrency=2,
        requests_per_worker=1, external=True,
    )
    metrics, fixture, observations = stress.run_external(config, manifest, manifest["base_url"])
    assert metrics and observations
    assert fixture["mode"] == "external-http-client"
    assert fixture["latency_scope"] == "client_observed_end_to_end"
    assert all(url.startswith("http://10.0.0.20:8000/") for url, _body in requests)
    assert any(url.endswith("/health") for url, _body in requests)
    assert any(url.endswith("/ready") for url, _body in requests)
    assert {item.operation for item in observations} >= {
        "login", "available_metadata", "preview", "practice_download",
        "media_manifest", "media_read", "restricted_denied",
    }


def test_external_mode_rejects_manifest_url_or_concurrency_mismatch(monkeypatch):
    manifest = seeded_manifest()
    config = stress.RunConfig(profile="multi-account", concurrency=2, external=True)
    with pytest.raises(ValueError, match="base_url"):
        stress.run_external(config, manifest, "http://10.0.0.21:8000")
    with pytest.raises(ValueError, match="concurrency"):
        stress.run_external(
            stress.RunConfig(profile="multi-account", concurrency=3, external=True),
            manifest,
            manifest["base_url"],
        )
