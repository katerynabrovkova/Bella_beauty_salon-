from django.db import models

from core.tenancy import TenantContextMissingError, get_current_salon_id


class TimeStamped(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class TenantScopedQuerySet(models.QuerySet["TenantScopedModel"]):
    pass


class TenantScopedManager(models.Manager["TenantScopedModel"]):
    """
    Default manager for every tenant-owned model. Auto-filters to the
    currently bound tenant (core.tenancy) and raises if none is bound —
    there is no silent "all tenants" fallback. Deliberate bypass is
    `Model.unscoped_objects`, a differently named plain manager (see
    docs/ARCHITECTURE.md § 5).
    """

    def get_queryset(self) -> TenantScopedQuerySet:
        salon_id = get_current_salon_id()
        if salon_id is None:
            raise TenantContextMissingError(
                f"{self.model.__name__}.objects used with no tenant bound. "
                "Bind one with core.tenancy.tenant_context(salon_id), or use "
                f"{self.model.__name__}.unscoped_objects if this access is "
                "deliberately cross-tenant."
            )
        return TenantScopedQuerySet(self.model, using=self._db).filter(salon_id=salon_id)


class TenantScopedModel(models.Model):
    """
    Abstract base for every tenant-owned model. See docs/ARCHITECTURE.md § 5.
    """

    salon = models.ForeignKey(
        "tenants.Salon",
        on_delete=models.CASCADE,
        related_name="%(app_label)s_%(class)s_set",
    )

    objects = TenantScopedManager()
    unscoped_objects = models.Manager()

    class Meta:
        abstract = True
        constraints = [
            models.UniqueConstraint(
                fields=["id", "salon"],
                name="%(app_label)s_%(class)s_id_salon_uniq",
            ),
        ]
