from django.urls import path

from specialists import views

app_name = "specialists"

urlpatterns = [
    path("specialists/", views.SpecialistListCreateView.as_view(), name="specialist-list"),
    path(
        "specialists/<int:pk>/",
        views.SpecialistDetailView.as_view(),
        name="specialist-detail",
    ),
]
