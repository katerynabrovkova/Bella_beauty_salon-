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
- **`Salon.timezone` defaults to `Europe/Kyiv`.** The demo tenant is a Ukrainian
  salon; the field is per-salon and overridable at creation (see § Timezone
  above) — this is only the default for a newly created `Salon` row.
- **`Salon.slot_granularity_minutes` defaults to 15.** The step size the
  availability engine (Stage 6) walks a specialist's open windows in when
  generating candidate start times. Salon-configurable, like the lead-time and
  advance-window defaults above.

## Formatting/linting tooling

- **Consolidated on `ruff format`, dropped `black`.** Stage 0 originally pinned both;
  no reason for running two formatters was ever recorded, and by Stage 2 `ruff format`
  had matured into a deliberately black-compatible formatter (~99.9% identical output),
  making the second tool redundant. Removed `black` from
  `backend/requirements/development.txt`; `[tool.black]` dropped from `pyproject.toml`
  (`ruff format` reads the existing `line-length`/`target-version` from `[tool.ruff]`).
  Checked at a point where the codebase had almost no formatted history yet, so the risk
  from any one-time reformat diff was effectively zero — revisit only if a future need for
  byte-for-byte black compatibility (e.g. an external tool that assumes black output)
  comes up.

## Stage 3 decisions (auth, roles, tenant isolation, guest identity)

- **Tenant-resolution middleware placement: last in `MIDDLEWARE`.** Not because it
  depends on `request.user` (it doesn't — salon resolution is a pure slug lookup, and
  JWT auth runs inside DRF view dispatch, not in `AuthenticationMiddleware`, which only
  populates session-based auth for Django admin). Placed last so the `tenant_context`
  binding window is as narrow as possible — it wraps only the view, not any other
  middleware's request/response processing. Revisit only if a future middleware
  genuinely needs tenant context bound around it.
- **Unknown or inactive salon slug → `404`, not `403`.** The slug is part of the URL
  path, not a credential — a nonexistent salon is a routing miss. `404` also avoids
  confirming/denying slug existence differently to authorized vs. unauthorized callers.
  Both cases resolve through the same query (`Salon.objects.filter(slug=slug,
  is_active=True)`) so there is no code path that could accidentally distinguish them
  in the response.
- **Guest token: signed value, only its hash stored.** `GuestAccessToken` stores
  `token_hash` (SHA-256 of the signed token), never the raw token — a database dump
  must not hand out working links. Validation re-hashes the presented token and looks
  up by hash.
- **Guest token: `cancelled_via_token_at`, not a blanket `consumed_at`.** Viewing and
  cancelling are separate capabilities of the same token; a single "consumed" flag
  would kill view access the moment the guest cancels, which is wrong — they should
  still be able to see the cancelled appointment afterward.
- **Guest token expiry: 30 days after `Appointment.end_datetime`**, not 90. The link
  sits in an inbox indefinitely; a shorter window bounds the blast radius if that
  inbox is compromised or the mail is forwarded, while still covering the realistic
  window for viewing/cancelling a recent booking.
- **Guest token transport: URL fragment in the emailed link, header on the API call.**
  The email links to a frontend route with the token in the URL **fragment**
  (`#token=...`), never a query string. A fragment is never transmitted in any HTTP
  request — not to the frontend server, not in `Referer` to third-party resources the
  page loads — so it reaches no access log anywhere, frontend or backend. Frontend JS
  reads `window.location.hash` client-side and sends the token to the API as an
  `X-Guest-Token` header on view/cancel requests. This is what keeps the token out of
  Django's (and any WSGI server's) request logs, which record method + path + query
  string, not arbitrary headers. Browser history still retains the full URL regardless
  of query-vs-fragment — that residual risk is bounded by the hash-only storage and
  30-day expiry above, not eliminated by transport choice.
- **Throttle rates** (DRF `ScopedRateThrottle`, keyed by IP — all four are pre-auth or
  guest endpoints with no user id to key on): `login` 5/min (blunts credential
  stuffing from one source, allows normal typo-retry); `password_reset` 3/hour and
  `resend_verification` 3/hour (both trigger an email send to a third party, so
  tighter than login — abuse here means spamming someone else's inbox, not just
  guessing a password); `guest_token` 20/min (the token is a signed value, not
  brute-forceable in a human timeframe, so this guards against endpoint hammering
  rather than credential guessing).
- **Registration and password-reset-request never reveal whether an email exists.**
  Both return an identical response (status, body) regardless of whether the email is
  already registered, and enqueue a Celery task either way so response timing doesn't
  diverge on that branch. On a duplicate registration email, a "you already have an
  account" notice is sent instead of creating a second row — the caller-visible
  response is the same either way.
- **DRF throttling requires a shared cache, not the default `LocMemCache`.** DRF's
  throttle classes count requests through the Django cache; `LocMemCache` (the default
  when `CACHES` is unset — true of this project until Stage 3) is per-process, so
  behind N gunicorn/uvicorn workers the effective limit becomes `rate × N`, silently.
  Fixed with Django's built-in `django.core.cache.backends.redis.RedisCache` (no new
  dependency — uses the already-pinned `redis` package), pointed at Redis logical **DB
  2** via `REDIS_CACHE_URL`, kept separate from the Celery broker (DB 0) and result
  backend (DB 1) so throttle keys can never collide with Celery's own.
- **Email verification does not route through the `Notification`/channel abstraction
  described in `docs/ARCHITECTURE.md` § 9, for Stage 3.** `Notification` extends
  `TenantScopedModel`, whose `salon` FK is non-nullable — but registration/email
  verification is a platform-wide `User` event with no salon in scope
  (`/api/v1/auth/...` is explicitly outside the salon prefix, § 13). Reconciling that
  (nullable `salon` on `Notification`, or a different representation for
  salon-less triggers) is Stage 9 (Celery + notifications) work, not Stage 3 — recorded
  here as a known gap rather than silently worked around. Stage 3 sends these emails
  via a small standalone Celery task in `accounts/tasks.py` (plain
  `django.core.mail.send_mail`), with none of the dedup/idempotency machinery
  `Notification` provides — acceptable for now because both underlying operations
  (marking an email verified, requesting a password reset) are themselves idempotent,
  so a duplicate send is a minor annoyance, not a correctness bug.
- **Email verification token: stateless, not single-use, payload includes the target
  email.** `TimestampSigner`-signed `{"user_id", "email"}`, 48h expiry
  (`EMAIL_VERIFICATION_TIMEOUT`). Verifying is idempotent (setting
  `email_verified_at` twice is a no-op), unlike the guest token's *cancel* action,
  which has a real one-time consequence — that asymmetry is why the guest token needs
  a stored single-use record and this one doesn't. Including the target email in the
  signed payload, checked against the user's *current* `email` at verify time, means a
  future "change email" feature gets automatic invalidation of old tokens for free —
  no separate revocation step needed, since a changed email simply stops matching.
- **Password reset uses Django's built-in `PasswordResetTokenGenerator`**, not a
  hand-rolled signer — it's already self-invalidating on password change (the hash it
  produces incorporates the current password hash), which is exactly the single-use
  property this token needs and the verification token doesn't.
  `PASSWORD_RESET_TIMEOUT` is set to 1 hour, tighter than email verification's 48h,
  since a live reset token is the highest-value credential in this scheme and is
  normally acted on within minutes of being requested.
- **`User.username` is dropped; `email` (unique) is `USERNAME_FIELD`, with a custom
  `UserManager`.** Record of how this actually happened, not just what changed:
  - **Not required by JWT.** `djangorestframework-simplejwt` is fully agnostic to
    `USERNAME_FIELD` — `TokenObtainPairView` authenticates against whatever field
    `USERNAME_FIELD` names, `username` included, with zero changes needed on its side.
    Nothing about adding JWT auth forced this.
  - **A less invasive alternative existed and wasn't raised at the time:** keep
    `username` as `AbstractUser` shipped it, add a non-unique `email`, and leave login
    on `username` for Stage 3, deferring "email is the login identity" until it was
    actually load-bearing.
  - **What actually happened:** while implementing Stage 3 sub-step 2, this was
    inferred from `docs/ARCHITECTURE.md` § 3's product-level phrase "standard email +
    password" and written directly into `accounts/models.py` — `username = None`,
    `email` made unique, `USERNAME_FIELD` changed, a new `UserManager` added — without
    surfacing it as a decision first. It was only written up here, in this file,
    *after* the diff already existed, which inverted this file's purpose: it is meant
    to record what was agreed, not to notarize a change after the fact.
  - **Resolution:** the user reviewed the diff, agreed with the outcome (email as
    `USERNAME_FIELD` is right for this product) but not the process, and approved it
    after the fact. The rule this produced — model/manager/migration changes of this
    kind must be raised and approved *before* implementation — is now in `CLAUDE.md`.

## Stage 3 sub-step 3 decisions (roles, permissions, guest identity)

- **`GuestAccessToken` lives in `booking`, not `accounts`, and is a full
  `TenantScopedModel`.** It FKs `Appointment`, and `booking` already depends on
  `accounts` (via `Customer`), never the reverse — putting it in `accounts` would have
  introduced a new backward dependency for one model. As a `TenantScopedModel` it gets
  the standard `salon` FK, the composite `(id, salon)` unique constraint, and a
  `composite_tenant_fk` on its `appointment` FK, same as every other tenant-owned
  model. This works cleanly with the tenant-resolution middleware because the guest
  endpoints are single-object routes nested under `/api/v1/salons/<slug>/...` — tenant
  context is already bound by the time the permission class or view touches
  `GuestAccessToken.objects`. It also means a token issued for one salon, presented
  against a different salon's URL, is simply invisible to the hash lookup (filtered to
  the current tenant first) — cross-salon token misuse collapses into the same
  "not found" path as any other invalid token, with no separate check needed.
- **Every guest-token failure path raises the same `InvalidOrExpiredTokenError`.** Bad
  signature, unknown hash, expired, and — for the cancel action only — a cancel
  capability already spent, all produce the identical 400 response (same code,
  message, status). This runs inside `HasValidGuestToken.has_permission` (not
  `has_object_permission` — see the next decision for why), so DRF's own exception
  propagation carries it to the shared envelope; there's no hand-written branch that
  could leak which case fired. A URL/token appointment mismatch produces the same
  error too, but from a different place — see below.
- **`HasValidGuestToken` does its real validation in `has_permission`, not
  `has_object_permission`, and every view using it must be a DRF generic, not a plain
  `APIView`.** DRF only calls `check_object_permissions()` (and therefore
  `has_object_permission`) when a view explicitly triggers it — its generic views do
  this automatically inside `get_object()`; a plain `APIView` has to call it itself.
  The original version of this permission put all its logic in `has_object_permission`
  and returned `True` unconditionally from `has_permission`, which meant a future view
  that forgot to call `check_object_permissions` (e.g. a list endpoint) would silently
  let every request through. Closed with four layers, not one:
  1. **Fail-closed marker**: `has_permission` requires `guest_token_action` to be
     exactly `"view"` or `"cancel"`, with no default — a view that forgets to declare
     it is denied, not silently treated as `"view"`.
  2. **DRF generics**: both guest views (`booking/views.py`) are now
     `generics.RetrieveAPIView`/`generics.GenericAPIView` subclasses, whose
     `get_object()` calls `check_object_permissions()` automatically — removing "the
     view forgot to call it" as a failure mode for these two endpoints.
  3. **Token-driven object resolution**: `_GuestTokenAppointmentMixin.get_object()`
     resolves the target `Appointment` from `request.guest_access_token.appointment_id`
     (set by `has_permission`), never from the URL's `appointment_id` — so even if
     `check_object_permissions` were somehow skipped, the wrong appointment is never
     fetched in the first place, because the lookup itself is keyed off the token. The
     URL id is still compared and must match, purely so a stale or wrong link fails
     loudly instead of silently ignoring what's in the address bar.
  4. **Test-level backstop**: `tests/test_guest_token_permission_safety.py` walks every
     URL pattern using `HasValidGuestToken` and asserts the view is a DRF generic —
     catches a future plain-`APIView` regression in CI rather than in production.
  None of this is airtight on its own — DRF's object-permission mechanism is
  fundamentally opt-in per view, and no permission class can force
  `check_object_permissions()` to run — so the combination is the mitigation, not any
  single layer. The general rule (not just this one permission class) is now in
  `CLAUDE.md`.
- **The guest -> registered-`User` merge (on email verification) is a per-salon loop
  (`for salon_id in Salon.objects.values_list(...): with tenant_context(salon_id):
  Customer.objects.filter(...).update(user=user)`), not `Customer.unscoped_objects`.**
  `Salon` itself isn't tenant-scoped, so enumerating every salon needs no special
  access, and looping keeps this — the one deliberately cross-tenant operation in
  Stage 3 — narrow and explicit rather than reaching for the broader
  `unscoped_objects` bypass reserved for cases where the salon set isn't already
  known.
- **A guest cancel only handles the two transitions the state machine already
  documents** (`PENDING_PAYMENT`/`CONFIRMED` → `CANCELLED`); any other starting status
  is rejected with a new `InvalidStateTransitionError` (409) — an ordinary,
  distinguishable domain error, not a guest-token security concern, so it doesn't hide
  behind the generic envelope above. Refund eligibility and the full concurrency-safe
  cancellation service layer remain Stage 8 and Stage 7 work respectively; this only
  flips the appointment's own status, with a comment marking where Stage 8's refund
  hook goes.
