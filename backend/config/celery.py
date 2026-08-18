import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")

app = Celery("bella")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

# First entry: Stage 7.F's appointment-expiry sweep (docs/DECISIONS.md §
# Stage 7.F decisions). Reminder tasks (24h/2h) land in the notifications
# stage.
app.conf.beat_schedule = {
    "expire-pending-payment-appointments": {
        "task": "booking.tasks.expire_pending_payment_appointments",
        "schedule": 60.0,
    },
}
