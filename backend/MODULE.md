# Backend Module

## Responsibility

The `backend/` module contains core application logic, business rules, OCR/CV orchestration, security, validation, persistence, and production readiness checks.

## Layering

```text
app_service.py
  -> parking_service.py
  -> db.py
  -> alpr_service.py / OCR adapters
  -> validators.py
```

## Important Files

| File | Purpose |
|---|---|
| `app_service.py` | Application-level use cases for processing images and confirming entry/exit |
| `parking_service.py` | Ticket lifecycle and business rules |
| `db.py` | SQLite schema and persistence helpers |
| `auth.py` | Users, passwords, session tokens, RBAC |
| `alpr_service.py` | Detection/OCR orchestration and fusion |
| `openai_vision_adapter.py` | 9Router/OpenAI-compatible Vision adapter |
| `plate_format.py` | Vietnamese plate normalization/format support |
| `ocr_quality.py` | OCR quality assessment and uncertainty labels |
| `validators.py` | Input validation |
| `production_readiness.py` | Production readiness checks |

## Business Rule Boundary

All ticket state changes should go through `parking_service.py` or `app_service.py`.

Do not update ticket status directly from UI/API code.

## OCR Policy

Primary OCR:

```text
9Router / OpenAI-compatible provider -> runtime-configured ITS_OPENAI_VISION_MODEL
```

Fallbacks:

- fast-alpr/EasyOCR.
- PaddleOCR.
- lossless identity formatting (no automatic B/8 or O/0 repair).

OCR result policy:

- `is_usable` means format usable, not guaranteed true.
- disagreement must be surfaced, not hidden.
- manual override should be recorded.
- Vision defaults to a fast single request through the configured provider,
  with full-frame context and at most one raw crop. The supported SOL model
  uses low reasoning; no local OCR delays a structured primary response.
- Set `ITS_OPENAI_VISION_VERIFY=true` to restore two readings, high reasoning
  and an enhanced crop. Exact agreement is then required. Neither mode retries
  an abstention to force a guess. Keep human confirmation in both modes.
- Local OCR keeps differing candidates, uses the weaker row's confidence when
  combining rows, and never adds confidence for matching a plate pattern.
- See `../docs/OCR_ACCURACY.md` for budgets, diagnostic limits and deployment.

## Security Policy

- PBKDF2 password hashing.
- Strong JWT secret in production.
- Static bearer tokens disabled in production.
- Role checks must be centralized via auth helpers.
- Database-backed JWT sessions carry an identity source and account auth version.
  Current active state, role and version are checked on every authenticated request.
  Password, role and active-state changes rotate that version atomically; deleted
  and recreated usernames receive a fresh version. Schema version 3 backfills
  existing accounts once without changing their passwords or roles.
- A database username never falls back to environment credentials after a failed
  password check. Environment-only sessions remain a separate identity source.
- Tokens issued before account binding was introduced require a fresh sign-in.
