import pytest

from accounts.models import Customer
from core.tenancy import TenantContextMissingError, tenant_context


@pytest.mark.django_db
def test_reading_without_bound_tenant_raises() -> None:
    with pytest.raises(TenantContextMissingError):
        list(Customer.objects.all())


@pytest.mark.django_db
def test_creating_without_bound_tenant_raises(salon) -> None:
    with pytest.raises(TenantContextMissingError):
        Customer.objects.create(
            salon=salon, name="Alice", email="alice@example.com", phone="+10000000000"
        )


@pytest.mark.django_db
def test_objects_manager_scopes_to_the_bound_tenant_only(salon, other_salon) -> None:
    with tenant_context(salon.id):
        Customer.objects.create(
            salon=salon, name="Alice", email="alice@example.com", phone="+10000000000"
        )
    with tenant_context(other_salon.id):
        Customer.objects.create(
            salon=other_salon, name="Bob", email="bob@example.com", phone="+10000000001"
        )

    with tenant_context(salon.id):
        names = list(Customer.objects.values_list("name", flat=True))
    assert names == ["Alice"]

    with tenant_context(other_salon.id):
        names = list(Customer.objects.values_list("name", flat=True))
    assert names == ["Bob"]


@pytest.mark.django_db
def test_unscoped_objects_bypasses_tenant_filtering(salon, other_salon) -> None:
    with tenant_context(salon.id):
        Customer.objects.create(
            salon=salon, name="Alice", email="alice@example.com", phone="+10000000000"
        )
    with tenant_context(other_salon.id):
        Customer.objects.create(
            salon=other_salon, name="Bob", email="bob@example.com", phone="+10000000001"
        )

    names = set(Customer.unscoped_objects.values_list("name", flat=True))
    assert names == {"Alice", "Bob"}
