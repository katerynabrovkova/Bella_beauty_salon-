from rest_framework import serializers

from booking.models import Appointment


class AppointmentGuestSerializer(serializers.ModelSerializer):
    """Read-only representation for the guest view/cancel endpoints (booking/views.py)."""

    class Meta:
        model = Appointment
        fields = [
            "id",
            "status",
            "start_datetime",
            "end_datetime",
            "specialist",
            "service",
            "cancelled_at",
            "cancelled_by",
            "cancellation_reason",
        ]
        read_only_fields = fields
