# Architectural Decisions

This is the source of truth for architectural decisions on this project.
Read it before changing anything structural (tenancy, data model shape,
payment/notification abstractions, etc.). If a decision here needs to
change, update this file in the same change — do not let the code and this
document drift apart.

Decisions are recorded in the order they were made, not grouped by topic,
so the history stays legible.

---

## Overall style

- **Modular monolith**, not microservices. A single Django project with
  domain-bounded apps (`catalog`, `scheduling`, `booking`, `payments`, etc.).
  No technical justification yet exists for splitting into services; revisit
  only if a concrete scaling or team-boundary problem appears.

## Multi-tenancy

- **Shared database, shared schema, row-level isolation.** Every
  tenant-owned model carries a `salon` FK. Tenant scoping is enforced
  through a shared base manager/queryset, not left to each view to
  remember. Chosen over schema-per-tenant (e.g. `django-tenants`) because
  the migration/ops overhead of schema-per-tenant isn't justified by one
  demo tenant, and shared-schema is easier to write isolation tests against.
- **Tenant resolution: path prefix**, `/api/salons/<slug>/...`. Chosen over
  subdomain-based resolution because it works locally without DNS/hosts-file
  changes. The resolution logic must live in a single, isolated middleware
  component so it can be swapped for subdomain-based resolution later
  without touching every view. **Not yet implemented** — this is a Stage 1
  (tenant + auth foundation) commitment, recorded now so it isn't
  improvised differently when that stage starts.

## Identity: Customer vs. User

- Guest booking is allowed. There is **one `Customer` table for the whole
  platform**, scoped to a salon (`salon` FK), with `name`, `email`, `phone`,
  and a **nullable** FK to `User`.
  - Guest = `Customer` with `user=NULL`.
  - Registered = `Customer` with `user` set.
- **`Appointment` always references `Customer`, never `User` directly.**
  This keeps booking logic identical for guests and registered customers —
  there is exactly one path through the booking code, not two.
- **Email is unique per salon on `Customer`.** A returning guest using the
  same email within the same salon is treated as the same `Customer`
  (updates their existing row rather than creating a duplicate).
- **One `User` may be linked to multiple `Customer` rows** — one per salon,
  since a platform-wide user account can be a customer at more than one
  tenant.
- **Linking a guest `Customer` to a new `User` account happens only after
  email verification.** Never link by phone number — phone numbers are not
  a reliable identity signal (reassigned, unverified, shared).
- **Guests manage their appointment through a single-use signed token link**
  sent by email (view/cancel), not through an account login.
- **Guests cannot leave reviews.** Review submission requires an
  authenticated `User`-linked `Customer`.

## Timezone

- **Single timezone per salon.** Store all timestamps in UTC
  (`USE_TZ = True`, Django's global `TIME_ZONE = "UTC"`). Local-time
  rendering for a given salon is an application-layer concern driven by a
  per-`Salon` timezone field (added when the `tenants` app is built), not a
  global Django setting — this avoids baking in an assumption that gets
  reopened the moment a second salon in a different timezone is onboarded.

## Currency

- **Assumption: UAH**, stated by the product owner. Flagged for
  confirmation because it has downstream effects once the `payments` app
  exists (minor-unit rounding for the 20% deposit, display formatting,
  Stripe currency configuration). Has **no effect on Stage 0** — no models
  or money fields exist yet. Revisit this note when the `payments` app is
  designed, since real Stripe test mode requires knowing the currency
  up front (it affects rounding behavior for the 20% deposit calculation).

## Payments

- **Mock `PaymentProvider` implementation first.** A provider-agnostic
  interface is defined; a Stripe adapter is added later behind the same
  interface. **Tests must never require network access** — the mock
  provider is what test suites exercise, not a sandboxed Stripe.

## Notifications

- **Channel abstraction from day one**, but only an email adapter is
  implemented in the notifications stage. Telegram is added later as a
  second adapter in its own stage, behind the same interface.

## Frontend cadence

- **Backend-first.** No frontend work starts until the booking and payments
  domains are complete on the backend. Avoids building UI against APIs that
  are still shifting shape.

## Dependency versions (Stage 0)

Pins in `backend/requirements/*.txt` are verified against PyPI directly
(`pip index versions`), not assumed from training knowledge, and checked for
mutual compatibility via each package's declared `requires_dist`, not just
"does it install." Two packages are deliberately *not* pinned to their
newest release because the newest release is incompatible with something
else in the stack:

- **`redis` is capped at `6.4.0`**, not the newest `8.1.0`. `kombu`
  (Celery's transport library) declares `redis!=4.5.5,!=5.0.2,<6.5,>=4.5.2`
  for its `redis` extra. `redis-py` 7.x/8.x are not yet supported by Celery's
  transport layer — pinning the newest client would leave the Redis
  broker/result-backend running against an untested, unsupported version.
  `base.txt` uses `celery[redis]` (not a bare `celery` line) specifically so
  pip enforces this constraint automatically on any future version bump,
  instead of relying on a comment staying in sync.
- **`mypy` is capped at `1.19.1`**, not the newest `2.3.0`. `django-stubs`'s
  `compatible-mypy` extra declares `mypy<1.20,>=1.13`. Same reasoning:
  `development.txt` uses `django-stubs[compatible-mypy]` so pip enforces
  this rather than a comment.
- **`django-stubs` is pinned to the `5.2.x` line (`5.2.9`)**, not the newest
  `6.0.9`. `6.0.9` targets Django 6.0 with only partial support for 5.2;
  `5.2.9` is the line built specifically for our pinned Django 5.2.

**Django is pinned to `5.2.17`** — the latest patch of the current LTS line
(5.2), not `6.1` (latest overall release, but not LTS) — per the standing
preference for LTS unless there's a compatibility reason not to.

When bumping any pin later, re-check `requires_dist` for the packages above
before taking "latest," not just whether `pip install` succeeds — a clean
install doesn't guarantee the runtime integration (e.g. Celery↔Redis) was
actually tested against that combination.

## Stage 0 scope note

Stage 0 is infrastructure and project skeleton only: no domain apps, no
models, no API endpoints, no business logic. Settings, Docker, Celery
wiring, and tooling exist so every later stage has a consistent foundation
to build on — nothing in Stage 0 should need to be revisited for
architectural reasons, only extended.
