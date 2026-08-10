"""
core/permissions.py (docs/ARCHITECTURE.md § 4). IsSalonStaff/
IsAuthenticatedCustomer/IsOwnCustomer have no production endpoint yet in
Stage 3 (staff/customer-facing views land in later stages) — exercised
directly here, plus one end-to-end HTTP test proving IsSalonStaff actually
denies cross-salon staff through DRF's real dispatch/exception-handling
path, not just via a unit-level True/False check.
"""

import datetime as dt

import pytest
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory, force_authenticate
from rest_framework.views import APIView

from accounts.models import SalonStaff, SalonStaffRole, User
from booking.guest_tokens import issue_guest_token
from core.permissions import IsAuthenticatedCustomer, IsOwnCustomer, IsSalonStaff
from core.tenancy import tenant_context
from tests.conftest import make_appointment

pytestmark = pytest.mark.django_db

factory = APIRequestFactory()


class _StaffOnlyProbeView(APIView):
    permission_classes = [IsSalonStaff()]

    def get(self, request):
        return Response({"ok": True})


class _NoPermissionClassProbeView(APIView):
    def get(self, request):
        return Response({"ok": True})


@pytest.fixture
def staff_user(salon) -> User:
    user = User.objects.create_user(email="staff@example.com", password="a-strong-passw0rd!")
    with tenant_context(salon.id):
        SalonStaff.objects.create(salon=salon, user=user, role=SalonStaffRole.ADMIN)
    return user


# --- IsSalonStaff (unit-level) ---------------------------------------------


def test_is_salon_staff_allows_staff_of_the_current_salon(salon, staff_user):
    request = factory.get("/")
    request.user = staff_user
    permission = IsSalonStaff()()

    with tenant_context(salon.id):
        assert permission.has_permission(request, _StaffOnlyProbeView()) is True


def test_is_salon_staff_denies_staff_of_a_different_salon(salon, other_salon, staff_user):
    request = factory.get("/")
    request.user = staff_user
    permission = IsSalonStaff()()

    with tenant_context(other_salon.id):
        assert permission.has_permission(request, _StaffOnlyProbeView()) is False


def test_is_salon_staff_denies_an_anonymous_request(salon):
    request = factory.get("/")
    request.user = None
    permission = IsSalonStaff()()

    with tenant_context(salon.id):
        assert permission.has_permission(request, _StaffOnlyProbeView()) is False


def test_is_salon_staff_restricted_to_a_role_excludes_other_roles(salon, staff_user):
    permission = IsSalonStaff("some_other_role")()
    request = factory.get("/")
    request.user = staff_user

    with tenant_context(salon.id):
        assert permission.has_permission(request, _StaffOnlyProbeView()) is False


# --- IsAuthenticatedCustomer (unit-level) ----------------------------------


def test_is_authenticated_customer_true_for_a_users_own_customer_row(salon, customer):
    user = User.objects.create_user(email="cust@example.com", password="a-strong-passw0rd!")
    with tenant_context(salon.id):
        customer.user = user
        customer.save(update_fields=["user"])

    request = factory.get("/")
    request.user = user
    with tenant_context(salon.id):
        assert IsAuthenticatedCustomer().has_permission(request, APIView()) is True


def test_is_authenticated_customer_false_with_no_linked_customer_row(salon):
    user = User.objects.create_user(email="nocust@example.com", password="a-strong-passw0rd!")
    request = factory.get("/")
    request.user = user
    with tenant_context(salon.id):
        assert IsAuthenticatedCustomer().has_permission(request, APIView()) is False


# --- IsOwnCustomer (unit-level) --------------------------------------------


def test_is_own_customer_true_for_the_jwt_users_own_customer(salon, customer, specialist, service):
    user = User.objects.create_user(email="owner@example.com", password="a-strong-passw0rd!")
    with tenant_context(salon.id):
        customer.user = user
        customer.save(update_fields=["user"])
        appointment = make_appointment(
            salon=salon,
            customer=customer,
            specialist=specialist,
            service=service,
            start=dt.datetime(2026, 10, 1, 10, 0, tzinfo=dt.UTC),
        )

    request = factory.get("/")
    request.user = user
    with tenant_context(salon.id):
        assert IsOwnCustomer().has_object_permission(request, APIView(), appointment) is True


def test_is_own_customer_false_for_a_different_customers_appointment(
    salon, customer, specialist, service
):
    user = User.objects.create_user(email="notowner@example.com", password="a-strong-passw0rd!")
    with tenant_context(salon.id):
        appointment = make_appointment(
            salon=salon,
            customer=customer,
            specialist=specialist,
            service=service,
            start=dt.datetime(2026, 10, 1, 10, 0, tzinfo=dt.UTC),
        )

    request = factory.get("/")
    request.user = user
    with tenant_context(salon.id):
        assert IsOwnCustomer().has_object_permission(request, APIView(), appointment) is False


def test_is_own_customer_true_for_a_matching_guest_token(salon, customer, specialist, service):
    with tenant_context(salon.id):
        appointment = make_appointment(
            salon=salon,
            customer=customer,
            specialist=specialist,
            service=service,
            start=dt.datetime(2026, 10, 2, 10, 0, tzinfo=dt.UTC),
        )
        _raw_token, token_row = issue_guest_token(appointment)

    request = factory.get("/")
    request.user = None
    request.guest_access_token = token_row

    assert IsOwnCustomer().has_object_permission(request, APIView(), appointment) is True


# --- HTTP-level: fail-closed defaults --------------------------------------


def test_a_view_with_no_permission_class_still_requires_auth():
    """
    Fail-closed default (docs/DECISIONS.md § Stage 3 decisions,
    REST_FRAMEWORK.DEFAULT_PERMISSION_CLASSES = [IsAuthenticated]): a view
    that never sets permission_classes must not be silently open.
    """
    request = factory.get("/")
    response = _NoPermissionClassProbeView.as_view()(request)

    assert response.status_code == 401


def test_staff_of_salon_a_gets_403_hitting_a_staff_only_view_bound_to_salon_b(
    salon, other_salon, staff_user
):
    """
    Same check as the unit-level test above, but through DRF's real
    dispatch/permission/exception-handling path end to end, not just a
    direct has_permission() call.
    """
    request = factory.get("/")
    force_authenticate(request, user=staff_user)

    with tenant_context(other_salon.id):
        response = _StaffOnlyProbeView.as_view()(request)

    assert response.status_code == 403
