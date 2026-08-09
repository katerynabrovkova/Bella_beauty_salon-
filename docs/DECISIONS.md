# Architectural Decisions

This is the source of truth for architectural decisions on this project.
Read it before changing anything structural (tenancy, data model shape,
payment/notification abstractions, etc.). If a decision here needs to
change, update this file in the same change — do not let the code and this
document drift apart.

Decisions are recorded in the order they were made, not grouped by topic,
so the history stays legible.

---

## Agreed stage order

The project is built one stage at a time, in this order. Do not implement
ahead of the current stage. When a decision elsewhere in this file
references "Stage N," it refers to this list — keep those references in
sync if the order ever changes.

0. Scaffolding (done)
1. Detailed backend architecture, written to `docs/ARCHITECTURE.md`, no code
2. Domain models + migrations
3. Auth, roles, tenant isolation, guest identity
4. Catalog (categories, services)
5. Specialists + reviews — read-only
6. Availability engine — pure slot computation, read-only, heavily unit-tested
7. Booking core — creation, statuses, cancellation, concurrency
8. Payments — provider abstraction, deposit, webhooks, refunds
9. Celery + notifications (email + channel abstraction)
10. Telegram adapter
11. Review submission (completed-appointment gating)
12. Frontend skeleton — design system, API client, auth
13. Frontend catalog / service / specialists / reviews
14. Frontend booking flow + payment + confirmation
15. Frontend customer account + guest token management
16. AI assistant backend
17. AI assistant frontend widget
18. Admin shell + dashboard + appointments list
19. Admin calendar + appointment create/edit
20. Admin services, specialists, working hours, days off
21. Admin clients, reviews, notifications, statistics
22. Productionization — Docker, CI/CD, README
23. Production-readiness audit (fresh session)

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
  without touching every view. **Not yet implemented** — this is a Stage 3
  (auth, roles, tenant isolation, guest identity) commitment, recorded now
  so it isn't improvised differently when that stage starts.

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

## Business rules

Recorded here because these are product decisions that must survive a fresh
session, not architectural shape — `docs/ARCHITECTURE.md` describes the mechanisms
that implement them; this section is the source of truth for the actual numbers, so
they are stated once, not duplicated.

- **Deposit: 20% of service price, paid online at booking.** A single salon-wide
  setting (`Salon.deposit_percentage`, default 20%), not overridable per service in
  v1 — add a per-service override only if a real salon actually asks for one.
- **The remaining 80% is paid in person at the salon.** Not tracked or collected by
  the platform in any form.
- **Cancellation refund depends on WHO cancelled, not only WHEN.** For a
  customer-initiated cancellation: ≥ 24 hours before appointment start, deposit
  refunded; < 24 hours before start, deposit forfeited (a single cutoff, no
  tiered/partial refund). For a **salon-initiated cancellation** (specialist
  illness, `TimeOff` added over an already-booked slot, a working-hours change that
  displaces a booking, etc.), the deposit is **always fully refunded regardless of
  timing** — the customer is never penalized for a change the salon made.
  `Appointment.cancelled_by` is what refund eligibility is computed from; it is not
  a bare time comparison.
- **Staff changes to `TimeOff`/`WorkingHours` that conflict with an existing
  appointment must be detected and explicitly resolved — never silently orphaned.**
  Affected customers are offered: rebook with another specialist who performs the
  same service, rebook with the same specialist at a later time, or cancel with a
  full refund (the salon-initiated-cancellation rule above). The resolution UI/flow
  itself is Stage 19 (admin calendar) work, not Stage 2 — this only records that the
  Stage 2 data model must be able to represent the conflict and that the
  Stage 7/8 cancellation path must support a salon-initiated, always-refunded
  cancellation reason.
- **Reviews require a `COMPLETED` appointment; exactly one review per appointment.**
  Guests cannot review (see § Identity above). Reviews are immutable once posted and
  the salon cannot post a public reply in v1; staff can hide a review, but deletion
  is not exposed to anyone.
- **Appointment completion is an automatic scheduled transition**
  (`CONFIRMED → COMPLETED` once `end_datetime` passes), with a staff override
  available in the admin for correcting mistakes. Automatic because review
  eligibility depends on `COMPLETED`, and that can't be left waiting on a staff
  member remembering to mark every appointment.
- **`NO_SHOW` is a staff-marked appointment status with no automatic effects in
  v1** — no customer penalty, and the deposit is already forfeited by that point
  regardless. It exists purely for admin record-keeping and statistics; revisit
  once there's a real pattern worth reacting to.
- **Booking window: minimum 3 hours' lead time, maximum 60 days in advance.**
  Salon-configurable; these are the defaults.
- **A `PENDING_PAYMENT` appointment holds its slot for 15 minutes before the
  expiry sweep releases it.** Fixed for v1, not salon-configurable — this is a
  payment-UX parameter, not a business lever a salon would tune. Reasoning: long
  enough to complete a card payment including a 3-D-Secure challenge (which
  normally resolves in well under 10 minutes), short enough that an abandoned or
  malicious checkout only blocks a slot briefly rather than making it trivially
  blockable for an extended window.
- **Service buffer time blocks the calendar but is never itself offered as a
  bookable start.** E.g. a 90-minute service with a 15-minute buffer occupies 105
  minutes of the specialist's schedule; a following appointment may start exactly
  when the buffer ends. Buffer is set per service (equipment/room turnaround
  differs by service), not a salon-wide value. See `docs/ARCHITECTURE.md` § 6–7 for
  the mechanism, including how it's enforced in the double-booking exclusion
  constraint.
- **No specialist logins in this build.** Specialists are managed entirely by
  salon staff/admin; add specialist accounts only if a later stage needs them.
- **One `SalonStaff` role for v1.** The `role` field is kept on the model so a
  second role can be added later without a shape migration — only the field's
  value space grows.
- **The AI assistant only ever proposes a service and slot; it never creates a
  binding appointment directly.** The user must confirm through the normal booking
  flow, which is what actually calls the booking service layer. Chosen over letting
  the assistant book directly because a hallucinated parameter should never be able
  to produce a real, paid appointment.
- **AI assistant memory is session-only, for every customer including logged-in
  ones — nothing is persisted to a database.** Held in Redis with a TTL instead
  (see `docs/ARCHITECTURE.md` § 10). Salon chat routinely surfaces health-adjacent
  personal information (skin conditions, allergies, treatment contraindications);
  the deliberate choice is to not retain that by default for anyone, rather than
  carve out an exception for logged-in customers.
