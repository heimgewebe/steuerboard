from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from scripts.validate_examples import load_json, validate_instance

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schemas" / "recent-problem-repos.v1.schema.json"
EXAMPLE_PATH = ROOT / "examples" / "recent-problem-repos" / "multiple-reports.json"
REPORTS = [
    "examples/omnipull-reports/non-default-branch.json",
    "examples/omnipull-reports/dirty-worktree.json",
    "examples/omnipull-reports/mixed-run.json",
]


def _run(arguments: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "steuerboard", *arguments],
        cwd=ROOT,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def test_recent_problem_repos_cli_emits_schema_valid_json() -> None:
    result = _run(
        [
            "omnipull-report",
            "recent-problems",
            *REPORTS,
            "--limit",
            "3",
            "--json",
        ]
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    validate_instance(payload, load_json(SCHEMA_PATH), Path("recent-problems-cli.json"))
    assert payload == load_json(EXAMPLE_PATH)


def test_recent_problem_repos_cli_requires_explicit_reports() -> None:
    result = _run(["omnipull-report", "recent-problems", "--json"])

    assert result.returncode == 2
    assert "report_json" in result.stderr
    assert "Traceback" not in result.stderr


def test_recent_problem_repos_cli_rejects_invalid_limit_without_traceback() -> None:
    result = _run(
        [
            "omnipull-report",
            "recent-problems",
            REPORTS[1],
            "--limit",
            "0",
            "--json",
        ]
    )

    assert result.returncode == 2
    assert "limit must be between 1 and 100" in result.stderr
    assert "Traceback" not in result.stderr
