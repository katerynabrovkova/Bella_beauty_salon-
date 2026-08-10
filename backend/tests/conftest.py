import datetime as dt

import pytest
from django.core.cache import cache

from accounts.models import Customer
from booking.models import Appointment, AppointmentStatus
from catalog.models import Service, ServiceCategory
from core.tenancy import tenant_context
from specialists.models import Specialist
from tenants.models import Salon


@pytest.fixture(autouse=True)
def _celery_eager(settings):
    """
    Runs @shared_task calls inline instead of dispatching to a real worker —
    .delay()/.apply_async() still go through Celery's own machinery, so this
    doesn't hide a view that forgot to enqueue at all (docs/DECISIONS.md §
    Stage 3 decisions). Combined with pytest-django's automatic EMAIL_BACKEND
    override to locmem, sent mail lands in django.core.mail.outbox.
    """
    settings.CELERY_TASK_ALWAYS_EAGER = True
    settings.CELERY_TASK_EAGER_PROPAGATES = True


@pytest.fixture(autouse=True)
def _clear_cache():
    """DRF throttling counts requests in the Django cache (real Redis here,
    same as dev/prod) — clear it so one test's throttle counter can't leak
    into the next."""
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def salon(db):
    return Salon.objects.create(name="Bella Demo Salon", slug="bella-demo")


@pytest.fixture
def other_salon(db):
    return Salon.objects.create(name="Other Salon", slug="other-salon")


@pytest.fixture
def service_category(salon):
    with tenant_context(salon.id):
        return ServiceCategory.objects.create(salon=salon, name="Nails")


@pytest.fixture
def service(salon, service_category):
    with tenant_context(salon.id):
        return Service.objects.create(
            salon=salon,
            category=service_category,
            name="Manicure",
            duration_minutes=60,
            price="500.00",
            buffer_minutes=15,
        )


@pytest.fixture
def specialist(salon):
    with tenant_context(salon.id):
        return Specialist.objects.create(salon=salon, name="Jane")


@pytest.fixture
def customer(salon):
    with tenant_context(salon.id):
        return Customer.objects.create(
            salon=salon, name="Alice", email="alice@example.com", phone="+10000000000"
        )


def make_appointment(
    *,
    salon: Salon,
    customer: Customer,
    specialist: Specialist,
    service: Service,
    start: dt.datetime,
    status: str = AppointmentStatus.CONFIRMED,
) -> Appointment:
    end = start + dt.timedelta(minutes=service.duration_minutes)
    blocked_until = end + dt.timedelta(minutes=service.buffer_minutes)
    with tenant_context(salon.id):
        return Appointment.objects.create(
            salon=salon,
            customer=customer,
            specialist=specialist,
            service=service,
            start_datetime=start,
            end_datetime=end,
            blocked_until=blocked_until,
            service_price_at_booking=service.price,
            deposit_percentage_at_booking=salon.deposit_percentage,
            status=status,
        )
