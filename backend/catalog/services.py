"""
Catalog service layer (docs/ARCHITECTURE.md § 2; Stage 4 sub-step 4).

Soft delete only — Service/ServiceCategory rows are never hard-deleted once
they could be referenced (docs/ARCHITECTURE.md § 2). Deactivating a Service
that already has appointments is fine: Appointment snapshots price/deposit
at booking time, so an existing booking is unaffected either way
(docs/DECISIONS.md § Stage 4 decisions).
"""

from catalog.models import Service, ServiceCategory
from core.exceptions import CategoryHasActiveServicesError


def soft_delete_category(category: ServiceCategory) -> None:
    """
    Mirrors the real FK's on_delete=PROTECT posture (Service.category) in
    the soft-delete world: a category with active services can't be
    deactivated out from under them — staff must deactivate/reassign the
    services first, an explicit resolution rather than a silent cascade or
    a silently orphaned category.
    """
    if category.services.filter(is_active=True).exists():
        raise CategoryHasActiveServicesError()
    category.is_active = False
    category.save(update_fields=["is_active"])


def soft_delete_service(service: Service) -> None:
    service.is_active = False
    service.save(update_fields=["is_active"])
