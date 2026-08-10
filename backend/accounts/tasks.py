"""
Auth email sending. A standalone Celery task, not the Notification/channel
abstraction described in docs/ARCHITECTURE.md § 9 — see docs/DECISIONS.md §
Stage 3 decisions for why (Notification.salon is non-nullable, but this is a
platform-wide User event with no salon in scope; reconciling that is Stage 9
work). Always dispatched via .delay() from the view layer, never called
directly — an SMTP timeout must not become a failed HTTP response.
"""

from celery import shared_task
from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from accounts.models import User
from accounts.tokens import generate_email_verification_token


@shared_task
def send_verification_email(user_id: int) -> None:
    user = User.objects.get(pk=user_id)
    token = generate_email_verification_token(user)
    link = f"{settings.FRONTEND_URL}/verify-email#token={token}"
    send_mail(
        subject="Confirm your email",
        message=f"Confirm your email by visiting: {link}\n\nThis link expires in 48 hours.",
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email],
    )


@shared_task
def send_account_exists_email(user_id: int) -> None:
    user = User.objects.get(pk=user_id)
    send_mail(
        subject="You already have an account",
        message=(
            "Someone (hopefully you) tried to register with this email address, but "
            "an account already exists. If this was you, log in normally, or use "
            "'forgot password' if you don't remember your password."
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email],
    )


@shared_task
def send_password_reset_email(user_id: int) -> None:
    user = User.objects.get(pk=user_id)
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    link = f"{settings.FRONTEND_URL}/reset-password#uid={uid}&token={token}"
    send_mail(
        subject="Reset your password",
        message=f"Reset your password by visiting: {link}\n\nThis link expires in 1 hour.",
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email],
    )
