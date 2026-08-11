# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

**Before changing anything architectural — tenancy, data model shape, payment/notification
abstractions, or anything else that isn't a local implementation detail — read
`docs/DECISIONS.md` first.** It is the source of truth for *why* the system is shaped the way
it is. If you make a new architectural decision, record it there in the same change.

**`docs/DECISIONS.md` records what was agreed, not what you concluded.** Never write an
entry there to notarize a change you already made — if a decision needed approval and
didn't get it first, the write-up must say so plainly (what changed, what alternative
existed, that approval came after the fact), not read as if it were agreed in advance.

**The following require an explicit decision point, raised and approved *before* you
write the change, never folded into a diff for later review:** any change to
`AUTH_USER_MODEL` or its shape, any change to a model's `Meta` (constraints, ordering,
managers), any change to which manager is default/first-declared, and any migration
containing `RemoveField`, `AlterField`, or `DeleteModel`. Generating the migration to see
what it contains is fine; applying it, or writing the model change that produces it,
is not, until approved.

## Stage-by-stage workflow

This project is built one stage at a time, in the order recorded in
`docs/DECISIONS.md` under "Agreed stage order." Do not implement ahead of the
current stage — e.g. don't add domain apps, models, or endpoints that belong
to a later stage.

Before implementing any stage:

1. Analyze the requirements for that stage.
2. Explain the proposed approach.
3. State assumptions explicitly — do not silently invent requirements.
4. Identify edge cases.
5. Propose the relevant files/architecture.
6. **Wait for explicit instruction before writing code.**

When implementing:

- Make small, logically grouped changes; don't rewrite unrelated code.
- Don't silently change architecture — if something in `docs/DECISIONS.md`
  needs to change, say so and update it in the same change.
- Run the relevant tests/checks after implementing and report the results.

## Project purpose

A production-quality, reusable multi-tenant SaaS platform for beauty salons: client-facing
booking (browse services, book a specialist, pay a deposit, manage/cancel appointments, leave
reviews) plus a salon admin back-office, plus an AI assistant grounded in the salon's real
service catalog. The first tenant is a demo "universal" salon (manicure, pedicure, brows,
lashes, sugaring, laser hair removal); the architecture must support additional independent
salons without rework.

## Tech stack

- **Backend:** Python, Django, PostgreSQL, Celery + Redis, pytest — wired up as of Stage 0.
  Django REST Framework and JWT auth (DRF SimpleJWT) landed in Stage 3. OpenAPI/Swagger is
  still part of the plan but **not yet added** (lands with the stage that needs it, per
  `docs/DECISIONS.md`'s stage order). Exact
  versions live in `backend/requirements/*.txt`, not here — that file is the source of truth
  and this one will drift if it restates numbers. Version-compatibility reasoning (LTS choice,
  why some packages are deliberately not pinned to their newest release) lives in
  `docs/DECISIONS.md`.
- **Frontend:** Next.js / React, TypeScript (not started yet — backend-first, see
  `docs/DECISIONS.md`).
- **AI:** LLM access through a provider-agnostic abstraction (not started yet).
- Everything runs in Docker locally; **PostgreSQL is the database in every environment,
  including tests — never SQLite.**

## Architectural rules

- Modular monolith: one Django project, domain-bounded apps (`catalog`, `scheduling`,
  `booking`, `payments`, `notifications`, `reviews`, `ai_assistant`, etc.). No microservices
  without a concrete technical justification.
- Multi-tenancy is shared-database/shared-schema with row-level isolation: every tenant-owned
  model carries a `salon` FK, enforced through a shared base manager/queryset — never rely on
  each view remembering to filter by tenant.
- On every `TenantScopedModel` subclass, `objects` must be declared before `unscoped_objects`.
  Django treats the first manager declared in a model body as its default manager regardless of
  name; reordering would silently make the unfiltered `unscoped_objects` manager the default,
  defeating tenant isolation wherever Django uses the default manager internally (reverse
  relations, admin, etc.). ruff's DJ012 actively suggests this reorder as a style fix — the
  `# noqa: DJ012` on `unscoped_objects` in `core/models.py` is deliberate; do not "fix" it.
- `Appointment` always references `Customer`, never `User` directly — see `docs/DECISIONS.md`
  for the guest/registered customer model.
- Business logic (availability computation, cancellation/refund eligibility, booking
  concurrency guarantees) lives in a service layer, not in views/serializers, so it's testable
  independently and reusable from Celery tasks and the AI assistant.
- External integrations (payments, notifications) are built behind a provider interface first,
  with a real adapter (Stripe, email, Telegram, ...) added behind it — never coupled directly
  to one vendor's SDK from business logic. Tests must never require network access.
- No hardcoded secrets or credentials, ever. All configuration is environment-driven
  (`django-environ`); `.env` is gitignored, `.env.example` documents every variable.
- **DRF object-level permissions (`has_object_permission`) never fire on their own for
  list/collection views** — DRF only calls `check_object_permissions()` when a view
  explicitly triggers it (its generic views do this automatically inside
  `get_object()`; a plain `APIView` must call it itself). A permission class that puts
  its real check only in `has_object_permission` is a silent no-op on any view shape
  that never reaches that call — nothing stops a future list endpoint from citing that
  permission class and exposing everything. Every permission class must therefore
  enforce in `has_permission` whatever it can without the object (explicit required
  marker attributes with no silently-safe default, credential/token validation that
  doesn't depend on the specific object, etc.), and object-scoped views should prefer
  DRF generics specifically because their `get_object()` guarantees the call. See
  `core/permissions.py`'s `HasValidGuestToken` and `booking/views.py`'s
  `_GuestTokenAppointmentMixin` for the pattern: `has_permission` does the real
  validation and resolves which object to act on from the credential itself (never
  from a URL parameter, which a view could be tricked into using without the
  corresponding object-permission check ever running); `has_object_permission` is only
  a redundant confirmation once the object is fetched.

## Coding conventions

- Type hints throughout; `mypy` (with `django-stubs`) must pass.
- Formatting/linting: `ruff` (lint + format), configured in `backend/pyproject.toml`.
- Tests: `pytest` + `pytest-django`, against a real PostgreSQL instance.

## Running the project

From the repository root:

```bash
cp .env.example .env        # first time only
docker compose build
```

`.env.example` ships `DJANGO_SECRET_KEY=change-me-to-a-random-value-in-every-environment` as a
literal placeholder — it is not safe to run with as-is. Generate a real one and put it in
`.env`:

```bash
docker compose run --rm backend python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

```bash
docker compose up
```

This starts PostgreSQL, Redis, the Django dev server (`backend`), a Celery worker, and Celery
beat. The backend is served on `http://localhost:${HOST_BACKEND_PORT}` (default `8000`).
Postgres, Redis, and the backend each have an independently configurable host port
(`HOST_DB_PORT` / `HOST_REDIS_PORT` / `HOST_BACKEND_PORT` in `.env`) — the in-network service
addresses (`db:5432`, `redis:6379`) never change, only what's exposed to your machine. Override
these when the defaults collide with another project's containers on the same host.

Run Django management commands inside the `backend` container, e.g.:

```bash
docker compose exec backend python manage.py migrate
docker compose exec backend python manage.py createsuperuser
```

## Running tests and linters

```bash
docker compose exec backend pytest
docker compose exec backend ruff check .
docker compose exec backend ruff format --check .
docker compose exec backend mypy .
```
