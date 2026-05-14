from __future__ import annotations

from typing import Any

# Keep this list in sync with examples/failure-cases/*.json.
EXISTING_FAILURE_CASE_IDS = {
    "backup_repo_accidentally_used",
    "branch_local_only",
    "branch_remote_deleted",
    "detached_head",
    "dirty_submodule",
    "dirty_worktree",
    "dubious_ownership",
    "duplicate_repo",
    "evidence_contains_secret_like_pattern",
    "feature_branch_merged",
    "feature_branch_unmerged",
    "ff_only_not_possible",
    "foreign_owner_present",
    "gdrive_shadow_repo",
    "missing_upstream",
    "omnipull_skip_unknown_reason",
    "origin_main_stale",
    "remote_missing",
    "remote_unreachable",
    "stale_metarepo",
    "stale_omnipull_log",
    "unknown_default_branch",
    "wrong_remote",
}

ASSESSMENT_PROVENANCE: dict[str, dict[str, list[str]]] = {
    "not_git_repo": {
        "rule_refs": ["assessment.rule.not_git_repo_blocks_action"],
        "falsification_refs": [],
        "freshness_refs": ["freshness.local_git_probe.current_invocation"],
    },
    "scope_shadow": {
        # scope_shadow is currently emitted by inventory/duplicates, not by
        # single-path assess repo. Keep mapping for future duplicate-aware
        # assessment surfaces.
        "rule_refs": ["assessment.rule.scope_shadow_blocks_action"],
        "falsification_refs": ["failure-case.duplicate_repo"],
        "freshness_refs": ["freshness.local_scope_config.current_invocation"],
    },
    "scope_backup": {
        "rule_refs": ["assessment.rule.scope_backup_blocks_action"],
        "falsification_refs": ["failure-case.backup_repo_accidentally_used"],
        "freshness_refs": ["freshness.local_scope_config.current_invocation"],
    },
    "scope_gdrive": {
        "rule_refs": ["assessment.rule.scope_gdrive_blocks_action"],
        "falsification_refs": ["failure-case.gdrive_shadow_repo"],
        "freshness_refs": ["freshness.local_scope_config.current_invocation"],
    },
    "scope_excluded": {
        "rule_refs": ["assessment.rule.scope_excluded_blocks_action"],
        "falsification_refs": [],
        "freshness_refs": ["freshness.local_scope_config.current_invocation"],
    },
    "scope_unknown": {
        "rule_refs": ["assessment.rule.scope_unknown_blocks_action"],
        "falsification_refs": [],
        "freshness_refs": ["freshness.local_scope_config.current_invocation"],
    },
    "dirty_worktree": {
        "rule_refs": ["assessment.rule.dirty_worktree_blocks_action"],
        "falsification_refs": ["failure-case.dirty_worktree"],
        "freshness_refs": ["freshness.local_git_status.current_invocation"],
    },
    "detached_head": {
        "rule_refs": ["assessment.rule.detached_head_blocks_action"],
        "falsification_refs": ["failure-case.detached_head"],
        "freshness_refs": ["freshness.local_git_branch.current_invocation"],
    },
    "default_branch_unknown": {
        "rule_refs": ["assessment.rule.default_branch_unknown_requires_evidence"],
        "falsification_refs": ["failure-case.unknown_default_branch"],
        "freshness_refs": ["freshness.default_branch_candidate.unavailable"],
    },
    "non_default_branch": {
        "rule_refs": ["assessment.rule.non_default_branch_requires_lifecycle_evidence"],
        "falsification_refs": [
            "failure-case.feature_branch_unmerged",
            "failure-case.origin_main_stale",
        ],
        "freshness_refs": [
            "freshness.local_git_branch.current_invocation",
            "freshness.remote_branch_lifecycle.not_observed_no_fetch",
        ],
    },
    "clean_default_current": {
        "rule_refs": [
            "assessment.rule.clean_default_current_is_clear_but_default_source_unverified"
        ],
        "falsification_refs": [],
        "freshness_refs": [
            "freshness.local_git_status.current_invocation",
            "freshness.default_branch_source.unverified",
        ],
    },
}


def _dedupe_keep_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def _validate_falsification_refs(refs: list[str]) -> list[str]:
    for ref in refs:
        prefix = "failure-case."
        if not ref.startswith(prefix):
            raise ValueError(f"Invalid falsification_ref prefix: {ref!r}")
        case_id = ref[len(prefix) :]
        if case_id not in EXISTING_FAILURE_CASE_IDS:
            raise ValueError(f"Unknown falsification_ref: {ref!r}")
    return refs


def attach_assessment_provenance(
    derived_status: list[str],
    source_refs: list[str] | None = None,
) -> dict[str, list[str]]:
    if not derived_status:
        raise ValueError("derived_status must not be empty")

    # When scope_unknown is caused by a missing config file, the config was
    # never read, so freshness_refs must say "unavailable" instead of
    # "current_invocation" — the two would directly contradict each other.
    config_unavailable = (
        source_refs is not None and "local_config.unavailable" in source_refs
    )

    rule_refs: list[str] = []
    freshness_refs: list[str] = []
    falsification_refs: list[str] = []

    for status in derived_status:
        provenance: dict[str, Any] | None = ASSESSMENT_PROVENANCE.get(status)
        if provenance is None:
            raise ValueError(f"No provenance mapping defined for derived_status={status!r}")
        status_rules: list[str] = provenance.get("rule_refs", [])
        if not status_rules:
            raise ValueError(f"No rule_refs defined for derived_status={status!r}")

        rule_refs.extend(status_rules)

        status_freshness: list[str] = list(provenance.get("freshness_refs", []))
        if status == "scope_unknown" and config_unavailable:
            status_freshness = [
                "freshness.local_scope_config.unavailable"
                if ref == "freshness.local_scope_config.current_invocation"
                else ref
                for ref in status_freshness
            ]
        freshness_refs.extend(status_freshness)

        falsification_refs.extend(provenance.get("falsification_refs", []))

    return {
        "rule_refs": _dedupe_keep_order(rule_refs),
        "freshness_refs": _dedupe_keep_order(freshness_refs),
        "falsification_refs": _dedupe_keep_order(
            _validate_falsification_refs(falsification_refs)
        ),
    }
