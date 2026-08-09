from django.db import models

from core.models import TimeStamped


class Salon(TimeStamped):
    """
    The tenant root. Everything else in the platform scopes to one of these
    via a `salon` FK (docs/DECISIONS.md § Multi-tenancy). Not itself a
    TenantScopedModel — a Salon doesn't belong to a tenant, it is one.
    """

    name = models.CharField(max_length=255)
    slug = models.SlugField(unique=True)

    # Local-time rendering input (docs/DECISIONS.md § Timezone). Default is
    # the demo tenant's own timezone, not a platform-wide assumption.
    timezone = models.CharField(max_length=63, default="Europe/Kyiv")

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
