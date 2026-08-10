from typing import ClassVar

from django.conf import settings
from django.contrib.auth.base_user import BaseUserManager
from django.contrib.auth.models import AbstractUser
from django.db import models

from core.models import TenantScopedModel, TimeStamped


class UserManager(BaseUserManager["User"]):
    """
    email is USERNAME_FIELD (see User below), so Django's default
    UserManager — built around `username` — doesn't apply. use_in_migrations
    so `migrate`/`createsuperuser` can rely on this manager existing.
    """

    use_in_migrations = True

    def _create_user(self, email: str, password: str | None, **extra_fields: object) -> "User":
        if not email:
            raise ValueError("Users must have an email address.")
        user = self.model(email=self.normalize_email(email), **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(
        self, email: str, password: str | None = None, **extra_fields: object
    ) -> "User":
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(
        self, email: str, password: str | None = None, **extra_fields: object
    ) -> "User":
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")
        return self._create_user(email, password, **extra_fields)


class User(AbstractUser):
    """
    Platform-wide auth identity (docs/DECISIONS.md § Identity). A thin
    subclass of AbstractUser — made custom from Stage 0, not later, because
    swapping AUTH_USER_MODEL after the first migration is a disruptive,
    hard-to-reverse change; this keeps the door open at zero present cost.

    `username` is dropped and `email` is the login identity (USERNAME_FIELD)
    — docs/ARCHITECTURE.md § 3 already committed to "standard email +
    password" login, which needs a unique, login-bearing email field; this is
    that commitment's implementation, recorded in docs/DECISIONS.md § Stage 3
    decisions.
    """

    username = None  # type: ignore[assignment]
    email = models.EmailField(unique=True)

    # Nullable: unset means unverified. Before verification a user can log
    # in, but cannot complete guest->account merge or access SalonStaff-gated
    # endpoints even with a real SalonStaff row (docs/ARCHITECTURE.md § 3,
    # docs/DECISIONS.md § Stage 3 decisions).
    email_verified_at = models.DateTimeField(null=True, blank=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: ClassVar[list[str]] = []

    # django-stubs types AbstractUser.objects as django.contrib.auth.models.
    # UserManager[User]; our UserManager is a from-scratch BaseUserManager
    # subclass (Django's own UserManager assumes `username`), so it isn't a
    # subtype of that stub's declared type. Same pattern as `username = None`
    # above — a known, standard friction point with a custom-email-login
    # manager, not a real type error.
    objects = UserManager()  # type: ignore[assignment, misc]


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
