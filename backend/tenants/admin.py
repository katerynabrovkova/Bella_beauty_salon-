from django.contrib import admin

from tenants.models import Salon


@admin.register(Salon)
class SalonAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "is_active", "timezone")
    list_filter = ("is_active",)
