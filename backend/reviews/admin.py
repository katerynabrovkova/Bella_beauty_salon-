from django.contrib import admin

from core.admin import ReadOnlySalonScopedAdmin
from reviews.models import Review


@admin.register(Review)
class ReviewAdmin(ReadOnlySalonScopedAdmin):
    """
    Read-only: reviews are immutable once posted (docs/DECISIONS.md §
    Business rules) — admin edit would directly violate that, not just get
    ahead of an unbuilt stage. `hidden_at` is the one sanctioned staff
    mutation, but its real UI is Stage 21; deferred rather than building
    partial-field editability now.
    """

    list_display = ("salon", "appointment", "customer", "rating", "hidden_at")
