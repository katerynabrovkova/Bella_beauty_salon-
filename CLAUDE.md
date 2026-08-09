# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

**Before changing anything architectural — tenancy, data model shape, payment/notification
abstractions, or anything else that isn't a local implementation detail — read
`docs/DECISIONS.md` first.** It is the source of truth for *why* the system is shaped the way
it is. If you make a new architectural decision, record it there in the same change.

## Project purpose

A production-quality, reusable multi-tenant SaaS platform for beauty salons: client-facing
booking (browse services, book a specialist, pay a deposit, manage/cancel appointments, leave
reviews) plus a salon admin back-office, plus an AI assistant grounded in the salon's real
service catalog. The first tenant is a demo "universal" salon (manicure, pedicure, brows,
lashes, sugaring, laser hair removal); the architecture must support additional independent
salons without rework.

This is being built incrementally, stage by stage, per `docs/DECISIONS.md` and direction from
the product owner. Do not build ahead of the current stage — e.g. don't add domain apps,
models, or endpoints that haven't been explicitly scoped yet.

## Tech stack

- **Backend:** Python 3.12, Django 5.1, Django REST Framework (added when the first API stage
  lands), PostgreSQL, Celery + Redis, JWT auth, pytest.
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

## Coding conventions

- Type hints throughout; `mypy` (with `django-stubs`) must pass.
- Formatting/linting: `black` and `ruff`, both configured in `backend/pyproject.toml`.
- Tests: `pytest` + `pytest-django`, against a real PostgreSQL instance.

## Running the project

From the repository root:

```bash
cp .env.example .env        # first time only
docker compose build
docker compose up
```

This starts PostgreSQL, Redis, the Django dev server (`backend`), a Celery worker, and Celery
beat. The backend is served at `http://localhost:8000`.

Run Django management commands inside the `backend` container, e.g.:

```bash
docker compose exec backend python manage.py migrate
docker compose exec backend python manage.py createsuperuser
```

## Running tests and linters

```bash
docker compose exec backend pytest
docker compose exec backend ruff check .
docker compose exec backend black --check .
docker compose exec backend mypy .
```
