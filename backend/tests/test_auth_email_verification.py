import pytest
from django.core import mail
from rest_framework.test import APIClient

from accounts.models import User
from accounts.tokens import generate_email_verification_token

pytestmark = pytest.mark.django_db

PASSWORD = "a-genuinely-strong-passw0rd!"


@pytest.fixture
def client() -> APIClient:
    return APIClient()


@pytest.fixture
def user() -> User:
    return User.objects.create_user(email="verify-me@example.com", password=PASSWORD)


def test_verify_email_sets_email_verified_at(client: APIClient, user: User) -> None:
    token = generate_email_verification_token(user)

    response = client.post("/api/v1/auth/verify-email/", {"token": token})

    assert response.status_code == 200
    user.refresh_from_db()
    assert user.email_verified_at is not None


def test_verifying_twice_with_the_same_token_is_a_safe_no_op(client: APIClient, user: User) -> None:
    token = generate_email_verification_token(user)
    client.post("/api/v1/auth/verify-email/", {"token": token})
    user.refresh_from_db()
    first_verified_at = user.email_verified_at

    response = client.post("/api/v1/auth/verify-email/", {"token": token})

    assert response.status_code == 200
    user.refresh_from_db()
    assert user.email_verified_at == first_verified_at


def test_token_stops_working_after_the_users_email_changes(client: APIClient, user: User) -> None:
    """
    The token payload includes the email it was issued for (docs/DECISIONS.md
    § Stage 3 decisions) — a changed email should invalidate any outstanding
    token for the old address, with no separate revocation step.
    """
    token = generate_email_verification_token(user)
    user.email = "changed@example.com"
    user.save(update_fields=["email"])

    response = client.post("/api/v1/auth/verify-email/", {"token": token})

    assert response.status_code == 400
    user.refresh_from_db()
    assert user.email_verified_at is None


def test_resend_verification_enqueues_a_new_email_for_an_unverified_user(
    client: APIClient, user: User
) -> None:
    response = client.post("/api/v1/auth/resend-verification/", {"email": user.email})

    assert response.status_code == 202
    assert len(mail.outbox) == 1


def test_resend_verification_response_is_identical_for_an_unknown_email(
    client: APIClient, user: User
) -> None:
    known = client.post("/api/v1/auth/resend-verification/", {"email": user.email})
    unknown = client.post("/api/v1/auth/resend-verification/", {"email": "nobody@example.com"})

    assert known.status_code == unknown.status_code == 202
    assert known.data == unknown.data
