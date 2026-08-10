"""
Auth views under /api/v1/auth/ (docs/ARCHITECTURE.md § 3, § 13). All opt out
of the project-wide IsAuthenticated default with AllowAny except logout,
which relies on that default deliberately — it needs a valid access token to
blacklist a refresh token (docs/DECISIONS.md § Stage 3 decisions).
"""

from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from accounts.models import User
from accounts.serializers import (
    LogoutSerializer,
    PasswordResetConfirmSerializer,
    PasswordResetRequestSerializer,
    RegisterSerializer,
    ResendVerificationSerializer,
    VerifyEmailSerializer,
)
from accounts.tasks import (
    send_account_exists_email,
    send_password_reset_email,
    send_verification_email,
)
from core.exceptions import InvalidOrExpiredTokenError


class RegisterView(APIView):
    permission_classes = [AllowAny]

    def post(self, request: Request) -> Response:
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user, created = serializer.create_or_notify()
        if created:
            send_verification_email.delay(user.id)
        else:
            send_account_exists_email.delay(user.id)
        # Identical response either way: registration must not reveal
        # whether the email is already registered.
        return Response(
            {"detail": "If this email can be registered, check your inbox to continue."},
            status=status.HTTP_202_ACCEPTED,
        )


class LoginView(TokenObtainPairView):
    # TokenViewBase (simplejwt) has no explicit annotation on
    # permission_classes, so django-stubs infers its type from `()` — the
    # empty-tuple literal type — and any non-empty override is flagged
    # regardless of list vs. tuple syntax. Known stub friction, not a real
    # type error.
    permission_classes = (AllowAny,)  # type: ignore[assignment]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"


class RefreshView(TokenRefreshView):
    permission_classes = (AllowAny,)  # type: ignore[assignment]


class LogoutView(APIView):
    def post(self, request: Request) -> Response:
        serializer = LogoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            RefreshToken(serializer.validated_data["refresh"]).blacklist()
        except TokenError as exc:
            raise InvalidOrExpiredTokenError("Invalid or already-used refresh token.") from exc
        return Response(status=status.HTTP_205_RESET_CONTENT)


class VerifyEmailView(APIView):
    permission_classes = [AllowAny]

    def post(self, request: Request) -> Response:
        serializer = VerifyEmailSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user_id = serializer.validated_data["token"]
        # Filtered update, not a read-then-write: a second verification of
        # an already-verified user is a safe no-op, not a re-stamped time.
        User.objects.filter(pk=user_id, email_verified_at__isnull=True).update(
            email_verified_at=timezone.now()
        )
        return Response({"detail": "Email verified."}, status=status.HTTP_200_OK)


class ResendVerificationView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "resend_verification"

    def post(self, request: Request) -> Response:
        serializer = ResendVerificationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"]
        user = User.objects.filter(email=email, email_verified_at__isnull=True).first()
        if user is not None:
            send_verification_email.delay(user.id)
        # Identical response whether or not the email exists / needs verifying.
        return Response(
            {"detail": "If this email needs verifying, check your inbox."},
            status=status.HTTP_202_ACCEPTED,
        )


class PasswordResetRequestView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "password_reset"

    def post(self, request: Request) -> Response:
        serializer = PasswordResetRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"]
        user = User.objects.filter(email=email).first()
        if user is not None:
            send_password_reset_email.delay(user.id)
        # Identical response whether or not the email is registered.
        return Response(
            {"detail": "If this email is registered, check your inbox for a reset link."},
            status=status.HTTP_202_ACCEPTED,
        )


class PasswordResetConfirmView(APIView):
    permission_classes = [AllowAny]

    def post(self, request: Request) -> Response:
        serializer = PasswordResetConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data["user"]
        user.set_password(serializer.validated_data["new_password"])
        user.save(update_fields=["password"])
        return Response({"detail": "Password reset."}, status=status.HTTP_200_OK)
