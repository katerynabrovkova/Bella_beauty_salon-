"""
Auth serializers (docs/ARCHITECTURE.md § 3, docs/DECISIONS.md § Stage 3
decisions). Registration and password-reset-request never raise on an
unknown/duplicate email — the caller (accounts/views.py) issues an identical
response regardless, per the no-enumeration rule.
"""

from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.tokens import default_token_generator
from django.core import signing
from django.utils.encoding import force_str
from django.utils.http import urlsafe_base64_decode
from rest_framework import serializers

from accounts.models import User
from accounts.tokens import read_email_verification_token
from core.exceptions import InvalidOrExpiredTokenError


class RegisterSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, validators=[validate_password])

    def validate_email(self, value: str) -> str:
        return value.strip().lower()

    def create_or_notify(self) -> tuple[User, bool]:
        """Returns (user, created) — never raises on a duplicate email."""
        email = self.validated_data["email"]
        existing = User.objects.filter(email=email).first()
        if existing is not None:
            return existing, False
        user = User.objects.create_user(email=email, password=self.validated_data["password"])
        return user, True


class ResendVerificationSerializer(serializers.Serializer):
    email = serializers.EmailField()

    def validate_email(self, value: str) -> str:
        return value.strip().lower()


class VerifyEmailSerializer(serializers.Serializer):
    token = serializers.CharField()

    def validate_token(self, value: str) -> int:
        try:
            return read_email_verification_token(value)
        except signing.BadSignature as exc:
            raise InvalidOrExpiredTokenError() from exc


class PasswordResetRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()

    def validate_email(self, value: str) -> str:
        return value.strip().lower()


class PasswordResetConfirmSerializer(serializers.Serializer):
    uid = serializers.CharField()
    token = serializers.CharField()
    new_password = serializers.CharField(write_only=True)

    def validate(self, attrs: dict) -> dict:
        try:
            user_id = force_str(urlsafe_base64_decode(attrs["uid"]))
            user = User.objects.get(pk=user_id)
        except (User.DoesNotExist, ValueError, TypeError, OverflowError) as exc:
            raise InvalidOrExpiredTokenError() from exc

        if not default_token_generator.check_token(user, attrs["token"]):
            raise InvalidOrExpiredTokenError()

        validate_password(attrs["new_password"], user=user)
        attrs["user"] = user
        return attrs


class LogoutSerializer(serializers.Serializer):
    refresh = serializers.CharField()
