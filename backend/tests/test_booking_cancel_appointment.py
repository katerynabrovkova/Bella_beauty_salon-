"""
Stage 7.E — `cancel_appointment` service function (docs/ARCHITECTURE.md § 2,
§ 7, the State machines section; docs/DECISIONS.md § Stage 7.E decisions).
Tests only — written before the service exists. Expected to fail on
collection (ImportError: cannot import name 'cancel_appointment' from
'booking.services') until that function is added — same two-step red shape
`test_booking_create_appointment.py` established for `create_appointment`
itself.

Signature under test:

    cancel_appointment(*, appointment_id, salon, cancelled_by, now,
                        reason="") -> Appointment

Real-DB integration tests throughout (the service does select_for_update()
plus a write) — no monkeypatching. All `now` values are tz-aware UTC
literals, never `timezone.now()` (§ Stage 6.F/6.I decisions' discipline).
Every appointment/customer/token created here passes `salon=` explicitly
(Stage 6 shell-seeding trap, per CLAUDE.md).
"""

import datetime as dt

import pytest

from booking.models import Appointment, AppointmentStatus, CancelledBy
from booking.services import cancel_appointment
from core.exceptions import InvalidStateTransitionError
from core.tenancy import tenant_context
from tests.conftest import make_appointment

pytestmark = pytest.mark.django_db

START = dt.datetime(2026, 8, 20, 10, 0, tzinfo=dt.UTC)
NOW = dt.datetime(2026, 8, 18, 9, 0, tzinfo=dt.UTC)


def _unrelated_fields(appt: Appointment) -> dict:
    """Fields cancel_appointment must never touch, for the "only the
    cancellation fields changed" assertions (items 1/2)."""
    return {
        "start_datetime": appt.start_datetime,
        "end_datetime": appt.end_datetime,
        "blocked_until": appt.blocked_until,
        "specialist_id": appt.specialist_id,
        "service_id": appt.service_id,
        "customer_id": appt.customer_id,
        "service_price_at_booking": appt.service_price_at_booking,
        "deposit_percentage_at_booking": appt.deposit_percentage_at_booking,
        "hold_expires_at": appt.hold_expires_at,
    }


# --- 1 & 2. Happy path: any ACTIVE status -----------------------------------


def test_cancel_appointment_happy_path_cancels_a_pending_payment_appointment(
    salon, specialist, service, customer
):
    appt = make_appointment(
        salon=salon,
        customer=customer,
        specialist=specialist,
        service=service,
        start=START,
        status=AppointmentStatus.PENDING_PAYMENT,
    )
    # Refresh before snapshotting: the in-memory object from .create() still
    # carries service_price_at_booking/deposit_percentage_at_booking as
    # whatever Python type the service/salon fixtures assigned (str/int),
    # not the Decimal a DB read returns — the same coercion trap
    # test_booking_create_appointment.py's snapshot-fields test documents.
    # Comparing against a later DB-fetched row without this fails on type,
    # not value.
    with tenant_context(salon.id):
        appt.refresh_from_db()
    before = _unrelated_fields(appt)

    with tenant_context(salon.id):
        result = cancel_appointment(
            appointment_id=appt.id,
            salon=salon,
            cancelled_by=CancelledBy.CUSTOMER,
            now=NOW,
            reason="change of plans",
        )

    assert result.status == AppointmentStatus.CANCELLED
    assert result.cancelled_at == NOW
    assert result.cancelled_by == CancelledBy.CUSTOMER
    assert result.cancellation_reason == "change of plans"

    with tenant_context(salon.id):
        row = Appointment.objects.get(pk=appt.id)
    assert row.status == AppointmentStatus.CANCELLED
    assert row.cancelled_at == NOW
    assert row.cancelled_by == CancelledBy.CUSTOMER
    assert row.cancellation_reason == "change of plans"
    assert _unrelated_fields(row) == before


def test_cancel_appointment_also_cancels_a_confirmed_appointment(
    salon, specialist, service, customer
):
    """Proves the guard is "in ACTIVE_APPOINTMENT_STATUSES", not
    "== PENDING_PAYMENT" — CONFIRMED is the other member of that set."""
    appt = make_appointment(
        salon=salon,
        customer=customer,
        specialist=specialist,
        service=service,
        start=START,
        status=AppointmentStatus.CONFIRMED,
    )
    # Same coercion trap as the PENDING_PAYMENT test above — refresh before
    # snapshotting so `before` is comparable to the later DB-fetched `row`.
    with tenant_context(salon.id):
        appt.refresh_from_db()
    before = _unrelated_fields(appt)

    with tenant_context(salon.id):
        result = cancel_appointment(
            appointment_id=appt.id,
            salon=salon,
            cancelled_by=CancelledBy.CUSTOMER,
            now=NOW,
            reason="change of plans",
        )

    assert result.status == AppointmentStatus.CANCELLED
    assert result.cancelled_at == NOW
    assert result.cancelled_by == CancelledBy.CUSTOMER
    assert result.cancellation_reason == "change of plans"

    with tenant_context(salon.id):
        row = Appointment.objects.get(pk=appt.id)
    assert row.status == AppointmentStatus.CANCELLED
    assert row.cancelled_at == NOW
    assert row.cancelled_by == CancelledBy.CUSTOMER
    assert row.cancellation_reason == "change of plans"
    assert _unrelated_fields(row) == before


# --- 3. Non-active statuses raise InvalidStateTransitionError ---------------


def test_cancel_appointment_rejects_an_already_cancelled_appointment(
    salon, specialist, service, customer
):
    appt = make_appointment(
        salon=salon,
        customer=customer,
        specialist=specialist,
        service=service,
        start=START,
        status=AppointmentStatus.CANCELLED,
    )

    with tenant_context(salon.id), pytest.raises(InvalidStateTransitionError) as exc_info:
        cancel_appointment(
            appointment_id=appt.id,
            salon=salon,
            cancelled_by=CancelledBy.CUSTOMER,
            now=NOW,
        )

    assert exc_info.value.details == {"current_status": AppointmentStatus.CANCELLED}
    with tenant_context(salon.id):
        row = Appointment.objects.get(pk=appt.id)
    assert row.status == AppointmentStatus.CANCELLED
    assert row.cancelled_at is None
    assert row.cancelled_by is None
    assert row.cancellation_reason == ""


def test_cancel_appointment_rejects_an_expired_appointment(salon, specialist, service, customer):
    """The sweep-flipped-to-EXPIRED case — the second distinct reason this
    guard exists, alongside repeat-cancel."""
    appt = make_appointment(
        salon=salon,
        customer=customer,
        specialist=specialist,
        service=service,
        start=START,
        status=AppointmentStatus.EXPIRED,
    )

    with tenant_context(salon.id), pytest.raises(InvalidStateTransitionError) as exc_info:
        cancel_appointment(
            appointment_id=appt.id,
            salon=salon,
            cancelled_by=CancelledBy.CUSTOMER,
            now=NOW,
        )

    assert exc_info.value.details == {"current_status": AppointmentStatus.EXPIRED}
    with tenant_context(salon.id):
        row = Appointment.objects.get(pk=appt.id)
    assert row.status == AppointmentStatus.EXPIRED
    assert row.cancelled_at is None
    assert row.cancelled_by is None
    assert row.cancellation_reason == ""


# --- 4. cancelled_by round-trips for every role ------------------------------


def test_cancel_appointment_stores_cancelled_by_guest(salon, specialist, service, customer):
    appt = make_appointment(
        salon=salon,
        customer=customer,
        specialist=specialist,
        service=service,
        start=START,
        status=AppointmentStatus.CONFIRMED,
    )
    with tenant_context(salon.id):
        result = cancel_appointment(
            appointment_id=appt.id, salon=salon, cancelled_by=CancelledBy.GUEST, now=NOW
        )
    assert result.cancelled_by == CancelledBy.GUEST


def test_cancel_appointment_stores_cancelled_by_customer(salon, specialist, service, customer):
    appt = make_appointment(
        salon=salon,
        customer=customer,
        specialist=specialist,
        service=service,
        start=START,
        status=AppointmentStatus.CONFIRMED,
    )
    with tenant_context(salon.id):
        result = cancel_appointment(
            appointment_id=appt.id, salon=salon, cancelled_by=CancelledBy.CUSTOMER, now=NOW
        )
    assert result.cancelled_by == CancelledBy.CUSTOMER


def test_cancel_appointment_stores_cancelled_by_staff(salon, specialist, service, customer):
    appt = make_appointment(
        salon=salon,
        customer=customer,
        specialist=specialist,
        service=service,
        start=START,
        status=AppointmentStatus.CONFIRMED,
    )
    with tenant_context(salon.id):
        result = cancel_appointment(
            appointment_id=appt.id, salon=salon, cancelled_by=CancelledBy.STAFF, now=NOW
        )
    assert result.cancelled_by == CancelledBy.STAFF


# --- 5. reason is optional and wired through ---------------------------------


def test_cancel_appointment_defaults_reason_to_empty_string(salon, specialist, service, customer):
    appt = make_appointment(
        salon=salon,
        customer=customer,
        specialist=specialist,
        service=service,
        start=START,
        status=AppointmentStatus.CONFIRMED,
    )
    with tenant_context(salon.id):
        result = cancel_appointment(
            appointment_id=appt.id, salon=salon, cancelled_by=CancelledBy.CUSTOMER, now=NOW
        )
    assert result.cancellation_reason == ""


def test_cancel_appointment_stores_a_non_empty_reason(salon, specialist, service, customer):
    appt = make_appointment(
        salon=salon,
        customer=customer,
        specialist=specialist,
        service=service,
        start=START,
        status=AppointmentStatus.CONFIRMED,
    )
    with tenant_context(salon.id):
        result = cancel_appointment(
            appointment_id=appt.id,
            salon=salon,
            cancelled_by=CancelledBy.CUSTOMER,
            now=NOW,
            reason="specialist unavailable",
        )
    assert result.cancellation_reason == "specialist unavailable"


# --- 6. Nonexistent appointment -----------------------------------------------


def test_cancel_appointment_nonexistent_id_raises_bare_does_not_exist(salon):
    """The service doesn't know HTTP — a nonexistent id is a bare
    Appointment.DoesNotExist, not a translated 404."""
    with tenant_context(salon.id), pytest.raises(Appointment.DoesNotExist):
        cancel_appointment(
            appointment_id=999_999_999,
            salon=salon,
            cancelled_by=CancelledBy.CUSTOMER,
            now=NOW,
        )


# --- 7. Tenant isolation ------------------------------------------------------


def test_cancel_appointment_does_not_find_another_salons_appointment(
    salon, other_salon, specialist, service, customer
):
    """specialist/service/customer/appointment all belong to `salon`; the
    call passes salon=other_salon. select_for_update().get(salon=salon,
    pk=...) filters by the passed salon, so a foreign appointment is
    indistinguishable from a nonexistent one — this proves `salon` is
    actually applied in the fetch, not silently ignored."""
    appt = make_appointment(
        salon=salon,
        customer=customer,
        specialist=specialist,
        service=service,
        start=START,
        status=AppointmentStatus.CONFIRMED,
    )

    with tenant_context(salon.id), pytest.raises(Appointment.DoesNotExist):
        cancel_appointment(
            appointment_id=appt.id,
            salon=other_salon,
            cancelled_by=CancelledBy.CUSTOMER,
            now=NOW,
        )
