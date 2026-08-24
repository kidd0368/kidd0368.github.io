#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Normalize review semantics for Industry Intelligence Hub records.

The system must not turn ordinary source metadata differences into user work.
A record is review_required only when at least one open review item explicitly
requires a user decision or additional user-supplied evidence.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

HUB_ROOT = Path(__file__).resolve().parents[1]
RECORD_DIR = HUB_ROOT / "data" / "records"
VERSION = "1.0.0"

IMPORTANT_SEVERITIES = {"important", "warning", "critical"}


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"record root must be object: {path}")
    return data


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def text_of(item: dict[str, Any], *keys: str) -> str:
    return " ".join(str(item.get(key) or "") for key in keys).strip()


def slug(value: str, fallback: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "-", value).strip("-").upper()
    return cleaned[:72] or fallback


def infer_note_category(item: dict[str, Any]) -> tuple[str, str]:
    kind = str(item.get("type") or item.get("category") or "").lower()
    combined = text_of(item, "topic", "title", "description", "source_a", "source_b", "resolution")

    if "檔名" in combined or kind in {"source_identity", "source_metadata"} or "來源身分" in combined:
        return "source_metadata", "info"
    if kind in {"bundle_scope", "source_scope"} or "資料包" in combined or "附件範圍" in combined:
        return "source_scope", "info"
    if kind in {"date", "source_date"} or "日期" in combined:
        return "source_date", "info"
    if kind in {"period", "internal_inconsistency", "numeric_inconsistency"}:
        return "internal_inconsistency", "important"
    if "同一報告" in combined or ("EPS" in combined and ("FY26" in combined or "FY27" in combined)):
        return "internal_inconsistency", "important"
    if "訂單約束力" in combined or "backlog" in combined.lower():
        return "interpretation_scope", "info"
    if "時程精度" in combined or "更多客戶" in combined or "適用範圍" in combined:
        return "scope_qualification", "info"
    return "interpretation_note", "info"


def legacy_conflict_to_note(item: dict[str, Any], index: int) -> dict[str, Any]:
    category, severity = infer_note_category(item)
    conflict_id = str(item.get("conflict_id") or item.get("id") or f"LEGACY-{index:03d}")
    title = str(item.get("topic") or item.get("title") or item.get("description") or conflict_id)
    description = str(item.get("description") or "")
    if not description:
        parts = [str(item.get("source_a") or ""), str(item.get("source_b") or "")]
        description = "；".join(part for part in parts if part)
    resolution = str(item.get("resolution") or item.get("recommended_resolution") or "")

    return {
        "note_id": f"NOTE-{slug(conflict_id, f'LEGACY-{index:03d}')}",
        "category": category,
        "severity": severity,
        "title": title,
        "description": description,
        "resolution": resolution or None,
        "requires_user_action": False,
        "source_ids": item.get("source_ids") or [],
        "evidence_ids": item.get("evidence_ids") or [],
        "affected_claim_ids": item.get("affected_claim_ids") or [],
        "legacy_conflict_id": conflict_id,
    }


def legacy_conflict_to_review(item: dict[str, Any], index: int) -> dict[str, Any]:
    conflict_id = str(item.get("conflict_id") or item.get("id") or f"LEGACY-{index:03d}")
    question = str(item.get("question") or item.get("description") or item.get("topic") or conflict_id)
    return {
        "review_id": f"REVIEW-{slug(conflict_id, f'LEGACY-{index:03d}')}",
        "category": str(item.get("type") or item.get("category") or "substantive_conflict"),
        "title": str(item.get("topic") or item.get("title") or question),
        "question": question,
        "why_user_input_needed": str(item.get("why_user_input_needed") or "缺乏可防禦的預設判定，需由使用者選擇。"),
        "options": item.get("options") or [],
        "recommended_option": item.get("recommended_option"),
        "status": str(item.get("status") or "open"),
        "requires_user_action": True,
        "source_ids": item.get("source_ids") or [],
        "evidence_ids": item.get("evidence_ids") or [],
        "affected_claim_ids": item.get("affected_claim_ids") or [],
        "legacy_conflict_id": conflict_id,
    }


def dedupe(items: list[dict[str, Any]], id_key: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        key = str(item.get(id_key) or item.get("title") or item.get("description") or json.dumps(item, sort_keys=True, ensure_ascii=False))
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def apply_known_content_repairs(record: dict[str, Any]) -> None:
    """Repair wording that previously mislabelled normal metadata as conflicts."""
    task_id = record.get("task_id")

    if task_id == "TASK-20260823-235332-LK3H4":
        source = record.get("source") or {}
        for sub in source.get("sub_sources") or []:
            if sub.get("source_resolution_status") == "resolved_with_filename_conflict":
                sub["source_resolution_status"] = "resolved_from_document_body"
        scope = source.get("source_scope_resolution") or {}
        if "filename_conflict_file_indices" in scope:
            scope["filename_metadata_mismatch_file_indices"] = scope.pop("filename_conflict_file_indices")

        for claim in record.get("metric_claims") or []:
            if claim.get("claim_id") == "CLM-TFC-CPO-MP-DATE":
                claim["notes"] = (
                    "NVIDIA官方於2026-05-31宣布Spectrum-X Ethernet Photonics進入量產；"
                    "野村報告另引用2026-08-14，兩個日期分別保留並註明來源，不視為待使用者裁決的衝突。"
                )
        for item in record.get("external_verification_sources") or []:
            if item.get("source_id") == "EXT-NVDA-20260531":
                item["verification_result"] = "supports_CPO_production_and_TFC_role_with_different_source_reference_date"
        for issue in record.get("source_quality_issues") or []:
            if issue.get("issue_id") == "SQ-001":
                issue["severity"] = "info"
                issue["action"] = "公司身分一律以正文、英文公司名與股票代碼判定；檔名僅作追溯。"

        details = record.get("validation_details") or {}
        if "source_identity_conflicts_preserved" in details:
            details["source_metadata_mismatches_preserved"] = details.pop("source_identity_conflicts_preserved")

    if task_id == "TASK-20260824-081915-PMVAY":
        if record.get("analysis_type") == "broker_report":
            record["analysis_type"] = "interview_notes"
        source = record.get("source") or {}
        if source.get("source_type") == "broker_report":
            source["source_type"] = "interview_notes"
        for sub in source.get("sub_sources") or []:
            if sub.get("source_resolution_status") == "unresolved_user_authored_research_note":
                sub["source_resolution_status"] = "resolved_user_authored_research_note"


def normalize_record(record: dict[str, Any]) -> bool:
    before = json.dumps(record, ensure_ascii=False, sort_keys=True)
    apply_known_content_repairs(record)

    existing_notes = [item for item in (record.get("important_notes") or []) if isinstance(item, dict)]
    existing_reviews = [item for item in (record.get("review_items") or []) if isinstance(item, dict)]
    legacy_conflicts = [item for item in (record.get("conflicts") or []) if isinstance(item, dict)]

    notes = list(existing_notes)
    reviews = list(existing_reviews)
    retained_conflicts: list[dict[str, Any]] = []

    for index, item in enumerate(legacy_conflicts, start=1):
        requires_action = item.get("requires_user_action") is True
        if requires_action:
            reviews.append(legacy_conflict_to_review(item, index))
            retained_conflicts.append(item)
        else:
            notes.append(legacy_conflict_to_note(item, index))

    notes = dedupe(notes, "note_id")
    reviews = dedupe(reviews, "review_id")

    open_reviews = [
        item for item in reviews
        if item.get("requires_user_action") is True and str(item.get("status") or "open") not in {"resolved", "closed", "dismissed"}
    ]
    important_count = sum(1 for item in notes if str(item.get("severity") or "info") in IMPORTANT_SEVERITIES)
    source_note_count = sum(
        1 for item in notes
        if str(item.get("category") or "").startswith("source_") or str(item.get("severity") or "info") == "info"
    )

    record["review_semantics_version"] = VERSION
    record["important_notes"] = notes
    record["review_items"] = reviews
    record["conflicts"] = retained_conflicts

    if record.get("record_status") != "rejected":
        record["record_status"] = "review_required" if open_reviews else "accepted"

    validation = record.setdefault("validation", {})
    validation["review_semantics_version"] = VERSION
    validation["user_action_required_count"] = len(open_reviews)
    validation["important_note_count"] = important_count
    validation["source_note_count"] = source_note_count
    validation["conflicts_found"] = len(open_reviews)

    statistics = record.get("statistics")
    if isinstance(statistics, dict):
        statistics["conflict_count"] = len(open_reviews)
        statistics["user_action_required_count"] = len(open_reviews)
        statistics["important_note_count"] = important_count

    after = json.dumps(record, ensure_ascii=False, sort_keys=True)
    return before != after


def main() -> int:
    changed = 0
    scanned = 0
    for path in sorted(RECORD_DIR.rglob("*.json")) if RECORD_DIR.exists() else []:
        scanned += 1
        record = load_json(path)
        if normalize_record(record):
            write_json(path, record)
            changed += 1
            print(f"NORMALIZED {path.relative_to(HUB_ROOT)}")
    print(f"review_semantics_scanned={scanned} changed={changed} version={VERSION}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
