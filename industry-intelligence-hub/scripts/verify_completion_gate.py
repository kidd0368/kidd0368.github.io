#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fail the build unless every indexed record has a valid GitHub completion receipt."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
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


def run_git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalized_repo_path(path: str) -> str:
    value = path.lstrip("/")
    prefix = f"{HUB_ROOT.name}/"
    return value if value.startswith(prefix) else f"{prefix}{value}"


def main() -> int:
    registry = load_json(REGISTRY)
    records_doc = load_json(RECORDS_INDEX)
    changelog_doc = load_json(CHANGELOG)
    manifest = load_json(MANIFEST)
    errors: list[str] = []

    rows = records_doc.get("records") or []
    changelog_by_task = {
        entry.get("task_id"): entry for entry in (changelog_doc.get("entries") or []) if entry.get("task_id")
    }
    seen_tasks: set[str] = set()
    seen_paths: set[str] = set()

    for row in rows:
        task_id = str(row.get("task_id") or "")
        repo_path = normalized_repo_path(str(row.get("record_path") or ""))
        receipt = row.get("write_receipt") or {}

        if not task_id:
            errors.append("index row missing task_id")
            continue
        if task_id in seen_tasks:
            errors.append(f"duplicate task_id in index: {task_id}")
        seen_tasks.add(task_id)
        if repo_path in seen_paths:
            errors.append(f"duplicate record_path in index: {repo_path}")
        seen_paths.add(repo_path)

        record_path = REPO_ROOT / repo_path
        if not record_path.is_file():
            errors.append(f"{task_id}: record missing at {repo_path}")
            continue

        record = load_json(record_path)
        if record.get("task_id") != task_id:
            errors.append(f"{task_id}: record task_id mismatch ({record.get('task_id')})")

        if receipt.get("gate_version") != GATE_VERSION:
            errors.append(f"{task_id}: completion gate version missing or stale")
        if receipt.get("status") != "committed_and_indexed":
            errors.append(f"{task_id}: receipt status is {receipt.get('status')!r}")
        if receipt.get("repository") != registry.get("target_repository"):
            errors.append(f"{task_id}: receipt repository mismatch")
        if receipt.get("branch") != (registry.get("completion_gate") or {}).get("branch", "main"):
            errors.append(f"{task_id}: receipt branch mismatch")
        if receipt.get("record_path") != repo_path:
            errors.append(f"{task_id}: receipt path mismatch")

        content_hash = sha256(record_path)
        if receipt.get("record_content_sha256") != content_hash:
            errors.append(f"{task_id}: content SHA-256 mismatch")

        try:
            latest_commit = run_git("log", "-1", "--format=%H", "--", repo_path)
            if not latest_commit:
                raise RuntimeError("empty git log result")
            run_git("cat-file", "-e", f"{latest_commit}^{{commit}}")
        except Exception as exc:
            errors.append(f"{task_id}: commit cannot be resolved ({exc})")
            latest_commit = ""

        if receipt.get("record_commit_sha") != latest_commit:
            errors.append(f"{task_id}: latest record commit mismatch")

        try:
            blob_sha = run_git("hash-object", repo_path)
        except Exception as exc:
            errors.append(f"{task_id}: blob SHA cannot be calculated ({exc})")
            blob_sha = ""
        if receipt.get("record_blob_sha") != blob_sha:
            errors.append(f"{task_id}: record blob SHA mismatch")

        changelog_receipt = (changelog_by_task.get(task_id) or {}).get("write_receipt")
        if changelog_receipt != receipt:
            errors.append(f"{task_id}: changelog receipt differs from records index")

        invalid_matches = [
            item for item in (manifest.get("validation_errors") or [])
            if item.get("task_id") == task_id or normalized_repo_path(str(item.get("path") or "")) == repo_path
        ]
        if invalid_matches:
            errors.append(f"{task_id}: manifest lists this record as invalid")

    if manifest.get("completion_gate_version") != GATE_VERSION:
        errors.append("manifest completion_gate_version missing or stale")
    if int(manifest.get("completed_record_count") or 0) != len(rows):
        errors.append("manifest completed_record_count does not equal indexed record count")
    if int(manifest.get("completion_receipt_error_count") or 0) != 0:
        errors.append("manifest reports completion receipt errors")
    if int(records_doc.get("valid_record_count") or 0) != len(rows):
        errors.append("records.json valid_record_count does not equal records length")

    if errors:
        for error in errors:
            print(f"COMPLETION_GATE_ERROR: {error}", file=sys.stderr)
        print(f"verified=0 errors={len(errors)}", file=sys.stderr)
        return 1

    print(f"verified={len(rows)} errors=0 gate_version={GATE_VERSION}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
