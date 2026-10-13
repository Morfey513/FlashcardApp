# Phase 7 external client

This tooling-only mode preserves the established Phase 7 read workload while
moving its HTTP client to W1. It does not add an API endpoint and W1 does not
need a PostgreSQL connection.

## W2: prepare an isolated fixture

Use a PowerShell session whose test URL targets exactly `study_buddy_test`:

```powershell
$env:STUDY_BUDDY_TEST_DATABASE_URL = "postgresql://<user>:<password>@127.0.0.1:5432/study_buddy_test"
.\.venv\Scripts\python.exe tools\phase7_fixture.py prepare --base-url http://10.0.0.20:8000 --concurrency 12
```

The command prints the generated manifest and dedicated media-root paths. The
manifest is written below `.temp/phase7/fixtures/`, which Git ignores. It
contains dynamically generated benchmark credentials, so transfer it to W1
over a trusted local mechanism and do not commit or publish it.

Start the normal API in the same PowerShell process with its database and media
root set to the values used by the fixture:

```powershell
$env:STUDY_BUDDY_DATABASE_URL = $env:STUDY_BUDDY_TEST_DATABASE_URL
$env:STUDY_BUDDY_MEDIA_ROOT = "<media_root printed by prepare>"
.\.venv\Scripts\python.exe -m uvicorn src.api.main:app --host 0.0.0.0 --port 8000
```

Explicit process environment variables take precedence over `.env`. Verify the
normal `/health` and `/ready` endpoints before a run.

## W1: sanity check and external workload

The health check does not require the fixture manifest:

```powershell
.\.venv\Scripts\python.exe tools\phase7_stress.py --base-url http://10.0.0.20:8000 --health-check-only
```

Run the established multi-account workload using the copied manifest. Its
concurrency must match the value used when preparing the fixture:

```powershell
.\.venv\Scripts\python.exe tools\phase7_stress.py --profile multi-account --shape soak --concurrency 12 --requests-per-worker <baseline-value> --soak-seconds <baseline-value> --base-url http://10.0.0.20:8000 --fixture-manifest "<copied-manifest.json>"
```

External result latency is labeled `client_observed_end_to_end`; it includes W1,
LAN transit, W2 FastAPI, W2 PostgreSQL, and the response path. Server-side
timings are intentionally not inferred by W1.

## W2: cleanup

Stop the API process before cleanup so it cannot continue using the fixture,
then run:

```powershell
$env:STUDY_BUDDY_TEST_DATABASE_URL = "postgresql://<user>:<password>@127.0.0.1:5432/study_buddy_test"
.\.venv\Scripts\python.exe tools\phase7_fixture.py cleanup --manifest "<manifest path printed by prepare>"
```

Cleanup validates the manifest, removes only its identity-derived rows and
dedicated media directory, and is safe to repeat. It never truncates or clears
the test database.
