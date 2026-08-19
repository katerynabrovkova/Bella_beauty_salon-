from django.core.validators import RegexValidator
from django.db import models

from core.models import TimeStamped

_ISO_4217_VALIDATOR = RegexValidator(r"^[A-Z]{3}$")


class Salon(TimeStamped):
    """
    The tenant root. Everything else in the platform scopes to one of these
    via a `salon` FK (docs/DECISIONS.md § Multi-tenancy). Not itself a
    TenantScopedModel — a Salon doesn't belong to a tenant, it is one.
    """

    name = models.CharField(max_length=255)
    slug = models.SlugField(unique=True)

    # Drives the Stage 3 tenant-resolution middleware's 404 for a deactivated
    # tenant (docs/DECISIONS.md § Stage 3 decisions) — deliberately not a
    # delete, since Salon is the FK target for every tenant-owned row.
    is_active = models.BooleanField(default=True)

    # Local-time rendering input (docs/DECISIONS.md § Timezone). Default is
    # the demo tenant's own timezone, not a platform-wide assumption.
    timezone = models.CharField(max_length=63, default="Europe/Kyiv")

    # ISO 4217, e.g. "UAH". Deliberately no model-level default — a new
    # salon must specify its currency explicitly, never silently inherit
    # UAH (docs/DECISIONS.md § Stage 8 decisions). Frozen onto each Payment
    # at creation time; see payments.models.Payment.currency.
    currency = models.CharField(max_length=3, validators=[_ISO_4217_VALIDATOR])

    # Business rules — see docs/DECISIONS.md § Business rules for the "why"
    # behind every default below; all are salon-configurable.
    deposit_percentage = models.DecimalField(max_digits=5, decimal_places=2, default=20)
    min_lead_time_hours = models.PositiveIntegerField(default=3)
    max_advance_days = models.PositiveIntegerField(default=60)
    slot_granularity_minutes = models.PositiveIntegerField(default=15)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name
