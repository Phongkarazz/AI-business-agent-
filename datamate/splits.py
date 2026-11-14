"""Stratified 24-train / 6-validation split utilities for local DataMate benchmarking."""

from __future__ import annotations

import json
import pathlib
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

VAL_BUSINESS_IDS: Tuple[str, ...] = (
    "biz_105",  # multi-table cafe .xlsx + unit conversions + subtotals/dupes + unanswerable
    "biz_109",  # multi-table retail .xlsx + table + boolean + unanswerable
    "biz_110",  # single-table .csv + daily subtotals
    "biz_118",  # building materials .xlsx + delivery schedules + aging debt + unanswerable
    "biz_123",  # POS .sqlite database (17 tables, dirty NgayLap) + table + boolean + unanswerable
    "biz_127",  # multi-file .csv + deduped orders + table
)

VAL_BUSINESS_SET = frozenset(VAL_BUSINESS_IDS)


def load_jsonl(path: str | pathlib.Path) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    with pathlib.Path(path).open("r", encoding="utf-8") as fh:
        for line in fh:
            s = line.strip()
            if s:
                records.append(json.loads(s))
    return records


def write_jsonl(path: str | pathlib.Path, records: Iterable[Dict[str, Any]]) -> None:
    out_path = pathlib.Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")


def load_split_dataset(
    dataset_dir: str | pathlib.Path,
    split: str = "val",
    business_ids: Optional[Sequence[str]] = None,
    limit: Optional[int] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    """
    Load questions (and optional answers when available) filtered by split.

    Args:
        dataset_dir: Root directory containing questions.jsonl, optional answers.jsonl, and data/.
        split: One of "train" (24 businesses), "val" (6 held-out businesses), or "all".
        business_ids: Optional explicit subset of business_ids to keep.
        limit: Optional cap on number of returned questions (after deterministic ordering).
    """
    root = pathlib.Path(dataset_dir)
    questions = load_jsonl(root / "questions.jsonl")

    ans_path = root / "answers.jsonl"
    answers_by_id: Dict[str, Dict[str, Any]] = {}
    if ans_path.exists():
        for rec in load_jsonl(ans_path):
            qid = rec.get("id") or rec.get("question_id")
            if qid is not None:
                answers_by_id[str(qid)] = rec

    split_norm = (split or "all").strip().lower()
    if split_norm == "val":
        allowed = VAL_BUSINESS_SET
    elif split_norm == "train":
        allowed = None
    elif split_norm == "all":
        allowed = None
    else:
        raise ValueError(f"Unsupported split={split!r}; expected 'train', 'val', or 'all'.")

    explicit_set = set(business_ids) if business_ids else None
    filtered: List[Dict[str, Any]] = []
    for q in questions:
        bid = q.get("business_id", "")
        if split_norm == "val" and bid not in VAL_BUSINESS_SET:
            continue
        if split_norm == "train" and bid in VAL_BUSINESS_SET:
            continue
        if explicit_set is not None and bid not in explicit_set:
            continue
        filtered.append(q)

    if limit is not None and limit >= 0:
        filtered = filtered[:limit]
    return filtered, answers_by_id
