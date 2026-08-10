import pytest
from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from rest_framework.test import APIClient

from accounts.models import User

pytestmark = pytest.mark.django_db

OLD_PASSWORD = "old-genuinely-strong-pw1!"
NEW_PASSWORD = "brand-new-genuinely-strong-pw2!"


@pytest.fixture
def client() -> APIClient:
    return APIClient()


@pytest.fixture
def user() -> User:
    return User.objects.create_user(email="reset-me@example.com", password=OLD_PASSWORD)


def test_reset_request_response_is_identical_for_known_and_unknown_email(
    client: APIClient, user: User
) -> None:
    known = client.post("/api/v1/auth/password-reset/", {"email": user.email})
    unknown = client.post("/api/v1/auth/password-reset/", {"email": "nobody@example.com"})

    assert known.status_code == unknown.status_code == 202
    assert known.data == unknown.data
    assert len(mail.outbox) == 1  # only the known-email branch actually sends


def test_reset_confirm_changes_the_password(client: APIClient, user: User) -> None:
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)

    response = client.post(
        "/api/v1/auth/password-reset/confirm/",
        {"uid": uid, "token": token, "new_password": NEW_PASSWORD},
    )

    assert response.status_code == 200
    user.refresh_from_db()
    assert user.check_password(NEW_PASSWORD)


def test_reset_confirm_rejects_an_invalid_token(client: APIClient, user: User) -> None:
    uid = urlsafe_base64_encode(force_bytes(user.pk))

    response = client.post(
        "/api/v1/auth/password-reset/confirm/",
        {"uid": uid, "token": "not-a-real-token", "new_password": NEW_PASSWORD},
    )

    assert response.status_code == 400
    user.refresh_from_db()
    assert user.check_password(OLD_PASSWORD)


def test_reset_token_is_invalid_once_the_password_has_already_changed(
    client: APIClient, user: User
) -> None:
    """
    Why password reset uses Django's built-in PasswordResetTokenGenerator
    instead of a hand-rolled signer (docs/DECISIONS.md § Stage 3 decisions):
    it's self-invalidating on password change.
    """
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    user.set_password("someone-got-here-first-pw!")
    user.save(update_fields=["password"])

    response = client.post(
        "/api/v1/auth/password-reset/confirm/",
        {"uid": uid, "token": token, "new_password": NEW_PASSWORD},
    )

    assert response.status_code == 400
