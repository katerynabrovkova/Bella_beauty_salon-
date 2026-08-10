import pytest
from django.db import IntegrityError, transaction

from accounts.models import Customer
from core.tenancy import tenant_context


@pytest.mark.django_db
def test_same_email_rejected_within_one_salon(salon) -> None:
    with tenant_context(salon.id):
        Customer.objects.create(
            salon=salon, name="Alice", email="alice@example.com", phone="+10000000000"
        )
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                Customer.objects.create(
                    salon=salon, name="Alice Two", email="alice@example.com", phone="+10000000001"
                )


@pytest.mark.django_db
def test_same_email_allowed_across_different_salons(salon, other_salon) -> None:
    with tenant_context(salon.id):
        Customer.objects.create(
            salon=salon, name="Alice", email="alice@example.com", phone="+10000000000"
        )
    with tenant_context(other_salon.id):
        Customer.objects.create(
            salon=other_salon, name="Alice", email="alice@example.com", phone="+10000000001"
        )

    assert Customer.unscoped_objects.filter(email="alice@example.com").count() == 2
