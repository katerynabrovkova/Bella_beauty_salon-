from django.db import models

from accounts.models import Customer
from booking.models import Appointment
from core.models import TenantScopedModel, TimeStamped


class Review(TenantScopedModel, TimeStamped):
    """
    docs/ARCHITECTURE.md § 11. One review per appointment (OneToOne), tied to
    a specific completed visit rather than the customer-salon relationship in
    general. Immutable after posting; staff can hide (`hidden_at`), deletion
    isn't exposed to anyone.
    """

    appointment = models.OneToOneField(Appointment, on_delete=models.PROTECT, related_name="review")
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name="reviews")
    rating = models.PositiveSmallIntegerField()
    text = models.TextField(blank=True)
    hidden_at = models.DateTimeField(null=True, blank=True)

    class Meta(TenantScopedModel.Meta):
        abstract = False
        constraints = [
            *TenantScopedModel.Meta.constraints,
            models.CheckConstraint(
                condition=models.Q(rating__gte=1) & models.Q(rating__lte=5),
                name="review_rating_between_1_and_5",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.rating}* review for {self.appointment}"
