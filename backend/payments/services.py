"""
Stage 8.C — payment-initiation core (docs/ARCHITECTURE.md § 8;
docs/DECISIONS.md § Stage 8 decisions, § Stage 8.C decisions).

Requires tenant context to already be bound (core.tenancy.tenant_context) —
this function does not bind it itself, same convention as
booking/services.py's create_appointment/cancel_appointment.

`reference` passed to `provider.start_payment()` is `str(appointment.id)`,
not the `Payment` id the original Stage 8 decision described: on a fresh
attempt no `Payment` row exists yet at call time (§ Stage 8.C's "write the
row only after a successful provider response"), so a not-yet-existing pk
can't be used. `Payment.appointment_id` is unique (one-to-one), so
`appointment.id` is an equally valid webhook-correlation key — but this is a
deviation from the literal old wording, worth reconciling in
docs/DECISIONS.md.
"""

import datetime as dt
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction

from booking.models import Appointment, AppointmentStatus
from core.exceptions import InvalidStateTransitionError, PaymentProviderError
from payments.models import Payment, PaymentStatus
from payments.providers.base import PaymentProvider
from tenants.models import Salon


def _round_half_up_to_whole(amount: Decimal) -> Decimal:
    return amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP).quantize(Decimal("0.01"))


def _compute_deposit_amount(appointment: Appointment) -> Decimal:
    raw = (
        appointment.service_price_at_booking
        * appointment.deposit_percentage_at_booking
        / Decimal("100")
    )
    return _round_half_up_to_whole(raw)


def initiate_payment(
    *,
    appointment_id: int,
    salon: Salon,
    provider: PaymentProvider,
    now: dt.datetime,
) -> tuple[Payment, object | None]:
    """
    docs/DECISIONS.md § Stage 8.C decisions. The select_for_update() fetch,
    the PENDING_PAYMENT recheck, and the existing-Payment check all happen
    inside one short atomic() block — locked, decided, released — before the
    network call to the provider, mirroring the booking/payment-separation
    rule (DB transactions stay short; network calls live outside them).

    Idempotency: an existing PENDING Payment is returned as-is, with
    provider_data=None, and the provider is not called again. An existing
    FAILED Payment is retried in place — same row (same pk), transitioned
    FAILED -> PENDING with a new provider_reference_id — never a second row,
    since Payment.appointment is a OneToOneField.
    """
    with transaction.atomic():
        appointment = Appointment.objects.select_for_update().get(salon=salon, pk=appointment_id)
        if appointment.status != AppointmentStatus.PENDING_PAYMENT:
            raise InvalidStateTransitionError(details={"current_status": appointment.status})

        existing_payment = Payment.objects.filter(appointment=appointment).first()
        if existing_payment is not None and existing_payment.status == PaymentStatus.PENDING:
            return existing_payment, None

    deposit_amount = _compute_deposit_amount(appointment)
    try:
        intent = provider.start_payment(
            amount=deposit_amount,
            currency=salon.currency,
            reference=str(appointment.id),
        )
    except Exception as exc:
        raise PaymentProviderError() from exc

    if existing_payment is not None:
        existing_payment.status = PaymentStatus.PENDING
        existing_payment.provider_reference_id = intent.provider_reference_id
        existing_payment.save(update_fields=["status", "provider_reference_id"])
        payment = existing_payment
    else:
        payment = Payment.objects.create(
            salon=salon,
            appointment=appointment,
            amount=deposit_amount,
            currency=salon.currency,
            status=PaymentStatus.PENDING,
            provider_reference_id=intent.provider_reference_id,
        )

    return payment, intent.provider_data
