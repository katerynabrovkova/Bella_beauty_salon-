from django.contrib import admin

from core.admin import SalonScopedAdmin
from specialists.models import Specialist, SpecialistService, TimeOff, WorkingHours


@admin.register(Specialist)
class SpecialistAdmin(SalonScopedAdmin):
    list_display = ("salon", "name")


@admin.register(SpecialistService)
class SpecialistServiceAdmin(SalonScopedAdmin):
    list_display = ("salon", "specialist", "service")


@admin.register(WorkingHours)
class WorkingHoursAdmin(SalonScopedAdmin):
    list_display = ("salon", "specialist", "day_of_week", "start_time", "end_time")


@admin.register(TimeOff)
class TimeOffAdmin(SalonScopedAdmin):
    list_display = ("salon", "specialist", "start_datetime", "end_datetime", "reason")
