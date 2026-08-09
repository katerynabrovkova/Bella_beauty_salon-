import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")

app = Celery("bella")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

# Populated in the notifications stage (24h/2h reminder tasks, etc.).
app.conf.beat_schedule = {}
