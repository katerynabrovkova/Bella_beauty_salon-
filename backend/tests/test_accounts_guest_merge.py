import pytest
from rest_framework.test import APIClient

from accounts.models import Customer, User
from accounts.tokens import generate_email_verification_token
from core.tenancy import tenant_context

pytestmark = pytest.mark.django_db

PASSWORD = "a-genuinely-strong-passw0rd!"


@pytest.fixture
def client() -> APIClient:
    return APIClient()


@pytest.fixture
def user() -> User:
    return User.objects.create_user(email="guest-turned-user@example.com", password=PASSWORD)


def test_verification_links_guest_customers_with_a_matching_email_across_salons(
    client, user, salon, other_salon
):
    with tenant_context(salon.id):
        matching_a = Customer.objects.create(
            salon=salon, name="Guest A", email=user.email, phone="+10000000000"
        )
    with tenant_context(other_salon.id):
        matching_b = Customer.objects.create(
            salon=other_salon, name="Guest B", email=user.email, phone="+10000000001"
        )
    token = generate_email_verification_token(user)

    response = client.post("/api/v1/auth/verify-email/", {"token": token})

    assert response.status_code == 200
    matching_a.refresh_from_db()
    matching_b.refresh_from_db()
    assert matching_a.user_id == user.id
    assert matching_b.user_id == user.id


def test_verification_does_not_link_a_different_email(client, user, salon):
    with tenant_context(salon.id):
        other_email_customer = Customer.objects.create(
            salon=salon, name="Someone Else", email="someone-else@example.com", phone="+1000"
        )
    token = generate_email_verification_token(user)

    response = client.post("/api/v1/auth/verify-email/", {"token": token})

    assert response.status_code == 200
    other_email_customer.refresh_from_db()
    assert other_email_customer.user_id is None


def test_verification_does_not_relink_an_already_linked_customer_to_a_different_user(
    client, user, salon
):
    already_linked_owner = User.objects.create_user(
        email="original-owner@example.com", password=PASSWORD
    )
    with tenant_context(salon.id):
        already_linked = Customer.objects.create(
            salon=salon, name="Already Linked", email=user.email, user=already_linked_owner
        )
    token = generate_email_verification_token(user)

    response = client.post("/api/v1/auth/verify-email/", {"token": token})

    assert response.status_code == 200
    already_linked.refresh_from_db()
    assert already_linked.user_id == already_linked_owner.id
