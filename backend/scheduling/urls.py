from django.urls import path

from scheduling import views

app_name = "scheduling"

urlpatterns = [
    path("availability/", views.AvailabilityView.as_view(), name="availability"),
    path(
        "availability/specialists/",
        views.SpecialistsAtTimeView.as_view(),
        name="availability-specialists",
    ),
]
