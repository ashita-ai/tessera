"""Tests for proposal model validation."""

import pytest
from pydantic import ValidationError

from tessera.models.proposal import ObjectionCreate


def test_objection_create_reason_validation():
    """Test validation for ObjectionCreate.reason field."""
    # Test valid reason
    obj = ObjectionCreate(reason="Valid Reason")
    assert obj.reason == "Valid Reason"

    # Test whitespace stripping
    obj = ObjectionCreate(reason="  Valid Reason  ")
    assert obj.reason == "Valid Reason"

    # Test empty string (should fail)
    with pytest.raises(ValidationError) as exc:
        ObjectionCreate(reason="")
    assert "String should have at least 1 character" in str(exc.value)

    # Test whitespace only string (should fail due to validator)
    with pytest.raises(ValidationError) as exc:
        ObjectionCreate(reason="   ")
    assert "Reason cannot be empty or whitespace only" in str(exc.value)

    # Test None (should fail)
    with pytest.raises(ValidationError):
        ObjectionCreate(reason=None)
