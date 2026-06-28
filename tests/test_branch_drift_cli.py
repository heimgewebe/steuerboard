import json
from pathlib import Path

import pytest

from scripts.validate_examples import ROOT, load_json
from steuerboard.cli import build_parser, main


def test_parser_requires_explicit_bounded_threshold():
    parser = build_parser()
    args = parser.parse_args([
        "inventory", "branch-drift", "--warning-threshold", "7", "--json"
    ])
    assert args.warning_threshold == 7
    with pytest.raises(SystemExit):
        parser.parse_args(["inventory", "branch-drift", "--json"])
    for invalid in ("0", "1001", "word"):
        with pytest.raises(SystemExit):
            parser.parse_args([
                "inventory", "branch-drift", "--warning-threshold", invalid, "--json"
            ])


def test_cli_dispatches_config_and_threshold(monkeypatch, capsys):
    expected = load_json(ROOT / "examples/branch-drift/mixed.json")
    calls = []

    def build(*, config_path, warning_threshold):
        calls.append((config_path, warning_threshold))
        return expected

    monkeypatch.setattr("steuerboard.cli.build_branch_drift_report", build)
    result = main([
        "inventory", "branch-drift", "--config", "config.json",
        "--warning-threshold", "2", "--json"
    ])
    assert result == 0
    assert calls == [(Path("config.json"), 2)]
    assert json.loads(capsys.readouterr().out) == expected
