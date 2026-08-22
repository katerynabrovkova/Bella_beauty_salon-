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


class PaymentWebhookEventSerializer(serializers.Serializer):
    """
    Inbound webhook body (docs/DECISIONS.md § Stage 8.E decisions):
    {event_id, event_type, provider_reference_id}. Not a ModelSerializer —
    this validates the provider's event envelope, not a Payment row. The
    signature travels in the X-Signature header, not here; it's verified
    against the raw request body before this serializer ever runs
    (payments/views.py's PaymentWebhookView).
    """

    event_id = serializers.CharField()
    event_type = serializers.CharField()
    provider_reference_id = serializers.CharField()
