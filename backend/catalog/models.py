from django.db import models

from core.models import TenantScopedModel, TimeStamped


class ServiceCategory(TenantScopedModel, TimeStamped):
    name = models.CharField(max_length=255)
    ordering = models.PositiveIntegerField(default=0)

    class Meta(TenantScopedModel.Meta):
        abstract = False
        constraints = [
            *TenantScopedModel.Meta.constraints,
            models.UniqueConstraint(fields=["salon", "name"], name="servicecategory_salon_name_uniq"),
        ]
        ordering = ["ordering", "name"]

    def __str__(self) -> str:
        return self.name


class Service(TenantScopedModel, TimeStamped):
    """
    docs/ARCHITECTURE.md § 2. `buffer_minutes` blocks the calendar after the
    appointment but is never itself a bookable start (§ 6-7).
    """

    category = models.ForeignKey(ServiceCategory, on_delete=models.PROTECT, related_name="services")
    name = models.CharField(max_length=255)
    duration_minutes = models.PositiveIntegerField()
    price = models.DecimalField(max_digits=10, decimal_places=2)
    buffer_minutes = models.PositiveIntegerField(default=0)

    def __str__(self) -> str:
        return self.name
