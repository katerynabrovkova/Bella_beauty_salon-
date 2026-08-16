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
1. Detailed backend architecture, written to `docs/ARCHITECTURE.md`, no code (done)
2. Domain models + migrations (done)
3. Auth, roles, tenant isolation, guest identity (done)
4. Catalog (categories, services) (done)
5. Specialists — full CRUD (read public, writes gated by IsSalonStaff — same split as Stage 4 catalog) (done)
6. Availability engine — pure slot computation, read-only, heavily unit-tested
7. Booking core — creation, statuses, cancellation, concurrency
8. Payments — provider abstraction, deposit, webhooks, refunds
9. Celery + notifications (email + channel abstraction)
10. Telegram adapter
11. Reviews — read endpoints and submission (completed-appointment gating)
11.5. Content localization — per-salon language settings, translatable content
    across catalog, salon profile, and notification templates. Numbered 11.5,
    not renumbered into the sequence, so it doesn't invalidate every existing
    `Stage N` reference elsewhere in this file, `ARCHITECTURE.md`, and code
    comments for a placement that doesn't require it.
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

## Open questions

Not yet decided — recorded here so they surface before the stages that depend
on them, rather than being forgotten and improvised in the moment.

- **Business model: one-off site sale vs. recurring SaaS subscription.**
  Affects the stages covering salon onboarding, plans, and billing. Decision
  needed before those stages.
- **Tenant resolution source: URL path prefix only, or also custom domain per
  salon.** Currently path prefix only (Stage 3 middleware, § Multi-tenancy
  below). Adding domain-based resolution would be additive to the existing
  middleware, not a rewrite. Decision needed before the public frontend stage.
- **Salon-level closure/holiday model.** No salon-wide closure exists today —
  only per-specialist `TimeOff` (§ Stage 6 decisions). Needed before the
  admin calendar stage (Stage 19/20), which is where staff would actually
  declare a closure.
- **Overlap-prevention validation on `WorkingHours`.** Nothing today stops
  two overlapping rows for the same specialist/day being saved (no
  uniqueness constraint, no `clean()`, admin-writable) — the availability
  engine defends itself by merging overlapping rows at ingestion time (§
  Stage 6 decisions), but the write side has no equivalent guard. Add
  validation when `WorkingHours` gains a real write API (Stage 20); until
  then the merge is the only protection.
- **Buffer-at-shift-end rule revisit.** Stage 6 requires the buffer to fit
  inside the specialist's own working window (§ Stage 6 decisions), because
  no salon-level closing time exists yet to compare against. Once salon
  working hours (or the closure model above) exist, the rule should become
  "buffer must fit before the earlier of specialist shift end and salon
  closing time," so a specialist who finishes before the salon closes
  doesn't lose a slot needlessly. Revisit alongside the closure model
  decision.
- **Blocker provenance through the availability engine.**
  `compute_open_windows` (§ Stage 6.D decisions) flattens every blocking
  source — `TimeOff`, `Appointment`, and any future closure source — into
  indistinguishable `Window`s before subtraction. If a future consumer
  (e.g. Stage 19's admin calendar, or the AI assistant) needs to explain
  *why* a specific slot is unavailable, this loses that information by
  design. Not solved now: the one imagined use case can read the
  underlying rows directly instead.
- **`Salon.timezone` write-time validation.** Nothing currently validates
  that `Salon.timezone` is a real IANA zone name at write time (model,
  serializer, or admin form) — a malformed value would only surface as an
  unhandled `zoneinfo.ZoneInfoNotFoundError` the first time
  `scheduling.compute_open_windows` tries to resolve it (§ Stage 6
  decisions), from the orchestrator specifically, by deliberate placement —
  not read-time defended against there either. Needs a decision on where the
  validation belongs, and whether a bad existing value should be caught and
  translated into a clearer error or left as an uncaught 500, since it would
  indicate corrupted configuration data, not user input.
- **Lower-bound validation on `Salon.slot_granularity_minutes` and
  `Service.duration_minutes` at the model level.** Today
  `Service.duration_minutes >= 1` is enforced only in `catalog/serializers.py`
  (`min_value=1`), not at the model/DB layer, and
  `Salon.slot_granularity_minutes` has no lower-bound enforcement anywhere —
  no serializer exists for `Salon` yet, and the admin form has no validator.
  `scheduling._step_windows` (§ Stage 6.E decisions) now guards against
  `granularity_minutes <= 0` / `occupied_minutes <= 0` at read time, but that
  guard exists precisely because the write side has no equivalent one; the
  real fix is closing the gap at the source. Needed by Stage 19/20, when
  salon settings (and possibly `Service`) get a write API.
- **`compute_candidate_start_times`'s `salon` argument is not checked
  against `specialist.salon`.** (§ Stage 6.E decisions.) The orchestrator
  takes `specialist: Specialist` and `salon: Salon` as two independent
  parameters; nothing in `scheduling/services.py`, `TenantScopedManager`, or
  anywhere else verifies the caller passed the specialist's actual salon.
  Passing a mismatched `salon` would silently resolve
  `granularity_minutes` from the wrong tenant's settings and localize the
  specialist's real `WorkingHours` against the wrong tenant's timezone —
  wrong output, not a crash, and nothing in the current test suite would
  catch it either since query counts and return values would both look
  superficially plausible. No guard added yet (deliberately, per the 6.E
  design decision) — needs a decision on whether this belongs in 6.E itself
  (e.g. `assert specialist.salon_id == salon.id`, or deriving `salon` from
  `specialist.salon` after all and accepting the extra query) or stays
  documented-only on the theory that every real caller already gets both
  objects from the same tenant-scoped request context and could not produce
  a mismatch without a bug elsewhere that unit tests on this function alone
  wouldn't be positioned to catch regardless. **6.F widens the blast
  radius:** a mismatched `salon` now also supplies the lead time and the
  max-advance window, on top of granularity and timezone. Also, correct the
  cost argument this entry originally implied: a guard does not cost a
  fourth query — `specialist.salon_id` is a plain column on the
  already-loaded row (verified in § Stage 6.F decisions), and only
  `specialist.salon` (the lazy relation) would fire one. The affordability
  objection therefore does not apply; what remains is a judgement call about
  likelihood, not cost.
- **Local-time presentation across a DST transition** — on a spring-forward
  day the candidate list jumps (…01:40, 02:00, 03:00, 03:20…) because 02:xx
  does not exist locally. Whether to show that as-is, label it, or suppress
  the affected candidates is a presentation decision belonging to the
  local-time formatting substage, not to stepping.
- **Max-advance boundary computed as local midnight can land on a
  non-existent local time.** (§ Stage 6.F decisions.) The boundary is
  midnight at the start of the day following `today + max_advance_days`, in
  the salon's timezone. In IANA zones whose DST transition happens exactly
  at midnight (e.g. `America/Santiago`, `America/Havana`), that local
  midnight does not exist on one day per year, and `zoneinfo` resolves a
  non-existent local time by shifting rather than raising — so the boundary
  would silently move by an hour for that salon on that day. Not defended
  against now: `Salon.timezone` defaults to `Europe/Kyiv`, which transitions
  at 03:00, not midnight. But `Salon.timezone` is already a per-salon field
  accepting any zone string (§ `Salon.timezone` write-time validation,
  above), so this does not require international expansion to trigger — a
  single salon configured with such a zone is enough. This is a different
  question from "Local-time presentation across a DST transition" directly
  above, which is about what to *display*; this one is about where the
  boundary silently *moves to*. Do not merge them.
- **Per-specialist service duration and the "any specialist" union rule.**
  Today `occupied_minutes` (`service.duration_minutes +
  service.buffer_minutes`) is identical for every specialist in the union —
  `Service.duration_minutes`/`buffer_minutes` are single fields on
  `catalog.Service`, and `SpecialistService` (the through-model) carries no
  per-specialist override of either — so "free" is unambiguous: the same
  occupied span is checked against every qualifying specialist's calendar.
  If per-specialist duration overrides are ever introduced, the union rule
  (§ Stage 6 decisions, "Multi-specialist availability") needs revisiting —
  "at least one specialist free" would then mean free for *that
  specialist's own* duration, not a shared one, which changes what a bare
  time in the response actually promises.
- **`compute_multi_specialist_availability` query count is ~`1 + 3*N`**
  (§ Stage 6.H decisions) — one query for `_fetch_qualifying_specialists`,
  plus `compute_candidate_start_times`'s own three queries per qualifying
  specialist. Confirmed exact, not just an upper bound: every specialist
  reaching the loop is already `is_active=True`, so `compute_open_windows`'s
  own `is_active` early return, which would otherwise skip those three
  queries, never fires. Accepted N+1 for now; revisit if salons routinely
  have many specialists per service. Tests assert this as a formula of N,
  not a fixed number.
- **Specialist experience/seniority as a structured field.** Today experience is
  not modelled — a specialist can mention years of experience in the free-text
  `bio` field, but there is no structured `experience_years` (or similar) on the
  `Specialist` model. The Stage 6.J specialist-picker mockup showed both options;
  the free-text approach was chosen for Stage 6 because seniority is a specialist-
  profile concern, not an availability-engine one, and adding a field mid-Stage-6
  would pull in its own sub-decisions. A structured field is wanted later (frontend
  specialist-profile / admin stage, ~Stage 13). Key sub-decision when it lands:
  store a raw number ("8 years") vs. a career-start date/year. A raw number freezes
  and goes stale (it will still read "8" two years on); a start date recomputes
  itself and never lies — lean toward the date. Decide before the specialist-profile
  frontend stage.

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

## Stage 3 sub-step 4 decisions (Django admin, Stage 3 cleanup)

- **`core.admin.SalonScopedAdmin` is a deliberate, blanket cross-tenant tool for
  platform operators, not a per-salon back office.** Every salon's data is visible
  together in `/admin/` by design — that's Django `is_staff`/`is_superuser` territory
  (`docs/ARCHITECTURE.md` § 4's "Platform superuser" role), not the product back
  office, which is Stages 18–21, built on the JWT + `IsSalonStaff` API surface
  instead. It overrides `get_queryset` (list views) to read through
  `unscoped_objects`, since admin requests never bind tenant context the way
  `/api/v1/salons/<slug>/...` requests do. It also overrides
  `formfield_for_foreignkey`, which turned out to need more than just supplying a
  `queryset` kwarg: Django's `ForeignKey.formfield()` unconditionally evaluates the
  related model's `_default_manager` while building its own `defaults` dict, *before*
  applying any `queryset` override passed in — so opening the add/change form for a
  model with a FK to another `TenantScopedModel` (e.g. `Service` → `ServiceCategory`)
  still 500s unless *something* is bound. The fix binds a throwaway sentinel tenant
  (`tenant_context(-1)`) around that one call — the eagerly-computed queryset it
  produces is immediately discarded in favor of the real `unscoped_objects` one, so
  which id is bound doesn't matter, only that one is. Found by a test
  (`test_service_add_form_renders_without_a_bound_tenant`) that actually opened the
  form rather than only checking the changelist.
- **`GuestAccessToken` is registered, read-only.** `token_hash` is a SHA-256 hash, not
  the raw token — the entire reason it's hashed (this file, Stage 3 sub-step 3
  decisions) is that knowing the hash doesn't grant access, so showing it to an
  authorized platform operator isn't equivalent to leaking a working link, and it has
  real support value (did this guest's link get used? when does it expire?).
  Read-only because rows are only ever meant to come from `issue_guest_token` — an
  admin-typed `token_hash` wouldn't correspond to any real signed token.
  `token_hash` is left out of `list_display`, and — found only by writing a test that
  actually loaded the change page rather than reasoning about it — was still rendered
  on the change/detail form regardless, since with no `fields`/`exclude` set Django's
  default `ModelAdmin` includes every model field on that page no matter what
  `list_display` says, and `has_change_permission=False` only disables editing, not
  visibility. Now excluded explicitly (`exclude = ("token_hash",)`), with
  `tests/test_admin_tenant_scoping.py::test_guest_access_token_change_view_does_not_render_token_hash`
  guarding the regression.
- **Read-only models: `Appointment`, `Payment`, `Notification`, `ProcessedWebhookEvent`,
  `GuestAccessToken`, `Review`.** `Appointment` and `Payment` each carry a `status`
  field driven by a service layer that doesn't exist yet (booking core is Stage 7,
  payments Stage 8) — made the *whole* model read-only rather than only `status`,
  since the other fields (`cancelled_by`, the price/deposit snapshots,
  `hold_expires_at`) are just as capable of corrupting invariants that layer will
  assume hold, and there's no legitimate hand-edit case before it exists.
  `Notification.status` drives Stage 9's dedup/idempotency machinery the same way.
  `ProcessedWebhookEvent` is a pure idempotency ledger with no legitimate hand-edit
  case, kept read-only for debugging visibility only — not a `TenantScopedModel` (no
  `salon` field, arrives before salon is known), so it uses `ReadOnlyAdminMixin`
  directly rather than `ReadOnlySalonScopedAdmin`. `Review` is the one case where the
  reasoning is stronger than "not built yet": reviews are explicitly **immutable once
  posted** (this file, § Business rules), so admin edit would directly violate that
  rule, not just get ahead of an unbuilt stage. `hidden_at` is the one sanctioned
  staff mutation, but its real UI is Stage 21 — deferred rather than building
  partial-field editability now. Editable: `SalonStaff`, `Customer` (support/operator
  tooling this surface exists for), `ServiceCategory`, `Service`, `Specialist`,
  `SpecialistService`, `WorkingHours`, `TimeOff`, `Salon` — reference/config data with
  no not-yet-built state machine underneath any of it.
- **Cross-tenant FK mismatch via admin (e.g. a `Service` saved with `salon`=A but
  `category` from salon B) is already closed at the database layer — no new
  application-level guard added.** `salon` stays a visible, explicitly-chosen field on
  every add/change form; there's no ambient tenant context to silently get wrong. Every
  `TenantScopedModel` with a second tenant-scoped FK already has a DB-level composite
  FK (`core/db.py`'s `composite_tenant_fk`, 14 call sites across migrations, enforcing
  `(child.fk_id, child.salon_id) -> (parent.id, parent.salon_id)`, tested since Stage 2
  commit `fb3605e`) — a mismatched submission fails as an `IntegrityError` at the
  database, not a silent cross-tenant link. That's an ugly generic-500 failure mode for
  an internal tool, not a correctness gap. Deliberately not adding admin-form
  `clean()`-level cross-validation to turn it into a friendlier message — that's UX
  polish beyond this sub-step, revisit only if a real operator workflow needs it.

## Stage 4 decisions (catalog API)

**Summary.** Stage 4 adds the API layer over the existing (Stage 2) `ServiceCategory`/
`Service` models — no new domain apps, only `catalog/serializers.py`, `catalog/views.py`,
`catalog/urls.py`, and the model additions below. It exposes standard CRUD, id-keyed
(no slugs — see below), under `/api/v1/salons/<slug>/{categories,services}/`, list and
detail, all paginated (`core.pagination.DefaultPagination`, page size 20 / cap 100).

**Read/write split:** reads (`GET`) are public — `AllowAny`, no authentication — matching
the product requirement that any visitor can browse a salon's catalog before booking.
Writes (`POST`/`PUT`/`PATCH`/`DELETE`) require `IsSalonStaff` for the URL's resolved
tenant, computed once per request via `get_permissions()`, reusing the Stage 3 permission
class rather than new ad-hoc logic. Deactivated (`is_active=False`) rows are filtered out
of every read by default; the one privileged exception is `include_inactive=true`, which
only surfaces them to staff of *that exact* salon (§ "Catalog read semantics" below) —
and, as of the write-method fix also recorded below, is never required on a write, only
on reads.

**Soft-delete policy:** `DELETE` never removes a row — `catalog/services.py`'s
`soft_delete_category`/`soft_delete_service` just flip `is_active` to `False` (204 on
success). Categories refuse to deactivate while they still have active services
(`CategoryHasActiveServicesError`, 409) — mirroring the real FK's `on_delete=PROTECT`
in the soft-delete world, an explicit staff resolution rather than a silent cascade or
orphan. Deactivating a `Service` with existing appointments is unconditionally allowed:
`Appointment` already snapshots price/deposit at booking time, so a deactivation can't
retroactively change what's owed on a booking already made — it only stops *new* ones
(enforced later, in Stage 7's booking-creation service layer, not here).

**Two-layer uniqueness defence** for each model's `(salon, name)` constraint (added in
this stage): an explicit `validate_name` on both serializers is the primary, friendly
check (tenant-scoped manager, no access to `salon` needed, since `salon` is always
read-only). It's check-then-write, not race-proof, so `core.exceptions.exception_handler`
backstops it — any `psycopg.errors.UniqueViolation` that reaches the database anyway
(a genuine concurrent race, or any future model that forgets the serializer-level check)
is translated into the same structured 400 shape, project-wide, rather than surfacing as
an uncaught 500. Full mechanism and the DRF gotcha that made the explicit check necessary
in the first place are detailed below.

- **Catalog `slug` fields are dropped from Stage 4.** Considered and withdrawn: the
  Stage 4 API addresses `ServiceCategory`/`Service` by numeric `<id>` throughout, so a
  `slug` field would have no consumer in this stage. It's a future frontend concern
  only — pretty/SEO per-service URLs — and it isn't yet decided whether the public
  frontend will even have per-service pages rather than a single `/services` listing.
  Adding it now would drag in transliteration, a new dependency, empty-result
  fallbacks, and collision-suffix handling for a field nothing reads. Both tables are
  empty and will stay empty until real salons exist, so adding it later (when the
  frontend's URL shape is actually decided) is no more expensive than adding it now.
  Revisit when the public frontend's routing is designed (the Frontend skeleton
  stage, § Agreed stage order).
- **Catalog read semantics: reading is public, with no cross-salon surface.** Any
  visitor, on any salon's site, sees that salon's active services without
  authentication. Salons are independent — there is no cross-salon browsing surface,
  no salon directory, and salon owners have no visibility into each other. The one
  authenticated read privilege is `include_inactive=true`, which lets a salon's own
  staff see their deactivated services. This privilege is scoped to the staff member's
  own salon: applying it against another salon's endpoint returns the ordinary public
  (active-only) result, silently — not an error, not elevated access. Tested
  explicitly, because the common failure mode here is a permission check that verifies
  "is staff" without verifying "is staff of *this* salon."
- **`include_inactive=true` only gates read visibility (list/retrieve GET); it is not
  required, and has no effect, on writes.** Found while confirming the
  deactivate→reactivate round trip: `RetrieveUpdateDestroyAPIView` uses the same
  `get_queryset()` for every method, so the naive version of the is_active filter
  also hid a deactivated row from `PATCH`/`DELETE`, making a plain `PATCH
  /services/<id>/ {"is_active": true}` 404 unless the client *also* passed
  `?include_inactive=true` — a non-obvious, undiscoverable requirement on a write.
  Fixed by skipping the visibility filter entirely for non-`SAFE_METHODS`: by the time
  `get_queryset()` runs for a write, `get_permissions()` has already restricted it to
  `IsSalonStaff` for this exact salon (DRF checks permissions in `dispatch()`, ahead of
  any handler method), so there's no protective reason left to also hide a deactivated
  row from a same-salon staff member editing or reactivating it. Reads are unaffected —
  a public caller, or staff without the flag, still can't `GET` an inactive row, list or
  single-object.
- **DRF 3.18 silently skips a `UniqueTogetherValidator` built from `Meta.constraints`
  when one of the constrained fields is read-only with no default.** Determined by
  reading `rest_framework/serializers.py`'s `get_unique_together_validators()`
  directly and confirming empirically
  (`ServiceCategorySerializer().get_validators()` returned `[]`): DRF 3.18 *does*
  build a unique-together validator from a `UniqueConstraint` in `Meta.constraints`
  (not only the legacy `Meta.unique_together`), but the method only considers fields
  present in `self._writable_fields`, plus read-only fields carrying a `default`. Every
  `TenantScopedModel`'s `salon` field is read-only (it comes from the URL's tenant
  context, never the client) and carries no Django-level default, so its `issuperset`
  guard silently drops any `(salon, X)` constraint's validator, with no error raised —
  `Service`/`ServiceCategory`'s `(salon, name)` constraints (sub-step 1) hit this
  immediately. A POSTed duplicate name passed `is_valid()` cleanly and only failed at
  `.save()`, as an uncaught `IntegrityError` — a 500, not a 400. Fixed two ways: an
  explicit `validate_name` on both serializers (checks the already-tenant-scoped
  manager directly — needs no access to `salon` at all) for the ordinary case; and a
  `core.exceptions.exception_handler` branch translating any
  `psycopg.errors.UniqueViolation` into the same structured 400, as a backstop for the
  concurrent-POST race the serializer check can't close on its own — the database
  constraint is the actual guarantee, the serializer check is only for a good error
  message. That handler branch is intentionally generic (no per-field detail parsed
  from the constraint name) to keep `core` domain-agnostic, and applies project-wide —
  it can only ever turn an already-broken uncaught-`IntegrityError`-as-500 into a clean
  400, never change a currently-passing request (verified: the three existing
  `IntegrityError` tests all assert at the ORM layer directly, never through DRF's
  request cycle, so none of them exercise this code path). This will recur on every
  future `TenantScopedModel` with a `(salon, X)` constraint — see `CLAUDE.md`'s
  Architectural rules for the standing instruction.

## Content localization (deferred to Stage 11.5)

Not part of Stage 4, or any stage before it — recorded now because the scope and
design principle were settled while doing Stage 4's catalog work, and deferring them
undocumented would risk the catalog model being bolted onto later instead.

- **Deferred to its own dedicated stage** (Stage 11.5, see § Agreed stage order —
  placed after the backend model/API stages and before the frontend stages, since the
  frontend needs the real translatable-content shape to build against, not a
  catalog-only stopgap. Numbered 11.5 rather than inserted into the main sequence,
  specifically so it doesn't renumber every stage after it and invalidate existing
  `Stage N` references elsewhere).
- **Scope is platform-wide, not catalog-only.** Translated content covers service
  names/descriptions, category names, salon description, and notification templates.
  It must be designed as one mechanism across all of those models, not bolted onto
  `catalog` alone and then reinvented for the others.
- **Design principle already agreed: languages are a per-salon setting, not a
  platform constant.** A salon declares which languages it operates in. A
  single-language salon sees single-value fields and is never forced to invent a
  translation it doesn't need; a multi-language salon must supply every language it
  has declared. This removes the need for a fallback rule — there's no "missing
  translation" state to fall back from, because a declared language is a required
  field, not an optional extra.
- **Do not implement any part of this before its own stage (Stage 11.5)** — not the
  model shape, not a placeholder field, not a migration.

## Stage 5 decisions (specialists API)

Decided 2026-08-11, before implementation — recorded here as agreed-in-advance
decisions, not as notes written after the fact.

- **Reviews removed from Stage 5; read endpoints move to Stage 11, alongside
  submission.** The stage order originally bundled "Specialists + reviews —
  read-only" into one stage. Split apart because a read-only review endpoint
  built now would return an empty list — no completed appointment can exist
  yet, since booking (Stage 7) hasn't landed — and would prove nothing in a
  test. Stage 11 (review submission, completed-appointment gated) would need
  to touch the same serializer anyway once real data exists, so building it
  twice (once now, against no data, and again in Stage 11) is pure rework.
  `docs/ARCHITECTURE.md`'s app table already places `Review` in its own
  `reviews` app, unaffected by this — only the *stage* that ships its read API
  moved, not its ownership.
- **Stage 5 is full CRUD, not read-only.** The original stage-order line said
  "read-only." Changed because Stages 18–21 are frontend admin layers
  (services/specialists/working-hours management, per § Agreed stage order)
  and need a write API to already exist by the time they're built — exactly
  the same reasoning Stage 4 used to justify catalog CRUD rather than a
  read-only catalog API. Reads stay public (`AllowAny`) and writes gated by
  `IsSalonStaff`, the same split as catalog.
- **`Specialist.is_active` moves from Stage 20 to Stage 5.** `docs/ARCHITECTURE.md`
  § 5 previously assigned this field to Stage 20 ("admin services, specialists,
  working hours, days off"), reasoning that Stage 2 had no admin UI to set it.
  That reasoning no longer holds once Stage 5 ships a write API of its own — a
  specialist CRUD API with no way to deactivate a former employee without a
  hard delete would immediately violate the "never hard-delete a row an
  `Appointment` might reference" rule (`docs/ARCHITECTURE.md` § 5). Moved
  earlier so the CRUD API is complete on arrival rather than shipping a
  known-incomplete delete story now and patching it in fifteen stages. Its
  meaning is employment status only: `True` = currently employed, `False` =
  no longer employed. It is explicitly **not** a general availability or
  visibility flag — it says nothing about whether a specialist is bookable on
  a given day.
- **Temporary absence (vacation, sick leave, parental leave) is not modelled
  as a status on `Specialist` — it is `TimeOff` rows, which already exist.**
  Considered and rejected: adding an absence-related status field would
  duplicate what `TimeOff` already represents and raise a question `TimeOff`
  doesn't have to answer — how long an absence must be before it flips a
  status, and what happens automatically when it's over. No duration
  threshold is needed anywhere in code for this: the booking/availability
  window is capped at 60 days out (`docs/DECISIONS.md` § Business rules), so a
  specialist absent longer than that simply has no bookable slots inside the
  window the client can ever see — the absence is invisible on its own,
  without any code needing to know how long it is or classify it as "long"
  vs. "short."
- **No `UniqueConstraint(salon, name)` on `Specialist`, and consequently no
  `validate_name`.** The catalog pattern (`(salon, name)` uniqueness on
  `ServiceCategory`/`Service`, with the DRF 3.18 unique-together trap worked
  around via an explicit `validate_name`, `docs/DECISIONS.md` § Stage 4
  decisions) does not transfer here. Catalog uniqueness models a real business
  rule — a salon shouldn't offer two identically-named services. Two
  specialists sharing a name is not an error; salons legitimately employ two
  people with the same first name. Since there's no uniqueness constraint on
  `Specialist`, the DRF gotcha that motivated `validate_name` on the catalog
  serializers doesn't arise here — there is nothing for the automatic
  validator to silently skip, because there is no constraint for it to be
  built from.
- **Stage 6 (availability engine) must exclude `is_active=False` specialists
  from slot computation, and this does not follow automatically from
  `TimeOff`.** A terminated employee has no `TimeOff` rows — nothing marks
  their calendar as unavailable — so an engine that only subtracts
  `WorkingHours` minus `TimeOff` minus existing appointments would happily
  keep offering slots for someone who no longer works at the salon. Recorded
  here, against Stage 5, rather than left for Stage 6 to discover, because
  `is_active` is deliberately *not* an availability flag (the point directly
  above) — that framing makes it easy for a later reader to conclude the
  availability engine has no business consulting it at all, when in fact it
  must, just as a hard exclusion rather than as part of the open-windows
  computation.
- **Deactivating a specialist with future non-cancelled appointments is refused
  (409), not allowed-and-cleaned-up.** `docs/DECISIONS.md` § Business rules
  already requires that a staff-side change conflicting with an existing
  appointment be detected and explicitly resolved — never silently orphaned —
  offering the customer a rebooking with another specialist, a rebooking with
  the same specialist later, or a fully refunded cancellation. Stage 5 has no
  payment layer (Stage 8), no notifications (Stage 10), and no
  conflict-resolution flow (Stage 19); it can detect the conflict but cannot
  honor any of those three resolutions. Refusing outright is the only behavior
  consistent with the existing rule until those stages exist. Revisit at Stage
  19, when the real resolution flow can replace this refusal.
- **"Still expected," for that refusal, reuses `booking`'s own
  `ACTIVE_APPOINTMENT_STATUSES` (`PENDING_PAYMENT`, `CONFIRMED`) directly,
  imported from `booking.models` — not a second, hand-written list.** The
  double-booking exclusion constraint (`booking/models.py`,
  `appointment_no_overlapping_active_bookings`) already treats exactly this
  status set as "this appointment holds a slot," and it's already reused once
  across an app boundary this way (`booking/views.py`'s guest-cancellation
  eligibility check). "Does this appointment hold a slot" and "does this
  appointment block specialist termination" are the same underlying question;
  importing the same constant, rather than writing a second one, is what keeps
  them from silently drifting apart the day a status is added or renamed.
- **"Future," for that refusal, means `end_datetime > now()` — `blocked_until`
  was considered and rejected.** `blocked_until` (`end_datetime` plus the
  service's buffer minutes) is the more conservative-looking option, but the
  buffer exists to block the calendar for room/equipment turnaround — it is
  not the specialist's obligation to a customer. The refusal exists because a
  customer is still expected; once the visit itself ends, nobody is waiting on
  the specialist anymore, even if the room is nominally still occupied for
  cleanup. Using `end_datetime` also means an appointment already in progress
  (started, not yet ended) counts as blocking — the specialist has a live
  commitment right up until the visit ends. `now()` is
  `django.utils.timezone.now()`, compared directly against the UTC-stored
  `end_datetime` with no conversion (`docs/DECISIONS.md` § Timezone).
- **The 409 response includes both a count and the conflicting appointment
  ids:** `details={"future_appointment_count": N, "future_appointment_ids":
  [...]}`. A bare count (the original proposal) was rejected as leaving staff
  with a known blocker and no way to act on it without a manual hunt. Full
  appointment detail (customer name, time, service) was also rejected: that
  would mean designing a response shape for Stage 19's not-yet-built
  conflict-resolution UI before its actual needs are known. Ids are neither —
  they're keys the caller already has a way to resolve, cost nothing extra
  (the same query that produces the count produces them), and carry no
  customer-facing information.
- **`core/exceptions.py`'s handler is deliberately narrowed to `UniqueViolation`,
  so a `ForeignKeyViolation` from a composite tenant FK surfaces as a 500, not a
  400 — established empirically, not assumed, by Stage 5 sub-step 4's
  deliberate-break exercise.** Swapping `SpecialistSerializer`'s tenant-scoped
  queryset for `unscoped_objects` let a cross-salon service id pass validation;
  the resulting `.save()` raised a raw `psycopg.errors.ForeignKeyViolation` from
  `SpecialistService`'s composite tenant FK, and the handler's
  `UniqueViolation`-only rescue (by design — an unrelated integrity bug should
  surface loudly, not be reinterpreted as client error) does not catch it.
  Consequence, generalized beyond this one field: the composite tenant FK
  guarantees a cross-tenant row can never be written, full stop — but it is a
  last resort that fails loudly (500), never gracefully (400). The clean,
  field-specific 400 always comes entirely from the serializer-level
  tenant-scoped queryset check, never from the database constraint underneath
  it. This applies to every future `many=True` tenant-scoped relation, not only
  `services`.

## Stage 6 decisions (availability engine)

Decided 2026-08-13, before implementation — recorded here as agreed-in-advance
decisions, not as notes written after the fact.

- **Buffer at the end of a shift: the buffer must fit inside the specialist's
  working window, not spill past it.** The last bookable start time for a
  window is `window_end − service.duration_minutes − service.buffer_minutes`.
  Reasoning: the salon physically closes at the end of the shift; a buffer
  extending past window end would require the specialist to do
  equipment/room turnaround in a building that's already locked — the buffer
  is real time someone needs, not a bookkeeping convenience that can slide
  past closing. Rejected alternative: letting the buffer spill past window
  end, which gains exactly one extra slot per specialist per day but assumes
  the premises stay open past the nominal closing time — an assumption
  nothing else in this project makes. Consequence worth stating explicitly
  because it's easy to get wrong in a test: the last slot of a day is not
  necessarily on a round slot-granularity boundary from window start — e.g. a
  shift ending at 21:00, a 60-minute service with a 15-minute buffer, gives a
  last bookable start of 19:45, not 20:00 or 20:15.
- **Overlapping `WorkingHours` rows are merged into disjoint windows at
  ingestion time (window-building), not deduplicated at output.**
  Reasoning: nothing in the schema or the write path prevents two overlapping
  rows for the same specialist/day today — no uniqueness constraint, no
  `clean()`, and the rows are already admin-writable
  (`specialists/admin.py`'s `WorkingHoursAdmin`, plain `SalonScopedAdmin`, no
  overlap check) — so the engine must tolerate the data as it actually can
  exist, not as it ideally would. A duplicated slot surfacing in an API
  response because two overlapping rows both generated it independently is a
  **wrong answer** (the caller sees the same start time twice, or double-
  counts it in a merge elsewhere), not merely wasted computation. Rejected
  alternative: deduplicating identical slots at the output stage instead —
  rejected because it requires two mechanisms (a merge-shaped one at output,
  doing the same job the window-building step could do once) where one at the
  source suffices, and because dedup-at-output has to reason about slot
  *equality* after the fact instead of window *disjointness* before the fact,
  a strictly harder invariant to get right. Split shifts — two genuinely
  non-overlapping `WorkingHours` rows for the same day, with a lunch break
  represented as the absence of a row between them, per the model's own
  docstring — are unaffected: merging only ever acts on rows that actually
  overlap.
- **Salon-level closure (public holidays, planned shutdowns) is not modelled
  in Stage 6.** Recorded instead as an open question (§ Open questions,
  below). Reasoning: the real requirement doesn't decompose into one shape —
  it's at minimum one-off closures, annually-recurring holidays, partial-day
  closures, and eventually per-room rather than per-salon closures — and a
  minimal model built now to unblock Stage 6 would almost certainly be
  rewritten, with a data migration, once the real requirement is scoped
  properly (likely alongside the admin calendar work, Stage 19/20). **This
  has a consequent design requirement for Stage 6 itself, not just a
  deferral note:** the window-building step's blocking-interval subtraction
  must accept a generalised list of blocking intervals, not be hardcoded to
  read `TimeOff` specifically, so a future closure source becomes one
  additional entry in that list rather than a rewrite of the subtraction
  logic. See `docs/ARCHITECTURE.md` § 6 for the corresponding wording.
- **Interval boundaries — established fact, not a decision.** Postgres's
  `TSTZRANGE(a, b)` with the bounds argument omitted defaults to `'[)'` —
  inclusive lower bound, exclusive upper bound. The exclusion constraint
  (`booking/models.py`'s `appointment_no_overlapping_active_bookings`) uses
  exactly this two-argument form, so a candidate starting exactly at a
  previous appointment's `blocked_until` does not overlap it and is free.
  This isn't a new decision — § Business rules already states "a following
  appointment may start exactly when the buffer ends," and it's already
  covered by a passing test,
  `test_back_to_back_appointment_after_buffer_is_allowed`
  (`tests/test_booking_exclusion_constraint.py`) — recorded here only so the
  availability engine's own slot-walking arithmetic is written to agree with
  it deliberately, not by accident.
- **Multi-specialist availability: both modes are required, as two
  functions, not one.** The per-specialist function stays the primitive,
  with the signature `docs/ARCHITECTURE.md` § 6 already documents (specialist
  + service + date range). A separate, thin composition function in the same
  `scheduling` app handles "any available specialist for this service": it
  enumerates the service's `SpecialistService`-qualified, `is_active`
  specialists and unions each one's per-specialist availability. Rejected
  alternatives: (a) making `specialist` optional on the primitive itself —
  rejected because it turns one function into two behaviors gated by whether
  an argument is `None`, signature sprawl for what is really a distinct,
  higher-level operation (fan-out + union) layered on top of the primitive,
  not a variant of it; (b) leaving the fan-out to the frontend — rejected
  because it turns "show me any available time for this service" into N HTTP
  requests per page view (one per qualified specialist), which doesn't scale
  with the number of specialists a salon employs and pushes a backend
  concern onto every client. Named explicitly, these are the two booking
  entry paths: **"any specialist"** goes through the composition wrapper —
  a time is available if at least one qualifying specialist is free then;
  **"specific specialist"** calls `compute_candidate_start_times` directly,
  no composition. Both read through the same single-specialist engine and
  differ only in the wrapper above it.
- **Reversed 2026-08-15 — response shape for the multi-specialist mode: a
  slot in the availability response is a bare time, not a list of
  specialists.** This reverses the decision originally recorded here on
  2026-08-13: "each slot carries the list of specialists available at that
  time, not a bare time," reasoned on the grounds that "a specialist is not
  an interchangeable resource... the composition function already has every
  qualified specialist's name in hand while computing the union, so
  attaching it costs nothing extra." That reasoning about the *data* being
  cheap to attach was correct and still holds — the reversal is about
  *presentation*, not cost: each specialist is shown with a photo and a
  description, which does not fit stacked under every time row and needs
  its own screen. The specialist-availability mapping the composition
  function computes while unioning is therefore still computed, exactly as
  before — it is simply not serialized into this response. It is what the
  second endpoint (§ Stage 6.G decisions) serves once the client has picked
  a time; nothing here is discarded, only deferred to the next request.
- **Stage 6 scope includes a read-only `GET` endpoint, not only the internal
  `scheduling` service function.** Reasoning: where tenant context gets
  bound for `TenantScopedManager` (`core.tenancy.tenant_context`, per
  `docs/ARCHITECTURE.md` § 5) can only really be answered while an actual
  view is being written against an actual request — designing the service
  function's signature without ever exercising it through a view risks
  getting that signature wrong and discovering it only once Stage 7 (already
  the heaviest remaining stage) is underway and depending on it. The stage
  title's "read-only" was originally ambiguous between "the computation has
  no side effects" (true of the internal function regardless) and "there's a
  `GET` endpoint" — this decision resolves it to mean both.
- **DST handling belongs at the window-building step, not only at response
  formatting.** `WorkingHours.start_time`/`end_time` are plain `TimeField`s
  keyed by `day_of_week` — salon-local wall-clock time with no date attached.
  Turning "09:00–18:00 on day X" into a concrete UTC interval requires
  localizing against a specific calendar date via `zoneinfo`, and on a
  DST-transition day that localization changes the real UTC duration of the
  window (8 or 10 hours, not the naive 9) — so the DST-aware conversion has
  to happen at window construction, before subtraction and slot-walking even
  start, not only when converting the final candidate slots back to local
  time for the response.

### Stage 6.C decisions (open-window computation — design addendum)

Decided 2026-08-13, before implementation, resolving the open questions raised
by the 6.C design proposal.

- **`compute_open_windows`'s `date_from`/`date_to` are salon-local calendar
  dates (`dt.date`), not UTC instants.** Reasoning: a customer asks "what's
  free on 15 September" in salon-local terms — accepting UTC instants here
  would push a day-boundary explanation into every layer above
  `compute_open_windows` (the composition function, the eventual `GET`
  endpoint, the frontend) instead of settling it once, at the one place that
  already has to reason about salon-local wall-clock time (`WorkingHours`
  itself).
- **`date_from > date_to` raises, rather than returning an empty list.**
  Reasoning: an invalid range is a caller error, not a legitimate data state
  — an empty list is indistinguishable from "genuinely nothing available,"
  which would let a view-level bug (e.g. swapped query params) pass through
  silently instead of surfacing. The eventual `GET` endpoint translates the
  exception into a 400.
- **`_subtract_intervals` must produce a result independent of
  blocking-interval order, including when blockers overlap each other.**
  Same reasoning already applied to `WorkingHours` above: nothing in the
  schema prevents two overlapping `TimeOff` rows for the same specialist
  either — no uniqueness constraint, no `clean()` — so the generalised
  subtraction step must tolerate that shape of input, not just the shape the
  schema happens to make more common.
- **The pure window/interval functions (`_merge_intervals`,
  `_subtract_intervals`) use the same half-open `[start, end)` convention as
  the `Appointment` exclusion constraint** — a window boundary that only
  touches a blocker, without overlapping it, is not clipped. Reasoning: this
  project already has one boundary convention, established for the exclusion
  constraint (the "Interval boundaries — established fact" decision above);
  running a second, different convention through the pure scheduling
  functions would be a guaranteed off-by-one the moment the two are compared
  or composed.
- **`_merge_intervals` merges intervals that touch with zero gap (one ends
  exactly where the next begins), not only intervals that strictly
  overlap.** Two `WorkingHours` rows with no gap between them (e.g.
  `09:00–12:50` and `12:50–18:00`) describe one continuous period of work —
  how a shift happens to be split into rows is incidental data entry, not a
  fact about the day. This matters concretely once slot-walking exists
  (a later substage): with granularity 20 minutes, merging the two rows
  above into one `09:00–18:00` window walks candidates `..., 12:40, 13:00,
  ...`, while leaving them as two separate windows walks `..., 12:40 |
  12:50, 13:10, ...` — a different candidate grid for the rest of the day,
  entirely as a side effect of how the row happened to be split. An
  incidental data-entry choice must not shift the whole day's slot grid.
- **`is_active=False` specialist exclusion is guarded in two places, not
  one: an early-return empty list inside `compute_open_windows`, and the
  caller filtering its specialist list before calling in.** Mirrors this
  project's existing serializer-plus-database-constraint pattern (e.g. the
  tenant-scoped `validate_name` check backstopped by the database's own
  `UniqueViolation` translation, § Stage 4 decisions) — the cheap local
  check inside `compute_open_windows` costs one attribute access and stops a
  forgetful caller from ever reaching the ORM queries at all, while the
  caller-side filter is what actually matters for the multi-specialist
  composition function's enumeration (§ Stage 6 decisions above) and avoids
  spending a query on a specialist who can never have a window regardless.
- **A malformed `Salon.timezone` (a string `zoneinfo.ZoneInfo` can't
  resolve) is not handled inside `compute_open_windows` or
  `_localize_window`.** Reasoning: validating that `Salon.timezone` is a
  real IANA zone name is a write-time concern — it belongs wherever
  `Salon.timezone` is created or edited, not on every read of every
  availability computation. Recorded as an open question (§ Open questions)
  rather than handled defensively here.
- **Window/interval values are a `NamedTuple` (`Window(start: datetime, end:
  datetime)`), not a bare `tuple[datetime, datetime]`, from the start of
  Stage 6.C.** Reasoning: these values travel through multiple further
  layers (6.D's busy-interval subtraction, the multi-specialist composition
  function, and eventually a serializer) — `w[0]`/`w[1]` at the third or
  fourth layer of composition is unreadable and error-prone (nothing stops
  swapping start/end positionally), while `w.start`/`w.end` is
  self-documenting at every layer. Decided now, rather than deferred as a
  style choice, specifically so no downstream substage gets written against
  the bare-tuple shape and then needs a mechanical rewrite.
- **`salon_timezone` stays a `str` parameter on `compute_open_windows` and is
  converted to a `zoneinfo.ZoneInfo` once, inside the orchestrator, before
  being passed down to `_localize_window`.** Recorded here as a deliberate
  placement, not an accident to be rediscovered while debugging: it means a
  `zoneinfo.ZoneInfoNotFoundError` (an unresolvable timezone name — see the
  malformed-`salon_timezone` decision above) surfaces from
  `compute_open_windows` itself, not from a helper several calls deep.
  `compute_open_windows`'s docstring states this explicitly.
- **Stage 6.C's computation lives in `scheduling/services.py`, not a
  separately-named module.** Matches this project's existing service-layer
  convention (`catalog/services.py`, `specialists/services.py`) — naming
  this one app's equivalent module something else would leave an
  unexplained inconsistency about where business/computation logic lives
  across apps, for no benefit.
- **`date_from > date_to` raises `core.exceptions.InvalidDateRangeError`, a
  new `DomainError` subclass.** Its HTTP-status/error-envelope mapping is
  not decided now — that lands with the `GET`-endpoint substage, alongside
  `docs/ARCHITECTURE.md` § 14's `EXCEPTION_HANDLER`.

### Stage 6.D decisions (busy-interval subtraction from Appointments)

Decided 2026-08-13, before implementation, resolving the open questions
raised by the 6.D design proposal.

- **6.D extends `compute_open_windows` directly — no new orchestrator
  function, no second `_subtract_intervals` call.** Two new functions only:
  `_fetch_appointments` (mirrors `_fetch_time_off`, with the added
  `status__in=ACTIVE_APPOINTMENT_STATUSES` filter `TimeOff` has no
  equivalent of) and `_appointments_to_blocking_intervals` (mirrors
  `_time_off_to_blocking_intervals`). Their output is concatenated into the
  same blocking-interval list already built for `TimeOff`, before the
  single existing `_subtract_intervals` call. Reasoning: `_subtract_intervals`
  was built in § Stage 6.C decisions specifically to not know a blocker's
  source; a second real source is that generalisation being used for the
  second time it was built for, not a new step. `compute_open_windows`'s
  signature and return type are unchanged.
- **The interval subtracted is `(start_datetime, blocked_until)`, never
  `(start_datetime, end_datetime)`.** This is the same buffered interval
  the `Appointment` exclusion constraint itself protects
  (`docs/ARCHITECTURE.md` § 2, § 7; `booking/models.py`'s
  `appointment_no_overlapping_active_bookings`). Subtracting the bare
  service interval instead would let this engine offer a start time the
  database is guaranteed to reject — not as a race-condition "you lost the
  race" case, but deterministically, every time.
- **Blocking statuses are `booking.ACTIVE_APPOINTMENT_STATUSES`, imported
  directly, not a second hand-written list.** Same reuse principle already
  applied in § Stage 5 decisions for `specialists/services.py`'s own
  future-appointment check — `CANCELLED`, `EXPIRED`, `COMPLETED`, and
  `NO_SHOW` appointments never block.
- **`hold_expires_at` is not read by this substage.** A `PENDING_PAYMENT`
  appointment whose hold has already passed, but whose status the
  not-yet-built expiry sweep hasn't flipped to `EXPIRED` yet, still counts
  as blocking. This is the correct failure mode for a read path: it can
  only ever under-offer availability, never over-offer it — the
  double-booking guarantee comes from the database exclusion constraint,
  which doesn't consult `hold_expires_at` either. The sweep itself is Stage
  7's, not this substage's.
- **`django_assert_num_queries(3)` is a required test, not an optional
  nice-to-have.** `compute_open_windows` issues exactly three queries after
  this change (`WorkingHours`, `TimeOff`, `Appointment`) — pinned because
  this project has already lost query efficiency to an unpinned regression
  once (a missing `select_related` in Stage 4, caught only because a
  query-count assertion existed elsewhere). The risk here is identical: a
  future change silently turning one fetch into an N+1, with nothing else
  in the suite positioned to notice.
- **Blocker provenance (which source — `TimeOff` vs. `Appointment` —
  produced a given blocked span) is not carried through
  `_subtract_intervals`'s output.** Recorded as an open question (§ Open
  questions, below), not solved here: carrying it through would change
  `_subtract_intervals`'s return type and break the "knows nothing about
  its sources" contract that is the entire point of the § Stage 6.C
  decisions generalisation. The one concrete use case for it (Stage 19's
  admin calendar explaining *why* a slot is unavailable) can read
  `Appointment`/`TimeOff` rows directly rather than reconstructing them
  from derived slots, so the need is speculative, not demonstrated.

### Stage 6.E decisions (slot stepping)

Decided 2026-08-14, before implementation, resolving the open questions raised
by the 6.E design proposal.

- **Two layers, in `scheduling/services.py`, alongside the 6.C/6.D pure
  functions and `compute_open_windows`:**

  ```python
  def _step_windows(
      windows: Sequence[Window],
      granularity_minutes: int,
      occupied_minutes: int,
  ) -> list[dt.datetime]: ...

  def compute_candidate_start_times(
      specialist: Specialist,
      service: Service,
      salon: Salon,
      date_from: dt.date,
      date_to: dt.date,
  ) -> list[dt.datetime]: ...
  ```

  `_step_windows` is pure — plain numbers for `granularity_minutes`/
  `occupied_minutes`, but still the `Window`/`dt.datetime` vocabulary
  `_merge_intervals`/`_subtract_intervals` already use, not a further
  reduction to bare numbers, which would break consistency with the rest of
  the pure layer for no benefit. `compute_candidate_start_times` calls
  `compute_open_windows` itself — the same shape already established for
  the (not yet built) multi-specialist composition function, which the
  Stage 6 decision on multi-specialist availability specifies as calling
  the per-specialist primitive itself rather than receiving its results —
  and resolves `occupied_minutes = service.duration_minutes +
  service.buffer_minutes`, `granularity_minutes =
  salon.slot_granularity_minutes`, then calls `_step_windows`. Rejected
  alternative: the orchestrator receiving pre-computed `windows` as an
  argument instead of calling `compute_open_windows` itself — rejected
  because no caller in current or near-term scope (the GET endpoint, the
  composition function) has a reason to compute windows and stepped slots
  separately, and passing windows in would require every caller to keep
  `specialist`/`date_from`/`date_to`/`salon` in sync across two call sites
  instead of one, the same caller-must-remember-an-invariant shape this
  project has already avoided elsewhere (`TenantScopedManager`, the
  `is_active` double guard, § Stage 6.C decisions).
- **Grid remainder: strict grid only, no off-grid last slot.**
  `_step_windows` walks each window independently from `window.start` in
  steps of `granularity_minutes`, keeping a candidate only while `candidate
  + occupied_minutes <= window.end`; a tail shorter than one full step is
  never offered, even when `occupied_minutes` would fit inside it.
  Rejected alternative: additionally emitting `window.end -
  occupied_minutes` as an explicit final candidate whenever it lands
  off-grid. Rejected because it would make the primitive carry two rules
  instead of one, and would produce visibly uneven spacing between the last
  two candidates in what's ultimately a slot picker. The Stage 6 decision
  on buffer-at-shift-end (§ Stage 6 decisions, "Buffer at the end of a
  shift") is not evidence for the rejected alternative, despite reading
  that way out of context: its example — a window starting 09:00, a
  60-minute service with a 15-minute buffer, "last bookable start of
  19:45" — sits on the strict grid already. 19:45 is 645 minutes after
  09:00; at the salon's default `slot_granularity_minutes` of 15, 645 / 15
  = 43 exactly, so 19:45 is step 43 from window start, not an off-grid
  value the strict rule would have to special-case. That decision was
  recorded before slot-stepping was designed at all, as a statement about
  the *closed-form ceiling* on the last bookable start (`window_end -
  occupied_minutes`), not a claim that this ceiling must always be offered
  regardless of grid alignment. Recorded here explicitly so this isn't
  re-opened by a future reader skimming that example out of context.
- **`granularity_minutes <= 0` and `occupied_minutes <= 0` raise, inside
  `_step_windows`, rather than being silently trusted.** A new
  `DomainError` subclass, `InvalidSteppingParametersError` (`core/
  exceptions.py`, `code = "invalid_stepping_parameters"`, `status_code =
  500`), in the `DomainError`-subclass shape `InvalidDateRangeError` uses
  (§ Stage 6.C decisions) but deliberately mapped to a different status:
  `InvalidDateRangeError`'s `date_from > date_to` arrives in the request
  itself, so 400 correctly tells the client their input was malformed and
  fixable by sending a different request; `InvalidSteppingParametersError`
  fires because a `Salon` or `Service` row already in the database is
  misconfigured (§ Open questions, "Lower-bound validation on
  `Salon.slot_granularity_minutes`..." above) — the request that triggered
  it may be perfectly well-formed, the client has nothing to change, and
  telling them otherwise sends the frontend into a dead end. 500 is
  correct here precisely because it is server misconfiguration, not caller
  error, despite both being `DomainError` subclasses raised from the same
  service layer. This mapping is recorded now but not implemented in 6.E —
  same as `InvalidDateRangeError`'s own HTTP mapping (§ Stage 6.C
  decisions), it lands with the `GET`-endpoint substage, alongside
  `docs/ARCHITECTURE.md` § 14's `EXCEPTION_HANDLER`. Reasoning this needs a
  guard at all, rather than trusting the schema like `_subtract_intervals`
  trusts
  well-formed `Window`s: `Service.duration_minutes >= 1` is enforced only
  by `catalog/serializers.py` (`min_value=1`), not at the model/DB layer,
  and `Salon.slot_granularity_minutes` has no lower-bound enforcement
  anywhere yet — no `Salon` serializer exists, and the admin form has no
  validator. `granularity_minutes = 0` is therefore creatable through
  `/admin/` today, and the naive stepping loop (`candidate +=
  timedelta(minutes=granularity_minutes)`) would not raise or return wrong
  data on such a row — it would hang the request (or Celery task, or AI
  assistant tool call) indefinitely. That failure mode is categorically
  worse than the other three options this project already guards against
  (silent wrong data, a loud crash, or a clear domain error), so it gets
  the same treatment `InvalidDateRangeError` gets rather than being left
  for the write-side validation this project doesn't have yet (tracked
  as an open question below, and § Open questions above).
- **`occupied_minutes` larger than every open window in range returns an
  empty list, not an exception.** Already implied by
  `docs/ARCHITECTURE.md` § 6's existing edge-case note ("a service
  duration longer than any single open window never produces a slot —
  correct behavior, not a bug"); this decision only confirms
  `compute_candidate_start_times` follows that same rule rather than
  treating "nothing available" as an error condition. No `_step_windows`
  or `compute_candidate_start_times` code change is implied beyond what §
  Grid remainder above already describes — a window that can't fit even
  one candidate simply contributes none, the same as a window with a
  0-minute-wide tail.
- **`compute_candidate_start_times` takes `salon: Salon` as an explicit
  parameter, not derived from `specialist.salon`.** Rejected alternative:
  deriving `salon = specialist.salon` inside the orchestrator, which would
  save one constructor argument. Rejected because it's a lazy FK access —
  firing a fourth query, on first attribute touch, on top of the three
  `compute_open_windows` already issues and that `django_assert_num_queries
  (3)` pins (§ Stage 6.D decisions) — and because it would happen silently,
  inside a function whose entire job is translating already-resolved model
  objects into numbers; if that's the job, it should receive the objects it
  translates rather than reach for one of them itself. With `salon` passed
  in, `compute_candidate_start_times` itself issues zero queries of its own
  (pure resolution plus the `compute_open_windows` call), so the pinned
  query count is unaffected by this substage. `compute_open_windows`'s own
  signature is unchanged — the orchestrator passes `salon.timezone` into it
  as the existing `salon_timezone: str` parameter, forwarding rather than
  re-deciding that convention (§ Stage 6.C decisions).
- **`ARCHITECTURE.md` § 6 step 3 wording is unchanged.** The strict-grid
  remainder rule, the `InvalidSteppingParametersError` guard, and the exact
  function signatures above are Catalog-precedent detail (`docs/DECISIONS.md`
  § Stage 4 decisions' endpoint lists and exception classes never
  appearing in `ARCHITECTURE.md`) — they belong only here, not folded into
  `ARCHITECTURE.md`'s "what" description of step 3, which already covers
  slot-granularity stepping and the full-duration-plus-buffer requirement
  at the right altitude and needs no addition for this substage.

### Stage 6.F decisions (booking-window filtering)

Decided 2026-08-14, before implementation. No separate 6.F design proposal
preceded this section — these decisions came directly out of discussion and
are recorded here as agreed, not resolved against a prior written proposal.

- **`now` is an explicit parameter, with no default and no `None` fallback.**
  The system clock is I/O, the same category as the ORM, and this project
  already isolates I/O in the `_fetch_*` functions (§ Stage 6.C decisions). A
  default would let a test silently omit it and go green for the wrong
  reason — the same failure shape as the fixture collision found in 6.E.
  `timezone.now()` is called exactly once, in the view, landing with the
  `GET`-endpoint substage; until then, tests pass it explicitly.
- **Minimum lead time is a duration.** A candidate is kept if `candidate >=
  now + timedelta(hours=salon.min_lead_time_hours)`.
- **Maximum advance is a calendar boundary, not a duration.** Compute today's
  date in the salon's timezone, add `salon.max_advance_days`, and the
  exclusive upper bound is midnight at the start of the *following* day in
  the salon timezone, converted to UTC; a candidate is kept if `candidate <
  boundary`. Half-open `[)`, consistent with the rest of the engine and with
  `TSTZRANGE`. Rejected alternative: `now + timedelta(days=N)`. Rejected
  because a rolling boundary moves continuously — a customer refreshing the
  page at 23:00 sees a day that was not there at 01:00 — and because salon
  staff reason about "60 days ahead" in calendar days, not 1440 hours. The
  resulting asymmetry — the lower bound is a moment, the upper bound is a
  calendar edge — is deliberate: lead time protects the specialist from a
  last-minute booking, max advance is the salon's planning horizon, and
  those are different kinds of limits with different natural units. Only the
  upper bound needs the salon timezone; the lower bound does not.
- **A new pure function does the filtering, called by the orchestrator after
  `_step_windows`.** Rejected alternative: trimming the open windows
  themselves before stepping. Rejected because trimming would move the
  stepping anchor, and § Stage 6.C decisions' decision 5 pins that anchor to
  the window start — trimming a window's start to the lead-time or
  max-advance boundary would make slot times depend on when the request
  happened to arrive, the same grid-stability problem 6.C decision 5 already
  rules out for a different reason.
- **The max-advance boundary computation gets its own pure function,
  `_max_advance_boundary(now: dt.datetime, max_advance_days: int, tz:
  ZoneInfo) -> dt.datetime`, with an inlined two-line body — not a call to
  `_localize_window(...).start`.** `_localize_window` does not validate
  `start_time` against `end_time`, and `start_time == end_time` is already
  the established idiom in this module for extracting a single instant —
  `compute_open_windows` uses it twice today, for `range_start_utc` and
  `range_end_utc` — so reusing it here would have worked. It is rejected on
  concept, not on breakage: the arithmetic is identical, but
  `_localize_window` builds a working-hours `Window`, and this is a single
  cutoff instant, not a window that happens to have zero width. Routing
  through it would mean constructing a `Window` only to discard half of it,
  leaving a reader wondering why a booking-window boundary is built out of a
  working-hours type. Giving the boundary computation its own name and body
  also makes it directly unit-testable in isolation — including the § Open
  questions entry on midnight-transition zones, with a synthetic
  `ZoneInfo("America/Santiago")` on its transition day — with no ORM, no
  `tenant_context`, and no fixtures.
- **`now` must be timezone-aware; `compute_candidate_start_times` checks this
  on its very first line, before anything else runs, and raises a plain
  `ValueError` if it isn't** — via `django.utils.timezone.is_naive(now)`,
  not a hand-rolled `now.tzinfo is None`, because `is_naive` correctly
  handles a `tzinfo` object that is set but returns `None` from
  `utcoffset()`, which the hand-rolled check would miss. Placed first for
  the same reason `date_from > date_to` is the first thing
  `compute_open_windows` checks, and the same reason § Stage 6.C decisions
  resolves `ZoneInfo` at the top rather than several calls deep: a naive
  `now` should always fail the same way, in the same place, not sometimes
  loudly and sometimes silently depending on what else happens to run
  first. Without this guard, a naive `now` survives `now + timedelta`
  unchanged, then `.astimezone(tz)` silently presumes the host's local zone
  instead of raising, and `_filter_candidates_by_booking_window`'s
  comparison only raises `TypeError` once `candidates` is non-empty — with
  an empty candidate list the whole call would instead return `[]`,
  indistinguishable from "genuinely nothing available." Raises a plain
  `ValueError`, not a new `DomainError` subclass: every existing
  `DomainError` subclass exists so `core.exceptions.exception_handler` can
  turn it into a structured client-facing response, for errors a request or
  a misconfigured database row can trigger. A naive `now` can be neither —
  per the first decision above, `timezone.now()` is called exactly once, in
  the view, and is always aware — so the only way a naive value reaches
  this function is a caller's code being wrong (a test, or a future
  non-view caller such as a Celery task or the AI assistant's tool
  function), with no API boundary to cross. This follows the same
  precedent already set in this module: `compute_open_windows` lets
  `zoneinfo.ZoneInfoNotFoundError` propagate raw, unwrapped, for the same
  reason (§ Open questions, "`Salon.timezone` write-time validation") — a
  problem with the caller or the configuration, not with client input.

Verified before writing the above: `Salon.min_lead_time_hours` (default `3`)
and `Salon.max_advance_days` (default `60`) match § Business rules' stated
defaults — no mismatch found. `specialist.salon_id` is a plain column on
`TenantScopedModel` (a standard `ForeignKey`), so it is present on any
normally-fetched `Specialist` row with no additional query; only
`specialist.salon` (the lazy relation, not the `_id` column) would fire one.

### Stage 6.G decisions (multi-specialist response-shape reversal — second-lookup endpoint)

Decided 2026-08-15, before implementation. No separate 6.G design proposal
preceded this section — these decisions came directly out of discussion and
are recorded here as agreed, not resolved against a prior written proposal.
Companion to the response-shape reversal recorded in § Stage 6 decisions
above ("Reversed 2026-08-15").

- **The second endpoint (specialist lookup for a chosen time) takes a raw
  time plus `service` and the same date range already used for the
  time-grid call as parameters — no token, no server-side stored
  computation.** Consistent with this project's existing minimal-state
  preference. It always **re-computes** which qualifying specialists are
  free at that time; it never reuses a cached result from the first
  (time-grid) response — the specialist-availability mapping computed while
  building the time grid is not persisted or handed back as an opaque
  reference to be redeemed later. A **re-computed empty result is a valid
  answer, not an error**: between the two requests another booking may have
  taken the only qualifying specialist at that moment (the ordinary booking
  race already described in `docs/ARCHITECTURE.md` § 6's edge cases and
  guarded for real at booking time per § 7), so the endpoint returns an
  empty list as such, never mapped to a 4xx/5xx — the client's job is to
  tell the customer the time is no longer available and let them pick
  another, the same way it would treat an empty time grid.
- **The "specific specialist" pick list is filtered by `is_active` before
  any slot computation runs — an inactive specialist is never offered as
  pickable at all.** Distinct from the existing `is_active` guard inside
  `compute_open_windows` (§ Stage 6.C decisions, "`is_active=False`
  specialist exclusion is guarded in two places"): that guard concerns a
  specialist's own schedule, so a stray direct call for an inactive
  specialist still resolves to an empty result rather than stale data or a
  crash. This decision concerns an earlier step — which specialists a
  customer is offered to choose from in the first place, before "specific
  specialist" ever makes that direct call. The same `is_active` filter the
  composition function already applies when enumerating candidates for the
  "any specialist" path (§ Stage 6 decisions, "Multi-specialist
  availability") applies to this pick list too, so both entry paths present
  only currently-employed specialists to the customer, for the same reason:
  nobody should be offered to book someone who no longer works at the salon
  (§ Stage 5 decisions).

### Stage 6.H decisions (multi-specialist availability composition)

Decided 2026-08-15, before implementation. No separate 6.H design proposal
preceded this section — these decisions came directly out of discussion and
are recorded here as agreed, not resolved against a prior written proposal.

- **New function `compute_multi_specialist_availability(service, salon,
  date_from, date_to, now) -> dict[dt.datetime, list[Specialist]]`, calling
  the existing `compute_candidate_start_times` once per qualifying
  specialist and merging the results into `{start_time: [specialists free
  then]}`.** Consumed by both endpoints from § Stage 6.G decisions: the
  "any specialist" (time-grid) endpoint takes the sorted keys; the second
  (chosen-time) endpoint calls this same function again and reads the value
  for the chosen time — it does not call a different, narrower function.
  The mapping is not persisted between the two calls; each call recomputes
  it from scratch, per § Stage 6.G's "always re-computes... never reuses a
  cached result" decision. Recomputing per call is the deliberate cost of
  that freshness choice, not incidental waste — the alternative (persisting
  the first call's mapping and looking up the chosen time in it) is exactly
  the token/stored-computation shape § Stage 6.G already rejected.
- **Imperative shell / pure core split, matching the rest of this module.**
  `_fetch_qualifying_specialists(service: Service) -> QuerySet[Specialist]`
  is the only ORM-touching part — one query,
  `Specialist.objects.filter(services=service, is_active=True)`, already
  tenant-scoped via `TenantScopedManager`. No `.distinct()`:
  `SpecialistService`'s `UniqueConstraint(fields=["specialist", "service"])`
  already rules out more than one join row per specialist for a given
  `service`, so the filter can't produce duplicate `Specialist` rows to
  begin with. Merging is a separate pure function,
  `_merge_specialist_availability`, over in-memory `(specialist, times)`
  pairs — no DB, no tenant context — unit-testable the same way
  `_merge_intervals` is. It sorts keys explicitly, `dict(sorted(...))`:
  plain dicts preserve insertion order but do not sort themselves, so the
  ascending-key guarantee (§ Stage 6.G's return-shape expectations) has to
  be produced deliberately, not assumed from iteration order.
- **Mapping value is full `Specialist` objects, not ids — no lazy-load
  optimization now.** The second endpoint needs the full row to serialize
  photo and description (the reason for the response-shape reversal, §
  Stage 6 decisions). Optimizing the fetch (e.g. `select_related`/deferred
  fields) waits until an actual serializer shows a real cost — the same
  "correctness first, optimize once it's a demonstrated bottleneck" posture
  already applied to the availability engine as a whole
  (`docs/ARCHITECTURE.md` § 6, "Where it lives").
- **Qualifying specialists are those linked via `SpecialistService` AND
  `is_active=True`; an inactive specialist never appears in the mapping,
  under any key.** Zero qualifying specialists returns an empty mapping
  `{}` — a valid answer, not an error, not an exception (same posture as
  `compute_open_windows`/`compute_candidate_start_times` returning `[]` for
  "genuinely nothing available," as opposed to raising). This is a backend
  data answer only; presenting "no specialists available" to a customer is
  a frontend concern for a later stage, not something this function or its
  endpoint decides.
- **`now` is re-validated on this function's first line, via
  `timezone.is_naive(now)`, not left to the inner
  `compute_candidate_start_times` guard.** Reason, precisely: with zero
  qualifying specialists, the inner function is never called at all, so a
  naive `now` would otherwise silently produce `{}` — indistinguishable
  from "genuinely nothing available," the exact failure shape § Stage 6.F's
  naive-`now` guard was written to prevent for the single-specialist path.
  Raises a plain `ValueError`, same class and same reasoning as
  `compute_candidate_start_times`'s own guard (§ Stage 6.F decisions): not
  a new `DomainError` subclass, because the only way a naive value reaches
  this function is a caller's code being wrong, not a request or a
  misconfigured database row.

### Stage 6.I decisions (availability time-grid GET endpoint)

Decided 2026-08-15, before implementation. No separate design proposal
preceded this section — these decisions came directly out of a planning pass
over § Stage 6 decisions, § Stage 6.G decisions, § Stage 6.H decisions above,
`docs/ARCHITECTURE.md` § 6, `CLAUDE.md`, and the catalog/specialists `views.py`/
`serializers.py`/`urls.py` as the closest read-endpoint precedent — and are
recorded here as agreed, not resolved against a prior written proposal.

- **One `GET` endpoint, `/api/v1/salons/<slug>/availability/`, under the
  existing tenant path prefix.** Required query params `service` (int) and
  `date_from`/`date_to` (ISO dates); optional `specialist` (int). `specialist`
  present → the "specific specialist" path, a direct
  `compute_candidate_start_times` call; `specialist` absent → the "any
  specialist" path, `compute_multi_specialist_availability`, with the
  response taking its sorted keys. The response is **identical** in both
  modes — a list of start times, never a list of specialists (§ Stage 6
  decisions, "Reversed 2026-08-15"); who's free at a chosen time stays the
  second endpoint's job (§ Stage 6.G decisions).
- **Response shape: `{"available_times": [...]}`, not a bare top-level
  array.** Every other endpoint in this API returns a JSON object at the top
  level (DRF's pagination wraps list endpoints in `{"count", "next",
  "previous", "results"}`); a lone bare-array endpoint would be the only
  shape inconsistency in the API, for no benefit, and an object leaves room
  for metadata (e.g. a salon timezone name) if a future stage needs it,
  without a breaking shape change later. Each time is a salon-local ISO 8601
  string — `candidate.astimezone(ZoneInfo(salon.timezone)).isoformat()` — the
  UTC offset is embedded in `isoformat()`'s own output, so no separate
  timezone field is needed to interpret it. **This is where the
  previously-pending Stage 6 "local-time conversion" item lands**
  (`docs/ARCHITECTURE.md` § 6 step 5) — in this endpoint's serializer/
  response, not as a change to any `scheduling/services.py` function; every
  service function keeps returning UTC `dt.datetime`s, exactly as today.
- **Query-param validation is a plain `serializers.Serializer`, not a
  `ModelSerializer`.** There's no model instance to serialize — this is the
  first view in the codebase backed by a computed value rather than an ORM
  row. `service`/`specialist` are `PrimaryKeyRelatedField`s, rebound in
  `__init__` to the tenant-scoped querysets (`Service.objects.all()` /
  `Specialist.objects.all()`) — the same pattern `catalog/serializers.py`'s
  `ServiceSerializer.category_id` already uses, not the `.child_relation`
  variant, since neither field is `many=True`. **The existing query-param
  precedent, catalog's `category` list filter, does not apply here and is
  not being extended.** That filter is an optional refinement, silently
  ignored when malformed (`category_id.isdigit()`) — a reasonable degrade
  for a param that only narrows an otherwise-valid response. `service`/
  `date_from`/`date_to` here are required and load-bearing for the
  computation itself; silently degrading a malformed one would produce a
  wrong-shaped answer, not a graceful no-op — so malformed input must
  hard-fail via the serializer instead.
- **HTTP status mapping — all through the existing `core/exceptions.py`
  handler, with no view-level `try`/`except`:**
  - Missing or malformed `service`/`specialist`/`date_from`/`date_to` → 400
    (an ordinary DRF `ValidationError` from the query serializer, caught by
    the handler's existing generic branch).
  - Unknown or cross-tenant `service`/`specialist` id → 400, **not 404.**
    These are query-param references resolved against a tenant-scoped
    queryset, the same role `category_id` plays in `ServiceSerializer` — not
    the URL's own addressed resource, where a miss legitimately is a 404
    (`catalog`/`specialists`' `RetrieveUpdateDestroyAPIView`s).
    `TenantScopedManager` already makes a cross-tenant id indistinguishable
    from a nonexistent one at the query level, so both surface as the
    field's ordinary "does not exist" `ValidationError` — the same 400 as
    any other invalid id, not a cross-tenant leak, per CLAUDE.md's
    `category_id` precedent.
  - `InvalidDateRangeError` (`date_from > date_to`) → 400, already wired
    (`status_code = 400` on the class, § Stage 6.C decisions). The view does
    **not** re-check `date_from <= date_to` itself before calling the
    service — that check stays the service layer's job, so there is exactly
    one place, and one error shape, for that condition.
  - `InvalidSteppingParametersError` → 500, already wired (§ Stage 6.E
    decisions) — server/data misconfiguration, not a malformed request. The
    view does nothing special; the `DomainError` passes straight through the
    shared handler.
  - A naive `now` reaching a service function raises a plain `ValueError` →
    500, but this is **unreachable in practice**: `timezone.now()` under
    `USE_TZ = True` (`config/settings/base.py`) is always aware, and the view
    is the sole call site (last bullet below). No view-level code guards
    against it; if it ever fired, the handler's existing catch-all
    (`logger.exception` + the generic `internal_error` 500 envelope) already
    covers it correctly, as our bug rather than the client's.
- **`permission_classes = [AllowAny]`, set explicitly on the class.**
  `DEFAULT_PERMISSION_CLASSES` (`config/settings/base.py`) is
  `IsAuthenticated` globally — every existing public-read view (catalog,
  specialists) already overrides this explicitly for `SAFE_METHODS`, and
  omitting the override here would silently block the unauthenticated
  browsing this endpoint exists for (a customer checking availability before
  ever creating an account). No `get_permissions()`/`SAFE_METHODS` branching
  is needed, unlike catalog's/specialists' mixins — this endpoint is
  `GET`-only, so there is no write path to branch away from.
- **`specialist` in the direct-mode is resolved via `Specialist.objects.all()`
  (tenant-scoped), not filtered by `is_active`.** A deactivated specialist's
  id already yields `[]` from `compute_open_windows`'s own `is_active` guard
  (§ Stage 6.C decisions, "guarded in two places") — filtering it out at the
  view/serializer level would instead turn "no free times" into a 400
  "doesn't exist," the wrong failure mode for a legitimate, if empty,
  answer. The § Stage 6.G `is_active` pick-list rule is a different concern
  — which specialists a customer is offered to *choose from* on the
  pick-list screen — not what happens when a specific id is passed directly,
  which this endpoint's specific-specialist mode does. For the
  any-specialist path, `is_active` is already filtered inside
  `_fetch_qualifying_specialists` (§ Stage 6.H decisions); no additional
  view-level filtering is needed there either.
- **The view resolves the full `Salon` row, not only the tenant id.**
  `compute_candidate_start_times`/`compute_multi_specialist_availability`
  need `salon.timezone`, `salon.min_lead_time_hours`, `salon.max_advance_days`,
  and `salon.slot_granularity_minutes` — every existing view only ever
  touches `core.tenancy.get_current_salon_id()` (an int), so this is new:
  `get_object_or_404(Salon, pk=get_current_salon_id())`. `Salon.objects` is
  a plain, non-tenant-scoped manager — `Salon` is the tenant root, not a
  `TenantScopedModel` (`tenants/models.py`'s own docstring: "Not itself a
  TenantScopedModel — a Salon doesn't belong to a tenant, it is one").
  `now = timezone.now()` is called exactly once, here in the view, and
  passed explicitly into both service functions — the single I/O call site
  the no-default-`now` design was built around (§ Stage 6.F decisions).

### Specialist photos — resolved (Stage 6.J)

**Field shape (settled now):** `photo = CharField(max_length=1024, null=True, blank=True)` on the `Specialist` model.

**Field type — CharField, not ImageField:** `ImageField`/`FileField` are coupled
to Django's storage machinery (`DEFAULT_FILE_STORAGE`, `MEDIA_ROOT`/`MEDIA_URL`,
Pillow validation, `.save()` via `request.FILES`) — all of which activates at
upload time, and there is no upload at Stage 6. The DB stores only the object
key (a string like `salons/42/specialists/17.jpg`), so `CharField` states the
truth: a text identifier, not a Django-managed file.

**Storage:** photos live in S3-compatible object storage; the DB holds only the
key, never the bytes. PostgreSQL is not a file server — `bytea` bloats the table
and every backup, and serving images through Django kills performance. DB knows
*where*, object storage (via CDN) serves *what*. Files-in-DB rejected: only
justified for tiny blobs or hard transactional coupling; avatars are neither.

**max_length = 1024:** taken from the S3 limit (an object key is ≤1024 bytes),
NOT computed from our own key schema — because the real key schema doesn't exist
yet (upload deferred), and sizing from a guess would freeze that guess into the
DB. Binding to the storage limit is honest and survives whatever schema we
eventually choose.

**null=True, blank=True (not empty string):** the API returns `photo: null`, not
`""`. JSON `null` conveys "no photo" more precisely, and the frontend checks
`photo === null` cleanly. Django's "no null on string fields" convention guards
against NULL-vs-"" ambiguity — removed here by simply never writing `""`.

**Optionality:** optional; the specialist and salon owner decide together, most
will have one. Creating a specialist is never blocked by a missing photo.

**Placeholder is a frontend concern:** absence of a photo is rendered by Next.js
as a grey-silhouette avatar (social-media style). The backend returns `null`
honestly and never invents a default-image URL — otherwise it would know about
the visual, and changing the silhouette would mean a backend change instead of
CSS. Same principle as local-time and formatting: backend returns the fact,
frontend renders the look.

**Field added now, not hardcoded in the serializer:** the field goes into the
model as a small migration (first step of this sub-step), rather than serving a
constant `null` from the serializer. A `null` constant would make the serializer
expose a field the model lacks — the source of truth would be a hardcode, not
the schema — and it would be two serializer edits (add constant now, replace
with real field at upload stage) instead of one cheap `ADD COLUMN NULL`
migration. The response shape is identical either way; there is no client-side
gain to justify the desync.

**Real upload deferred:** the model field and response shape are settled now,
but actual file upload (object-storage wiring, presigned URLs, upload endpoint)
is NOT built at Stage 6 — it's infrastructure, not part of the availability
engine, and belongs to a later dedicated stage. At Stage 6 every specialist
returns `photo: null`; the second endpoint serialises it as-is.

### Stage 6.K decisions (specialist-availability endpoint — second lookup, time → specialists)

Decided 2026-08-16, before implementation. No separate design proposal
preceded this section — these decisions came directly out of a planning pass
over § Stage 6 decisions, § Stage 6.G decisions, § Stage 6.H decisions, §
Stage 6.I decisions above, and are recorded here as agreed, not resolved
against a prior written proposal.

- **One `GET` endpoint, `/api/v1/salons/<slug>/availability/specialists/`, the
  second of the two availability endpoints, under the same `/availability/`
  path as the time-grid endpoint (§ Stage 6.I decisions)** — the two are kept
  together because they are two halves of one booking flow, not two
  unrelated resources. `permission_classes = [AllowAny]`, set explicitly on
  the class, same reasoning as § Stage 6.I decisions: `DEFAULT_PERMISSION_CLASSES`
  is `IsAuthenticated` globally, so a client browsing before registering
  would be silently blocked without this override.
- **Purpose: step 2 of the "any specialist" flow.** The client already picked
  a time from the grid (§ Stage 6.I decisions' response); this endpoint
  answers *who* is free at that exact time, returning each qualifying
  specialist with the fields needed to render a chooser card. This is the
  second half of the reversal decided in § Stage 6 decisions ("Reversed
  2026-08-15"): time first, specialist second.
- **Query params: `service` (required, int) and `datetime` (required, ISO
  8601 with offset, e.g. `2026-08-20T14:00:00+03:00`) — the exact string the
  first endpoint returned, echoed back unchanged by the client.** Validated
  via a plain `serializers.Serializer` over `request.query_params`, not a
  `ModelSerializer` — there is no instance to serialize, same reasoning as §
  Stage 6.I decisions. `service` is a `PrimaryKeyRelatedField` rebound in
  `__init__` to the tenant-scoped queryset (`Service.objects.all()`), the
  same pattern as `ServiceSerializer.category_id` and § Stage 6.I decisions'
  own `service`/`specialist` fields. `datetime` is a plain DRF
  `DateTimeField`, which parses ISO-with-offset out of the box — no custom
  parsing needed.
- **Datetime contract: the client sends back the local-time ISO string it
  received, offset included; the view converts to UTC internally to match
  the mapping's keys (which are UTC).** "Echo back what you received" is the
  simplest, most error-resistant contract available — the client never
  computes timezones itself. The explicit offset also disambiguates the
  moment on a DST-transition day, where a bare local time can be ambiguous
  or non-existent (§ Open questions, "Local-time presentation across a DST
  transition"), and a client bug that sends the wrong salon's offset
  surfaces as an empty result rather than silently matching the wrong slot.
- **How one `datetime` maps onto the range-based engine:** the endpoint
  takes a single moment, but `compute_multi_specialist_availability` (§
  Stage 6.H decisions) works over a date range. The view derives the date
  from the submitted `datetime`, in the salon's timezone, and calls the
  engine with `date_from == date_to ==` that date — computing the one-day
  mapping — then selects the mapping value for the exact submitted moment,
  compared in UTC. The contract stays simple on the outside; the range
  mechanics stay internal.
- **Always recomputes: no cached result from the first endpoint is reused.**
  There is no server-stored state between the two calls — they are two
  separate HTTP requests, each computing fresh from the current state of
  `Appointment`/`TimeOff`/`WorkingHours`. Freshness is chosen over
  cross-step consistency, the same trade-off § Stage 6 decisions ("Reversed
  2026-08-15") already made for the two-step flow as a whole, and the same
  "always re-computes... never reuses a stored computation" rule § Stage 6.H
  decisions restates for the first endpoint.
- **Response shape: `{"specialists": [{"photo": ..., "name": ..., "bio":
  ...}, ...]}`, not a bare top-level array.** Consistent with the time-grid
  endpoint's `{"available_times": [...]}` (§ Stage 6.I decisions) and with
  DRF's pagination convention; an object leaves room for metadata later
  without a breaking shape change. Each specialist serialises exactly three
  fields: `photo` (the S3 object key, `null` for now — no upload flow yet, §
  Stage 6.J), `name`, `bio`. Order follows the mapping's specialist order,
  which is `Specialist.Meta.ordering`, `["name", "id"]`.
- **Experience/seniority is not a field here.** It lives in free-text `bio`
  for now, not a structured field — see § Open questions, "Specialist
  experience/seniority as a structured field," for the deferred decision and
  why.
- **An empty result is valid, not an error.** If the chosen time was taken
  between the two steps (a booking race), the mapping has no entry for that
  moment, and the endpoint returns `{"specialists": []}` with HTTP 200, not
  a 4xx/5xx. The human-facing "this time was just taken, pick another" copy
  is the frontend's job; the backend returns `[]` as plain data, the same
  "genuinely nothing available" shape § Stage 6.H decisions already
  distinguishes from an error.
- **Error contract is inherited from § Stage 6.I decisions, entirely through
  `core/exceptions.py`'s handler, no view-level `try`/`except`:**
  - Missing or malformed `service`/`datetime` → 400 (ordinary DRF field
    validation).
  - Unknown or cross-tenant `service` id → 400, not 404 — the id is a query
    *parameter*, not the URL's own addressed resource, and
    `TenantScopedManager` makes a cross-tenant id indistinguishable from a
    nonexistent one at the query level, so both surface as the same
    ordinary "does not exist" 400, per CLAUDE.md's `category_id` precedent
    (also § Stage 6.I decisions).
  - `InvalidDateRangeError` cannot arise here: `date_from == date_to` by
    construction, so the condition it guards against never occurs.
