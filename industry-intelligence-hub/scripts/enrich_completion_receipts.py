#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Add cryptographic GitHub write receipts to generated Industry Intelligence indexes.

This runs immediately after rebuild_records.py. A record is considered complete only
when the file exists in git, its latest modifying commit is resolvable, and its exact
content hash can be stored in records.json/changelog.json/manifest.json.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

HUB_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = HUB_ROOT.parent
RECORDS_INDEX = HUB_ROOT / "data" / "records.json"
CHANGELOG = HUB_ROOT / "data" / "changelog.json"
MANIFEST = HUB_ROOT / "data" / "manifest.json"
REGISTRY = HUB_ROOT / "data" / "registry.json"
GATE_VERSION = "1.0.0"


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run_git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def full_repo_path(indexed_path: str) -> str:
    normalized = indexed_path.lstrip("/")
    hub_prefix = f"{HUB_ROOT.name}/"
    return normalized if normalized.startswith(hub_prefix) else f"{hub_prefix}{normalized}"


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def latest_commit_for_path(repo_relative_path: str) -> str:
    commit = run_git("log", "-1", "--format=%H", "--", repo_relative_path)
    if not commit:
        raise RuntimeError(f"no git commit found for {repo_relative_path}")
    run_git("cat-file", "-e", f"{commit}^{{commit}}")
    return commit


def receipt_for_record(row: dict[str, Any], registry: dict[str, Any], indexed_at: str | None) -> dict[str, Any]:
    indexed_path = str(row.get("record_path") or "")
    if not indexed_path:
        raise RuntimeError(f"record {row.get('task_id')} has no record_path")

    repo_path = full_repo_path(indexed_path)
    absolute_path = REPO_ROOT / repo_path
    if not absolute_path.is_file():
        raise RuntimeError(f"record file does not exist: {repo_path}")

    record = load_json(absolute_path)
    if record.get("task_id") != row.get("task_id"):
        raise RuntimeError(
            f"task_id mismatch for {repo_path}: index={row.get('task_id')} file={record.get('task_id')}"
        )

    commit_sha = latest_commit_for_path(repo_path)
    blob_sha = run_git("hash-object", repo_path)
    commit_message = run_git("show", "-s", "--format=%s", commit_sha)
    gate_config = registry.get("completion_gate") or {}

    return {
        "gate_version": GATE_VERSION,
        "status": "committed_and_indexed",
        "repository": registry.get("target_repository"),
        "branch": gate_config.get("branch", "main"),
        "record_path": repo_path,
        "record_commit_sha": commit_sha,
        "record_blob_sha": blob_sha,
        "record_content_sha256": file_sha256(absolute_path),
        "commit_message": commit_message,
        "index_path": registry.get("aggregate_path"),
        "manifest_path": gate_config.get(
            "manifest_path", f"{registry.get('base_path', HUB_ROOT.name)}/data/manifest.json"
        ),
        "indexed_at": indexed_at,
    }


def main() -> int:
    registry = load_json(REGISTRY)
    records_doc = load_json(RECORDS_INDEX)
    changelog_doc = load_json(CHANGELOG)
    manifest_doc = load_json(MANIFEST)
    indexed_at = records_doc.get("generated_at")

    receipts: dict[str, dict[str, Any]] = {}
    errors: list[dict[str, str]] = []

    for row in records_doc.get("records", []):
        task_id = str(row.get("task_id") or "")
        try:
            receipt = receipt_for_record(row, registry, indexed_at)
            row["write_receipt"] = receipt
            receipts[task_id] = receipt
        except Exception as exc:
            row["write_receipt"] = {
                "gate_version": GATE_VERSION,
                "status": "verification_failed",
                "error": str(exc),
            }
            errors.append({"task_id": task_id, "error": str(exc)})

    for entry in changelog_doc.get("entries", []):
        receipt = receipts.get(str(entry.get("task_id") or ""))
        if receipt:
            entry["write_receipt"] = receipt

    manifest_doc["completion_gate_version"] = GATE_VERSION
    manifest_doc["completed_record_count"] = len(receipts)
    manifest_doc["completion_receipt_error_count"] = len(errors)
    manifest_doc["completion_receipt_errors"] = errors
    if errors:
        manifest_doc["status"] = "review_required"

    write_json(RECORDS_INDEX, records_doc)
    write_json(CHANGELOG, changelog_doc)
    write_json(MANIFEST, manifest_doc)

    print(f"completion_receipts={len(receipts)} errors={len(errors)}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
