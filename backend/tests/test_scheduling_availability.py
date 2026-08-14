"""
Scheduling app's availability-engine test suite (docs/ARCHITECTURE.md § 6;
docs/DECISIONS.md § Stage 6 decisions and its Stage 6.C/6.D/6.E addenda).
Scoped to the availability engine as a whole, not to open-window computation
specifically — open windows (§ 6 steps 1-2) are the only computation this
file covers so far, but the filename and this docstring are deliberately not
scoped narrower than that, so later substages' tests (e.g. 6.E's slot
stepping) land in this same file rather than reopening where tests belong.

Written against the agreed design before any implementation exists — this
file is expected to fail on collection (ModuleNotFoundError) until
scheduling/services.py is written. Two layers, matching the functional-core
/ imperative-shell split from the design proposal:

- The _merge_intervals / _subtract_intervals / _localize_window tests below
  exercise the pure functions directly, with plain Window/datetime literals
  — no database, no tenant context. These are leading-underscore "internal"
  functions; testing them directly is deliberate for a module whose whole
  point is being a heavily-unit-tested pure computation core
  (docs/ARCHITECTURE.md § 6), not a convention break — same precedent as
  specialists/services.py's _future_appointments.
- The compute_open_windows tests exercise the orchestrator end-to-end
  against real WorkingHours/TimeOff/Appointment rows, via
  make_working_hours/make_time_off/make_appointment (tests/conftest.py).
  Several of these exist specifically to prove the pure functions above are
  actually wired into the orchestrator, not just correct in isolation — 6.D
  extends this same section (compute_open_windows's signature is unchanged;
  only its body gained a second blocking source, docs/DECISIONS.md § Stage
  6.D decisions), rather than adding a new file or a new entry point.
"""

import datetime as dt
from zoneinfo import ZoneInfo

import pytest

from accounts.models import Customer
from booking.models import ACTIVE_APPOINTMENT_STATUSES, AppointmentStatus
from catalog.models import Service, ServiceCategory
from core.exceptions import InvalidDateRangeError
from core.tenancy import tenant_context
from scheduling.services import (
    Window,
    _localize_window,
    _merge_intervals,
    _subtract_intervals,
    compute_open_windows,
)
from specialists.models import Specialist
from tests.conftest import make_appointment, make_time_off, make_working_hours

UTC = dt.UTC
DAY = dt.date(2026, 8, 17)


def _t(hour: int, minute: int = 0) -> dt.datetime:
    return dt.datetime(DAY.year, DAY.month, DAY.day, hour, minute, tzinfo=UTC)


def _localized_midnight(salon, date: dt.date) -> dt.datetime:
    """
    Local helper, used once (the full-day TimeOff fixture below) — not
    promoted to conftest.py since it's not part of the shared
    factory-helper set the way make_working_hours/make_time_off are.
    """
    return dt.datetime(date.year, date.month, date.day, tzinfo=ZoneInfo(salon.timezone)).astimezone(
        UTC
    )


WINDOW = Window(_t(9), _t(18))


# --- _merge_intervals --------------------------------------------------


def test_merge_intervals_empty_input_returns_empty():
    assert _merge_intervals([]) == []


def test_merge_intervals_single_interval_returns_unchanged():
    assert _merge_intervals([WINDOW]) == [WINDOW]


def test_merge_intervals_no_overlap_stays_separate():
    a, b = Window(_t(9), _t(12)), Window(_t(14), _t(18))
    assert _merge_intervals([a, b]) == [a, b]


def test_merge_intervals_overlapping_pair_merges():
    a, b = Window(_t(9), _t(14)), Window(_t(12), _t(18))
    assert _merge_intervals([a, b]) == [WINDOW]


def test_merge_intervals_three_overlapping_merge_into_one():
    rows = [Window(_t(9), _t(12)), Window(_t(11), _t(15)), Window(_t(14), _t(18))]
    assert _merge_intervals(rows) == [WINDOW]


def test_merge_intervals_touching_with_zero_gap_merges():
    """Case 21 — pins decision 5 (touching WorkingHours rows merge)."""
    a, b = Window(_t(9), _t(12, 50)), Window(_t(12, 50), _t(18))
    assert _merge_intervals([a, b]) == [WINDOW]


# --- _subtract_intervals -------------------------------------------------


def test_subtract_intervals_no_blockers_returns_windows_unchanged():
    assert _subtract_intervals([WINDOW], []) == [WINDOW]


def test_subtract_intervals_blocker_clips_start():
    blocker = Window(_t(7), _t(10))
    assert _subtract_intervals([WINDOW], [blocker]) == [Window(_t(10), _t(18))]


def test_subtract_intervals_blocker_clips_end():
    blocker = Window(_t(17), _t(20))
    assert _subtract_intervals([WINDOW], [blocker]) == [Window(_t(9), _t(17))]


def test_subtract_intervals_blocker_splits_window_in_two():
    blocker = Window(_t(12), _t(13))
    assert _subtract_intervals([WINDOW], [blocker]) == [
        Window(_t(9), _t(12)),
        Window(_t(13), _t(18)),
    ]


def test_subtract_intervals_blocker_covers_window_entirely_returns_empty():
    blocker = Window(_t(8), _t(19))
    assert _subtract_intervals([WINDOW], [blocker]) == []


def test_subtract_intervals_blocker_exactly_matches_window_returns_empty():
    blocker = Window(_t(9), _t(18))
    assert _subtract_intervals([WINDOW], [blocker]) == []


def test_subtract_intervals_blocker_touching_start_boundary_does_not_clip():
    """[) convention: blocker ending exactly at window start doesn't overlap."""
    blocker = Window(_t(7), _t(9))
    assert _subtract_intervals([WINDOW], [blocker]) == [WINDOW]


def test_subtract_intervals_blocker_touching_end_boundary_does_not_clip():
    """[) convention: blocker starting exactly at window end doesn't overlap."""
    blocker = Window(_t(18), _t(20))
    assert _subtract_intervals([WINDOW], [blocker]) == [WINDOW]


def test_subtract_intervals_blocker_outside_window_leaves_window_unchanged():
    blocker = Window(_t(19), _t(20))
    assert _subtract_intervals([WINDOW], [blocker]) == [WINDOW]


@pytest.mark.parametrize("blocker_order", [0, 1])
def test_subtract_intervals_overlapping_blockers_are_order_independent(blocker_order):
    """Case 15. Blockers 10-14 and 12-16 overlap each other; result must not
    depend on which order they're passed in."""
    blockers = [Window(_t(10), _t(14)), Window(_t(12), _t(16))]
    if blocker_order:
        blockers = list(reversed(blockers))
    assert _subtract_intervals([WINDOW], blockers) == [
        Window(_t(9), _t(10)),
        Window(_t(16), _t(18)),
    ]


def test_subtract_intervals_multiple_windows_each_handled_independently():
    other_day_window = Window(_t(9) + dt.timedelta(days=1), _t(18) + dt.timedelta(days=1))
    blocker = Window(_t(12), _t(13))  # only overlaps WINDOW, not other_day_window
    result = _subtract_intervals([WINDOW, other_day_window], [blocker])
    assert result == [Window(_t(9), _t(12)), Window(_t(13), _t(18)), other_day_window]


# --- _localize_window ----------------------------------------------------


def test_localize_window_ordinary_day_produces_correct_utc_offset():
    """January — no DST in effect, Europe/Kyiv is a flat UTC+2."""
    start, end = _localize_window(
        date=dt.date(2026, 1, 15),
        start_time=dt.time(9, 0),
        end_time=dt.time(18, 0),
        tz=ZoneInfo("Europe/Kyiv"),
    )
    assert (start, end) == (
        dt.datetime(2026, 1, 15, 7, 0, tzinfo=UTC),
        dt.datetime(2026, 1, 15, 16, 0, tzinfo=UTC),
    )


def test_localize_window_non_whole_hour_offset():
    """Case 20 — confirms the arithmetic doesn't assume :00-minute offsets."""
    start, end = _localize_window(
        date=dt.date(2026, 6, 1),
        start_time=dt.time(9, 0),
        end_time=dt.time(18, 0),
        tz=ZoneInfo("Asia/Kathmandu"),  # UTC+5:45
    )
    assert (start, end) == (
        dt.datetime(2026, 6, 1, 3, 15, tzinfo=UTC),
        dt.datetime(2026, 6, 1, 12, 15, tzinfo=UTC),
    )


def test_localize_window_spring_forward_calendar_day_is_23_hours_in_utc():
    """
    Case 12 (spring-forward half). 2026-03-29 is the last Sunday of March —
    the EU/Europe-Kyiv spring-forward date. Spans the whole calendar day by
    comparing local midnight to the next local midnight, so the assertion
    doesn't depend on knowing the transition's exact local clock hour.
    """
    tz = ZoneInfo("Europe/Kyiv")
    midnight, _ = _localize_window(dt.date(2026, 3, 29), dt.time(0, 0), dt.time(0, 0), tz)
    next_midnight, _ = _localize_window(dt.date(2026, 3, 30), dt.time(0, 0), dt.time(0, 0), tz)
    assert next_midnight - midnight == dt.timedelta(hours=23)


def test_localize_window_fall_back_calendar_day_is_25_hours_in_utc():
    """Case 12 (fall-back half). 2026-10-25 is the last Sunday of October."""
    tz = ZoneInfo("Europe/Kyiv")
    midnight, _ = _localize_window(dt.date(2026, 10, 25), dt.time(0, 0), dt.time(0, 0), tz)
    next_midnight, _ = _localize_window(dt.date(2026, 10, 26), dt.time(0, 0), dt.time(0, 0), tz)
    assert next_midnight - midnight == dt.timedelta(hours=25)


def test_localize_window_offset_recomputed_fresh_per_date_spring_forward():
    """
    Guards against the specific bug named in docs/DECISIONS.md's DST
    decision: resolving the UTC offset once and reusing it across dates,
    instead of resolving it fresh per date. Same local 09:00, one calendar
    day apart, straddling the transition: the UTC gap between them is 23h,
    not the naive 24h — the 1-hour deviation is the whole point of the
    assertion.
    """
    tz = ZoneInfo("Europe/Kyiv")
    before, _ = _localize_window(dt.date(2026, 3, 28), dt.time(9, 0), dt.time(18, 0), tz)
    after, _ = _localize_window(dt.date(2026, 3, 29), dt.time(9, 0), dt.time(18, 0), tz)
    assert after - before == dt.timedelta(hours=23)


def test_localize_window_offset_recomputed_fresh_per_date_fall_back():
    """
    Same guard, fall-back direction. Same local 09:00, one calendar day
    apart, straddling the transition: the UTC gap is 25h, not the naive
    24h — again, the 1-hour deviation is the whole point.
    """
    tz = ZoneInfo("Europe/Kyiv")
    before, _ = _localize_window(dt.date(2026, 10, 24), dt.time(9, 0), dt.time(18, 0), tz)
    after, _ = _localize_window(dt.date(2026, 10, 25), dt.time(9, 0), dt.time(18, 0), tz)
    assert after - before == dt.timedelta(hours=25)


# --- compute_open_windows (integration, DB-backed) ------------------------


def test_compute_open_windows_single_shift(salon, specialist):
    """Case 1."""
    monday = dt.date(2026, 8, 17)
    make_working_hours(
        salon=salon,
        specialist=specialist,
        day_of_week=monday.weekday(),
        start_time=dt.time(9, 0),
        end_time=dt.time(18, 0),
    )
    with tenant_context(salon.id):
        result = compute_open_windows(
            specialist=specialist,
            date_from=monday,
            date_to=monday,
            salon_timezone=salon.timezone,
        )
    assert len(result) == 1


def test_compute_open_windows_split_shift_with_lunch_gap(salon, specialist):
    """Case 2."""
    monday = dt.date(2026, 8, 17)
    make_working_hours(
        salon=salon,
        specialist=specialist,
        day_of_week=monday.weekday(),
        start_time=dt.time(9, 0),
        end_time=dt.time(13, 0),
    )
    make_working_hours(
        salon=salon,
        specialist=specialist,
        day_of_week=monday.weekday(),
        start_time=dt.time(14, 0),
        end_time=dt.time(18, 0),
    )
    with tenant_context(salon.id):
        result = compute_open_windows(
            specialist=specialist,
            date_from=monday,
            date_to=monday,
            salon_timezone=salon.timezone,
        )
    assert len(result) == 2  # lunch gap preserved, not merged


def test_compute_open_windows_merges_overlapping_working_hours_rows(salon, specialist):
    """
    Proves _merge_intervals is actually wired into compute_open_windows, not
    just correct in isolation (test_merge_intervals_overlapping_pair_merges
    above never calls the orchestrator at all). Europe/Kyiv is EEST (+3) in
    August, so 09:00-18:00 local is 06:00-15:00 UTC.
    """
    monday = dt.date(2026, 8, 17)
    make_working_hours(
        salon=salon,
        specialist=specialist,
        day_of_week=monday.weekday(),
        start_time=dt.time(9, 0),
        end_time=dt.time(14, 0),
    )
    make_working_hours(
        salon=salon,
        specialist=specialist,
        day_of_week=monday.weekday(),
        start_time=dt.time(12, 0),
        end_time=dt.time(18, 0),
    )
    with tenant_context(salon.id):
        result = compute_open_windows(
            specialist=specialist,
            date_from=monday,
            date_to=monday,
            salon_timezone=salon.timezone,
        )
    assert result == [
        Window(
            dt.datetime(2026, 8, 17, 6, 0, tzinfo=UTC),
            dt.datetime(2026, 8, 17, 15, 0, tzinfo=UTC),
        )
    ]


def test_compute_open_windows_time_off_partially_overlapping_shift_splits_window(salon, specialist):
    """
    Proves the TimeOff-to-blocking-interval adapter and _subtract_intervals
    are actually wired into compute_open_windows — case 11 below only
    covers a full-day TimeOff, which wouldn't catch a bug in how a
    partial-day, already-UTC TimeOff interval meets a freshly localized
    window. 12:00-13:00 salon-local (Europe/Kyiv, EEST +3 in August) is
    09:00-10:00 UTC.
    """
    monday = dt.date(2026, 8, 17)
    make_working_hours(
        salon=salon,
        specialist=specialist,
        day_of_week=monday.weekday(),
        start_time=dt.time(9, 0),
        end_time=dt.time(18, 0),
    )
    make_time_off(
        salon=salon,
        specialist=specialist,
        start_datetime=dt.datetime(2026, 8, 17, 9, 0, tzinfo=UTC),
        end_datetime=dt.datetime(2026, 8, 17, 10, 0, tzinfo=UTC),
    )
    with tenant_context(salon.id):
        result = compute_open_windows(
            specialist=specialist,
            date_from=monday,
            date_to=monday,
            salon_timezone=salon.timezone,
        )
    assert result == [
        Window(
            dt.datetime(2026, 8, 17, 6, 0, tzinfo=UTC),
            dt.datetime(2026, 8, 17, 9, 0, tzinfo=UTC),
        ),
        Window(
            dt.datetime(2026, 8, 17, 10, 0, tzinfo=UTC),
            dt.datetime(2026, 8, 17, 15, 0, tzinfo=UTC),
        ),
    ]


def test_compute_open_windows_day_with_no_working_hours_returns_empty(salon, specialist):
    """Case 9."""
    monday = dt.date(2026, 8, 17)
    with tenant_context(salon.id):
        result = compute_open_windows(
            specialist=specialist,
            date_from=monday,
            date_to=monday,
            salon_timezone=salon.timezone,
        )
    assert result == []


def test_compute_open_windows_range_spanning_several_days(salon, specialist):
    """Case 10. Monday has hours, Tuesday doesn't, Wednesday has hours."""
    monday = dt.date(2026, 8, 17)
    for offset in (0, 2):  # Monday, Wednesday
        day = monday + dt.timedelta(days=offset)
        make_working_hours(
            salon=salon,
            specialist=specialist,
            day_of_week=day.weekday(),
            start_time=dt.time(9, 0),
            end_time=dt.time(18, 0),
        )
    with tenant_context(salon.id):
        result = compute_open_windows(
            specialist=specialist,
            date_from=monday,
            date_to=monday + dt.timedelta(days=2),
            salon_timezone=salon.timezone,
        )
    assert len(result) == 2  # Monday + Wednesday, nothing for Tuesday


def test_compute_open_windows_time_off_on_different_weekday_does_not_affect_other_days(
    salon, specialist
):
    """Case 11."""
    monday = dt.date(2026, 8, 17)
    tuesday = monday + dt.timedelta(days=1)
    for day in (monday, tuesday):
        make_working_hours(
            salon=salon,
            specialist=specialist,
            day_of_week=day.weekday(),
            start_time=dt.time(9, 0),
            end_time=dt.time(18, 0),
        )
    # TimeOff covers all of Monday only.
    make_time_off(
        salon=salon,
        specialist=specialist,
        start_datetime=_localized_midnight(salon, monday),
        end_datetime=_localized_midnight(salon, tuesday),
    )
    with tenant_context(salon.id):
        result = compute_open_windows(
            specialist=specialist,
            date_from=monday,
            date_to=tuesday,
            salon_timezone=salon.timezone,
        )
    assert len(result) == 1  # Tuesday's window survives untouched


def test_compute_open_windows_single_day_range(salon, specialist):
    """Case 17."""
    monday = dt.date(2026, 8, 17)
    make_working_hours(
        salon=salon,
        specialist=specialist,
        day_of_week=monday.weekday(),
        start_time=dt.time(9, 0),
        end_time=dt.time(18, 0),
    )
    with tenant_context(salon.id):
        result = compute_open_windows(
            specialist=specialist,
            date_from=monday,
            date_to=monday,
            salon_timezone=salon.timezone,
        )
    assert len(result) == 1


def test_compute_open_windows_date_from_after_date_to_raises(salon, specialist):
    """Case 18."""
    with tenant_context(salon.id), pytest.raises(InvalidDateRangeError):
        compute_open_windows(
            specialist=specialist,
            date_from=dt.date(2026, 8, 20),
            date_to=dt.date(2026, 8, 15),
            salon_timezone=salon.timezone,
        )


def test_compute_open_windows_working_hours_weekday_absent_from_range_produces_no_window(
    salon, specialist
):
    """Case 19. WorkingHours exists for Sunday; range is Mon-Wed only."""
    monday = dt.date(2026, 8, 17)
    sunday = monday + dt.timedelta(days=6)
    make_working_hours(
        salon=salon,
        specialist=specialist,
        day_of_week=sunday.weekday(),
        start_time=dt.time(9, 0),
        end_time=dt.time(18, 0),
    )
    with tenant_context(salon.id):
        result = compute_open_windows(
            specialist=specialist,
            date_from=monday,
            date_to=monday + dt.timedelta(days=2),
            salon_timezone=salon.timezone,
        )
    assert result == []


def test_compute_open_windows_inactive_specialist_returns_empty_even_with_working_hours(
    salon, specialist
):
    """
    Case 6 (compute_open_windows half only — the caller-side filter half of
    the is_active guard belongs to the composition function's own future
    tests, not here).
    """
    monday = dt.date(2026, 8, 17)
    make_working_hours(
        salon=salon,
        specialist=specialist,
        day_of_week=monday.weekday(),
        start_time=dt.time(9, 0),
        end_time=dt.time(18, 0),
    )
    with tenant_context(salon.id):
        specialist.is_active = False
        specialist.save(update_fields=["is_active"])
        result = compute_open_windows(
            specialist=specialist,
            date_from=monday,
            date_to=monday,
            salon_timezone=salon.timezone,
        )
    assert result == []


def test_compute_open_windows_spring_forward_and_fall_back(salon, specialist):
    """
    Case 12, at the orchestrator level, both transition directions. Pure
    _localize_window tests above can't catch a bug where compute_open_windows
    itself resolves the offset once and reuses it across the loop over
    dates — only a real multi-day call through the orchestrator can. Saturday
    (2026-03-28/2026-10-24) and Sunday (2026-03-29/2026-10-25) share the same
    day_of_week values in both March and October, so one pair of WorkingHours
    rows covers both ranges.
    """
    for day_of_week in (5, 6):  # Saturday, Sunday
        make_working_hours(
            salon=salon,
            specialist=specialist,
            day_of_week=day_of_week,
            start_time=dt.time(9, 0),
            end_time=dt.time(18, 0),
        )

    with tenant_context(salon.id):
        spring = compute_open_windows(
            specialist=specialist,
            date_from=dt.date(2026, 3, 28),
            date_to=dt.date(2026, 3, 29),
            salon_timezone=salon.timezone,
        )
        fall = compute_open_windows(
            specialist=specialist,
            date_from=dt.date(2026, 10, 24),
            date_to=dt.date(2026, 10, 25),
            salon_timezone=salon.timezone,
        )

    spring_starts = sorted(w.start for w in spring)
    assert spring_starts[1] - spring_starts[0] == dt.timedelta(hours=23)

    fall_starts = sorted(w.start for w in fall)
    assert fall_starts[1] - fall_starts[0] == dt.timedelta(hours=25)


# --- compute_open_windows + Appointments (6.D) ------------------------


def test_compute_open_windows_no_appointments_matches_pre_appointment_behavior(salon, specialist):
    """Case 1 — appointments integrated, but zero exist; result is identical
    to 6.C's own single-shift behavior."""
    monday = dt.date(2026, 8, 17)
    make_working_hours(
        salon=salon,
        specialist=specialist,
        day_of_week=monday.weekday(),
        start_time=dt.time(9, 0),
        end_time=dt.time(18, 0),
    )
    with tenant_context(salon.id):
        result = compute_open_windows(
            specialist=specialist,
            date_from=monday,
            date_to=monday,
            salon_timezone=salon.timezone,
        )
    assert result == [
        Window(
            dt.datetime(2026, 8, 17, 6, 0, tzinfo=UTC), dt.datetime(2026, 8, 17, 15, 0, tzinfo=UTC)
        )
    ]


def test_compute_open_windows_appointment_splits_window(salon, customer, specialist, service):
    """Case 2."""
    monday = dt.date(2026, 8, 17)
    make_working_hours(
        salon=salon,
        specialist=specialist,
        day_of_week=monday.weekday(),
        start_time=dt.time(9, 0),
        end_time=dt.time(18, 0),
    )
    make_appointment(
        salon=salon,
        customer=customer,
        specialist=specialist,
        service=service,
        start=dt.datetime(2026, 8, 17, 9, 0, tzinfo=UTC),  # local 12:00
    )
    with tenant_context(salon.id):
        result = compute_open_windows(
            specialist=specialist,
            date_from=monday,
            date_to=monday,
            salon_timezone=salon.timezone,
        )
    assert result == [
        Window(
            dt.datetime(2026, 8, 17, 6, 0, tzinfo=UTC), dt.datetime(2026, 8, 17, 9, 0, tzinfo=UTC)
        ),
        Window(
            dt.datetime(2026, 8, 17, 10, 15, tzinfo=UTC),
            dt.datetime(2026, 8, 17, 15, 0, tzinfo=UTC),
        ),
    ]


def test_compute_open_windows_appointment_blocked_until_extends_past_window_end(
    salon, customer, specialist, service
):
    """Case 3."""
    monday = dt.date(2026, 8, 17)
    make_working_hours(
        salon=salon,
        specialist=specialist,
        day_of_week=monday.weekday(),
        start_time=dt.time(9, 0),
        end_time=dt.time(18, 0),
    )
    make_appointment(
        salon=salon,
        customer=customer,
        specialist=specialist,
        service=service,
        start=dt.datetime(2026, 8, 17, 14, 30, tzinfo=UTC),  # local 17:30; blocked_until 15:45 UTC
    )
    with tenant_context(salon.id):
        result = compute_open_windows(
            specialist=specialist,
            date_from=monday,
            date_to=monday,
            salon_timezone=salon.timezone,
        )
    assert result == [
        Window(
            dt.datetime(2026, 8, 17, 6, 0, tzinfo=UTC), dt.datetime(2026, 8, 17, 14, 30, tzinfo=UTC)
        )
    ]


def test_compute_open_windows_back_to_back_appointments_merge_into_one_gap(
    salon, customer, specialist, service
):
    """Case 4."""
    monday = dt.date(2026, 8, 17)
    make_working_hours(
        salon=salon,
        specialist=specialist,
        day_of_week=monday.weekday(),
        start_time=dt.time(9, 0),
        end_time=dt.time(18, 0),
    )
    first = make_appointment(
        salon=salon,
        customer=customer,
        specialist=specialist,
        service=service,
        start=dt.datetime(2026, 8, 17, 9, 0, tzinfo=UTC),
    )
    make_appointment(
        salon=salon,
        customer=customer,
        specialist=specialist,
        service=service,
        start=first.blocked_until,
    )
    with tenant_context(salon.id):
        result = compute_open_windows(
            specialist=specialist,
            date_from=monday,
            date_to=monday,
            salon_timezone=salon.timezone,
        )
    assert result == [
        Window(
            dt.datetime(2026, 8, 17, 6, 0, tzinfo=UTC), dt.datetime(2026, 8, 17, 9, 0, tzinfo=UTC)
        ),
        Window(
            dt.datetime(2026, 8, 17, 11, 30, tzinfo=UTC),
            dt.datetime(2026, 8, 17, 15, 0, tzinfo=UTC),
        ),
    ]


def test_compute_open_windows_window_after_appointment_starts_exactly_at_blocked_until(
    salon, customer, specialist, service
):
    """Case 5 — half-open boundary convention, through a real
    appointment-derived blocker rather than hand-built Window literals."""
    monday = dt.date(2026, 8, 17)
    make_working_hours(
        salon=salon,
        specialist=specialist,
        day_of_week=monday.weekday(),
        start_time=dt.time(9, 0),
        end_time=dt.time(18, 0),
    )
    appointment = make_appointment(
        salon=salon,
        customer=customer,
        specialist=specialist,
        service=service,
        start=dt.datetime(2026, 8, 17, 9, 0, tzinfo=UTC),
    )
    with tenant_context(salon.id):
        result = compute_open_windows(
            specialist=specialist,
            date_from=monday,
            date_to=monday,
            salon_timezone=salon.timezone,
        )
    assert result[1].start == appointment.blocked_until


@pytest.mark.parametrize("status", ACTIVE_APPOINTMENT_STATUSES)
def test_compute_open_windows_active_status_appointment_blocks(
    salon, customer, specialist, service, status
):
    """
    Mirror image of the terminal-status test below: an implementation using
    status=AppointmentStatus.CONFIRMED instead of
    status__in=ACTIVE_APPOINTMENT_STATUSES would pass every other test in
    this file, since make_appointment's own default is CONFIRMED —
    PENDING_PAYMENT would never be exercised as a blocking status otherwise.
    """
    monday = dt.date(2026, 8, 17)
    make_working_hours(
        salon=salon,
        specialist=specialist,
        day_of_week=monday.weekday(),
        start_time=dt.time(9, 0),
        end_time=dt.time(18, 0),
    )
    make_appointment(
        salon=salon,
        customer=customer,
        specialist=specialist,
        service=service,
        start=dt.datetime(2026, 8, 17, 9, 0, tzinfo=UTC),
        status=status,
    )
    with tenant_context(salon.id):
        result = compute_open_windows(
            specialist=specialist,
            date_from=monday,
            date_to=monday,
            salon_timezone=salon.timezone,
        )
    assert result == [
        Window(
            dt.datetime(2026, 8, 17, 6, 0, tzinfo=UTC), dt.datetime(2026, 8, 17, 9, 0, tzinfo=UTC)
        ),
        Window(
            dt.datetime(2026, 8, 17, 10, 15, tzinfo=UTC),
            dt.datetime(2026, 8, 17, 15, 0, tzinfo=UTC),
        ),
    ]


@pytest.mark.parametrize(
    "status",
    [
        AppointmentStatus.CANCELLED,
        AppointmentStatus.EXPIRED,
        AppointmentStatus.COMPLETED,
        AppointmentStatus.NO_SHOW,
    ],
)
def test_compute_open_windows_terminal_status_appointment_does_not_block(
    salon, customer, specialist, service, status
):
    """Case 6."""
    monday = dt.date(2026, 8, 17)
    make_working_hours(
        salon=salon,
        specialist=specialist,
        day_of_week=monday.weekday(),
        start_time=dt.time(9, 0),
        end_time=dt.time(18, 0),
    )
    make_appointment(
        salon=salon,
        customer=customer,
        specialist=specialist,
        service=service,
        start=dt.datetime(2026, 8, 17, 9, 0, tzinfo=UTC),
        status=status,
    )
    with tenant_context(salon.id):
        result = compute_open_windows(
            specialist=specialist,
            date_from=monday,
            date_to=monday,
            salon_timezone=salon.timezone,
        )
    assert result == [
        Window(
            dt.datetime(2026, 8, 17, 6, 0, tzinfo=UTC), dt.datetime(2026, 8, 17, 15, 0, tzinfo=UTC)
        )
    ]


def test_compute_open_windows_appointment_on_a_different_day_does_not_affect_other_days(
    salon, customer, specialist, service
):
    """Case 7."""
    monday = dt.date(2026, 8, 17)
    tuesday = monday + dt.timedelta(days=1)
    for day in (monday, tuesday):
        make_working_hours(
            salon=salon,
            specialist=specialist,
            day_of_week=day.weekday(),
            start_time=dt.time(9, 0),
            end_time=dt.time(18, 0),
        )
    make_appointment(
        salon=salon,
        customer=customer,
        specialist=specialist,
        service=service,
        start=dt.datetime(2026, 8, 17, 9, 0, tzinfo=UTC),  # Monday only
    )
    with tenant_context(salon.id):
        result = compute_open_windows(
            specialist=specialist,
            date_from=monday,
            date_to=tuesday,
            salon_timezone=salon.timezone,
        )
    assert result == [
        Window(
            dt.datetime(2026, 8, 17, 6, 0, tzinfo=UTC), dt.datetime(2026, 8, 17, 9, 0, tzinfo=UTC)
        ),
        Window(
            dt.datetime(2026, 8, 17, 10, 15, tzinfo=UTC),
            dt.datetime(2026, 8, 17, 15, 0, tzinfo=UTC),
        ),
        Window(
            dt.datetime(2026, 8, 18, 6, 0, tzinfo=UTC), dt.datetime(2026, 8, 18, 15, 0, tzinfo=UTC)
        ),
    ]


def test_compute_open_windows_appointment_for_a_different_specialist_does_not_block(
    salon, customer, specialist, service
):
    """Case 8."""
    monday = dt.date(2026, 8, 17)
    make_working_hours(
        salon=salon,
        specialist=specialist,
        day_of_week=monday.weekday(),
        start_time=dt.time(9, 0),
        end_time=dt.time(18, 0),
    )
    with tenant_context(salon.id):
        other_specialist = Specialist.objects.create(salon=salon, name="Other Specialist")
    make_appointment(
        salon=salon,
        customer=customer,
        specialist=other_specialist,
        service=service,
        start=dt.datetime(2026, 8, 17, 9, 0, tzinfo=UTC),
    )
    with tenant_context(salon.id):
        result = compute_open_windows(
            specialist=specialist,
            date_from=monday,
            date_to=monday,
            salon_timezone=salon.timezone,
        )
    assert result == [
        Window(
            dt.datetime(2026, 8, 17, 6, 0, tzinfo=UTC), dt.datetime(2026, 8, 17, 15, 0, tzinfo=UTC)
        )
    ]


def test_compute_open_windows_appointment_starting_before_range_still_clips(
    salon, customer, specialist, service
):
    """
    Case 9. An early-morning shift (00:00-03:00 local) puts the range
    boundary (local midnight) inside the window, so an appointment that
    started the salon-local day before but extends into the shift must
    still be fetched and still clip. A start_datetime__gte=range_start_utc
    filter, instead of the correct overlap condition, would exclude it and
    this test would see the whole window unclipped.
    """
    monday = dt.date(2026, 8, 17)
    make_working_hours(
        salon=salon,
        specialist=specialist,
        day_of_week=monday.weekday(),
        start_time=dt.time(0, 0),
        end_time=dt.time(3, 0),
    )
    make_appointment(
        salon=salon,
        customer=customer,
        specialist=specialist,
        service=service,
        start=dt.datetime(2026, 8, 16, 20, 30, tzinfo=UTC),  # local Aug 16 23:30
    )
    with tenant_context(salon.id):
        result = compute_open_windows(
            specialist=specialist,
            date_from=monday,
            date_to=monday,
            salon_timezone=salon.timezone,
        )
    assert result == [
        Window(
            dt.datetime(2026, 8, 16, 21, 45, tzinfo=UTC), dt.datetime(2026, 8, 17, 0, 0, tzinfo=UTC)
        )
    ]


def test_compute_open_windows_appointment_ending_after_range_still_clips(
    salon, customer, specialist, service
):
    """
    Case 10. A late-night shift (22:00-23:30 local) so an appointment whose
    blocked_until extends past the range's own end still clips. The correct
    query has no upper bound on blocked_until at all — a version that added
    one (e.g. blocked_until__lte=range_end_utc) would incorrectly exclude
    this appointment.
    """
    monday = dt.date(2026, 8, 17)
    make_working_hours(
        salon=salon,
        specialist=specialist,
        day_of_week=monday.weekday(),
        start_time=dt.time(22, 0),
        end_time=dt.time(23, 30),
    )
    make_appointment(
        salon=salon,
        customer=customer,
        specialist=specialist,
        service=service,
        start=dt.datetime(2026, 8, 17, 20, 0, tzinfo=UTC),  # local 23:00
    )
    with tenant_context(salon.id):
        result = compute_open_windows(
            specialist=specialist,
            date_from=monday,
            date_to=monday,
            salon_timezone=salon.timezone,
        )
    assert result == [
        Window(
            dt.datetime(2026, 8, 17, 19, 0, tzinfo=UTC), dt.datetime(2026, 8, 17, 20, 0, tzinfo=UTC)
        )
    ]


def test_compute_open_windows_time_off_and_appointment_overlapping_each_other_compose(
    salon, customer, specialist, service
):
    """Case 11 — a TimeOff and an Appointment overlapping EACH OTHER (not
    just the window), proving the two adapters' output is concatenated and
    merged as one list before subtraction, not applied as two independent
    passes."""
    monday = dt.date(2026, 8, 17)
    make_working_hours(
        salon=salon,
        specialist=specialist,
        day_of_week=monday.weekday(),
        start_time=dt.time(9, 0),
        end_time=dt.time(18, 0),
    )
    make_time_off(
        salon=salon,
        specialist=specialist,
        start_datetime=dt.datetime(2026, 8, 17, 9, 0, tzinfo=UTC),
        end_datetime=dt.datetime(2026, 8, 17, 10, 0, tzinfo=UTC),
    )
    make_appointment(
        salon=salon,
        customer=customer,
        specialist=specialist,
        service=service,
        start=dt.datetime(2026, 8, 17, 9, 45, tzinfo=UTC),
    )
    with tenant_context(salon.id):
        result = compute_open_windows(
            specialist=specialist,
            date_from=monday,
            date_to=monday,
            salon_timezone=salon.timezone,
        )
    assert result == [
        Window(
            dt.datetime(2026, 8, 17, 6, 0, tzinfo=UTC), dt.datetime(2026, 8, 17, 9, 0, tzinfo=UTC)
        ),
        Window(
            dt.datetime(2026, 8, 17, 11, 0, tzinfo=UTC), dt.datetime(2026, 8, 17, 15, 0, tzinfo=UTC)
        ),
    ]


def test_compute_open_windows_appointment_exactly_matching_window_returns_no_windows(
    salon, customer, specialist, service
):
    """Case 12. WorkingHours sized to exactly match the service's own
    duration+buffer block (75 minutes)."""
    monday = dt.date(2026, 8, 17)
    make_working_hours(
        salon=salon,
        specialist=specialist,
        day_of_week=monday.weekday(),
        start_time=dt.time(12, 0),
        end_time=dt.time(13, 15),
    )
    make_appointment(
        salon=salon,
        customer=customer,
        specialist=specialist,
        service=service,
        start=dt.datetime(2026, 8, 17, 9, 0, tzinfo=UTC),  # local 12:00
    )
    with tenant_context(salon.id):
        result = compute_open_windows(
            specialist=specialist,
            date_from=monday,
            date_to=monday,
            salon_timezone=salon.timezone,
        )
    assert result == []


def test_compute_open_windows_ignores_appointment_from_a_different_salon(
    salon, other_salon, specialist
):
    """
    Case 13. A cross-salon appointment does not leak into this salon's
    computed windows.

    This does NOT isolate tenant scoping specifically: _fetch_appointments
    filters by a specific specialist OBJECT, and Specialist uses one global
    auto-incrementing id across every salon, so no two Specialist rows
    anywhere can ever share a pk — `specialist=specialist` alone already
    makes cross-salon leakage structurally impossible here, regardless of
    Appointment.objects vs Appointment.unscoped_objects. The composite
    tenant FK on Appointment (core/db.py's composite_tenant_fk) additionally
    guarantees Appointment.salon_id always equals
    Appointment.specialist.salon_id, so the two managers can never disagree
    on a query already filtered to one specialist. other_salon's specialist
    is still named "Jane" — same as this file's own specialist fixture — so
    a reader can see no accidental name coincidence is doing any work
    either. This is a regression/documentation safety net for the
    guarantee, not a test that would fail under a manager swap.
    """
    monday = dt.date(2026, 8, 17)
    make_working_hours(
        salon=salon,
        specialist=specialist,
        day_of_week=monday.weekday(),
        start_time=dt.time(9, 0),
        end_time=dt.time(18, 0),
    )
    with tenant_context(other_salon.id):
        other_category = ServiceCategory.objects.create(salon=other_salon, name="Nails")
        other_service = Service.objects.create(
            salon=other_salon,
            category=other_category,
            name="Manicure",
            duration_minutes=60,
            price="500.00",
            buffer_minutes=15,
        )
        other_specialist = Specialist.objects.create(salon=other_salon, name="Jane")
        other_customer = Customer.objects.create(
            salon=other_salon, name="Bob", email="bob@example.com", phone="+10000000001"
        )
    make_appointment(
        salon=other_salon,
        customer=other_customer,
        specialist=other_specialist,
        service=other_service,
        start=dt.datetime(2026, 8, 17, 12, 0, tzinfo=UTC),
    )
    with tenant_context(salon.id):
        result = compute_open_windows(
            specialist=specialist,
            date_from=monday,
            date_to=monday,
            salon_timezone=salon.timezone,
        )
    assert result == [
        Window(
            dt.datetime(2026, 8, 17, 6, 0, tzinfo=UTC), dt.datetime(2026, 8, 17, 15, 0, tzinfo=UTC)
        )
    ]


def test_compute_open_windows_issues_exactly_three_queries(
    django_assert_num_queries, salon, customer, specialist, service
):
    """Case 14. docs/DECISIONS.md § Stage 6.D decisions: pinned because this
    project has already lost query efficiency to an unpinned regression once
    (a missing select_related in Stage 4)."""
    monday = dt.date(2026, 8, 17)
    make_working_hours(
        salon=salon,
        specialist=specialist,
        day_of_week=monday.weekday(),
        start_time=dt.time(9, 0),
        end_time=dt.time(18, 0),
    )
    make_time_off(
        salon=salon,
        specialist=specialist,
        start_datetime=dt.datetime(2026, 8, 17, 9, 0, tzinfo=UTC),
        end_datetime=dt.datetime(2026, 8, 17, 10, 0, tzinfo=UTC),
    )
    make_appointment(
        salon=salon,
        customer=customer,
        specialist=specialist,
        service=service,
        start=dt.datetime(2026, 8, 17, 11, 0, tzinfo=UTC),
    )
    with tenant_context(salon.id):
        with django_assert_num_queries(3):
            compute_open_windows(
                specialist=specialist,
                date_from=monday,
                date_to=monday,
                salon_timezone=salon.timezone,
            )
