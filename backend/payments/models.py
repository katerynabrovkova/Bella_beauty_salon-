from django.core.validators import RegexValidator
from django.db import models

from booking.models import Appointment
from core.models import TenantScopedModel, TimeStamped

_ISO_4217_VALIDATOR = RegexValidator(r"^[A-Z]{3}$")


class PaymentStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    PROCESSING = "processing", "Processing"
    SUCCEEDED = "succeeded", "Succeeded"
    FAILED = "failed", "Failed"
    EXPIRED = "expired", "Expired"
    CANCELLED = "cancelled", "Cancelled"
    REFUND_PENDING = "refund_pending", "Refund pending"
    REFUNDED = "refunded", "Refunded"


class Payment(TenantScopedModel, TimeStamped):
    """
    The deposit payment/refund lifecycle (docs/ARCHITECTURE.md § 8), modeled
    separately from Appointment.status. One deposit payment per appointment.
    """

    appointment = models.OneToOneField(
        Appointment, on_delete=models.PROTECT, related_name="payment"
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    # ISO 4217, frozen from Salon.currency at Payment creation time — copied
    # once and never mutated afterward, even if the salon later changes its
    # currency (docs/DECISIONS.md § Stage 8 decisions). No model-level
    # default; the copying itself is Stage 8.C, not this field addition.
    currency = models.CharField(max_length=3, validators=[_ISO_4217_VALIDATOR])
    status = models.CharField(
        max_length=32, choices=PaymentStatus.choices, default=PaymentStatus.PENDING
    )
    provider_reference_id = models.CharField(max_length=255, blank=True, db_index=True)
    # Stuck-refund alert marker, not a new state-machine status — REFUND_PENDING
    # already describes the state; this is a flag on top of it, set by a
    # future background sweep (docs/DECISIONS.md § Stage 8 decisions). No
    # db_index yet — nothing filters on it until an admin view needs to.
    flagged_for_review = models.BooleanField(default=False)

    def __str__(self) -> str:
        return f"Payment for {self.appointment} ({self.status})"


class ProcessedWebhookEvent(models.Model):
    """
    Idempotency ledger for inbound payment-provider webhooks
    (docs/ARCHITECTURE.md § 8). Not a TenantScopedModel: an event arrives
    before we know which salon its payment belongs to.
    """

    provider_event_id = models.CharField(max_length=255, unique=True)
    processed_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return self.provider_event_id
