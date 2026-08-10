"""
Guest -> registered-User linking (docs/ARCHITECTURE.md § 3, docs/DECISIONS.md
§ Identity). Deliberately the one cross-tenant operation in Stage 3: run
right after email verification, it must touch every salon's Customer rows,
not just one, since a User's linked bookings can span salons.
"""

from accounts.models import Customer, User
from core.tenancy import tenant_context
from tenants.models import Salon


def link_guest_customers(user: User) -> None:
    """
    Links every Customer row, across all salons, whose email exactly matches
    the verified user's email (docs/DECISIONS.md § Identity — never by
    phone). A per-salon loop, not Customer.unscoped_objects: Salon isn't
    itself tenant-scoped, so enumerating it needs no special access, and
    this keeps the deliberate cross-tenant reach narrow and explicit rather
    than reaching for the broader unscoped_objects bypass. Idempotent —
    user__isnull=True excludes rows already linked, so calling this twice
    for the same user is a safe no-op.
    """
    for salon_id in Salon.objects.values_list("id", flat=True):
        with tenant_context(salon_id):
            Customer.objects.filter(email=user.email, user__isnull=True).update(user=user)
