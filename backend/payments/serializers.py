from rest_framework import serializers

from payments.models import Payment


class PaymentGuestSerializer(serializers.ModelSerializer):
    """
    Read-only representation for the guest pay endpoint (booking/views.py's
    GuestAppointmentPayView), nested under the "payment" key of the
    provider-neutral response envelope (docs/DECISIONS.md § Stage 8.D
    decisions). Deliberately narrow — service name is excluded because it's
    a property of the appointment, not the payment; the client already has
    it from the POST /bookings/ response.
    """

    class Meta:
        model = Payment
        fields = ["id", "status", "amount", "currency"]
        read_only_fields = fields
