from django.contrib import admin

from core.admin import ReadOnlyAdminMixin, ReadOnlySalonScopedAdmin
from payments.models import Payment, ProcessedWebhookEvent


@admin.register(Payment)
class PaymentAdmin(ReadOnlySalonScopedAdmin):
    """Read-only: status is a provider-driven state machine (Stage 8) not built yet."""

    list_display = ("salon", "appointment", "amount", "status", "provider_reference_id")
    list_filter = (*ReadOnlySalonScopedAdmin.list_filter, "status")


@admin.register(ProcessedWebhookEvent)
class ProcessedWebhookEventAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
    """
    Not a TenantScopedModel (arrives before salon is known — see
    payments/models.py), so no salon filter/unscoped_objects needed. Pure
    idempotency ledger, kept read-only for debugging visibility only.
    """

    list_display = ("provider_event_id", "processed_at")
