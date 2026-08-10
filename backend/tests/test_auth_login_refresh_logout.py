import pytest
from rest_framework.test import APIClient

from accounts.models import User

pytestmark = pytest.mark.django_db

PASSWORD = "a-genuinely-strong-passw0rd!"


@pytest.fixture
def client() -> APIClient:
    return APIClient()


@pytest.fixture
def user() -> User:
    return User.objects.create_user(email="login-user@example.com", password=PASSWORD)


def test_login_returns_access_and_refresh_tokens(client: APIClient, user: User) -> None:
    response = client.post("/api/v1/auth/login/", {"email": user.email, "password": PASSWORD})

    assert response.status_code == 200
    assert "access" in response.data
    assert "refresh" in response.data


def test_refresh_rotates_and_blacklists_the_old_refresh_token(
    client: APIClient, user: User
) -> None:
    login = client.post("/api/v1/auth/login/", {"email": user.email, "password": PASSWORD}).data
    old_refresh = login["refresh"]

    refreshed = client.post("/api/v1/auth/refresh/", {"refresh": old_refresh})
    assert refreshed.status_code == 200
    assert refreshed.data["refresh"] != old_refresh

    reused = client.post("/api/v1/auth/refresh/", {"refresh": old_refresh})
    assert reused.status_code == 401


def test_logout_blacklists_the_refresh_token(client: APIClient, user: User) -> None:
    login = client.post("/api/v1/auth/login/", {"email": user.email, "password": PASSWORD}).data

    logout = client.post(
        "/api/v1/auth/logout/",
        {"refresh": login["refresh"]},
        HTTP_AUTHORIZATION=f"Bearer {login['access']}",
    )
    assert logout.status_code == 205

    reused = client.post("/api/v1/auth/refresh/", {"refresh": login["refresh"]})
    assert reused.status_code == 401


def test_logout_requires_authentication(client: APIClient, user: User) -> None:
    """
    LogoutView declares no permission_classes of its own — it relies on the
    project-wide DEFAULT_PERMISSION_CLASSES=IsAuthenticated default
    (docs/DECISIONS.md § Stage 3 decisions). This is the one endpoint whose
    correctness depends on that default actually being IsAuthenticated and
    not AllowAny.
    """
    login = client.post("/api/v1/auth/login/", {"email": user.email, "password": PASSWORD}).data

    response = client.post("/api/v1/auth/logout/", {"refresh": login["refresh"]})

    assert response.status_code == 401
