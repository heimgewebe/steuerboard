from __future__ import annotations

import hashlib
from typing import Any

from .assessment_rules import attach_assessment_provenance

_STATUS_MEANINGS: dict[str, tuple[str, str]] = {
    "not_git_repo": (
        "Path is not a Git repository; assessment cannot proceed as a repository assessment.",
        "blocks_action",
    ),
    "scope_backup": (
        "Repository path is classified as backup scope.",
        "blocks_action",
    ),
    "scope_gdrive": (
        "Repository path is classified as gdrive scope.",
        "blocks_action",
    ),
    "scope_excluded": (
        "Repository path is classified as excluded scope.",
        "blocks_action",
    ),
    "scope_unknown": (
        "Repository path scope is unknown from available local scope evidence.",
        "blocks_action",
    ),
    "scope_shadow": (
        "Repository path is classified as shadow scope (defined for duplicate-aware surfaces; single-path assess repo does not emit this status in this slice).",
        "blocks_action",
    ),
    "dirty_worktree": (
        "Working tree contains uncommitted changes.",
        "blocks_action",
    ),
    "detached_head": (
        "HEAD is detached and not on a named branch.",
        "blocks_action",
    ),
    "default_branch_unknown": (
        "Default branch candidate is not derivable from observed evidence.",
        "requires_evidence",
    ),
    "non_default_branch": (
        "Current branch differs from observed default branch candidate; remote branch lifecycle remains not observed in this read-only assessment.",
        "requires_evidence",
    ),
    "clean_default_current": (
        "Current branch matches observed default branch candidate and worktree is clean; default_branch_source remains unverified.",
        "assessment_clear",
    ),
}


def _as_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("Expected list of strings")
    for item in value:
        if not isinstance(item, str):
            raise ValueError("Expected list of strings")
    return value


def _summary_for(assessment_id: str, derived_status: list[str]) -> str:
    joined = ", ".join(derived_status)
    return (
        f"Assessment {assessment_id} is interpreted with status set [{joined}]. "
        "This explanation is read-only interpretation and does not authorise or plan actions."
    )


def _build_explanation_id(assessment_id: str, derived_status: list[str]) -> str:
    material = assessment_id + "|" + "|".join(derived_status)
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]
    return f"assess-expl-{digest}"


def explain_assessment(assessment: dict[str, Any]) -> dict[str, Any]:
    """Explain a repo-assessment.v1-like object without adding action advice."""
    if not isinstance(assessment, dict):
        raise ValueError("assessment must be an object")

    assessment_id = assessment.get("assessment_id")
    if not isinstance(assessment_id, str) or not assessment_id:
        raise ValueError("assessment_id must be a non-empty string")

    derived_status = assessment.get("derived_status")
    if not isinstance(derived_status, list) or not derived_status:
        raise ValueError("derived_status must be a non-empty list")
    for status in derived_status:
        if not isinstance(status, str) or not status:
            raise ValueError("derived_status must contain non-empty strings")

    source_refs = _as_string_list(assessment.get("source_refs"))
    missing_evidence = _as_string_list(assessment.get("missing_evidence"))

    observation_ref = assessment.get("observation_ref")
    evidence_refs = list(source_refs)
    if isinstance(observation_ref, str) and observation_ref:
        evidence_refs = [observation_ref, *source_refs]

    status_explanations: list[dict[str, Any]] = []
    for status in derived_status:
        mapping = _STATUS_MEANINGS.get(status)
        if mapping is None:
            raise ValueError(f"Unsupported derived_status: {status!r}")
        meaning, decision_effect = mapping
        provenance = attach_assessment_provenance([status], source_refs=source_refs)
        status_explanations.append(
            {
                "status": status,
                "meaning": meaning,
                "decision_effect": decision_effect,
                "evidence_refs": evidence_refs,
                "rule_refs": provenance["rule_refs"],
                "freshness_refs": provenance["freshness_refs"],
                "falsification_refs": provenance["falsification_refs"],
                "missing_evidence": missing_evidence,
            }
        )

    return {
        "schema_version": "repo-assessment-explanation.v1",
        "explanation_id": _build_explanation_id(assessment_id, derived_status),
        "assessment_ref": assessment_id,
        "summary": _summary_for(assessment_id, derived_status),
        "status_explanations": status_explanations,
        "boundary": {
            "does_not_authorise_actions": True,
            "does_not_mutate": True,
            "does_not_plan_actions": True,
        },
    }
