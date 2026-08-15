from django.urls import path

from scheduling import views

app_name = "scheduling"

urlpatterns = [
    path("availability/", views.AvailabilityView.as_view(), name="availability"),
]
