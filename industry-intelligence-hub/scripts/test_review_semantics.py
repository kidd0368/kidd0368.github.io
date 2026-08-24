#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Deterministic tests for review-semantic normalization."""
from copy import deepcopy

from normalize_review_semantics import normalize_record


def base_record() -> dict:
    return {
        "task_id": "TASK-20990101-000000-TEST",
        "record_status": "review_required",
        "validation": {"conflicts_found": 1, "review_notes": []},
        "conflicts": [],
    }


def test_filename_is_note() -> None:
    record = base_record()
    record["conflicts"] = [{
        "conflict_id": "FILENAME",
        "type": "source_identity",
        "description": "檔名寫中際旭創，但正文與股票代碼是新易盛。",
        "resolution": "以正文為準。",
    }]
    assert normalize_record(record)
    assert record["record_status"] == "accepted"
    assert record["validation"]["user_action_required_count"] == 0
    assert record["validation"]["important_note_count"] == 0
    assert record["important_notes"][0]["category"] == "source_metadata"


def test_same_report_period_is_important_note() -> None:
    record = base_record()
    record["conflicts"] = [{
        "conflict_id": "PERIOD",
        "type": "period",
        "description": "同一報告主文寫FY27 EPS，附錄寫FY26 EPS。",
        "resolution": "主文估值語境採FY27，附錄保留為替代口徑。",
    }]
    normalize_record(record)
    assert record["record_status"] == "accepted"
    assert record["validation"]["important_note_count"] == 1
    assert record["validation"]["user_action_required_count"] == 0


def test_explicit_user_action_remains_review_required() -> None:
    record = base_record()
    record["conflicts"] = [{
        "conflict_id": "CHOICE",
        "type": "substantive_conflict",
        "description": "兩個同等可信的絕對產能數字無法判定。",
        "requires_user_action": True,
        "options": ["採來源A", "採來源B", "兩筆並存"],
        "recommended_option": "兩筆並存",
    }]
    normalize_record(record)
    assert record["record_status"] == "review_required"
    assert record["validation"]["user_action_required_count"] == 1
    assert len(record["review_items"]) == 1


def test_idempotent() -> None:
    record = base_record()
    record["conflicts"] = [{
        "conflict_id": "DATE",
        "type": "date",
        "description": "券商引用日與官方事件日不同。",
    }]
    normalize_record(record)
    snapshot = deepcopy(record)
    assert normalize_record(record) is False
    assert record == snapshot


if __name__ == "__main__":
    test_filename_is_note()
    test_same_report_period_is_important_note()
    test_explicit_user_action_remains_review_required()
    test_idempotent()
    print("review_semantics_tests=4 passed=4")
