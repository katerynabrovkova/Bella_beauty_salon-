"""
Shared ISO 4217 currency-format validation (docs/DECISIONS.md § Stage 8
decisions). One source of truth for the format, used by both enforcement
layers: iso_4217_validator (Python-level, fires on full_clean()) and
ISO_4217_PATTERN directly in each currency field's CheckConstraint
(database-level, fires on every write regardless of path).
"""

from django.core.validators import RegexValidator

ISO_4217_PATTERN = r"^[A-Z]{3}$"
iso_4217_validator = RegexValidator(ISO_4217_PATTERN)
