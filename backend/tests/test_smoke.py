import pytest
from django.db import connection


@pytest.mark.django_db
def test_database_is_postgresql_and_reachable():
    """Proves settings/env wiring is correct end-to-end, not just that Django boots."""
    assert connection.vendor == "postgresql"
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
        assert cursor.fetchone() == (1,)
