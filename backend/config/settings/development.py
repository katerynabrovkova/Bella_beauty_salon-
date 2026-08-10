from .base import *  # noqa: F401,F403
from .base import env

DEBUG = env.bool("DJANGO_DEBUG", default=True)
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])

# Prints the full outgoing message to stdout instead of sending it — no
# mail-catcher container in docker-compose.yml. View it with:
#   docker compose logs celery_worker
# (email is always sent via a Celery task, never inline in the request — see
# docs/DECISIONS.md § Stage 3 decisions).
EMAIL_BACKEND = env("EMAIL_BACKEND", default="django.core.mail.backends.console.EmailBackend")
