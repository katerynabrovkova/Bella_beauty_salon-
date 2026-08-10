from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models

from core.models import TenantScopedModel, TimeStamped


class User(AbstractUser):
    """
    Platform-wide auth identity (docs/DECISIONS.md § Identity). A thin
    subclass of AbstractUser with no new fields yet — made custom now, not
    later, because swapping AUTH_USER_MODEL after the first migration is a
    disruptive, hard-to-reverse change; this keeps the door open at zero
    present cost.
    """


class SalonStaffRole(models.TextChoices):
    ADMIN = "admin", "Admin"


class SalonStaff(TenantScopedModel, TimeStamped):
    """A back-office login: User x Salon with a role (docs/ARCHITECTURE.md § 4)."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    role = models.CharField(
        max_length=32, choices=SalonStaffRole.choices, default=SalonStaffRole.ADMIN
    )

    class Meta(TenantScopedModel.Meta):
        abstract = False
        constraints = [
            *TenantScopedModel.Meta.constraints,
            models.UniqueConstraint(fields=["user", "salon"], name="salonstaff_user_salon_uniq"),
        ]

    def __str__(self) -> str:
        return f"{self.user} @ {self.salon} ({self.role})"


class Customer(TenantScopedModel, TimeStamped):
    """
    Per-salon identity, guest or registered (docs/DECISIONS.md § Identity).
    `Appointment` always references this, never `User` directly.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="customers",
    )
    name = models.CharField(max_length=255)
    email = models.EmailField()
    phone = models.CharField(max_length=32)

    class Meta(TenantScopedModel.Meta):
        abstract = False
        constraints = [
            *TenantScopedModel.Meta.constraints,
            models.UniqueConstraint(fields=["salon", "email"], name="customer_salon_email_uniq"),
        ]

    def __str__(self) -> str:
        return f"{self.name} @ {self.salon}"
