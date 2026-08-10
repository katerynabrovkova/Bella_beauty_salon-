from django.contrib import admin

from core.admin import ReadOnlySalonScopedAdmin
from notifications.models import Notification


@admin.register(Notification)
class NotificationAdmin(ReadOnlySalonScopedAdmin):
    """Read-only: status drives the Stage 9 dedup/idempotency machinery, not built yet."""

    list_display = ("salon", "trigger_type", "channel", "status", "sent_at")
    list_filter = (*ReadOnlySalonScopedAdmin.list_filter, "trigger_type", "channel", "status")
