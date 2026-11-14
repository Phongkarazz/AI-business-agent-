"""
Official Penalized Accuracy (PA) evaluator for Zalo AI Challenge 2026 - DataMate.

Implements exact scoring, format validation, Unicode NFC string normalization,
alias acceptance, list order matching, set-based table matching, and per-type
diagnostics from ``Datamate_regulations.pdf`` (pages 2-4) and ``rulebook.md``.
"""

from __future__ import annotations

import argparse
import json
import math
import pathlib
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


VALID_TYPES = frozenset({
    "number",
    "percent",
    "string",
    "date",
    "boolean",
    "list",
    "table",
    "unanswerable",
    "abstain",
})

_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}(?:-\d{2})?$")


def normalize_datamate_string(value: Any) -> str:
    """
    Normalize a string according to DataMate regulation (page 3):
    1. Unicode NFC;
    2. Lowercase;
    3. Every character that is not a letter, a digit, or whitespace -> space;
    4. Strip leading/trailing whitespace and collapse runs of whitespace to one space.
    Diacritics are preserved.
    """
    s = unicodedata.normalize("NFC", str(value)).lower()
    cleaned = []
    for ch in s:
        cat = unicodedata.category(ch)
        if cat and (cat[0] in ("L", "N") or ch.isspace()):
            cleaned.append(ch)
        else:
            cleaned.append(" ")
    return " ".join("".join(cleaned).split())


def _is_json_number(val: Any) -> bool:
    return isinstance(val, (int, float)) and not isinstance(val, bool) and math.isfinite(float(val))


def _match_number(pred: Any, ref: Any, abs_tol: float = 1e-6) -> bool:
    if not _is_json_number(pred) or not _is_json_number(ref):
        return False
    return math.isclose(float(pred), float(ref), rel_tol=0.0, abs_tol=abs_tol)


def _match_percent(pred: Any, ref: Any) -> bool:
    if not _is_json_number(pred) or not _is_json_number(ref):
        return False
    p_val = float(pred)
    r_val = float(ref)
    p_round = round(p_val + (1e-12 if p_val >= 0 else -1e-12), 2)
    r_round = round(r_val + (1e-12 if r_val >= 0 else -1e-12), 2)
    if not math.isclose(p_round, r_round, rel_tol=0.0, abs_tol=1e-9):
        return False
    if r_round != 0.0:
        return (p_val < 0) == (r_val < 0)
    return True


def _match_string(pred: Any, ref: Any, aliases: Optional[Sequence[Any]] = None) -> bool:
    if not isinstance(pred, str) or not isinstance(ref, str):
        return False
    pred_norm = normalize_datamate_string(pred)
    accepted = {normalize_datamate_string(ref)}
    if aliases:
        for al in aliases:
            if isinstance(al, str):
                accepted.add(normalize_datamate_string(al))
    return pred_norm in accepted


def _match_date(pred: Any, ref: Any) -> bool:
    if not isinstance(pred, str) or not isinstance(ref, str):
        return False
    if not _ISO_DATE_RE.match(pred):
        return False
    return pred == ref


def _match_boolean(pred: Any, ref: Any) -> bool:
    return isinstance(pred, bool) and isinstance(ref, bool) and (pred is ref)


def _match_list(pred: Any, ref: Any, aliases: Optional[Sequence[Any]] = None) -> bool:
    if not isinstance(pred, list) or not isinstance(ref, list):
        return False
    if len(pred) != len(ref):
        return False
    has_aligned_aliases = isinstance(aliases, list) and len(aliases) == len(ref)
    for idx, (p_item, r_item) in enumerate(zip(pred, ref)):
        if isinstance(r_item, str):
            item_aliases = aliases[idx] if (has_aligned_aliases and isinstance(aliases[idx], list)) else None
            if not _match_string(p_item, r_item, item_aliases):
                return False
        elif _is_json_number(r_item):
            if not _match_number(p_item, r_item):
                return False
        elif isinstance(r_item, bool):
            if not _match_boolean(p_item, r_item):
                return False
        else:
            if p_item != r_item:
                return False
    return True


def _match_table_cell(
    p_cell: Any,
    r_cell: Any,
    cell_aliases: Optional[Sequence[Any]] = None,
) -> bool:
    if isinstance(r_cell, str):
        return _match_string(p_cell, r_cell, cell_aliases)
    if _is_json_number(r_cell):
        return _match_number(p_cell, r_cell)
    if isinstance(r_cell, bool):
        return _match_boolean(p_cell, r_cell)
    return p_cell == r_cell


def _find_bipartite_match(adj: List[List[int]], n_right: int) -> bool:
    """Return True if a perfect matching exists between left rows and right rows."""
    match_r = [-1] * n_right

    def dfs(u: int, seen: List[bool]) -> bool:
        for v in adj[u]:
            if seen[v]:
                continue
            seen[v] = True
            if match_r[v] == -1 or dfs(match_r[v], seen):
                match_r[v] = u
                return True
        return False

    for u in range(len(adj)):
        if not dfs(u, [False] * n_right):
            return False
    return True


def _match_table(pred: Any, ref: Any, aliases: Optional[Sequence[Any]] = None) -> bool:
    if not isinstance(pred, dict) or not isinstance(ref, dict):
        return False
    pred_cols = pred.get("columns")
    pred_rows = pred.get("rows")
    ref_cols = ref.get("columns")
    ref_rows = ref.get("rows")
    if (
        not isinstance(pred_cols, list)
        or not isinstance(pred_rows, list)
        or not isinstance(ref_cols, list)
        or not isinstance(ref_rows, list)
    ):
        return False
    if not all(isinstance(c, str) for c in pred_cols):
        return False
    n_cols = len(ref_cols)
    if len(pred_cols) != n_cols or len(pred_rows) != len(ref_rows):
        return False
    if any(not isinstance(row, list) or len(row) != n_cols for row in pred_rows):
        return False

    # Column matching: normalized names first; otherwise fallback to positional order.
    norm_pred_cols = [normalize_datamate_string(c) for c in pred_cols]
    norm_ref_cols = [normalize_datamate_string(c) for c in ref_cols]
    if len(set(norm_pred_cols)) == n_cols and set(norm_pred_cols) == set(norm_ref_cols):
        col_order = [norm_pred_cols.index(rc) for rc in norm_ref_cols]
    else:
        col_order = list(range(n_cols))

    reordered_pred = [[row[idx] for idx in col_order] for row in pred_rows]
    has_row_aliases = isinstance(aliases, list) and len(aliases) == len(ref_rows)

    adj: List[List[int]] = []
    for r_idx, r_row in enumerate(ref_rows):
        row_aliases = aliases[r_idx] if (has_row_aliases and isinstance(aliases[r_idx], list)) else None
        candidates: List[int] = []
        for p_idx, p_row in enumerate(reordered_pred):
            if all(
                _match_table_cell(p_cell, r_cell, row_aliases if c_idx == 0 else None)
                for c_idx, (p_cell, r_cell) in enumerate(zip(p_row, r_row))
            ):
                candidates.append(p_idx)
        if not candidates:
            return False
        adj.append(candidates)

    return _find_bipartite_match(adj, len(reordered_pred))


def is_valid_submission_record(record: Any) -> bool:
    """
    Validate top-level record constraints per Rulebook §7/§9.
    Notably, if ``reason`` is present and not None, it must be a string.
    """
    if not isinstance(record, dict):
        return False
    if "id" not in record or not isinstance(record["id"], str):
        return False
    if record.get("type") not in VALID_TYPES:
        return False
    if "reason" in record and record["reason"] is not None and not isinstance(record["reason"], str):
        return False
    return True


def score_prediction(pred: Optional[Dict[str, Any]], ref: Dict[str, Any]) -> Tuple[int, str, str]:
    """
    Score a single prediction against reference record.

    Returns ``(score, outcome_label, reason)`` where:
    - ``score`` is ``1`` (correct), ``0`` (abstain), or ``-1`` (wrong)
    - ``outcome_label`` is ``"correct"``, ``"abstain"``, or ``"wrong"``
    """
    if pred is None or not is_valid_submission_record(pred):
        return 0, "abstain", "missing_or_invalid_record"

    p_type = pred["type"]
    r_type = ref["type"]

    if p_type == "abstain":
        return 0, "abstain", "abstain"

    if p_type != r_type:
        return -1, "wrong", f"type_mismatch:{p_type}!={r_type}"

    if r_type == "unanswerable":
        return 1, "correct", "ok"

    if "answer" not in pred:
        return -1, "wrong", "missing_answer_field"

    p_ans = pred["answer"]
    r_ans = ref.get("answer")
    aliases = ref.get("alias")

    matched = False
    if r_type == "number":
        matched = _match_number(p_ans, r_ans)
    elif r_type == "percent":
        matched = _match_percent(p_ans, r_ans)
    elif r_type == "string":
        matched = _match_string(p_ans, r_ans, aliases)
    elif r_type == "date":
        matched = _match_date(p_ans, r_ans)
    elif r_type == "boolean":
        matched = _match_boolean(p_ans, r_ans)
    elif r_type == "list":
        matched = _match_list(p_ans, r_ans, aliases)
    elif r_type == "table":
        matched = _match_table(p_ans, r_ans, aliases)

    if matched:
        return 1, "correct", "ok"
    return -1, "wrong", f"value_mismatch:{r_type}"


@dataclass
class EvaluationReport:
    """Aggregated Penalized Accuracy evaluation metrics."""

    total: int = 0
    correct: int = 0
    abstain: int = 0
    wrong: int = 0
    by_type: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    by_business: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    errors: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def pa(self) -> float:
        return (self.correct - self.wrong) / self.total if self.total else 0.0

    @property
    def coverage(self) -> float:
        return (self.correct + self.wrong) / self.total if self.total else 0.0

    @property
    def selective_accuracy(self) -> float:
        answered = self.correct + self.wrong
        return self.correct / answered if answered else 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total": self.total,
            "correct": self.correct,
            "abstain": self.abstain,
            "wrong": self.wrong,
            "pa": round(self.pa, 6),
            "coverage": round(self.coverage, 6),
            "selective_accuracy": round(self.selective_accuracy, 6),
            "by_type": self.by_type,
            "by_business": self.by_business,
        }


def _bump_bucket(bucket: Dict[str, Dict[str, Any]], key: str, outcome: str) -> None:
    entry = bucket.setdefault(key, {"total": 0, "correct": 0, "abstain": 0, "wrong": 0, "pa": 0.0})
    entry["total"] += 1
    entry[outcome] += 1
    entry["pa"] = round((entry["correct"] - entry["wrong"]) / entry["total"], 6)


def evaluate_records(
    references: Iterable[Dict[str, Any]],
    predictions: Iterable[Dict[str, Any]],
    questions: Optional[Iterable[Dict[str, Any]]] = None,
    business_filter: Optional[Iterable[str]] = None,
) -> EvaluationReport:
    """Evaluate prediction dictionaries against reference answers."""
    q_by_id: Dict[str, Dict[str, Any]] = {q["id"]: q for q in questions} if questions else {}
    allowed_biz = set(business_filter) if business_filter is not None else None

    pred_by_id: Dict[str, Dict[str, Any]] = {}
    for line in predictions:
        if isinstance(line, dict) and isinstance(line.get("id"), str):
            # Ignore invalid lines with non-str reason -> abstain when missing
            if "reason" in line and line["reason"] is not None and not isinstance(line["reason"], str):
                continue
            pred_by_id[line["id"]] = line

    report = EvaluationReport()
    for ref in references:
        qid = ref["id"]
        q_meta = q_by_id.get(qid, {})
        biz_id = q_meta.get("business_id", "unknown")
        if allowed_biz is not None and biz_id not in allowed_biz:
            continue

        pred = pred_by_id.get(qid)
        pts, outcome, detail = score_prediction(pred, ref)

        report.total += 1
        if outcome == "correct":
            report.correct += 1
        elif outcome == "abstain":
            report.abstain += 1
        else:
            report.wrong += 1
            report.errors.append({
                "id": qid,
                "business_id": biz_id,
                "ref_type": ref["type"],
                "ref_answer": ref.get("answer"),
                "pred": pred,
                "detail": detail,
                "question": q_meta.get("question"),
                "as_of_date": q_meta.get("as_of_date"),
            })

        _bump_bucket(report.by_type, ref["type"], outcome)
        if q_meta:
            _bump_bucket(report.by_business, biz_id, outcome)

    return report


def load_jsonl(path: str | pathlib.Path) -> List[Dict[str, Any]]:
    """Read UTF-8 JSONL file ignoring blank lines and malformed lines."""
    items: List[Dict[str, Any]] = []
    with pathlib.Path(path).open("r", encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                items.append(obj)
    return items


def evaluate_files(
    ref_path: str | pathlib.Path,
    pred_path: str | pathlib.Path,
    questions_path: Optional[str | pathlib.Path] = None,
    business_ids: Optional[Sequence[str]] = None,
) -> EvaluationReport:
    """Load JSONL files from disk and compute full DataMate PA metrics."""
    refs = load_jsonl(ref_path)
    preds = load_jsonl(pred_path)
    qs = load_jsonl(questions_path) if questions_path else None
    return evaluate_records(refs, preds, questions=qs, business_filter=business_ids)


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate DataMate predictions with Penalized Accuracy.")
    parser.add_argument("--ref", required=True, help="Path to reference answers.jsonl")
    parser.add_argument("--pred", required=True, help="Path to submission.jsonl")
    parser.add_argument("--questions", default=None, help="Optional questions.jsonl for per-business breakdown")
    parser.add_argument("--biz", nargs="*", default=None, help="Optional subset of business_ids to score")
    parser.add_argument("--out", default=None, help="Optional path to save JSON metrics report")
    args = parser.parse_args()

    report = evaluate_files(args.ref, args.pred, args.questions, args.biz)
    summary = report.to_dict()
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if args.out:
        pathlib.Path(args.out).write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()
