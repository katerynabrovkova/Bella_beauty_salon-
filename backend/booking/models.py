from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import RangeOperators
from django.db import models

from accounts.models import Customer
from catalog.models import Service
from core.models import TenantScopedModel, TimeStamped
from specialists.models import Specialist


class AppointmentStatus(models.TextChoices):
    PENDING_PAYMENT = "pending_payment", "Pending payment"
    CONFIRMED = "confirmed", "Confirmed"
    CANCELLED = "cancelled", "Cancelled"
    EXPIRED = "expired", "Expired"
    COMPLETED = "completed", "Completed"
    NO_SHOW = "no_show", "No-show"


ACTIVE_APPOINTMENT_STATUSES = [AppointmentStatus.PENDING_PAYMENT, AppointmentStatus.CONFIRMED]


class CancelledBy(models.TextChoices):
    CUSTOMER = "customer", "Customer"
    GUEST = "guest", "Guest"
    STAFF = "staff", "Staff"
    SYSTEM = "system", "System"


class Appointment(TenantScopedModel, TimeStamped):
    """
    docs/ARCHITECTURE.md § 2, § 7, and the "State machines" section.
    Status is modeled here as a plain field only — transition logic is
    Stage 7, not this stage.
    """

    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name="appointments")
    specialist = models.ForeignKey(Specialist, on_delete=models.PROTECT, related_name="appointments")
    service = models.ForeignKey(Service, on_delete=models.PROTECT, related_name="appointments")

    start_datetime = models.DateTimeField()
    end_datetime = models.DateTimeField()
    # end_datetime + service.buffer_minutes at booking time, stored rather
    # than recomputed via a join (docs/ARCHITECTURE.md § 2, § 7).
    blocked_until = models.DateTimeField()

    # Snapshots of Service.price / Salon.deposit_percentage at booking time —
    # a later price or deposit-percentage change must never rewrite what an
    # already-made booking owes (docs/ARCHITECTURE.md § 2, § 8).
    service_price_at_booking = models.DecimalField(max_digits=10, decimal_places=2)
    deposit_percentage_at_booking = models.DecimalField(max_digits=5, decimal_places=2)

    # Set at creation only for PENDING_PAYMENT appointments.
    hold_expires_at = models.DateTimeField(null=True, blank=True)

    status = models.CharField(
        max_length=32, choices=AppointmentStatus.choices, default=AppointmentStatus.PENDING_PAYMENT
    )

    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.CharField(max_length=16, choices=CancelledBy.choices, null=True, blank=True)
    cancellation_reason = models.TextField(blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["specialist", "start_datetime"], name="appt_specialist_start_idx"),
            models.Index(fields=["salon", "status"], name="appointment_salon_status_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(start_datetime__lt=models.F("end_datetime")),
                name="appointment_start_before_end",
            ),
            models.CheckConstraint(
                condition=models.Q(end_datetime__lte=models.F("blocked_until")),
                name="appointment_end_before_or_equal_blocked_until",
            ),
            # The actual double-booking guard (docs/ARCHITECTURE.md § 7):
            # operates on the buffered interval, filtered to statuses that
            # still hold the slot.
            ExclusionConstraint(
                name="appointment_no_overlapping_active_bookings",
                expressions=[
                    ("specialist", RangeOperators.EQUAL),
                    (
                        models.Func("start_datetime", "blocked_until", function="TSTZRANGE"),
                        RangeOperators.OVERLAPS,
                    ),
                ],
                condition=models.Q(status__in=ACTIVE_APPOINTMENT_STATUSES),
            ),
        ]

    def __str__(self) -> str:
        return f"{self.customer} / {self.specialist} @ {self.start_datetime.isoformat()}"
