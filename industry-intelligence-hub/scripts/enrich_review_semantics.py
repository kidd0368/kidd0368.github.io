#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Add actionable review counts and display state to generated IIH indexes."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

HUB_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = HUB_ROOT.parent
RECORDS_INDEX = HUB_ROOT / "data" / "records.json"
CHANGELOG = HUB_ROOT / "data" / "changelog.json"
MANIFEST = HUB_ROOT / "data" / "manifest.json"
VERSION = "1.0.0"


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def full_record_path(indexed_path: str) -> Path:
    normalized = indexed_path.lstrip("/")
    prefix = f"{HUB_ROOT.name}/"
    repo_path = normalized if normalized.startswith(prefix) else f"{prefix}{normalized}"
    return REPO_ROOT / repo_path


def counts(record: dict[str, Any]) -> tuple[int, int, int]:
    validation = record.get("validation") or {}
    action = int(validation.get("user_action_required_count") or 0)
    important = int(validation.get("important_note_count") or 0)
    source_notes = int(validation.get("source_note_count") or 0)
    return action, important, source_notes


def display_state(record: dict[str, Any], action: int, important: int) -> dict[str, str]:
    if record.get("record_status") == "rejected":
        return {"code": "rejected", "label": "拒絕"}
    if action > 0:
        return {"code": "user_action_required", "label": f"待你確認 · {action}"}
    if important > 0:
        return {"code": "completed_with_notes", "label": f"已完成 · {important}項重要註記"}
    return {"code": "completed", "label": "已完成"}


def main() -> int:
    records_doc = load_json(RECORDS_INDEX)
    changelog_doc = load_json(CHANGELOG)
    manifest = load_json(MANIFEST)
    by_task: dict[str, dict[str, Any]] = {}
    action_record_count = 0
    completed_with_notes_count = 0

    for row in records_doc.get("records") or []:
        path = full_record_path(str(row.get("record_path") or ""))
        record = load_json(path)
        action, important, source_notes = counts(record)
        state = display_state(record, action, important)
        row["review_semantics_version"] = VERSION
        row["user_action_required_count"] = action
        row["important_note_count"] = important
        row["source_note_count"] = source_notes
        row["display_status"] = state
        row["conflicts_found"] = action
        row["record_status"] = record.get("record_status", "accepted")
        by_task[str(row.get("task_id") or "")] = {
            "action": action,
            "important": important,
            "source_notes": source_notes,
            "state": state,
            "record_status": row["record_status"],
        }
        if action > 0:
            action_record_count += 1
        elif important > 0:
            completed_with_notes_count += 1

    for entry in changelog_doc.get("entries") or []:
        data = by_task.get(str(entry.get("task_id") or ""))
        if not data:
            continue
        entry["review_semantics_version"] = VERSION
        entry["user_action_required_count"] = data["action"]
        entry["important_note_count"] = data["important"]
        entry["source_note_count"] = data["source_notes"]
        entry["display_status"] = data["state"]
        entry["conflicts_found"] = data["action"]
        entry["record_status"] = data["record_status"]

    manifest["review_semantics_version"] = VERSION
    manifest["user_action_required_record_count"] = action_record_count
    manifest["completed_with_important_notes_count"] = completed_with_notes_count

    write_json(RECORDS_INDEX, records_doc)
    write_json(CHANGELOG, changelog_doc)
    write_json(MANIFEST, manifest)
    print(
        f"review_semantics_indexed={len(by_task)} "
        f"user_action_required={action_record_count} completed_with_notes={completed_with_notes_count}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
