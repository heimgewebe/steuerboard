"""Drift-guard for the generated CLI capability surface.

These tests fail whenever ``steuerboard.cli.build_parser()`` and the generated
documentation disagree: a stale ``docs/_generated/cli-surface.md``, a stale
README block, a newly added CLI command that has not been classified, or a
regression in the documented capability classes. Regenerate with ``make docs``.
"""
from __future__ import annotations

import re

import pytest

from scripts.docmeta import generate_cli_surface as surface
from steuerboard.cli import build_parser


def _class_by_command() -> dict[str, str]:
    _, rows = surface.collect_surface()
    return {command: capability_class for command, capability_class, _ in rows}


def _extract_make_target(makefile_text: str, target: str) -> str:
    """Return the recipe body of one Makefile target (until the next target)."""
    lines = makefile_text.splitlines()
    body: list[str] = []
    capturing = False
    for line in lines:
        if re.match(rf"^{re.escape(target)}\s*:", line):
            capturing = True
            continue
        if capturing:
            if line and not line.startswith("\t") and re.match(r"^[A-Za-z0-9_.\-]+\s*:", line):
                break
            body.append(line)
    return "\n".join(body)


def test_collect_surface_is_consistent() -> None:
    # collect_surface() raises SurfaceError if any parser command is unclassified
    # or any classification entry is stale. This is the core new-command guard.
    categories, rows = surface.collect_surface()
    assert rows, "expected a non-empty CLI surface"
    assert set(categories) == set(surface.CATEGORY_ORDER)


def test_every_parser_command_is_classified() -> None:
    parser_commands = {" ".join(path) for path, _ in surface._iter_leaf_commands(build_parser())}
    documented = set(_class_by_command())
    assert documented == parser_commands


def test_generated_doc_is_current() -> None:
    # (a) docs/_generated/cli-surface.md is up to date.
    categories, rows = surface.collect_surface()
    expected = surface.render_doc(categories, rows)
    actual = surface.GENERATED_DOC_PATH.read_text(encoding="utf-8")
    assert actual == expected, "docs/_generated/cli-surface.md is stale; run `make docs`"


def test_readme_block_is_current() -> None:
    # (b) the marked README block is up to date.
    _, rows = surface.collect_surface()
    expected_block = surface.render_block(rows)
    actual_block = surface.extract_readme_block(
        surface.README_PATH.read_text(encoding="utf-8")
    )
    assert actual_block == expected_block, "README cli-surface block is stale; run `make docs`"


def test_check_reports_no_drift() -> None:
    assert surface.check() == []


def test_run_git_pull_ff_only_is_mutating_stage_d() -> None:
    # (c) the bounded Stage-D executor is the documented mutating command.
    by_command = _class_by_command()
    assert by_command["action run-git-pull-ff-only"] == "mutating_stage_d"
    mutating = [command for command, klass in by_command.items() if klass == "mutating_stage_d"]
    assert mutating == ["action run-git-pull-ff-only"], "expected exactly one mutating executor"


def test_plan_switch_main_is_derivation_only() -> None:
    # (d) plan switch-main stays a preview-only derivation, never mutating/fetch.
    by_command = _class_by_command()
    assert by_command["plan switch-main"] == "derivation_only"
    assert by_command["plan switch-main"] not in {"mutating_stage_d", "fetch_only"}


def test_smoke_and_deploy_check_are_not_mutating() -> None:
    # (e) the smoke / deploy-check recipes must never exercise a mutating command.
    by_command = _class_by_command()
    mutating = [command for command, klass in by_command.items() if klass == "mutating_stage_d"]
    assert mutating, "sanity: expected at least one mutating command to guard against"

    makefile_text = (surface.ROOT / "Makefile").read_text(encoding="utf-8")
    for target in ("smoke", "deploy-check"):
        body = _extract_make_target(makefile_text, target)
        for command in mutating:
            assert command not in body, f"{target} target must not invoke mutating {command!r}"
            leaf = command.split()[-1]
            assert leaf not in body, f"{target} target must not invoke mutating leaf {leaf!r}"


def test_readme_states_bounded_stage_d_executor() -> None:
    # The architectural statement is corrected, not the blanket "no mutating executor".
    readme = surface.README_PATH.read_text(encoding="utf-8")
    assert "general mutating action executor" in readme
    assert "action run-git-pull-ff-only" in readme
    assert "or mutating action executor." not in readme
