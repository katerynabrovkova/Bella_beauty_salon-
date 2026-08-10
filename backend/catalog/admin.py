from django.contrib import admin

from catalog.models import Service, ServiceCategory
from core.admin import SalonScopedAdmin


@admin.register(ServiceCategory)
class ServiceCategoryAdmin(SalonScopedAdmin):
    list_display = ("salon", "name", "ordering")


@admin.register(Service)
class ServiceAdmin(SalonScopedAdmin):
    list_display = ("salon", "name", "category", "duration_minutes", "price", "buffer_minutes")
