"""
Migration helper for the cross-tenant FK protection described in
docs/ARCHITECTURE.md § 5.

Django's ForeignKey is single-column, so it can express the parent-side
`UNIQUE(id, salon)` (a normal UniqueConstraint on TenantScopedModel, picked up
by makemigrations) but not the composite FK itself. This adds a *second* FK
constraint on the same child column, pairing it with `salon_id`, on top of the
normal Django-managed single-column FK — Postgres allows two FK constraints on
the same column, and this second one is what actually rejects a child row
whose salon doesn't match its parent's.
"""

from django.db import migrations


def composite_tenant_fk(
    *, child_table: str, fk_column: str, parent_table: str, constraint_name: str
) -> migrations.RunSQL:
    return migrations.RunSQL(
        sql=(
            f"ALTER TABLE {child_table} "
            f"ADD CONSTRAINT {constraint_name} "
            f"FOREIGN KEY ({fk_column}, salon_id) REFERENCES {parent_table} (id, salon_id);"
        ),
        reverse_sql=(f"ALTER TABLE {child_table} DROP CONSTRAINT {constraint_name};"),
    )
