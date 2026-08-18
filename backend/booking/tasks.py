"""
Stage 7.F — the periodic appointment-expiry sweep (docs/ARCHITECTURE.md §
5, § 12; docs/DECISIONS.md § Stage 7.F decisions). Registered in
config/celery.py's beat_schedule.
"""

import logging

from celery import shared_task
from django.utils import timezone

from booking.services import expire_overdue_appointments
from core.tenancy import tenant_context
from tenants.models import Salon

logger = logging.getLogger(__name__)


@shared_task
def expire_pending_payment_appointments() -> None:
    """
    Loops every salon (Salon.objects.all() — Salon is the tenant root, not
    itself tenant-scoped), binding tenant_context(salon.id) per iteration so
    one salon's context can never bleed into the next. `now` is read once,
    before the loop, so every salon in a run is judged against the same
    instant. Each salon's processing is wrapped in its own try/except: one
    failing salon is logged and skipped, the rest still run. Deliberately no
    per-row try/except inside a salon's batch — only per-salon (§ Stage 7.F
    decisions).
    """
    now = timezone.now()
    for salon in Salon.objects.all():
        try:
            with tenant_context(salon.id):
                expired_count = expire_overdue_appointments(salon=salon, now=now)
            logger.info(
                "expire_pending_payment_appointments: expired %d appointment(s) for salon_id=%s",
                expired_count,
                salon.id,
            )
        except Exception:
            logger.exception(
                "expire_pending_payment_appointments: sweep failed for salon_id=%s", salon.id
            )
