from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, ValidationError


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads(
    (ROOT / "schemas" / "repo-favorites.v1.schema.json").read_text(encoding="utf-8")
)
EXAMPLE = json.loads(
    (ROOT / "examples" / "favorites" / "mixed.json").read_text(encoding="utf-8")
)
VALIDATOR = Draft202012Validator(SCHEMA)


def test_present_favorite_requires_observed_inventory_details() -> None:
    payload = copy.deepcopy(EXAMPLE)
    present = next(
        favorite
        for favorite in payload["favorites"]
        if favorite["inventory_status"] == "present"
    )
    present["scope"] = None

    with pytest.raises(ValidationError):
        VALIDATOR.validate(payload)


def test_missing_favorite_forbids_observed_inventory_details() -> None:
    payload = copy.deepcopy(EXAMPLE)
    missing = next(
        favorite
        for favorite in payload["favorites"]
        if favorite["inventory_status"] == "not_in_inventory"
    )
    missing["is_git_repo"] = True

    with pytest.raises(ValidationError):
        VALIDATOR.validate(payload)
