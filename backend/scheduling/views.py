"""
Availability time-grid GET endpoint (docs/ARCHITECTURE.md § 6;
docs/DECISIONS.md § Stage 6.I decisions).

Public read (AllowAny), set explicitly — DEFAULT_PERMISSION_CLASSES is
IsAuthenticated globally, so omitting this would silently block the
unauthenticated browsing this endpoint exists for. GET-only, so unlike
catalog's/specialists' mixins there is no write path to branch away from via
get_permissions()/SAFE_METHODS.

No view-level try/except: every documented failure (bad/missing query
params, an unknown or cross-tenant service/specialist id,
InvalidDateRangeError, InvalidSteppingParametersError, a naive `now`) maps to
its status entirely through the existing core.exceptions.exception_handler,
already wired as DRF's global EXCEPTION_HANDLER.
"""

from zoneinfo import ZoneInfo

from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from core.tenancy import get_current_salon_id
from scheduling.serializers import AvailabilityQuerySerializer
from scheduling.services import (
    compute_candidate_start_times,
    compute_multi_specialist_availability,
)
from tenants.models import Salon


class AvailabilityView(APIView):
    permission_classes = [AllowAny]

    def get(self, request: Request, *args: object, **kwargs: object) -> Response:
        query = AvailabilityQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        service = query.validated_data["service"]
        specialist = query.validated_data.get("specialist")
        date_from = query.validated_data["date_from"]
        date_to = query.validated_data["date_to"]

        # Salon is not a TenantScopedModel — it's the tenant root — so
        # Salon.objects is a plain manager; every existing view only ever
        # touched the bound tenant id, never the full row (§ Stage 6.I
        # decisions).
        salon = get_object_or_404(Salon, pk=get_current_salon_id())

        # The single now = timezone.now() call site (§ Stage 6.F/6.I
        # decisions) — passed explicitly into whichever service function
        # runs below, never re-read.
        now = timezone.now()

        if specialist is not None:
            # "Specific specialist" path: Specialist.objects.all(), not
            # filtered by is_active. A deactivated specialist's id already
            # yields [] via compute_open_windows' own is_active guard — the
            # § Stage 6.G pick-list is_active rule governs a different
            # concern (which specialists a customer is offered to choose
            # from), not a direct id call like this one.
            candidates = compute_candidate_start_times(
                specialist=specialist,
                service=service,
                salon=salon,
                date_from=date_from,
                date_to=date_to,
                now=now,
            )
        else:
            # "Any specialist" path: the response takes the composition's
            # sorted keys, never the specialists in its values — who's free
            # at a chosen time is the second endpoint's job (§ Stage 6.G
            # decisions).
            candidates = list(
                compute_multi_specialist_availability(
                    service=service,
                    salon=salon,
                    date_from=date_from,
                    date_to=date_to,
                    now=now,
                ).keys()
            )

        salon_tz = ZoneInfo(salon.timezone)
        available_times = [candidate.astimezone(salon_tz).isoformat() for candidate in candidates]
        return Response({"available_times": available_times})
