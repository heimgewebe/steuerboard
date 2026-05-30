#!/usr/bin/env python3
"""Generate and verify the steuerboard CLI capability surface.

Deterministic documentation drift-guard. The executable CLI surface is
introspected from ``steuerboard.cli.build_parser()`` and joined with an
explicit capability classification (``scripts/docmeta/cli_surface.json``).
The result is rendered into ``docs/_generated/cli-surface.md`` and into a
clearly marked block inside ``README.md``.

This is documentation scaffolding only. It does not scan repositories, run
Git, or execute steuerboard actions. Classification is declared explicitly in
the JSON sidecar and is never guessed from help text.

Usage::

    python scripts/docmeta/generate_cli_surface.py --write
    python scripts/docmeta/generate_cli_surface.py --check

``--write`` regenerates the generated doc and rewrites the README block.
``--check`` regenerates both in memory and exits non-zero on any drift,
including a CLI command that has no classification yet.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from steuerboard.cli import build_parser  # noqa: E402  (needs ROOT on sys.path)

CLASSIFICATION_PATH = Path(__file__).resolve().parent / "cli_surface.json"
GENERATED_DOC_PATH = ROOT / "docs" / "_generated" / "cli-surface.md"
README_PATH = ROOT / "README.md"

BEGIN_MARKER = "<!-- BEGIN GENERATED: cli-surface -->"
END_MARKER = "<!-- END GENERATED: cli-surface -->"

# Stable rendering order for capability classes (least to most privileged).
CATEGORY_ORDER = ["read_only", "derivation_only", "fetch_only", "mutating_stage_d"]

PROG = "python -m steuerboard"


class SurfaceError(Exception):
    """Raised when the parser and the explicit classification disagree."""


def _iter_leaf_commands(parser, prefix=()):
    """Yield ``(command_path_tuple, leaf_parser)`` for every invocable command.

    A parser is invocable when it has no subparsers, or when it carries an
    optional subparser group (e.g. ``inventory`` is valid with or without the
    ``duplicates`` subcommand).
    """
    subparser_actions = [
        action
        for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    ]
    if not subparser_actions:
        yield prefix, parser
        return
    if prefix and any(not action.required for action in subparser_actions):
        yield prefix, parser
    for action in subparser_actions:
        for name, subparser in action.choices.items():
            yield from _iter_leaf_commands(subparser, prefix + (name,))


def _metavar(action) -> str:
    raw = action.metavar or action.dest
    return raw.lower().replace("_", "-")


def _surface_required(action) -> bool:
    return action.required or getattr(action, "surface_required", False)


def _invocation(command_path, leaf_parser) -> str:
    """Reconstruct a deterministic example invocation for one leaf command."""
    parts = [PROG, *command_path]
    for action in leaf_parser._actions:
        if isinstance(action, (argparse._HelpAction, argparse._SubParsersAction)):
            continue
        if not action.option_strings:
            parts.append(f"<{_metavar(action)}>")
            continue
        flag = action.option_strings[0]
        if action.nargs == 0:
            token = flag
        else:
            token = f"{flag} <{_metavar(action)}>"
        if not _surface_required(action):
            token = f"[{token}]"
        parts.append(token)
    return " ".join(parts)


def load_classification() -> dict:
    return json.loads(CLASSIFICATION_PATH.read_text(encoding="utf-8"))


def collect_surface():
    """Return ``(categories, rows)`` for a consistent parser/classification pair.

    ``rows`` is a list of ``(command, capability_class, invocation)`` ordered by
    capability class (``CATEGORY_ORDER``) and then command name. Raises
    :class:`SurfaceError` when the parser and the explicit classification
    disagree, which is the core drift signal for newly added CLI commands.
    """
    invocations = {
        " ".join(path): _invocation(path, leaf)
        for path, leaf in _iter_leaf_commands(build_parser())
    }
    data = load_classification()
    categories = data["categories"]
    commands = data["commands"]

    problems: list[str] = []
    for command in sorted(set(invocations) - set(commands)):
        problems.append(
            f"command {command!r} is exposed by build_parser() but missing from "
            f"{CLASSIFICATION_PATH.name}"
        )
    for command in sorted(set(commands) - set(invocations)):
        problems.append(
            f"command {command!r} is classified in {CLASSIFICATION_PATH.name} but is "
            f"not exposed by build_parser()"
        )
    for command, capability_class in sorted(commands.items()):
        if capability_class not in categories:
            problems.append(
                f"command {command!r} has unknown capability class {capability_class!r}"
            )
    for capability_class in CATEGORY_ORDER:
        if capability_class not in categories:
            problems.append(
                f"capability class {capability_class!r} has no description in "
                f"{CLASSIFICATION_PATH.name}"
            )
    for capability_class in sorted(set(categories) - set(CATEGORY_ORDER)):
        problems.append(
            f"capability class {capability_class!r} is described but not listed in "
            f"CATEGORY_ORDER"
        )
    if problems:
        raise SurfaceError(
            "CLI surface classification is out of sync:\n  - " + "\n  - ".join(problems)
        )

    rows = []
    for capability_class in CATEGORY_ORDER:
        for command in sorted(c for c, k in commands.items() if k == capability_class):
            rows.append((command, capability_class, invocations[command]))
    return categories, rows


def render_block(rows) -> str:
    """Render the shared markdown table embedded in both README and the doc."""
    lines = [
        "| Command | Capability class | Invocation |",
        "| --- | --- | --- |",
    ]
    for command, capability_class, invocation in rows:
        lines.append(f"| `{command}` | `{capability_class}` | `{invocation}` |")
    return "\n".join(lines)


def render_doc(categories, rows) -> str:
    counts = {capability_class: 0 for capability_class in CATEGORY_ORDER}
    for _, capability_class, _ in rows:
        counts[capability_class] += 1
    count_str = ", ".join(f"{k}={counts[k]}" for k in CATEGORY_ORDER)

    lines = [
        "<!-- GENERATED FILE — do not edit by hand.",
        "     Source: steuerboard.cli.build_parser() + scripts/docmeta/cli_surface.json",
        "     Regenerate: make docs"
        "  (python scripts/docmeta/generate_cli_surface.py --write) -->",
        "",
        "# CLI capability surface (generated)",
        "",
        "This file enumerates every invocable `steuerboard` CLI command joined with an",
        "explicit capability classification. It is generated and verified by",
        "`scripts/docmeta/generate_cli_surface.py`; the same table is mirrored into the",
        "marked block in `README.md`. Classification lives in",
        "`scripts/docmeta/cli_surface.json` and is declared explicitly, never inferred",
        "from help text.",
        "",
        f"Capability counts: {count_str}.",
        "",
        BEGIN_MARKER,
        render_block(rows),
        END_MARKER,
        "",
        "## Capability classes",
        "",
    ]
    for capability_class in CATEGORY_ORDER:
        lines.append(f"- `{capability_class}` — {categories[capability_class]}")
    return "\n".join(lines) + "\n"


def extract_readme_block(readme_text):
    begin = readme_text.find(BEGIN_MARKER)
    end = readme_text.find(END_MARKER)
    if begin == -1 or end == -1 or end < begin:
        return None
    return readme_text[begin + len(BEGIN_MARKER):end].strip("\n")


def update_readme(readme_text, block) -> str:
    begin = readme_text.find(BEGIN_MARKER)
    end = readme_text.find(END_MARKER)
    if begin == -1 or end == -1 or end < begin:
        raise SurfaceError(
            f"README markers not found; expected {BEGIN_MARKER!r} ... {END_MARKER!r}"
        )
    before = readme_text[: begin + len(BEGIN_MARKER)]
    after = readme_text[end:]
    return f"{before}\n{block}\n{after}"


def check() -> list[str]:
    """Return a list of human-readable drift problems (empty when up to date)."""
    categories, rows = collect_surface()
    problems: list[str] = []

    expected_doc = render_doc(categories, rows)
    if not GENERATED_DOC_PATH.exists():
        problems.append(f"{GENERATED_DOC_PATH.relative_to(ROOT)} does not exist")
    elif GENERATED_DOC_PATH.read_text(encoding="utf-8") != expected_doc:
        problems.append(f"{GENERATED_DOC_PATH.relative_to(ROOT)} is out of date")

    expected_block = render_block(rows)
    actual_block = extract_readme_block(README_PATH.read_text(encoding="utf-8"))
    if actual_block is None:
        problems.append(f"{README_PATH.relative_to(ROOT)} is missing the generated block markers")
    elif actual_block != expected_block:
        problems.append(f"{README_PATH.relative_to(ROOT)} generated block is out of date")
    return problems


def write() -> None:
    categories, rows = collect_surface()
    GENERATED_DOC_PATH.parent.mkdir(parents=True, exist_ok=True)
    GENERATED_DOC_PATH.write_text(render_doc(categories, rows), encoding="utf-8")
    readme_text = README_PATH.read_text(encoding="utf-8")
    README_PATH.write_text(update_readme(readme_text, render_block(rows)), encoding="utf-8")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="generate_cli_surface",
        description="Generate or verify the steuerboard CLI capability surface.",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--write",
        action="store_true",
        help="Regenerate docs/_generated/cli-surface.md and the README block.",
    )
    mode.add_argument(
        "--check",
        action="store_true",
        help="Fail if the generated doc or README block is out of date.",
    )
    args = parser.parse_args(argv)

    try:
        if args.write:
            write()
            print(
                "cli-surface: wrote docs/_generated/cli-surface.md and updated the "
                "README block"
            )
            return 0
        problems = check()
    except SurfaceError as exc:
        print(f"cli-surface: {exc}", file=sys.stderr)
        return 1

    if problems:
        print("cli-surface: drift detected", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        print(
            "Run: make docs  (python scripts/docmeta/generate_cli_surface.py --write)",
            file=sys.stderr,
        )
        return 1

    print("cli-surface: docs/_generated/cli-surface.md and README block are up to date")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
