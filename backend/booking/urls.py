from django.urls import path

from booking import views

app_name = "booking"

urlpatterns = [
    path(
        "guest/appointments/<int:appointment_id>/",
        views.GuestAppointmentDetailView.as_view(),
        name="guest-appointment-detail",
    ),
    path(
        "guest/appointments/<int:appointment_id>/cancel/",
        views.GuestAppointmentCancelView.as_view(),
        name="guest-appointment-cancel",
    ),
]
