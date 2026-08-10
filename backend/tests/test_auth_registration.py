import pytest
from django.core import mail
from rest_framework.test import APIClient

from accounts.models import User

pytestmark = pytest.mark.django_db

STRONG_PASSWORD = "a-genuinely-strong-passw0rd!"


@pytest.fixture
def client() -> APIClient:
    return APIClient()


def test_register_creates_an_unverified_user_and_sends_verification_email(
    client: APIClient,
) -> None:
    response = client.post(
        "/api/v1/auth/register/", {"email": "new@example.com", "password": STRONG_PASSWORD}
    )

    assert response.status_code == 202
    user = User.objects.get(email="new@example.com")
    assert user.email_verified_at is None
    assert user.check_password(STRONG_PASSWORD)
    assert len(mail.outbox) == 1


def test_register_with_an_existing_email_does_not_create_a_second_user(
    client: APIClient,
) -> None:
    User.objects.create_user(email="existing@example.com", password=STRONG_PASSWORD)

    response = client.post(
        "/api/v1/auth/register/", {"email": "existing@example.com", "password": "another-pw-1!"}
    )

    assert response.status_code == 202
    assert User.objects.filter(email="existing@example.com").count() == 1
    assert len(mail.outbox) == 1  # the "you already have an account" notice, not a welcome email


def test_register_response_is_identical_for_new_and_existing_email(client: APIClient) -> None:
    User.objects.create_user(email="existing2@example.com", password=STRONG_PASSWORD)

    new_response = client.post(
        "/api/v1/auth/register/", {"email": "brand-new@example.com", "password": STRONG_PASSWORD}
    )
    existing_response = client.post(
        "/api/v1/auth/register/", {"email": "existing2@example.com", "password": STRONG_PASSWORD}
    )

    assert new_response.status_code == existing_response.status_code == 202
    assert new_response.data == existing_response.data
