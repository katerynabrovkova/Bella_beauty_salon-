"""
Query-param validation for the availability time-grid GET endpoint
(docs/DECISIONS.md § Stage 6.I decisions). A plain serializers.Serializer,
not a ModelSerializer — there's no model instance to serialize here, only
request.query_params to validate.
"""

from rest_framework import serializers

from catalog.models import Service
from specialists.models import Specialist


class AvailabilityQuerySerializer(serializers.Serializer):
    """
    `service`/`date_from`/`date_to` are required and load-bearing for the
    computation itself, unlike catalog's `category` list filter (an optional
    refinement, silently ignored when malformed) — malformed input here must
    hard-fail rather than silently degrade (§ Stage 6.I decisions).

    `service`/`specialist` are PrimaryKeyRelatedFields, rebound in __init__
    to the tenant-scoped querysets — the same pattern
    catalog/serializers.py's ServiceSerializer.category_id uses, not the
    .child_relation variant (neither field is many=True). The class-body
    placeholder queryset is a harmless, always-empty, non-tenant-scoped one
    (TenantScopedManager.get_queryset() raises with no tenant bound, and
    nothing is bound at import time) — __init__ rebinds it once a request is
    actually being served. A cross-tenant or nonexistent id then simply
    misses that scoped queryset and surfaces as DRF's ordinary "does not
    exist" ValidationError, the same 400 as any other invalid id, not a
    cross-tenant leak.
    """

    service = serializers.PrimaryKeyRelatedField(queryset=Service.unscoped_objects.none())
    specialist = serializers.PrimaryKeyRelatedField(
        queryset=Specialist.unscoped_objects.none(), required=False
    )
    date_from = serializers.DateField()
    date_to = serializers.DateField()

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self.fields["service"].queryset = Service.objects.all()
        self.fields["specialist"].queryset = Specialist.objects.all()
