"""
Domain exception hierarchy and the single DRF exception handler that
translates every API-boundary error into one JSON envelope
(docs/ARCHITECTURE.md § 13/14):

    {"error": {"code": "...", "message": "...", "details": {...}}}

The service layer raises DomainError subclasses — never DRF's
ValidationError directly — so it stays framework-agnostic and callable
identically from API views, Celery tasks, and the AI assistant's tool
functions. This module is the only place that knows how to turn either kind
of exception (DomainError, or DRF's own) into a response.
"""

import logging

from django.conf import settings
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler as _drf_exception_handler

logger = logging.getLogger(__name__)


class DomainError(Exception):
    """Base for every service-layer error the API boundary knows how to translate."""

    code = "domain_error"
    status_code = status.HTTP_400_BAD_REQUEST
    default_message = "A domain error occurred."

    def __init__(self, message: str | None = None, *, details: dict | None = None) -> None:
        self.message = message or self.default_message
        self.details = details or {}
        super().__init__(self.message)


class InvalidOrExpiredTokenError(DomainError):
    code = "invalid_or_expired_token"
    status_code = status.HTTP_400_BAD_REQUEST
    default_message = "This link is invalid or has expired."


def _envelope(*, code: str, message: str, details: dict | None = None) -> dict:
    return {"error": {"code": code, "message": message, "details": details or {}}}


def exception_handler(exc: Exception, context: dict) -> Response | None:
    if isinstance(exc, DomainError):
        return Response(
            _envelope(code=exc.code, message=exc.message, details=exc.details),
            status=exc.status_code,
        )

    response = _drf_exception_handler(exc, context)
    if response is not None:
        code = getattr(exc, "default_code", exc.__class__.__name__.lower())
        if isinstance(response.data, dict) and "detail" in response.data:
            message = str(response.data["detail"])
            details: dict = {}
        else:
            message = "Request failed."
            if isinstance(response.data, dict):
                details = response.data
            else:
                details = {"errors": response.data}
        response.data = _envelope(code=code, message=message, details=details)
        return response

    # Unrecognized exception: full traceback always logged server-side. In
    # DEBUG, let it propagate so Django's interactive traceback page still
    # works for API views during local development; otherwise return the
    # generic envelope with nothing leaked to the client.
    logger.exception("Unhandled exception in API view")
    if settings.DEBUG:
        return None
    return Response(
        _envelope(code="internal_error", message="An unexpected error occurred."),
        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )
