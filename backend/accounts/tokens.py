"""
Email verification token (docs/DECISIONS.md § Stage 3 decisions).

Stateless: a TimestampSigner-signed payload of {user_id, email}, checked
against the user's *current* email at verify time rather than tracked in a
database row. Verifying is idempotent (setting `email_verified_at` twice is
a no-op), unlike the guest access token's cancel action, which has a real
one-time consequence — that's why guest tokens need a stored single-use
record (see the accounts app's guest-token module, added in a later Stage 3
sub-step) and this one doesn't.

Password reset uses Django's built-in PasswordResetTokenGenerator instead
(accounts/views.py) — self-invalidating on password change, which is a
property this stateless signer intentionally does not try to replicate.
"""

from django.conf import settings
from django.core import signing

from accounts.models import User

_SALT = "accounts.email-verification"


def generate_email_verification_token(user: User) -> str:
    signer = signing.TimestampSigner(salt=_SALT)
    return signer.sign_object({"user_id": user.id, "email": user.email})


def read_email_verification_token(token: str) -> int:
    """
    Returns the verified user id, or raises signing.BadSignature /
    signing.SignatureExpired if the token is invalid, expired, or was issued
    for an email the user no longer has.
    """
    signer = signing.TimestampSigner(salt=_SALT)
    payload = signer.unsign_object(token, max_age=settings.EMAIL_VERIFICATION_TIMEOUT)
    user_id = payload["user_id"]
    email = payload["email"]

    try:
        user = User.objects.get(pk=user_id)
    except User.DoesNotExist as exc:
        raise signing.BadSignature("No such user.") from exc

    if user.email != email:
        raise signing.BadSignature("Token was issued for a different email address.")

    return user_id
