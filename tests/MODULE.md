# Tests Module

## Responsibility

The `tests/` module protects business rules, API contracts, authentication, OCR behavior, storage, migrations, and production readiness.

## Test Categories

- Auth/RBAC tests.
- API contract and response shape tests.
- Parking lifecycle tests.
- OCR/CV quality tests.
- Production readiness tests.
- Storage and database migration tests.
- Legacy Streamlit compatibility assertions; the delivered UI is the static SPA.
- Web UI error handling, supported uploads, button retry and permissions.
- Concurrent vehicle entry/exit and exactly-once audit/event records.
- Literal ticket search, nested path redaction and effective AI configuration.
- Account-bound JWT revocation across disable/delete/role/password changes,
  restored accounts, environment identity collisions and legacy password upgrades.
- CV readiness redaction for every role, including nested bare `path` fields.

## Rules

- Any business rule change must include tests.
- Any API response shape change must update contract tests.
- Any OCR behavior change must include uncertainty/fusion tests.
- Any production readiness change must update production readiness tests.

## Baseline Command

```powershell
py -3 scripts/run_checks.py
```

Use the latest JUnit / checks-summary and its source-manifest for verified counts. Historical counts are not evidence for edited source.

Preferred command: `python scripts/isolated_checks.py --coverage` (sanitized temporary source and runtime). Real HTTP smoke: `python scripts/demo_acceptance.py --output work/demo-acceptance.json`.

The test runtime database and logs are isolated in a temporary directory before
application modules are imported. Generated sample images can be tested against
the configured provider with `py -3 scripts/run_checks.py --live-vision`.
That opt-in run makes real provider requests and does not create parking tickets.
Synthetic image results are not a field-accuracy estimate.

The 2026-10-29 security remediation suite ran on a disposable source copy without
the deployment `.env`, using dummy credentials and temporary databases. Runtime
smoke checks after restart confirmed schema 3, a successful sign-in and no internal
path fields in the default CV readiness response. No live OCR call was needed.
