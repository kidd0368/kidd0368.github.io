#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Rebuild lightweight indexes for the Industry Intelligence Hub.

Scans data/records/**/*.json, performs deterministic structural validation,
then writes data/records.json, data/changelog.json, and data/manifest.json.
No third-party packages are required.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RECORD_DIR = ROOT / "data" / "records"
OUT_RECORDS = ROOT / "data" / "records.json"
OUT_CHANGELOG = ROOT / "data" / "changelog.json"
OUT_MANIFEST = ROOT / "data" / "manifest.json"

REQUIRED_TOP = [
    "schema_version", "task_id", "created_at", "updated_at", "analysis_type",
    "industry_id", "taxonomy_version_used", "source", "narrative", "findings",
    "financials", "operating_assumptions", "segment_estimates", "metric_claims",
    "relationships", "mentioned_entities", "evidence", "derived_metrics", "validation"
]
REQUIRED_ARRAYS = [
    "findings", "financials", "operating_assumptions", "segment_estimates",
    "metric_claims", "relationships", "mentioned_entities", "evidence", "derived_metrics"
]


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def validate_record(data: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["record root must be an object"]
    for key in REQUIRED_TOP:
        if key not in data:
            errors.append(f"missing required key: {key}")
    if data.get("schema_version") != "1.0.0":
        errors.append("schema_version must be 1.0.0")
    task_id = data.get("task_id")
    if not isinstance(task_id, str) or not task_id.startswith("TASK-"):
        errors.append("task_id must start with TASK-")
    for key in REQUIRED_ARRAYS:
        if key in data and not isinstance(data[key], list):
            errors.append(f"{key} must be an array")
    source = data.get("source")
    if not isinstance(source, dict):
        errors.append("source must be an object")
    else:
        for key in ("source_id", "source_type", "title", "received_date", "files"):
            if key not in source:
                errors.append(f"source missing key: {key}")
    narrative = data.get("narrative")
    if not isinstance(narrative, dict):
        errors.append("narrative must be an object")
    else:
        for key in ("executive_summary", "expanded_report"):
            if key not in narrative:
                errors.append(f"narrative missing key: {key}")
    validation = data.get("validation")
    if not isinstance(validation, dict):
        errors.append("validation must be an object")
    return errors


def record_summary(data: dict[str, Any], rel_path: str) -> dict[str, Any]:
    entities = []
    seen = set()
    for item in data.get("mentioned_entities", []):
        if not isinstance(item, dict):
            continue
        entity_id = item.get("entity_id")
        if entity_id and entity_id not in seen:
            seen.add(entity_id)
            entities.append({
                "entity_id": entity_id,
                "name": item.get("name"),
                "ticker": item.get("ticker"),
                "reason_mentioned": item.get("reason_mentioned")
            })
    narrative = data.get("narrative") or {}
    source = data.get("source") or {}
    return {
        "task_id": data.get("task_id"),
        "title": data.get("title") or source.get("title") or data.get("task_id"),
        "analysis_type": data.get("analysis_type"),
        "industry_id": data.get("industry_id"),
        "taxonomy_version_used": data.get("taxonomy_version_used"),
        "record_status": data.get("record_status", "accepted"),
        "created_at": data.get("created_at"),
        "updated_at": data.get("updated_at"),
        "source": {
            "source_id": source.get("source_id"),
            "source_type": source.get("source_type"),
            "title": source.get("title"),
            "publisher": source.get("publisher"),
            "published_date": source.get("published_date"),
            "received_date": source.get("received_date")
        },
        "executive_summary": narrative.get("executive_summary", ""),
        "entities": entities,
        "finding_count": len(data.get("findings", [])),
        "metric_count": len(data.get("metric_claims", [])) + len(data.get("financials", [])),
        "metric_ids": sorted({
            str(item.get("metric_id"))
            for item in [*data.get("metric_claims", []), *data.get("financials", [])]
            if isinstance(item, dict) and item.get("metric_id")
        }),
        "relationship_count": len(data.get("relationships", [])),
        "evidence_count": len(data.get("evidence", [])),
        "conflicts_found": (data.get("validation") or {}).get("conflicts_found", 0),
        "record_path": rel_path
    }


def main() -> int:
    generated_at = now_iso()
    valid: list[dict[str, Any]] = []
    invalid: list[dict[str, Any]] = []
    taxonomy_versions: dict[str, str] = {}

    files = sorted(RECORD_DIR.rglob("*.json")) if RECORD_DIR.exists() else []
    for path in files:
        rel = path.relative_to(ROOT).as_posix()
        try:
            data = load_json(path)
        except Exception as exc:
            invalid.append({"path": rel, "errors": [f"invalid JSON: {exc}"]})
            continue
        errors = validate_record(data)
        if errors:
            invalid.append({"path": rel, "task_id": data.get("task_id") if isinstance(data, dict) else None, "errors": errors})
            continue
        summary = record_summary(data, rel)
        valid.append(summary)
        taxonomy_versions[data["industry_id"]] = data["taxonomy_version_used"]

    valid.sort(key=lambda x: (x.get("updated_at") or "", x.get("task_id") or ""), reverse=True)
    latest = valid[0].get("updated_at") if valid else None

    records_doc = {
        "schema_version": "1.0.0",
        "generated_at": generated_at,
        "valid_record_count": len(valid),
        "invalid_record_count": len(invalid),
        "records": valid
    }
    changelog_doc = {
        "schema_version": "1.0.0",
        "generated_at": generated_at,
        "entries": [
            {
                "task_id": item.get("task_id"),
                "updated_at": item.get("updated_at"),
                "record_status": item.get("record_status"),
                "record_path": item.get("record_path"),
                "title": item.get("title"),
                "metric_count": item.get("metric_count"),
                "conflicts_found": item.get("conflicts_found")
            }
            for item in valid
        ]
    }
    manifest_doc = {
        "schema_version": "1.0.0",
        "generated_at": generated_at,
        "status": "ready" if not invalid else "review_required",
        "record_count": len(valid),
        "invalid_record_count": len(invalid),
        "latest_record_at": latest,
        "taxonomy_versions": taxonomy_versions,
        "validation_errors": invalid
    }

    for path, payload in (
        (OUT_RECORDS, records_doc),
        (OUT_CHANGELOG, changelog_doc),
        (OUT_MANIFEST, manifest_doc),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"valid={len(valid)} invalid={len(invalid)}")
    if invalid:
        for item in invalid:
            print(f"INVALID {item['path']}: {'; '.join(item['errors'])}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
