"""Stage 4 Fine-Tuning Pipeline (SFT + When2Call DPO -> Q4_K_M GGUF) for Google Colab L4 GPU."""

from __future__ import annotations

import argparse
import glob
import gzip
import inspect
import json
import os
import pathlib
import re
import shutil
from typing import Any, Dict, List, Optional, Set, Tuple


MODEL_PROFILES: Dict[str, Dict[str, str]] = {
    "3b": {
        "hf_model": "unsloth/Qwen2.5-Coder-3B-Instruct",
        "gguf_filename": "veraxus-coder-3b-q4_k_m.gguf",
        "ollama_tag": "veraxus-coder:3b",
    },
    "7b": {
        "hf_model": "unsloth/Qwen2.5-Coder-7B-Instruct",
        "gguf_filename": "veraxus-coder-7b-q4_k_m.gguf",
        "ollama_tag": "veraxus-coder:7b",
    },
}


def load_jsonl_any(path: pathlib.Path) -> List[Dict[str, Any]]:
    opener = gzip.open if path.suffix == ".gz" else pathlib.Path.open
    records: List[Dict[str, Any]] = []
    with opener(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            s = line.strip()
            if s:
                records.append(json.loads(s))
    return records


def resolve_dataset_file(data_dir: pathlib.Path, stem: str) -> pathlib.Path:
    for ext in (".jsonl.gz", ".jsonl"):
        p = data_dir / f"{stem}{ext}"
        if p.exists():
            return p
    raise FileNotFoundError(f"Dataset file not found in {data_dir} for {stem} (.jsonl.gz/.jsonl)")


_ALIAS_PAIRS: Tuple[Tuple[str, str], ...] = (
    ("processing_class", "tokenizer"),
    ("eval_strategy", "evaluation_strategy"),
    ("max_length", "max_seq_length"),
)


def _unwrap_init(target: Any) -> Any:
    """Unwrap __wrapped__ decorators and unsloth closure wrappers (`original_init`)."""
    fn = target.__init__ if isinstance(target, type) else target
    seen: Set[int] = set()
    while fn is not None and id(fn) not in seen:
        seen.add(id(fn))
        wrapped = getattr(fn, "__wrapped__", None)
        if wrapped is not None:
            fn = wrapped
            continue
        closure = getattr(fn, "__closure__", None)
        code = getattr(fn, "__code__", None)
        nxt = None
        if closure and code and "original_init" in getattr(code, "co_freevars", ()):
            idx = code.co_freevars.index("original_init")
            nxt = closure[idx].cell_contents
        if nxt is not None:
            fn = nxt
            continue
        break
    return fn


def _explicit_params_of(fn: Any) -> Tuple[Set[str], bool]:
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return set(), True
    names = {
        p.name
        for p in sig.parameters.values()
        if p.name != "self"
        and p.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
    }
    has_varkw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
    return names, has_varkw


def _resolve_alias_pairs(raw_kwargs: Dict[str, Any], explicit: Set[str]) -> Dict[str, Any]:
    resolved = dict(raw_kwargs)
    for primary, secondary in _ALIAS_PAIRS:
        if primary in resolved and secondary in resolved:
            if explicit and secondary in explicit and primary not in explicit:
                resolved.pop(primary, None)
            elif primary == "max_length" and explicit and "max_seq_length" in explicit and "max_length" not in explicit:
                resolved.pop(primary, None)
            else:
                resolved.pop(secondary, None)
    return resolved


def _filter_kwargs_for(fn_or_cls: Any, raw_kwargs: Dict[str, Any]) -> Dict[str, Any]:
    """Filter kwargs by inspecting unwrapped init + MRO and deduplicating API aliases."""
    leaf_fn = _unwrap_init(fn_or_cls)
    explicit, leaf_has_varkw = _explicit_params_of(leaf_fn)
    if isinstance(fn_or_cls, type) and (leaf_has_varkw or not explicit):
        mro_explicit: Set[str] = set(explicit)
        for base in fn_or_cls.__mro__:
            if base is object:
                continue
            b_names, _ = _explicit_params_of(_unwrap_init(base))
            mro_explicit.update(b_names)
        if mro_explicit:
            explicit = mro_explicit

    resolved = _resolve_alias_pairs(raw_kwargs, explicit)
    if explicit and (not leaf_has_varkw or isinstance(fn_or_cls, type)):
        return {k: v for k, v in resolved.items() if k in explicit}
    return resolved


def instantiate_resilient(cls: Any, raw_kwargs: Dict[str, Any]) -> Any:
    """Instantiate HuggingFace/Unsloth trainers/configs safely across TRL/Transformers versions."""
    kwargs = _filter_kwargs_for(cls, raw_kwargs)
    alt_map: Dict[str, str] = {}
    for a, b in _ALIAS_PAIRS:
        alt_map[a] = b
        alt_map[b] = a
    tried_fallback: Set[str] = set()

    for _ in range(8):
        try:
            return cls(**kwargs)
        except TypeError as exc:
            msg = str(exc)
            m = re.search(r"unexpected keyword argument '([^']+)'", msg)
            if not m:
                raise
            bad = m.group(1)
            if bad not in kwargs:
                raise
            kwargs.pop(bad, None)
            alt = alt_map.get(bad)
            if alt and alt in raw_kwargs and alt not in kwargs and alt not in tried_fallback:
                kwargs[alt] = raw_kwargs[alt]
                tried_fallback.add(alt)
    return cls(**kwargs)


def find_exported_ggufs(
    search_roots: List[pathlib.Path],
    final_gguf: pathlib.Path,
    export_quant: str = "q4_k_m",
) -> List[pathlib.Path]:
    """Locate exported GGUF files across export roots including Unsloth `*_gguf` sibling dirs."""
    q_low = (export_quant or "q4_k_m").lower()
    final_resolved = final_gguf.resolve()
    seen: Set[pathlib.Path] = set()
    cands: List[pathlib.Path] = []
    for root in search_roots:
        if not root.exists():
            continue
        for p in root.rglob("*.gguf"):
            rp = p.resolve()
            if rp == final_resolved or rp in seen:
                continue
            name_low = p.name.lower()
            if q_low not in ("bf16", "f16", "f32") and re.search(r"\.(?:bf16|f16|f32)\.gguf$", name_low):
                continue
            seen.add(rp)
            cands.append(p)
    cands.sort(key=lambda p: (0 if q_low in p.name.lower() else 1, -p.stat().st_size))
    return cands


def write_ollama_modelfile(gguf_filename: str, out_path: pathlib.Path) -> None:
    content = (
        f"FROM ./{gguf_filename}\n\n"
        'TEMPLATE """{{- if .Messages }}\n'
        '{{- range $i, $_ := .Messages }}\n'
        '<|im_start|>{{ .Role }}\n{{ .Content }}<|im_end|>\n'
        '{{- end }}\n'
        '<|im_start|>assistant\n'
        '{{- else }}\n'
        '{{- if .System }}<|im_start|>system\n{{ .System }}<|im_end|>\n{{- end }}\n'
        '{{- if .Prompt }}<|im_start|>user\n{{ .Prompt }}<|im_end|>\n{{- end }}\n'
        '<|im_start|>assistant\n'
        '{{- end }}{{ .Response }}{{- if .Response }}<|im_end|>{{- end }}"""\n\n'
        'PARAMETER stop "<|im_start|>"\n'
        'PARAMETER stop "<|im_end|>"\n'
        'PARAMETER stop "<|endoftext|>"\n'
        "PARAMETER temperature 0\n"
        "PARAMETER top_p 0.9\n"
        "PARAMETER num_ctx 4096\n"
    )
    out_path.write_text(content, encoding="utf-8")


def train_and_export(
    *,
    profile: str = "3b",
    data_dir: str | pathlib.Path = "training/datasets",
    out_dir: str | pathlib.Path = "training/outputs",
    max_seq_length: int = 3072,
    lora_rank: int = 32,
    epochs_sft: int = 2,
    epochs_dpo: int = 1,
    skip_dpo: bool = False,
    export_quant: str = "q4_k_m",
) -> pathlib.Path:
    import torch
    from datasets import Dataset
    from unsloth import FastLanguageModel, PatchDPOTrainer, is_bfloat16_supported
    from unsloth.chat_templates import get_chat_template, train_on_responses_only
    from trl import SFTConfig, SFTTrainer

    if profile not in MODEL_PROFILES:
        raise ValueError(f"Unsupported profile={profile!r}; choose from {list(MODEL_PROFILES)}")
    cfg_prof = MODEL_PROFILES[profile]
    ddir = pathlib.Path(data_dir)
    odir = pathlib.Path(out_dir) / f"veraxus_{profile}"
    odir.mkdir(parents=True, exist_ok=True)

    use_bf16 = is_bfloat16_supported()
    print(f"[Config] model={cfg_prof['hf_model']} | bf16={use_bf16} | max_seq={max_seq_length} | r={lora_rank}")

    # 1. Load datasets
    sft_train_raw = load_jsonl_any(resolve_dataset_file(ddir, "veraxus_sft_train"))
    sft_eval_raw = load_jsonl_any(resolve_dataset_file(ddir, "veraxus_sft_eval"))
    dpo_raw = [] if skip_dpo else load_jsonl_any(resolve_dataset_file(ddir, "veraxus_dpo_when2call"))
    print(f"[Data] SFT train={len(sft_train_raw)} | SFT eval={len(sft_eval_raw)} | DPO={len(dpo_raw)}")

    # 2. Load base model & apply LoRA
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=cfg_prof["hf_model"],
        max_seq_length=max_seq_length,
        dtype=torch.bfloat16 if use_bf16 else torch.float16,
        load_in_4bit=True,
    )
    tokenizer = get_chat_template(tokenizer, chat_template="qwen-2.5")

    model = FastLanguageModel.get_peft_model(
        model,
        r=lora_rank,
        target_modules=[
            "q_proj", "k_proj", "v_proj", "o_proj",
            "gate_proj", "up_proj", "down_proj",
        ],
        lora_alpha=lora_rank * 2,
        lora_dropout=0,
        bias="none",
        use_gradient_checkpointing="unsloth",
        random_state=2026,
    )

    def _fmt_sft(batch: Dict[str, List[Any]]) -> Dict[str, List[str]]:
        texts = [
            tokenizer.apply_chat_template(msgs, tokenize=False, add_generation_prompt=False)
            for msgs in batch["messages"]
        ]
        return {"text": texts}

    ds_sft_tr = Dataset.from_list([{"messages": r["messages"]} for r in sft_train_raw]).map(_fmt_sft, batched=True)
    ds_sft_ev = Dataset.from_list([{"messages": r["messages"]} for r in sft_eval_raw]).map(_fmt_sft, batched=True)

    # 3. Stage 1 — Structured Trajectory SFT
    sft_warmup_steps = max(5, int(0.06 * len(ds_sft_tr) * epochs_sft / 16))
    sft_args_dict = {
        "output_dir": str(odir / "sft_ckpt"),
        "per_device_train_batch_size": 2,
        "per_device_eval_batch_size": 2,
        "gradient_accumulation_steps": 8,
        "warmup_steps": sft_warmup_steps,
        "num_train_epochs": epochs_sft,
        "learning_rate": 2e-4,
        "fp16": not use_bf16,
        "bf16": use_bf16,
        "logging_steps": 10,
        "eval_strategy": "epoch",
        "evaluation_strategy": "epoch",
        "save_strategy": "no",
        "optim": "adamw_8bit",
        "weight_decay": 0.01,
        "lr_scheduler_type": "cosine",
        "seed": 2026,
        "report_to": "none",
        "dataset_text_field": "text",
        "max_seq_length": max_seq_length,
        "max_length": max_seq_length,
        "packing": False,
    }
    sft_args = instantiate_resilient(SFTConfig, sft_args_dict)
    sft_trainer_kwargs = {
        "model": model,
        "tokenizer": tokenizer,
        "processing_class": tokenizer,
        "train_dataset": ds_sft_tr,
        "eval_dataset": ds_sft_ev,
        "dataset_text_field": "text",
        "max_seq_length": max_seq_length,
        "args": sft_args,
    }
    sft_trainer = instantiate_resilient(SFTTrainer, sft_trainer_kwargs)
    sft_trainer = train_on_responses_only(
        sft_trainer,
        instruction_part="<|im_start|>user\n",
        response_part="<|im_start|>assistant\n",
    )
    print("[Stage 1] Running SFT...")
    sft_trainer.train()

    # 4. Stage 2 — When2Call DPO Preference Tuning
    if dpo_raw and not skip_dpo:
        PatchDPOTrainer()
        from trl import DPOConfig, DPOTrainer

        if hasattr(FastLanguageModel, "for_training"):
            FastLanguageModel.for_training(model)
        else:
            model.train()

        def _fmt_dpo_prompt(rec: Dict[str, Any]) -> Dict[str, str]:
            prompt_msgs = []
            if rec.get("system"):
                prompt_msgs.append({"role": "system", "content": rec["system"]})
            prompt_msgs.append({"role": "user", "content": rec["prompt"]})
            return {
                "prompt": tokenizer.apply_chat_template(prompt_msgs, tokenize=False, add_generation_prompt=True),
                "chosen": f"{rec['chosen']}<|im_end|>\n",
                "rejected": f"{rec['rejected']}<|im_end|>\n",
            }

        ds_dpo = Dataset.from_list([_fmt_dpo_prompt(r) for r in dpo_raw])
        dpo_warmup_steps = max(3, int(0.08 * len(ds_dpo) * epochs_dpo / 16))
        max_p_len = min(2560, max_seq_length - 512)
        dpo_args_dict = {
            "output_dir": str(odir / "dpo_ckpt"),
            "per_device_train_batch_size": 2,
            "gradient_accumulation_steps": 8,
            "warmup_steps": dpo_warmup_steps,
            "num_train_epochs": epochs_dpo,
            "learning_rate": 1e-5,
            "beta": 0.1,
            "fp16": not use_bf16,
            "bf16": use_bf16,
            "logging_steps": 10,
            "save_strategy": "no",
            "optim": "adamw_8bit",
            "lr_scheduler_type": "cosine",
            "seed": 2026,
            "report_to": "none",
            "max_length": max_seq_length,
            "max_prompt_length": max_p_len,
        }
        dpo_args = instantiate_resilient(DPOConfig, dpo_args_dict)
        dpo_trainer_kwargs: Dict[str, Any] = {
            "model": model,
            "ref_model": None,
            "args": dpo_args,
            "train_dataset": ds_dpo,
            "processing_class": tokenizer,
            "tokenizer": tokenizer,
        }
        for extra_k, extra_v in (
            ("beta", 0.1),
            ("max_length", max_seq_length),
            ("max_prompt_length", max_p_len),
        ):
            if not hasattr(dpo_args, extra_k):
                dpo_trainer_kwargs[extra_k] = extra_v
        dpo_trainer = instantiate_resilient(DPOTrainer, dpo_trainer_kwargs)
        print("[Stage 2] Running When2Call DPO...")
        dpo_trainer.train()

    # Save LoRA adapter + GGUF Q4_K_M + Ollama Modelfile
    lora_dir = odir / "lora_adapter"
    model.save_pretrained(str(lora_dir))
    tokenizer.save_pretrained(str(lora_dir))

    gguf_stage_dir = odir / "gguf_raw"
    gguf_stage_dir.mkdir(parents=True, exist_ok=True)
    final_gguf = odir / cfg_prof["gguf_filename"]
    search_roots = [odir, pathlib.Path(f"{gguf_stage_dir}_gguf"), pathlib.Path(".")]

    found_ggufs = find_exported_ggufs(search_roots, final_gguf, export_quant)
    if not final_gguf.exists() and not found_ggufs:
        print(f"[Export] Quantizing & exporting GGUF ({export_quant})...")
        model.save_pretrained_gguf(str(gguf_stage_dir), tokenizer, quantization_method=export_quant)
        found_ggufs = find_exported_ggufs(search_roots, final_gguf, export_quant)
    else:
        print("[Export] Found existing GGUF artifact; skipping redundant conversion.")

    if not final_gguf.exists():
        if found_ggufs:
            shutil.move(str(found_ggufs[0]), str(final_gguf))
        else:
            raise FileNotFoundError(f"Expected exported .gguf in {odir} or {gguf_stage_dir}_gguf, found none.")
    print(f"[Done] Exported GGUF -> {final_gguf} ({final_gguf.stat().st_size / (1024**3):.2f} GB)")

    modelfile_path = odir / "Modelfile"
    write_ollama_modelfile(cfg_prof["gguf_filename"], modelfile_path)
    print(f"[Done] Generated Ollama Modelfile -> {modelfile_path}")
    return final_gguf


def main() -> int:
    parser = argparse.ArgumentParser(description="Train Veraxus Stage 4 model on Colab L4 / CUDA GPU")
    parser.add_argument("--profile", choices=["3b", "7b"], default="3b")
    parser.add_argument("--data-dir", default="training/datasets")
    parser.add_argument("--out-dir", default="training/outputs")
    parser.add_argument("--max-seq-length", type=int, default=3072)
    parser.add_argument("--lora-rank", type=int, default=32)
    parser.add_argument("--epochs-sft", type=int, default=2)
    parser.add_argument("--epochs-dpo", type=int, default=1)
    parser.add_argument("--skip-dpo", action="store_true")
    parser.add_argument("--export-quant", default="q4_k_m")
    args = parser.parse_args()

    train_and_export(
        profile=args.profile,
        data_dir=args.data_dir,
        out_dir=args.out_dir,
        max_seq_length=args.max_seq_length,
        lora_rank=args.lora_rank,
        epochs_sft=args.epochs_sft,
        epochs_dpo=args.epochs_dpo,
        skip_dpo=args.skip_dpo,
        export_quant=args.export_quant,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
