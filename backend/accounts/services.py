"""
Guest -> registered-User linking (docs/ARCHITECTURE.md § 3, docs/DECISIONS.md
§ Identity). Deliberately the one cross-tenant operation in Stage 3: run
right after email verification, it must touch every salon's Customer rows,
not just one, since a User's linked bookings can span salons.
"""

from accounts.models import Customer, User
from core.tenancy import tenant_context
from tenants.models import Salon


def get_or_create_guest_customer(*, salon: Salon, name: str, email: str, phone: str) -> Customer:
    """
    docs/DECISIONS.md § Stage 7.C-bis decisions. Uses the ORM's own
    get_or_create() (not a hand-written check-then-create) so the
    (salon, email) unique constraint (customer_salon_email_uniq) plus its
    internal savepoint-and-retry-on-IntegrityError closes the
    concurrent-same-email race with no extra code here. `salon` is passed
    explicitly to both the lookup and the create defaults: the tenant-scoped
    manager filters reads but never injects `salon` on write.

    Option A (decided): a returning guest's name/phone are overwritten with
    the newly supplied values on every booking, unconditionally — the risk
    (a typo, or someone else's details under a shared email, silently
    overwriting good data) is accepted in exchange for a self-correcting
    default with no per-field logic. A brand-new email creates a guest row
    (user=NULL).
    """
    customer, created = Customer.objects.get_or_create(
        salon=salon, email=email, defaults={"name": name, "phone": phone}
    )
    if not created:
        customer.name = name
        customer.phone = phone
        customer.save(update_fields=["name", "phone"])
    return customer


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
