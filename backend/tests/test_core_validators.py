"""
Stage 8.B-bis — shared ISO 4217 validator (docs/DECISIONS.md § Stage 8
decisions). Tests only — written before core/validators.py exists. Expected
to fail on collection (ModuleNotFoundError: No module named 'core.validators')
until that module is added.

Pure unit tests: no DB, no @pytest.mark.django_db.
"""

import pytest
from django.core.exceptions import ValidationError

from core.validators import ISO_4217_PATTERN, iso_4217_validator


def test_iso_4217_validator_accepts_valid_code():
    iso_4217_validator("UAH")


def test_iso_4217_validator_rejects_lowercase():
    with pytest.raises(ValidationError):
        iso_4217_validator("uah")


def test_iso_4217_validator_rejects_empty_string():
    with pytest.raises(ValidationError):
        iso_4217_validator("")


def test_iso_4217_validator_rejects_wrong_length():
    with pytest.raises(ValidationError):
        iso_4217_validator("USDD")


def test_iso_4217_validator_built_from_shared_pattern():
    """
    Locks the "one shared constant, both enforcement layers read it"
    invariant — a future edit to one without the other would fail this.
    """
    assert iso_4217_validator.regex.pattern == ISO_4217_PATTERN
