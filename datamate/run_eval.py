"""Headless CLI runner and PA evaluation harness for DataMateAgent."""

from __future__ import annotations

import argparse
import json
import pathlib
import time
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional

from datamate.agent import AgentConfig, AgentResult, DataMateAgent
from datamate.evaluator_pa import evaluate_records, score_prediction
from datamate.llm_backend import LLMConfig
from datamate.splits import load_jsonl, load_split_dataset, write_jsonl


def run_evaluation(
    dataset_dir: str | pathlib.Path,
    out_path: str | pathlib.Path,
    split: str = "val",
    business_ids: Optional[List[str]] = None,
    limit: Optional[int] = None,
    questions_path: Optional[str | pathlib.Path] = None,
    ref_path: Optional[str | pathlib.Path] = None,
    cache_dir: Optional[str | pathlib.Path] = None,
    log_dir: Optional[str | pathlib.Path] = None,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    abstain_threshold: float = 0.52,
    max_sql_retries: int = 3,
    quiet: bool = False,
) -> Dict[str, Any]:
    """Run headless DataMateAgent over a question set and compute PA when references exist."""
    root = pathlib.Path(dataset_dir)
    cal_path = root / "calendar.csv"

    if questions_path:
        questions = load_jsonl(questions_path)
        if business_ids:
            bset = set(business_ids)
            questions = [q for q in questions if q.get("business_id") in bset]
        if limit is not None and limit >= 0:
            questions = questions[:limit]
        answers_by_id: Dict[str, Dict[str, Any]] = {}
        if ref_path and pathlib.Path(ref_path).exists():
            answers_by_id = {
                str(r.get("id") or r.get("question_id")): r
                for r in load_jsonl(ref_path)
            }
    else:
        questions, answers_by_id = load_split_dataset(
            root,
            split=split,
            business_ids=business_ids,
            limit=limit,
        )
        if ref_path and pathlib.Path(ref_path).exists():
            answers_by_id = {
                str(r.get("id") or r.get("question_id")): r
                for r in load_jsonl(ref_path)
            }

    llm_cfg = LLMConfig.from_env(
        provider=provider,
        model_name=model,
        api_key=api_key,
        base_url=base_url,
    )
    agent_cfg = AgentConfig(
        llm_config=llm_cfg,
        max_sql_retries=max_sql_retries,
        abstain_threshold=abstain_threshold,
    )
    agent = DataMateAgent(
        config=agent_cfg,
        calendar_path=str(cal_path) if cal_path.exists() else None,
    )

    # Group by business_id for single workspace load per shop while keeping output order
    by_biz: Dict[str, List[Tuple[int, Dict[str, Any]]]] = defaultdict(list)
    for idx, q in enumerate(questions):
        by_biz[q["business_id"]].append((idx, q))

    results_by_idx: Dict[int, AgentResult] = {}
    t0 = time.time()
    processed = 0

    for bid in sorted(by_biz):
        bdir = root / "data" / bid
        t_biz = time.time()
        knowledge = agent.get_knowledge(str(bdir), cache_dir=cache_dir)
        if not quiet:
            print(f"[{bid}] loaded ({len(knowledge.valid_tables)} tables, {time.time() - t_biz:.2f}s), running {len(by_biz[bid])} questions...", flush=True)

        for orig_idx, q in by_biz[bid]:
            res = agent.answer_question(q, knowledge)
            results_by_idx[orig_idx] = res
            processed += 1
            if not quiet and (processed % 20 == 0 or processed == len(questions)):
                print(f"  progress {processed}/{len(questions)} ({time.time() - t0:.1f}s)", flush=True)

    ordered_results = [results_by_idx[i] for i in range(len(questions))]
    predictions = [r.prediction for r in ordered_results]
    write_jsonl(out_path, predictions)

    summary: Dict[str, Any] = {
        "total_questions": len(questions),
        "elapsed_seconds": round(time.time() - t0, 2),
        "provider": llm_cfg.provider,
        "model": llm_cfg.model_name,
        "out_path": str(out_path),
    }

    if log_dir:
        ldir = pathlib.Path(log_dir)
        ldir.mkdir(parents=True, exist_ok=True)
        traces = []
        for q, r in zip(questions, ordered_results):
            qid = r.question_id
            ref = answers_by_id.get(qid)
            pts, outcome, detail = (score_prediction(r.prediction, ref) if ref else (None, None, ""))
            traces.append({
                "id": qid,
                "business_id": q["business_id"],
                "as_of_date": q.get("as_of_date"),
                "question": q["question"],
                "prediction": r.prediction,
                "confidence": r.confidence,
                "sql_attempts": r.sql_attempts,
                "sql": r.sql,
                "error": r.error,
                "notes": r.notes,
                "ref_type": ref.get("type") if ref else None,
                "ref_answer": ref.get("answer") if ref else None,
                "outcome": outcome,
                "points": pts,
                "detail": detail,
            })
        write_jsonl(ldir / "traces.jsonl", traces)

    if answers_by_id:
        refs = [answers_by_id[q["id"]] for q in questions if q["id"] in answers_by_id]
        if refs:
            rep = evaluate_records(refs, predictions, questions=questions)
            summary.update({
                "evaluated": rep.total,
                "correct": rep.correct,
                "wrong": rep.wrong,
                "abstain": rep.abstain,
                "pa": round(rep.pa, 6),
                "by_type": rep.by_type,
                "by_business": rep.by_business,
            })
            if log_dir:
                (pathlib.Path(log_dir) / "summary.json").write_text(
                    json.dumps(summary, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )

    return summary


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run headless DataMateAgent inference & PA evaluation")
    parser.add_argument("--data-dir", required=True, help="Dataset dir (contains questions.jsonl, data/, calendar.csv)")
    parser.add_argument("--out", required=True, help="Output submission JSONL path")
    parser.add_argument("--split", default="val", choices=["train", "val", "all"], help="Dataset split")
    parser.add_argument("--biz", nargs="*", default=None, help="Optional subset of business_ids")
    parser.add_argument("--limit", type=int, default=None, help="Optional max question limit")
    parser.add_argument("--questions", default=None, help="Optional explicit questions.jsonl path")
    parser.add_argument("--ref", default=None, help="Optional explicit answers.jsonl path")
    parser.add_argument("--cache-dir", default="/tmp/datamate_step1_cache", help="SQLite workspace cache directory")
    parser.add_argument("--log-dir", default=None, help="Directory for execution traces & summary.json")
    parser.add_argument("--provider", default=None, help="LLM provider override")
    parser.add_argument("--model", default=None, help="LLM model name override")
    parser.add_argument("--base-url", default=None, help="Custom OpenAI-compatible/Ollama base URL")
    parser.add_argument("--api-key", default=None, help="Optional API key override")
    parser.add_argument("--abstain-threshold", type=float, default=0.52, help="Confidence gate for abstaining")
    parser.add_argument("--max-sql-retries", type=int, default=3, help="Max SQL execution/repair iterations")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    summary = run_evaluation(
        dataset_dir=args.data_dir,
        out_path=args.out,
        split=args.split,
        business_ids=args.biz,
        limit=args.limit,
        questions_path=args.questions,
        ref_path=args.ref,
        cache_dir=args.cache_dir,
        log_dir=args.log_dir,
        provider=args.provider,
        model=args.model,
        base_url=args.base_url,
        api_key=args.api_key,
        abstain_threshold=args.abstain_threshold,
        max_sql_retries=args.max_sql_retries,
        quiet=args.quiet,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
