"""
Guest-token-authenticated appointment access (docs/ARCHITECTURE.md § 3, § 4).
Both routes are single-object: a guest views or cancels exactly the
appointment named in the URL, authenticated only by the X-Guest-Token
header, never JWT. Booking creation, availability, and the full
cancellation service layer (concurrency, notifications, refund triggering)
are Stage 7/8 work — this only flips status on an already-existing
Appointment.

Both views are DRF generics, not plain APIView, specifically so
check_object_permissions() is guaranteed to run (DRF generics call it
automatically inside get_object()) — see CLAUDE.md's "DRF object-level
permissions" rule and core/permissions.py's HasValidGuestToken docstring.
"""

from django.db.models import QuerySet
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle

from booking.models import (
    ACTIVE_APPOINTMENT_STATUSES,
    Appointment,
    AppointmentStatus,
    CancelledBy,
)
from booking.serializers import AppointmentGuestSerializer
from core.exceptions import InvalidOrExpiredTokenError, InvalidStateTransitionError
from core.permissions import HasValidGuestToken


class _GuestTokenAppointmentMixin:
    """
    Resolves the target Appointment from the validated guest token
    (request.guest_access_token, set by HasValidGuestToken.has_permission)
    — never from the URL. Even if check_object_permissions were somehow
    never invoked, a mismatched or tampered URL id can't reach the wrong
    appointment, because the wrong appointment is never fetched in the
    first place. The URL id is still compared and must match, purely so a
    stale or wrong link fails immediately rather than silently ignoring
    what's in the address bar (docs/DECISIONS.md § Stage 3 sub-step 3
    decisions).
    """

    lookup_url_kwarg = "appointment_id"

    def get_queryset(self) -> QuerySet[Appointment]:
        return Appointment.objects.all()

    def get_object(self) -> Appointment:
        token_row = self.request.guest_access_token  # type: ignore[attr-defined]
        url_appointment_id = self.kwargs[self.lookup_url_kwarg]  # type: ignore[attr-defined]
        if token_row.appointment_id != url_appointment_id:
            raise InvalidOrExpiredTokenError()

        appointment = get_object_or_404(self.get_queryset(), pk=token_row.appointment_id)
        self.check_object_permissions(self.request, appointment)  # type: ignore[attr-defined]
        return appointment


class GuestAppointmentDetailView(_GuestTokenAppointmentMixin, generics.RetrieveAPIView):
    permission_classes = [HasValidGuestToken]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "guest_token"
    guest_token_action = "view"
    serializer_class = AppointmentGuestSerializer


class GuestAppointmentCancelView(_GuestTokenAppointmentMixin, generics.GenericAPIView):
    permission_classes = [HasValidGuestToken]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "guest_token"
    guest_token_action = "cancel"
    serializer_class = AppointmentGuestSerializer

    def post(self, request: Request, *args: object, **kwargs: object) -> Response:
        appointment = self.get_object()

        if appointment.status not in ACTIVE_APPOINTMENT_STATUSES:
            raise InvalidStateTransitionError(
                f"Cannot cancel an appointment with status '{appointment.status}'."
            )

        now = timezone.now()
        appointment.status = AppointmentStatus.CANCELLED
        appointment.cancelled_at = now
        appointment.cancelled_by = CancelledBy.GUEST
        appointment.save(update_fields=["status", "cancelled_at", "cancelled_by"])

        # Refund eligibility (deposit refunded/forfeited depending on
        # cancelled_by/timing, docs/DECISIONS.md § Business rules) is Stage 8
        # work — hook it in here once Payment exists. Stage 7 also still
        # owns the full concurrency-safe cancellation service layer this
        # narrow guest path bypasses for now.
        token_row = request.guest_access_token  # type: ignore[attr-defined]
        token_row.cancelled_via_token_at = now
        token_row.save(update_fields=["cancelled_via_token_at"])

        return Response(self.get_serializer(appointment).data)
