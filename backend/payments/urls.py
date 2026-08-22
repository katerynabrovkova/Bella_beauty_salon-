from django.urls import path

from payments import views

app_name = "payments"

urlpatterns = [
    path("payments/", views.PaymentWebhookView.as_view(), name="payment-webhook"),
]
