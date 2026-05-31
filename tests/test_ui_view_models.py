"""Phase 10A boundary tests for the read-only UI display layer.

These tests prove that the Phase 10A slice is display-only:

- every ``examples/ui-view-models/*.json`` validates against
  ``schemas/ui-view-model.v1.schema.json`` and carries the const-true,
  display-only boundary;
- the schema rejects additional properties and any executable field
  (``command``/``argv``/``action_endpoint``/``method``/...);
- the runtime frontend scaffold contains no action/execution affordance
  (no Git command, subprocess, network mutation method, form submission, or
  inline action handler);
- the view-model examples contain no executable *field* anywhere;
- this slice adds no new mutating command — Stage D stays at exactly the two
  documented executors, and the CLI-surface summary view matches the real
  classification counts.

Design note on the two different scans. Runtime frontend code is scanned for
forbidden *substrings* (affordances). JSON view models are scanned for forbidden
*keys* (fields), never for forbidden value strings: a display layer must be able
to *name* the artifact it shows (e.g. ``run-switch-main-success``) without that
naming becoming an action affordance. The structural guarantee — "no executable
field" — is enforced by the schema (``additionalProperties: false``) and by the
recursive key scan. Contract docs are not scanned here; they legitimately list
these terms as forbidden.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from scripts.docmeta import generate_cli_surface as surface
from scripts.validate_examples import (
    EXAMPLES_DIR,
    SCHEMAS_DIR,
    ValidationError,
    load_json,
    validate_instance,
)

ROOT = Path(__file__).resolve().parents[1]
UI_SCHEMA_PATH = SCHEMAS_DIR / "ui-view-model.v1.schema.json"
UI_EXAMPLES_DIR = EXAMPLES_DIR / "ui-view-models"
FRONTEND_DIR = ROOT / "frontend"

REQUIRED_UI_VIEW_MODELS = {
    "cli-surface-summary.json",
    "switch-main-readiness-ready-view.json",
    "run-switch-main-success-view.json",
    "blocked-readiness-view.json",
}

DISPLAY_ONLY_BOUNDARY = {
    "does_not_execute": True,
    "does_not_mutate": True,
    "does_not_authorise_actions": True,
    "display_only": True,
}

# Executable/affordance *field names* that must never appear as a key anywhere in
# a view model. ``does_not_execute`` etc. are guarantees, not affordances, and do
# not match these exact keys.
FORBIDDEN_VIEW_MODEL_KEYS = {
    "command",
    "argv",
    "cmd",
    "action_endpoint",
    "endpoint",
    "url",
    "method",
    "http_method",
    "approve",
    "approval_decision",
    "authorise",
    "authorize",
    "execute",
    "exec",
    "run",
    "run_command",
    "shell",
    "subprocess",
}

# Runtime frontend code (not docs) must contain none of these action/execution
# affordances. These are deliberately *not* the read-only boundary verbs
# (execute/mutate/authorise), which legitimately appear as guarantee-flag names.
FORBIDDEN_FRONTEND_SUBSTRINGS = (
    "run-switch-main",
    "run-git-pull-ff-only",
    "git switch",
    "git pull",
    "git fetch",
    "git reset",
    "git clean",
    "git merge",
    "git rebase",
    "git push",
    "subprocess",
    "child_process",
    "execsync",
    "spawn",
    "fetch(",
    "xmlhttprequest",
    "websocket",
    "onclick",
    "onsubmit",
    "<form",
    ".submit(",
    "localhost",
    "127.0.0.1",
)

# Uppercase HTTP mutation methods are matched case-sensitively so they do not
# false-positive on benign words such as "input"/"output".
FORBIDDEN_FRONTEND_METHODS = ("POST", "PUT", "PATCH", "DELETE")

FRONTEND_CODE_SUFFIXES = {".html", ".htm", ".js", ".mjs", ".css"}


def _ui_schema() -> dict:
    return load_json(UI_SCHEMA_PATH)


def _valid_view_model() -> dict:
    return {
        "schema_version": "ui-view-model.v1",
        "view_id": "ui-view-test-base",
        "generated_at": "2026-05-31T00:00:00Z",
        "title": "Test view",
        "view_kind": "generic_artifact",
        "status": "ok",
        "source_artifact": {
            "artifact_schema_version": "repo-observation.v1",
            "artifact_ref": "obs-test-001",
        },
        "summary": [{"label": "Status", "value": "ok", "severity": "info"}],
        "sections": [
            {"heading": "Detail", "rows": [{"label": "key", "value": "value"}]}
        ],
        "source_refs": ["examples/observations/feature-branch-clean.json"],
        "boundary": dict(DISPLAY_ONLY_BOUNDARY),
    }


def _iter_keys(obj):
    if isinstance(obj, dict):
        for key, value in obj.items():
            yield key
            yield from _iter_keys(value)
    elif isinstance(obj, list):
        for item in obj:
            yield from _iter_keys(item)


def _frontend_code_files() -> list[Path]:
    return [
        path
        for path in FRONTEND_DIR.rglob("*")
        if path.is_file() and path.suffix.lower() in FRONTEND_CODE_SUFFIXES
    ]


# --------------------------------------------------------------------------- #
# A. schema/example validity                                                  #
# --------------------------------------------------------------------------- #


def test_contract_and_schema_exist():
    assert (ROOT / "docs" / "ui-readonly-contract.md").is_file()
    assert UI_SCHEMA_PATH.is_file()


def test_required_ui_view_models_present():
    actual = {path.name for path in UI_EXAMPLES_DIR.glob("*.json")}
    assert REQUIRED_UI_VIEW_MODELS <= actual


def test_all_ui_view_models_validate():
    schema = _ui_schema()
    examples = sorted(UI_EXAMPLES_DIR.glob("*.json"))
    assert examples, "expected at least one ui-view-model example"
    for path in examples:
        validate_instance(load_json(path), schema, path)


def test_every_example_boundary_is_display_only():
    for path in sorted(UI_EXAMPLES_DIR.glob("*.json")):
        view = load_json(path)
        assert view["schema_version"] == "ui-view-model.v1"
        assert view["boundary"] == DISPLAY_ONLY_BOUNDARY, (
            f"{path.name}: boundary must be exactly the four display-only flags, all true"
        )


def test_valid_view_model_base_passes():
    # Guards the negative schema tests below: the base really is valid.
    validate_instance(_valid_view_model(), _ui_schema(), UI_EXAMPLES_DIR / "valid-base.json")


# --------------------------------------------------------------------------- #
# B. no-mutation affordance                                                   #
# --------------------------------------------------------------------------- #


def test_view_models_carry_no_executable_field():
    for path in sorted(UI_EXAMPLES_DIR.glob("*.json")):
        keys = set(_iter_keys(load_json(path)))
        offenders = keys & FORBIDDEN_VIEW_MODEL_KEYS
        assert not offenders, f"{path.name}: forbidden executable field(s) {sorted(offenders)}"


def test_frontend_has_runtime_scaffold():
    assert any(path.name == "index.html" for path in _frontend_code_files())


def test_frontend_code_has_no_action_affordance():
    files = _frontend_code_files()
    assert files, "expected runtime frontend code to scan"
    for path in files:
        text = path.read_text(encoding="utf-8")
        lowered = text.lower()
        for token in FORBIDDEN_FRONTEND_SUBSTRINGS:
            assert token not in lowered, f"{path.name}: forbidden affordance {token!r}"
        for method in FORBIDDEN_FRONTEND_METHODS:
            assert method not in text, f"{path.name}: forbidden HTTP mutation method {method!r}"


def test_frontend_readme_states_read_only_boundary():
    readme = (FRONTEND_DIR / "README.md").read_text(encoding="utf-8").lower()
    for phrase in (
        "read-only",
        "ui-view-model.v1",
        "does not inspect git repositories",
        "does not execute actions",
        "does not authorise actions",
        "no action buttons",
        "out of scope",
    ):
        assert phrase in readme, f"frontend/README.md missing required phrase: {phrase!r}"


# --------------------------------------------------------------------------- #
# C. schema shape / rejection                                                 #
# --------------------------------------------------------------------------- #


def test_schema_rejects_display_only_false():
    invalid = _valid_view_model()
    invalid["boundary"] = {**DISPLAY_ONLY_BOUNDARY, "display_only": False}
    with pytest.raises(ValidationError):
        validate_instance(invalid, _ui_schema(), UI_EXAMPLES_DIR / "invalid-display-only-false.json")


def test_schema_requires_display_only_present():
    invalid = _valid_view_model()
    del invalid["boundary"]["display_only"]
    with pytest.raises(ValidationError):
        validate_instance(invalid, _ui_schema(), UI_EXAMPLES_DIR / "invalid-missing-display-only.json")


def test_schema_rejects_additional_top_level_property():
    invalid = _valid_view_model()
    invalid["extra"] = "nope"
    with pytest.raises(ValidationError):
        validate_instance(invalid, _ui_schema(), UI_EXAMPLES_DIR / "invalid-extra.json")


@pytest.mark.parametrize("field", ["command", "argv", "action_endpoint", "method", "approve_url"])
def test_schema_rejects_executable_top_level_field(field):
    invalid = _valid_view_model()
    invalid[field] = "x"
    with pytest.raises(ValidationError):
        validate_instance(invalid, _ui_schema(), UI_EXAMPLES_DIR / f"invalid-{field}.json")


def test_schema_rejects_command_field_on_row():
    invalid = _valid_view_model()
    invalid["summary"][0]["command"] = "git status"
    with pytest.raises(ValidationError):
        validate_instance(invalid, _ui_schema(), UI_EXAMPLES_DIR / "invalid-row-command.json")


def test_schema_rejects_unknown_view_kind():
    invalid = _valid_view_model()
    invalid["view_kind"] = "action_runner"
    with pytest.raises(ValidationError):
        validate_instance(invalid, _ui_schema(), UI_EXAMPLES_DIR / "invalid-view-kind.json")


# --------------------------------------------------------------------------- #
# D. no new mutating command; CLI-surface parity                              #
# --------------------------------------------------------------------------- #


def test_exactly_two_mutating_stage_d_commands():
    _, rows = surface.collect_surface()
    mutating = sorted(command for command, klass, _ in rows if klass == "mutating_stage_d")
    assert mutating == ["action run-git-pull-ff-only", "action run-switch-main"], (
        "Phase 10A must not add a mutating command; Stage D stays at exactly two executors"
    )


def test_cli_surface_summary_example_matches_real_counts():
    _, rows = surface.collect_surface()
    counts: dict[str, int] = {}
    for _, klass, _ in rows:
        counts[klass] = counts.get(klass, 0) + 1

    view = load_json(UI_EXAMPLES_DIR / "cli-surface-summary.json")
    by_label = {row["label"]: row["value"] for row in view["summary"]}

    assert by_label["mutating_stage_d"] == str(counts.get("mutating_stage_d", 0)) == "2"
    assert by_label["read_only"] == str(counts["read_only"])
    assert by_label["derivation_only"] == str(counts["derivation_only"])
    assert by_label["fetch_only"] == str(counts["fetch_only"])
    assert by_label["Total commands"] == str(sum(counts.values()))
