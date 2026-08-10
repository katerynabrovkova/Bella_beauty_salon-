from django.apps import apps
from django.db import models

from core.models import TenantScopedModel


def _concrete_tenant_scoped_models() -> list[type[models.Model]]:
    return [
        model
        for model in apps.get_models()
        if issubclass(model, TenantScopedModel) and not model._meta.abstract
    ]


def test_at_least_one_tenant_scoped_model_is_registered() -> None:
    # Guards against the whole test going vacuously true if app loading breaks.
    assert len(_concrete_tenant_scoped_models()) > 0


def test_every_tenant_scoped_model_has_id_salon_unique_constraint() -> None:
    """
    A concrete TenantScopedModel subclass that declares its own `Meta`
    without inheriting `TenantScopedModel.Meta` silently loses the abstract
    base's `UniqueConstraint(fields=["id", "salon"])` — Django does not merge
    an abstract parent's Meta into a child's own Meta automatically. This
    happened to three of nine models in one Stage 2 pass and was only caught
    by manual review; this test catches it going forward.
    """
    expected_name_by_model = {
        model: f"{model._meta.app_label}_{model._meta.model_name}_id_salon_uniq"
        for model in _concrete_tenant_scoped_models()
    }

    missing = []
    wrong_fields = []
    for model, expected_name in expected_name_by_model.items():
        constraints_by_name = {c.name: c for c in model._meta.constraints}
        constraint = constraints_by_name.get(expected_name)
        if constraint is None:
            missing.append(model.__name__)
            continue
        if not isinstance(constraint, models.UniqueConstraint) or list(constraint.fields) != [
            "id",
            "salon",
        ]:
            wrong_fields.append(model.__name__)

    assert not missing, (
        f"Models missing the (id, salon) UniqueConstraint (likely a Meta that "
        f"doesn't inherit TenantScopedModel.Meta): {missing}"
    )
    assert not wrong_fields, (
        f"Models whose id_salon constraint isn't a UniqueConstraint on exactly "
        f"['id', 'salon']: {wrong_fields}"
    )
