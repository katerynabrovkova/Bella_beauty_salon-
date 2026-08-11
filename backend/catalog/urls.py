from django.urls import path

from catalog import views

app_name = "catalog"

urlpatterns = [
    path(
        "categories/",
        views.ServiceCategoryListCreateView.as_view(),
        name="category-list",
    ),
    path(
        "categories/<int:pk>/",
        views.ServiceCategoryDetailView.as_view(),
        name="category-detail",
    ),
    path(
        "services/",
        views.ServiceListCreateView.as_view(),
        name="service-list",
    ),
    path(
        "services/<int:pk>/",
        views.ServiceDetailView.as_view(),
        name="service-detail",
    ),
]
