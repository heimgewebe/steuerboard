"""Tests for Phase 11A read-only runbook runner.

Groups:
A. Schema and examples
B. CLI and runner
C. Output safety
D. No mutation surface
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES_DIR = ROOT / "examples"
SCHEMAS_DIR = ROOT / "schemas"

sys.path.insert(0, str(ROOT))

from scripts.validate_examples import (  # noqa: E402
    ValidationError,
    load_json,
    validate_instance,
)
from steuerboard.runbooks import (  # noqa: E402
    check_decision_state,
    check_is_git_repo,
    check_not_detached_head,
    check_on_default_branch,
    check_worktree_clean,
    run_runbook,
)
from steuerboard.cli import build_parser, main  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _runbook_plan_schema() -> dict:
    return load_json(SCHEMAS_DIR / "runbook-plan.v1.schema.json")


def _runbook_result_schema() -> dict:
    return load_json(SCHEMAS_DIR / "runbook-result.v1.schema.json")


def _runbook_step_trace_schema() -> dict:
    return load_json(SCHEMAS_DIR / "runbook-step-trace.v1.schema.json")


def _valid_runbook_plan(repo_path: str = "/tmp/test-repo") -> dict:
    return {
        "schema_version": "runbook-plan.v1",
        "runbook_id": "runbook-test-001",
        "runbook_kind": "repo-sync-gate",
        "created_at": "2026-05-31T10:00:00Z",
        "repo_path": repo_path,
        "mode": "read_only",
        "source_refs": ["runbook-model.v1"],
        "boundary": {
            "does_not_execute_mutating_actions": True,
            "does_not_mutate": True,
            "does_not_authorise_actions": True,
            "read_only_or_dry_run_only": True,
        },
    }


# ---------------------------------------------------------------------------
# A. Schema and examples
# ---------------------------------------------------------------------------

class TestSchemaAndExamples:
    def test_runbook_schemas_declare_draft_2020_12_with_id(self):
        expected = {
            "runbook-plan.v1.schema.json": "https://example.invalid/steuerboard/schemas/runbook-plan.v1.schema.json",
            "runbook-result.v1.schema.json": "https://example.invalid/steuerboard/schemas/runbook-result.v1.schema.json",
            "runbook-step-trace.v1.schema.json": "https://example.invalid/steuerboard/schemas/runbook-step-trace.v1.schema.json",
        }
        for filename, schema_id in expected.items():
            schema = load_json(SCHEMAS_DIR / filename)
            assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
            assert schema["$id"] == schema_id

    def test_runbook_plan_example_validates(self):
        schema = _runbook_plan_schema()
        example = load_json(EXAMPLES_DIR / "runbooks/repo-sync-gate.json")
        validate_instance(example, schema, EXAMPLES_DIR / "runbooks/repo-sync-gate.json")

    def test_runbook_result_examples_validate(self):
        schema = _runbook_result_schema()
        for name in ["repo-sync-gate-passed.json", "repo-sync-gate-blocked.json", "repo-sync-gate-inconclusive.json"]:
            path = EXAMPLES_DIR / "runbook-results" / name
            example = load_json(path)
            validate_instance(example, schema, path)

    def test_runbook_trace_jsonl_example_validates_each_line(self):
        schema = _runbook_step_trace_schema()
        jsonl_path = EXAMPLES_DIR / "runbook-traces/repo-sync-gate-command-trace.jsonl"
        with jsonl_path.open("r", encoding="utf-8") as fh:
            lines = [line.strip() for line in fh if line.strip()]
        assert len(lines) > 0, "JSONL trace must have at least one line"
        for i, line in enumerate(lines):
            entry = json.loads(line)
            validate_instance(entry, schema, jsonl_path)

    def test_runbook_plan_rejects_unknown_runbook_kind(self):
        schema = _runbook_plan_schema()
        invalid = _valid_runbook_plan()
        invalid["runbook_kind"] = "dns-gate"
        with pytest.raises((ValidationError, Exception)):
            validate_instance(invalid, schema, Path("invalid-plan.json"))

    def test_runbook_plan_rejects_non_read_only_mode(self):
        schema = _runbook_plan_schema()
        invalid = _valid_runbook_plan()
        invalid["mode"] = "dry_run"
        with pytest.raises((ValidationError, Exception)):
            validate_instance(invalid, schema, Path("invalid-plan-mode.json"))

    def test_runbook_plan_rejects_boundary_false(self):
        schema = _runbook_plan_schema()
        invalid = _valid_runbook_plan()
        invalid["boundary"] = {
            **invalid["boundary"],
            "does_not_mutate": False,
        }
        with pytest.raises((ValidationError, Exception)):
            validate_instance(invalid, schema, Path("invalid-plan-boundary.json"))

    def test_runbook_plan_rejects_additional_properties(self):
        schema = _runbook_plan_schema()
        invalid = _valid_runbook_plan()
        invalid["extra_field"] = "not_allowed"
        with pytest.raises((ValidationError, Exception)):
            validate_instance(invalid, schema, Path("invalid-plan-extra.json"))


# ---------------------------------------------------------------------------
# B. CLI and runner
# ---------------------------------------------------------------------------

class TestCLIAndRunner:
    def test_runbook_run_cli_exists(self):
        parser = build_parser()
        # Build a namespace to verify runbook run is parseable
        args = parser.parse_args([
            "runbook", "run",
            "/tmp/plan.json",
            "--result-out", "/tmp/result.json",
            "--command-trace-out", "/tmp/trace.jsonl",
            "--json",
        ])
        assert args.command == "runbook"
        assert args.runbook_command == "run"
        assert args.runbook_plan_json == "/tmp/plan.json"
        assert args.result_out == "/tmp/result.json"
        assert args.command_trace_out == "/tmp/trace.jsonl"
        assert args.json is True

    def test_repo_sync_gate_success_writes_result_and_trace(self, tmp_path):
        """Running repo-sync-gate on the actual steuerboard repo should produce files."""
        plan = _valid_runbook_plan(repo_path=str(ROOT))
        result_out = str(tmp_path / "result.json")
        trace_out = str(tmp_path / "trace.jsonl")

        result = run_runbook(
            runbook_plan=plan,
            result_out=result_out,
            command_trace_out=trace_out,
        )

        # Files written
        assert Path(result_out).exists(), "result.json must be written"
        assert Path(trace_out).exists(), "trace.jsonl must be written"

        # Result has correct schema
        assert result["schema_version"] == "runbook-result.v1"
        assert result["runbook_kind"] == "repo-sync-gate"
        assert result["status"] in ("passed", "blocked", "inconclusive")
        assert result["runbook_ref"] == plan["runbook_id"]
        assert result["repo_path"] == str(ROOT)
        assert len(result["steps"]) > 0
        assert result["boundary"]["does_not_mutate"] is True
        assert result["boundary"]["does_not_execute_mutating_actions"] is True
        assert result["redaction_verified"] is True

        # Validate result against schema
        result_schema = _runbook_result_schema()
        validate_instance(result, result_schema, Path(result_out))

        # Written result matches returned result
        written_result = load_json(Path(result_out))
        assert written_result == result

        # Trace JSONL is valid
        trace_schema = _runbook_step_trace_schema()
        with Path(trace_out).open("r", encoding="utf-8") as fh:
            lines = [line.strip() for line in fh if line.strip()]
        assert len(lines) > 0, "trace JSONL must have at least one entry"
        for line in lines:
            entry = json.loads(line)
            validate_instance(entry, trace_schema, Path(trace_out))

    def test_repo_sync_gate_blocked_preserves_blocked_state(self, tmp_path):
        """blocked decision_state from assessment must map to blocked overall status."""
        # Use a non-existent path — assess_repo will produce assessment_clear=false
        # or action_blocked. We can also construct a fake observation with dirty=True.
        # Use a path that doesn't exist to get inconclusive or use a known approach.
        # The cleanest: create a git repo with a dirty worktree.
        import subprocess as _subprocess

        repo = tmp_path / "dirty-repo"
        repo.mkdir()
        _subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
        _subprocess.run(
            ["git", "-C", str(repo), "config", "user.email", "test@test.invalid"],
            check=True, capture_output=True,
        )
        _subprocess.run(
            ["git", "-C", str(repo), "config", "user.name", "Test"],
            check=True, capture_output=True,
        )
        # Create an initial commit
        (repo / "README.txt").write_text("hello\n")
        _subprocess.run(["git", "-C", str(repo), "add", "README.txt"], check=True, capture_output=True)
        _subprocess.run(
            ["git", "-C", str(repo), "commit", "-m", "init"],
            check=True, capture_output=True,
        )
        # Now dirty the worktree
        (repo / "dirty.txt").write_text("dirty\n")

        plan = _valid_runbook_plan(repo_path=str(repo))
        result_out = str(tmp_path / "result-blocked.json")
        trace_out = str(tmp_path / "trace-blocked.jsonl")

        result = run_runbook(
            runbook_plan=plan,
            result_out=result_out,
            command_trace_out=trace_out,
        )

        assert result["status"] == "blocked", (
            f"Expected blocked status for dirty worktree, got {result['status']!r}; "
            f"steps={result['steps']!r}"
        )
        # Verify blocked steps contain dirty-worktree-related step
        statuses = {s["step_id"]: s["status"] for s in result["steps"]}
        assert statuses.get("step-check-worktree-clean") == "blocked"
        assert statuses.get("step-check-decision-state") == "blocked"

        # Validate written result against schema
        result_schema = _runbook_result_schema()
        validate_instance(result, result_schema, Path(result_out))

    def test_repo_sync_gate_inconclusive_when_assessment_unclear(self, tmp_path):
        """evidence_missing decision_state should yield inconclusive overall status."""
        import subprocess as _subprocess

        repo = tmp_path / "clean-repo-no-upstream"
        repo.mkdir()
        _subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
        _subprocess.run(
            ["git", "-C", str(repo), "config", "user.email", "test@test.invalid"],
            check=True, capture_output=True,
        )
        _subprocess.run(
            ["git", "-C", str(repo), "config", "user.name", "Test"],
            check=True, capture_output=True,
        )
        # Create an initial commit on a branch
        (repo / "README.txt").write_text("hello\n")
        _subprocess.run(["git", "-C", str(repo), "add", "README.txt"], check=True, capture_output=True)
        _subprocess.run(
            ["git", "-C", str(repo), "commit", "-m", "init"],
            check=True, capture_output=True,
        )
        # Create a non-default branch (no upstream configured)
        _subprocess.run(
            ["git", "-C", str(repo), "checkout", "-b", "feature-branch"],
            check=True, capture_output=True,
        )

        plan = _valid_runbook_plan(repo_path=str(repo))
        result_out = str(tmp_path / "result-inconclusive.json")
        trace_out = str(tmp_path / "trace-inconclusive.jsonl")

        result = run_runbook(
            runbook_plan=plan,
            result_out=result_out,
            command_trace_out=trace_out,
        )

        # On a non-default branch: assessment gives evidence_missing or action_blocked
        # depending on the exact state. Either way it should NOT be softened to "passed".
        assert result["status"] in ("blocked", "inconclusive"), (
            f"Expected blocked or inconclusive, got {result['status']!r}"
        )

        result_schema = _runbook_result_schema()
        validate_instance(result, result_schema, Path(result_out))

    def test_result_stdout_matches_written_result(self, tmp_path):
        """The returned result dict must equal the written JSON file content."""
        plan = _valid_runbook_plan(repo_path=str(ROOT))
        result_out = str(tmp_path / "result-match.json")
        trace_out = str(tmp_path / "trace-match.jsonl")

        result = run_runbook(
            runbook_plan=plan,
            result_out=result_out,
            command_trace_out=trace_out,
        )

        written = load_json(Path(result_out))
        assert written == result

    def test_repo_sync_gate_observe_failure_stays_inconclusive(self, tmp_path, monkeypatch):
        plan = _valid_runbook_plan(repo_path=str(ROOT))
        result_out = str(tmp_path / "result.json")
        trace_out = str(tmp_path / "trace.jsonl")

        def _boom(_path):
            raise RuntimeError("observe exploded")

        def _assessment(_path):
            return {
                "decision_state": "evidence_missing",
                "source_refs": ["assessment.ref"],
            }

        monkeypatch.setattr("steuerboard.runbooks.observe_repo", _boom)
        monkeypatch.setattr("steuerboard.runbooks.assess_repo", _assessment)

        result = run_runbook(
            runbook_plan=plan,
            result_out=result_out,
            command_trace_out=trace_out,
        )

        assert result["status"] == "inconclusive"
        statuses = {s["step_id"]: s["status"] for s in result["steps"]}
        assert statuses["step-check-is-git-repo"] == "inconclusive"
        assert statuses["step-check-worktree-clean"] == "inconclusive"

    def test_repo_sync_gate_merges_source_refs_from_plan_observation_assessment(
        self, tmp_path, monkeypatch
    ):
        plan = _valid_runbook_plan(repo_path=str(ROOT))
        plan["source_refs"] = ["plan.ref"]
        result_out = str(tmp_path / "result.json")
        trace_out = str(tmp_path / "trace.jsonl")

        monkeypatch.setattr(
            "steuerboard.runbooks.observe_repo",
            lambda _path: {
                "observed_state": {
                    "is_git_repo": True,
                    "dirty": False,
                    "current_branch": "main",
                    "default_branch_candidate": "main",
                },
                "source_refs": ["obs.ref", "plan.ref", "", 123, None, True, [], {}],
            },
        )
        monkeypatch.setattr(
            "steuerboard.runbooks.assess_repo",
            lambda _path: {"decision_state": "assessment_clear", "source_refs": ["assess.ref", "obs.ref"]},
        )

        result = run_runbook(
            runbook_plan=plan,
            result_out=result_out,
            command_trace_out=trace_out,
        )

        assert result["source_refs"] == ["plan.ref", "obs.ref", "assess.ref"]
        assert "" not in result["source_refs"]
        assert " " not in result["source_refs"]
        assert 123 not in result["source_refs"]

    def test_cli_error_sentinel_schema_valid_for_invalid_runbook_kind(self, tmp_path, capsys):
        plan = _valid_runbook_plan(repo_path=str(ROOT))
        plan["runbook_kind"] = "dns-gate"
        plan_path = tmp_path / "plan.json"
        plan_path.write_text(json.dumps(plan), encoding="utf-8")
        result_out = tmp_path / "result.json"
        trace_out = tmp_path / "trace.jsonl"

        exit_code = main(
            [
                "runbook",
                "run",
                str(plan_path),
                "--result-out",
                str(result_out),
                "--command-trace-out",
                str(trace_out),
                "--json",
            ]
        )

        assert exit_code == 1
        assert not result_out.exists()
        assert not trace_out.exists()

        payload = json.loads(capsys.readouterr().out)
        validate_instance(payload, _runbook_result_schema(), Path("stdout"))
        assert payload["status"] == "blocked"
        assert payload["runbook_kind"] == "repo-sync-gate"
        assert "dns-gate" in payload["short_assessment"]
        assert "schema-compatibility fallback" in payload["short_assessment"]

    def test_cli_error_sentinel_normalizes_non_string_refs(self, tmp_path, capsys):
        plan = _valid_runbook_plan(repo_path=str(ROOT))
        plan["runbook_id"] = 123
        plan["repo_path"] = 456
        plan_path = tmp_path / "plan.json"
        plan_path.write_text(json.dumps(plan), encoding="utf-8")
        result_out = tmp_path / "result.json"
        trace_out = tmp_path / "trace.jsonl"

        exit_code = main(
            [
                "runbook",
                "run",
                str(plan_path),
                "--result-out",
                str(result_out),
                "--command-trace-out",
                str(trace_out),
                "--json",
            ]
        )

        assert exit_code == 1
        assert not result_out.exists()
        assert not trace_out.exists()

        payload = json.loads(capsys.readouterr().out)
        validate_instance(payload, _runbook_result_schema(), Path("stdout"))
        assert payload["status"] == "blocked"
        assert payload["runbook_ref"] == "unknown"
        assert payload["repo_path"] == "unknown"
        assert isinstance(payload["short_assessment"], str)
        assert "schema-compatibility fallback" in payload["short_assessment"]

    def test_cli_error_sentinel_normalizes_non_dict_json_array(self, tmp_path, capsys):
        plan_path = tmp_path / "plan.json"
        plan_path.write_text(json.dumps([]), encoding="utf-8")
        result_out = tmp_path / "result.json"
        trace_out = tmp_path / "trace.jsonl"

        exit_code = main(
            [
                "runbook",
                "run",
                str(plan_path),
                "--result-out",
                str(result_out),
                "--command-trace-out",
                str(trace_out),
                "--json",
            ]
        )

        assert exit_code == 1
        assert not result_out.exists()
        assert not trace_out.exists()

        payload = json.loads(capsys.readouterr().out)
        validate_instance(payload, _runbook_result_schema(), Path("stdout"))
        assert payload["status"] == "blocked"
        assert payload["runbook_ref"] == "unknown"
        assert payload["repo_path"] == "unknown"
        assert payload["runbook_kind"] == "repo-sync-gate"
        assert isinstance(payload["short_assessment"], str)
        assert "schema-compatibility fallback" in payload["short_assessment"]

    def test_cli_error_sentinel_normalizes_non_dict_json_string(self, tmp_path, capsys):
        plan_path = tmp_path / "plan.json"
        plan_path.write_text(json.dumps("not-an-object"), encoding="utf-8")
        result_out = tmp_path / "result.json"
        trace_out = tmp_path / "trace.jsonl"

        exit_code = main(
            [
                "runbook",
                "run",
                str(plan_path),
                "--result-out",
                str(result_out),
                "--command-trace-out",
                str(trace_out),
                "--json",
            ]
        )

        assert exit_code == 1
        assert not result_out.exists()
        assert not trace_out.exists()

        payload = json.loads(capsys.readouterr().out)
        validate_instance(payload, _runbook_result_schema(), Path("stdout"))
        assert payload["status"] == "blocked"
        assert payload["runbook_ref"] == "unknown"
        assert payload["repo_path"] == "unknown"
        assert payload["runbook_kind"] == "repo-sync-gate"
        assert isinstance(payload["short_assessment"], str)
        assert "schema-compatibility fallback" in payload["short_assessment"]


# ---------------------------------------------------------------------------
# C. Output safety
# ---------------------------------------------------------------------------

class TestOutputSafety:
    def test_rejects_existing_result_out(self, tmp_path):
        existing = tmp_path / "existing-result.json"
        existing.write_text("{}")
        plan = _valid_runbook_plan(repo_path=str(ROOT))

        with pytest.raises(ValueError, match="must not already exist"):
            run_runbook(
                runbook_plan=plan,
                result_out=str(existing),
                command_trace_out=str(tmp_path / "trace.jsonl"),
            )

    def test_rejects_existing_command_trace_out(self, tmp_path):
        existing = tmp_path / "existing-trace.jsonl"
        existing.write_text("{}\n")
        plan = _valid_runbook_plan(repo_path=str(ROOT))

        with pytest.raises(ValueError, match="must not already exist"):
            run_runbook(
                runbook_plan=plan,
                result_out=str(tmp_path / "result.json"),
                command_trace_out=str(existing),
            )

    def test_rejects_same_result_and_trace_path(self, tmp_path):
        same_path = str(tmp_path / "output.json")
        plan = _valid_runbook_plan(repo_path=str(ROOT))

        with pytest.raises(ValueError):
            run_runbook(
                runbook_plan=plan,
                result_out=same_path,
                command_trace_out=same_path,
            )

    def test_no_partial_outputs_on_precondition_failure(self, tmp_path):
        """If precondition fails, no output files are written."""
        result_out = tmp_path / "result.json"
        trace_out = tmp_path / "trace.jsonl"

        # Use an invalid plan (wrong runbook_kind)
        invalid_plan = _valid_runbook_plan()
        invalid_plan["runbook_kind"] = "dns-gate"  # unsupported kind

        with pytest.raises(ValueError):
            run_runbook(
                runbook_plan=invalid_plan,
                result_out=str(result_out),
                command_trace_out=str(trace_out),
            )

        assert not result_out.exists(), "result.json must NOT be written on precondition failure"
        assert not trace_out.exists(), "trace.jsonl must NOT be written on precondition failure"

    def test_no_partial_outputs_on_mode_precondition_failure(self, tmp_path):
        """If mode is wrong, no output files are written."""
        result_out = tmp_path / "result.json"
        trace_out = tmp_path / "trace.jsonl"

        invalid_plan = _valid_runbook_plan()
        invalid_plan["mode"] = "mutating"

        with pytest.raises(ValueError):
            run_runbook(
                runbook_plan=invalid_plan,
                result_out=str(result_out),
                command_trace_out=str(trace_out),
            )

        assert not result_out.exists()
        assert not trace_out.exists()

    def test_rejects_result_out_inside_repo_worktree(self, tmp_path):
        plan = _valid_runbook_plan(repo_path=str(ROOT))
        result_out = ROOT / "result-inside-worktree.json"
        trace_out = tmp_path / "trace.jsonl"

        with pytest.raises(ValueError, match="outside repository worktree"):
            run_runbook(
                runbook_plan=plan,
                result_out=str(result_out),
                command_trace_out=str(trace_out),
            )

        assert not result_out.exists()
        assert not trace_out.exists()

    def test_rejects_command_trace_out_inside_repo_worktree(self, tmp_path):
        plan = _valid_runbook_plan(repo_path=str(ROOT))
        result_out = tmp_path / "result.json"
        trace_out = ROOT / "trace-inside-worktree.jsonl"

        with pytest.raises(ValueError, match="outside repository worktree"):
            run_runbook(
                runbook_plan=plan,
                result_out=str(result_out),
                command_trace_out=str(trace_out),
            )

        assert not result_out.exists()
        assert not trace_out.exists()

    def test_no_partial_outputs_on_second_replace_failure(self, tmp_path, monkeypatch):
        """If os.replace succeeds for trace but fails for result, neither file exists.

        This verifies the rollback logic introduced for Fix 2: after the first
        os.replace commits the trace file, a failure on the second os.replace
        must clean up the already-committed trace file too.
        """
        import steuerboard.runbooks as _runbooks_mod

        original_replace = _runbooks_mod.os.replace
        call_count = [0]

        def _failing_replace(src, dst):
            call_count[0] += 1
            if call_count[0] == 1:
                # First call (trace): delegate to real os.replace
                original_replace(src, dst)
            else:
                # Second call (result): simulate failure
                raise OSError("simulated failure on second replace")

        monkeypatch.setattr(_runbooks_mod.os, "replace", _failing_replace)

        plan = _valid_runbook_plan(repo_path=str(ROOT))
        result_out = tmp_path / "result.json"
        trace_out = tmp_path / "trace.jsonl"

        with pytest.raises(OSError):
            run_runbook(
                runbook_plan=plan,
                result_out=str(result_out),
                command_trace_out=str(trace_out),
            )

        assert not result_out.exists(), (
            "result.json must NOT exist after second os.replace failure"
        )
        assert not trace_out.exists(), (
            "trace.jsonl must NOT exist after second os.replace failure — "
            "already-committed target must be rolled back"
        )

    def test_result_evidence_paths_contains_trace(self, tmp_path):
        """The written result JSON must contain the command_trace_out path in evidence_paths."""
        plan = _valid_runbook_plan(repo_path=str(ROOT))
        result_out = str(tmp_path / "result.json")
        trace_out = str(tmp_path / "trace.jsonl")
        # _require_output_path resolves the path; use the same resolution for comparison.
        resolved_trace_out = str(Path(trace_out).expanduser().resolve())

        result = run_runbook(
            runbook_plan=plan,
            result_out=result_out,
            command_trace_out=trace_out,
        )

        assert resolved_trace_out in result["evidence_paths"], (
            f"command_trace_out {resolved_trace_out!r} must appear in evidence_paths; "
            f"got {result['evidence_paths']!r}"
        )

        # Also verify the written JSON matches
        written = load_json(Path(result_out))
        assert resolved_trace_out in written["evidence_paths"]

    def test_invalid_generated_artifact_writes_nothing(self, tmp_path, monkeypatch):
        """If the generated result dict violates the schema, neither output file is written."""
        import steuerboard.runbooks as _runbooks_mod

        original_build = _runbooks_mod._build_short_assessment

        def _inject_extra_field(*args, **kwargs):
            # Return a string (valid short_assessment), but patch the result dict
            # by monkeypatching _result_id to force an extra field into the result later.
            return original_build(*args, **kwargs)

        # We inject an invalid field into the result dict by patching _result_id
        # to return a value, then patching the result construction path. The
        # cleanest approach: monkeypatch _validate_result to simulate a validation
        # error, which is what would happen if additionalProperties:false fired.
        def _always_fail(result):
            raise ValueError("schema validation error: extra_field is not allowed")

        monkeypatch.setattr(_runbooks_mod, "_validate_result", _always_fail)

        plan = _valid_runbook_plan(repo_path=str(ROOT))
        result_out = tmp_path / "result.json"
        trace_out = tmp_path / "trace.jsonl"

        with pytest.raises(ValueError):
            run_runbook(
                runbook_plan=plan,
                result_out=str(result_out),
                command_trace_out=str(trace_out),
            )

        assert not result_out.exists(), (
            "result.json must NOT be written when result schema validation fails"
        )
        assert not trace_out.exists(), (
            "trace.jsonl must NOT be written when result schema validation fails"
        )


# ---------------------------------------------------------------------------
# D. No mutation surface
# ---------------------------------------------------------------------------

class TestNoMutationSurface:
    """Inspect the runbooks.py source to verify no forbidden constructs appear
    in non-comment, non-string-literal runtime code paths.

    Strategy: use AST inspection to find actual Call nodes and Name/Attr references
    rather than simple text search, which would incorrectly flag doc strings or
    comments describing what IS forbidden.
    """

    @pytest.fixture(scope="class")
    def runbooks_source(self) -> str:
        runbooks_path = ROOT / "steuerboard" / "runbooks.py"
        return runbooks_path.read_text(encoding="utf-8")

    @pytest.fixture(scope="class")
    def runbooks_ast(self, runbooks_source) -> ast.Module:
        return ast.parse(runbooks_source)

    def _extract_string_literals(self, tree: ast.Module) -> set[str]:
        """Collect all string literal values from the AST."""
        result = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                result.add(node.value)
        return result

    def _extract_call_func_names(self, tree: ast.Module) -> list[str]:
        """Collect all called function/method names from the AST."""
        names = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    names.append(node.func.id)
                elif isinstance(node.func, ast.Attribute):
                    names.append(node.func.attr)
        return names

    def test_runbooks_module_does_not_import_stage_d_executors(self, runbooks_ast):
        """runbooks.py must not import run_git_pull_ff_only or run_switch_main."""
        forbidden_imports = {"run_git_pull_ff_only", "run_switch_main"}
        for node in ast.walk(runbooks_ast):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                if isinstance(node, ast.ImportFrom):
                    for alias in node.names:
                        assert alias.name not in forbidden_imports, (
                            f"runbooks.py imports forbidden Stage-D executor {alias.name!r}"
                        )
                else:
                    for alias in node.names:
                        assert alias.name not in forbidden_imports, (
                            f"runbooks.py imports forbidden Stage-D executor {alias.name!r}"
                        )

    def test_runbooks_module_contains_no_shell_true(self, runbooks_source, runbooks_ast):
        """runbooks.py must not contain shell=True in any call argument."""
        for node in ast.walk(runbooks_ast):
            if isinstance(node, ast.Call):
                for keyword in node.keywords:
                    if keyword.arg == "shell":
                        # Check if the value is True
                        if isinstance(keyword.value, ast.Constant) and keyword.value.value is True:
                            pytest.fail(
                                "runbooks.py contains shell=True in a function call"
                            )

    def test_runbooks_module_contains_no_forbidden_git_verbs(self, runbooks_ast):
        """runbooks.py must not contain forbidden git verb string literals as call arguments.

        We check string literals that appear as elements of list/tuple arguments to
        subprocess.run or similar. We specifically check that these exact forbidden
        command strings do not appear as standalone string constants in the AST
        outside of comment or docstring context.

        The forbidden verbs are: git switch, git pull, git fetch, git reset,
        git clean, git merge, git rebase, git push.
        """
        FORBIDDEN_GIT_VERBS = {
            "switch", "pull", "fetch", "reset", "clean", "merge", "rebase", "push"
        }
        # Walk through all list/tuple literals that might be subprocess argv
        for node in ast.walk(runbooks_ast):
            if isinstance(node, (ast.List, ast.Tuple)):
                string_elements = [
                    elt.value for elt in node.elts
                    if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
                ]
                # Check if "git" is in the list and any forbidden verb follows
                if "git" in string_elements:
                    for verb in FORBIDDEN_GIT_VERBS:
                        assert verb not in string_elements, (
                            f"runbooks.py has a git argv list containing forbidden verb {verb!r}"
                        )

    def test_runbook_cli_surface_is_read_only(self):
        """runbook run must be classified read_only in cli_surface.json."""
        surface_path = ROOT / "scripts" / "docmeta" / "cli_surface.json"
        surface = load_json(surface_path)
        assert "runbook run" in surface["commands"], (
            "runbook run is missing from cli_surface.json commands"
        )
        assert surface["commands"]["runbook run"] == "read_only", (
            f"runbook run is classified {surface['commands']['runbook run']!r}, expected read_only"
        )

    def test_mutating_stage_d_still_exactly_two(self):
        """Stage-D mutating executors must remain exactly: run-git-pull-ff-only and run-switch-main."""
        surface_path = ROOT / "scripts" / "docmeta" / "cli_surface.json"
        surface = load_json(surface_path)
        mutating = [
            cmd for cmd, cls in surface["commands"].items()
            if cls == "mutating_stage_d"
        ]
        assert sorted(mutating) == ["action run-git-pull-ff-only", "action run-switch-main"], (
            f"Stage-D mutating executors must be exactly run-git-pull-ff-only and run-switch-main, "
            f"got: {sorted(mutating)!r}"
        )


# ---------------------------------------------------------------------------
# Extra unit tests for step check functions
# ---------------------------------------------------------------------------

class TestStepCheckFunctions:
    def test_check_is_git_repo_inconclusive_when_missing(self):
        status, _ = check_is_git_repo({"observed_state": {}})
        assert status == "inconclusive"

    def test_check_is_git_repo_inconclusive_when_none(self):
        status, _ = check_is_git_repo({"observed_state": {"is_git_repo": None}})
        assert status == "inconclusive"

    def test_check_is_git_repo_inconclusive_when_non_bool(self):
        status, _ = check_is_git_repo({"observed_state": {"is_git_repo": "yes"}})
        assert status == "inconclusive"

    def test_check_is_git_repo_passes_for_git_repo(self):
        obs = {"observed_state": {"is_git_repo": True}}
        status, _ = check_is_git_repo(obs)
        assert status == "passed"

    def test_check_is_git_repo_blocks_for_non_git(self):
        obs = {"observed_state": {"is_git_repo": False}}
        status, _ = check_is_git_repo(obs)
        assert status == "blocked"

    def test_check_worktree_clean_passes_for_clean(self):
        obs = {"observed_state": {"is_git_repo": True, "dirty": False}}
        status, _ = check_worktree_clean(obs)
        assert status == "passed"

    def test_check_worktree_clean_inconclusive_when_missing(self):
        status, _ = check_worktree_clean({"observed_state": {"is_git_repo": True}})
        assert status == "inconclusive"

    def test_check_worktree_clean_inconclusive_when_none(self):
        status, _ = check_worktree_clean({"observed_state": {"dirty": None}})
        assert status == "inconclusive"

    def test_check_worktree_clean_inconclusive_when_non_bool(self):
        status, _ = check_worktree_clean({"observed_state": {"dirty": "false"}})
        assert status == "inconclusive"

    def test_check_worktree_clean_blocks_for_dirty(self):
        obs = {"observed_state": {"is_git_repo": True, "dirty": True}}
        status, _ = check_worktree_clean(obs)
        assert status == "blocked"

    def test_check_not_detached_head_passes_for_branch(self):
        obs = {"observed_state": {"is_git_repo": True, "current_branch": "main"}}
        status, _ = check_not_detached_head(obs)
        assert status == "passed"

    def test_check_not_detached_head_blocks_for_detached(self):
        obs = {"observed_state": {"is_git_repo": True, "current_branch": None}}
        status, _ = check_not_detached_head(obs)
        assert status == "blocked"

    def test_check_not_detached_head_inconclusive_when_branch_missing(self):
        obs = {"observed_state": {"is_git_repo": True}}
        status, _ = check_not_detached_head(obs)
        assert status == "inconclusive"

    def test_check_on_default_branch_passes_when_on_default(self):
        obs = {
            "observed_state": {
                "is_git_repo": True,
                "current_branch": "main",
                "default_branch_candidate": "main",
            }
        }
        status, _ = check_on_default_branch(obs)
        assert status == "passed"

    def test_check_on_default_branch_blocks_when_on_feature(self):
        obs = {
            "observed_state": {
                "is_git_repo": True,
                "current_branch": "feature",
                "default_branch_candidate": "main",
            }
        }
        status, _ = check_on_default_branch(obs)
        assert status == "blocked"

    def test_check_on_default_branch_inconclusive_when_unknown(self):
        obs = {
            "observed_state": {
                "is_git_repo": True,
                "current_branch": "main",
                "default_branch_candidate": None,
            }
        }
        status, _ = check_on_default_branch(obs)
        assert status == "inconclusive"

    def test_check_decision_state_passed_for_clear(self):
        assessment = {"decision_state": "assessment_clear"}
        status, _ = check_decision_state(assessment)
        assert status == "passed"

    def test_check_decision_state_inconclusive_for_evidence_missing(self):
        assessment = {"decision_state": "evidence_missing"}
        status, _ = check_decision_state(assessment)
        assert status == "inconclusive"

    def test_check_decision_state_blocked_for_action_blocked(self):
        assessment = {"decision_state": "action_blocked"}
        status, _ = check_decision_state(assessment)
        assert status == "blocked"

    def test_check_decision_state_does_not_soften_blocked(self):
        """blocked must remain blocked, never softened to passed or inconclusive."""
        assessment = {"decision_state": "action_blocked"}
        status, _ = check_decision_state(assessment)
        assert status not in ("passed", "inconclusive"), (
            f"action_blocked must not be softened; got {status!r}"
        )
