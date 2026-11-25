"""Unit tests for Stage 4 execution-verified training pipeline & Colab/Ollama artifacts."""

from __future__ import annotations

import ast
import csv
import gzip
import json
import pathlib
import random
import re
import sqlite3
import tempfile
import unittest

from datamate.llm_backend import extract_json_object
from datamate.loader import load_business_workspace
from datamate.schema_context import _annotate_optional_directory_edge, build_workspace_knowledge
from datamate.splits import VAL_BUSINESS_SET
from datamate.sql_executor import execute_sql_safe
from datamate.stage4_dataset_builder import mask_workspace_and_sql
from src.config import PROVIDER_CONFIGS
from training.train_colab_l4 import (
    MODEL_PROFILES,
    _filter_kwargs_for,
    find_exported_ggufs,
    instantiate_resilient,
    load_jsonl_any,
    resolve_dataset_file,
    write_ollama_modelfile,
)


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
TRAINING_DIR = REPO_ROOT / "training"
DATASETS_DIR = TRAINING_DIR / "datasets"


class TestStage4TrainingPipeline(unittest.TestCase):
    def test_ollama_provider_lists_veraxus_finetuned_tags(self) -> None:
        models = PROVIDER_CONFIGS["Ollama (Local AI Offline)"]["models"]
        self.assertIn("veraxus-coder:3b", models)
        self.assertIn("veraxus-coder:7b", models)
        self.assertIn("qwen2.5-coder:3b", models)

    def test_colab_notebook_valid_json_and_python_cells(self) -> None:
        nb_path = TRAINING_DIR / "Veraxus_Stage4_Colab_L4_Train.ipynb"
        self.assertTrue(nb_path.exists(), f"Missing notebook: {nb_path}")
        nb = json.loads(nb_path.read_text(encoding="utf-8"))
        self.assertEqual(nb.get("nbformat"), 4)
        code_cells = [c for c in nb.get("cells", []) if c.get("cell_type") == "code"]
        self.assertGreaterEqual(len(code_cells), 6)
        for idx, cell in enumerate(code_cells):
            src_lines = cell.get("source", [])
            src = "".join(src_lines) if isinstance(src_lines, list) else str(src_lines)
            clean = "\n".join(
                line for line in src.splitlines() if not line.lstrip().startswith(("!", "%"))
            )
            ast.parse(clean, filename=f"colab_cell_{idx}.py")

    def test_train_script_helpers_and_modelfile_template(self) -> None:
        self.assertIn("3b", MODEL_PROFILES)
        self.assertIn("7b", MODEL_PROFILES)
        self.assertTrue((TRAINING_DIR / "Modelfile.template").exists())
        self.assertTrue((TRAINING_DIR / "import_to_ollama.sh").exists())
        self.assertTrue((TRAINING_DIR / "README.md").exists())

        def _dummy(alpha: int, beta: str = "x") -> None:
            pass

        filtered = _filter_kwargs_for(_dummy, {"alpha": 1, "gamma": 99})
        self.assertEqual(filtered, {"alpha": 1})

        with tempfile.TemporaryDirectory() as tmp:
            tpath = pathlib.Path(tmp)
            mf = tpath / "Modelfile"
            write_ollama_modelfile("veraxus-coder-3b-q4_k_m.gguf", mf)
            text = mf.read_text(encoding="utf-8")
            self.assertIn("FROM ./veraxus-coder-3b-q4_k_m.gguf", text)
            self.assertIn("<|im_start|>assistant", text)
            self.assertIn("PARAMETER num_ctx 8192", text)

            gz_path = tpath / "sample.jsonl.gz"
            with gzip.open(gz_path, "wt", encoding="utf-8") as fh:
                fh.write(json.dumps({"k": 1}) + "\n")
            self.assertEqual(resolve_dataset_file(tpath, "sample"), gz_path)
            self.assertEqual(load_jsonl_any(gz_path), [{"k": 1}])

    def test_optional_directory_edge_annotation(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE ban_hang (phong TEXT, tien INTEGER)")
        conn.execute("CREATE TABLE danh_sach_phong (phong TEXT, gia INTEGER)")
        conn.executemany(
            "INSERT INTO ban_hang VALUES (?, ?)",
            [("P.01", 100), ("P.02", 200), ("P.99", 300)],
        )
        conn.executemany(
            "INSERT INTO danh_sach_phong VALUES (?, ?)",
            [("P.01", 10), ("P.02", 20)],
        )
        hint = _annotate_optional_directory_edge(conn, "ban_hang", "phong", "danh_sach_phong", "phong")
        self.assertIn("LEFT JOIN", hint)

        conn.execute("INSERT INTO danh_sach_phong VALUES ('P.99', 30)")
        hint_full = _annotate_optional_directory_edge(conn, "ban_hang", "phong", "danh_sach_phong", "phong")
        self.assertNotIn("LEFT JOIN", hint_full)

    def test_hammer_mask_workspace_and_sql_preserves_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            troot = pathlib.Path(tmp)
            ws_dir = troot / "shop"
            ws_dir.mkdir(parents=True, exist_ok=True)
            with (ws_dir / "don_hang.csv").open("w", newline="", encoding="utf-8") as fh:
                w = csv.writer(fh)
                w.writerow(["ma_don", "ngay", "ten_hang", "thanh_tien", "trang_thai"])
                w.writerow(["D1", "2026-04-01", "Cà phê sữa", "35000", "Hoàn thành"])
                w.writerow(["D2", "2026-04-02", "Trà đào", "40000", "Hoàn thành"])
                w.writerow(["D3", "2026-04-03", "Cà phê sữa", "35000", "Đã hủy"])

            ws = load_business_workspace(ws_dir, cache_dir=troot / "cache")
            sql = (
                "SELECT ROUND_HALF_UP(SUM(f.thanh_tien), 0) AS doanh_thu "
                "FROM don_hang f WHERE f.trang_thai != 'Đã hủy';"
            )
            orig = execute_sql_safe(ws.open_connection, sql, max_rows=50)
            self.assertTrue(orig.ok)
            self.assertEqual(orig.rows[0][0], 75000)

            masked = mask_workspace_and_sql(
                ws, sql, random.Random(42), troot / "masked", tag="unit"
            )
            self.assertIsNotNone(masked)
            _, _, m_sql, m_res = masked  # type: ignore[misc]
            self.assertNotIn("thanh_tien", m_sql)
            self.assertEqual(m_res.rows[0][0], orig.rows[0][0])

    def test_stage4_generated_datasets_and_zero_leakage(self) -> None:
        manifest_path = DATASETS_DIR / "manifest.json"
        self.assertTrue(manifest_path.exists(), f"Missing manifest: {manifest_path}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        self.assertEqual(manifest.get("val_leakage_count"), 0)
        self.assertGreaterEqual(manifest.get("sft_train_count", 0) + manifest.get("sft_eval_count", 0), 60)
        self.assertGreaterEqual(manifest.get("dpo_count", 0), 30)

        for fname in (
            "veraxus_sft_train.jsonl.gz",
            "veraxus_sft_eval.jsonl.gz",
            "veraxus_dpo_when2call.jsonl.gz",
        ):
            fpath = DATASETS_DIR / fname
            self.assertTrue(fpath.exists(), f"Missing dataset archive: {fpath}")
            self.assertLess(fpath.stat().st_size, 5 * 1024 * 1024)

        sft_train = load_jsonl_any(DATASETS_DIR / "veraxus_sft_train.jsonl.gz")
        sft_eval = load_jsonl_any(DATASETS_DIR / "veraxus_sft_eval.jsonl.gz")
        dpo_rows = load_jsonl_any(DATASETS_DIR / "veraxus_dpo_when2call.jsonl.gz")

        for rec in sft_train + sft_eval:
            bid = str(rec.get("business_id", ""))
            self.assertNotIn(bid, VAL_BUSINESS_SET)
            self.assertIsNone(re.match(r"^biz_\d+$", bid), f"Unexpected competition id: {bid}")
            msgs = rec.get("messages", [])
            self.assertEqual([m["role"] for m in msgs], ["system", "user", "assistant"])
            parsed = extract_json_object(msgs[2]["content"])
            self.assertIsNotNone(parsed, f"Invalid JSON in SFT {rec.get('id')}")
            self.assertIn(parsed.get("status"), ("ok", "unanswerable"))

        for rec in dpo_rows:
            bid = str(rec.get("business_id", ""))
            self.assertNotIn(bid, VAL_BUSINESS_SET)
            self.assertIsNone(re.match(r"^biz_\d+$", bid), f"Unexpected competition id: {bid}")
            self.assertTrue(rec.get("prompt"))
            self.assertNotEqual(rec.get("chosen"), rec.get("rejected"))
            self.assertIsNotNone(extract_json_object(rec["chosen"]))
            self.assertIsNotNone(extract_json_object(rec["rejected"]))

    def test_no_sensitive_competition_or_personal_strings(self) -> None:
        forbidden = (
            "Lưu " + "Kim Huệ",
            "Diệp " + "Trang An",
            "Zalo " + "AI Challenge",
            "Datamate_" + "regulations",
            "private_" + "test",
            "/Users/" + "phongha",
        )
        targets = [
            DATASETS_DIR / "manifest.json",
            TRAINING_DIR / "README.md",
            REPO_ROOT / "datamate" / "evaluator_pa.py",
            REPO_ROOT / "datamate" / "stage4_dataset_builder.py",
            REPO_ROOT / "tests" / "test_veraxus_ui_and_query_fixes.py",
            REPO_ROOT / "tests" / "test_stage2_hybrid_engine.py",
        ]
        for p in targets:
            txt = p.read_text(encoding="utf-8")
            for term in forbidden:
                self.assertNotIn(term, txt, f"Found {term!r} in {p}")

    def test_ollama_veraxus_coder_fallback_to_qwen_base(self) -> None:
        from types import SimpleNamespace
        from src.llm.client import _call_openai_compatible_impl

        called_models = []

        class _FakeCompletions:
            def create(self, **kwargs):
                called_models.append(kwargs["model"])
                if kwargs["model"] == "veraxus-coder:3b":
                    raise RuntimeError("Error code: 404 - model 'veraxus-coder:3b' not found")
                return SimpleNamespace(
                    choices=[SimpleNamespace(message=SimpleNamespace(content='{"status":"ok","sql":"SELECT 1;"}'))]
                )

        fake_client = SimpleNamespace(
            base_url="http://localhost:11434/v1",
            chat=SimpleNamespace(completions=_FakeCompletions()),
        )
        out = _call_openai_compatible_impl(
            fake_client, "veraxus-coder:3b", "ping", is_ollama=True
        )
        self.assertEqual(called_models, ["veraxus-coder:3b", "qwen2.5-coder:3b"])
        self.assertIn("SELECT 1", out)

    def test_unsloth_context_parallel_patched_init_and_resilient_instantiation(self) -> None:
        class _FakeDPOTrainer:
            def __init__(
                self,
                model,
                ref_model=None,
                args=None,
                train_dataset=None,
                processing_class=None,
            ) -> None:
                self.model = model
                self.ref_model = ref_model
                self.args = args
                self.train_dataset = train_dataset
                self.processing_class = processing_class

        original_init = _FakeDPOTrainer.__init__

        # Simulate Unsloth context_parallel wrapper without @functools.wraps
        def patched_init(self, *args, **kwargs):
            return original_init(self, *args, **kwargs)

        _FakeDPOTrainer.__init__ = patched_init  # type: ignore[method-assign]

        raw = {
            "model": "m",
            "ref_model": None,
            "args": "cfg",
            "train_dataset": [1, 2],
            "processing_class": "tok",
            "tokenizer": "tok",
            "beta": 0.1,
            "max_length": 3072,
            "max_prompt_length": 2560,
        }
        filtered = _filter_kwargs_for(_FakeDPOTrainer, raw)
        self.assertEqual(
            set(filtered.keys()),
            {"model", "ref_model", "args", "train_dataset", "processing_class"},
        )
        trainer = instantiate_resilient(_FakeDPOTrainer, raw)
        self.assertEqual(trainer.model, "m")
        self.assertEqual(trainer.processing_class, "tok")

        class _StrictLegacy:
            def __init__(self, model, tokenizer=None, **kwargs) -> None:
                if "processing_class" in kwargs:
                    raise TypeError("unexpected keyword argument 'processing_class'")
                self.model = model
                self.tokenizer = tokenizer

        legacy = instantiate_resilient(
            _StrictLegacy,
            {"model": "m", "processing_class": "tok", "tokenizer": "tok", "beta": 0.1},
        )
        self.assertEqual(legacy.tokenizer, "tok")

    def test_find_exported_ggufs_handles_unsloth_raw_gguf_sibling_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            troot = pathlib.Path(tmp)
            export_dir = troot / "veraxus_export"
            raw_dir = export_dir / "raw"
            sibling_dir = export_dir / "raw_gguf"
            raw_dir.mkdir(parents=True)
            sibling_dir.mkdir(parents=True)

            bf16 = sibling_dir / "Qwen2.5-Coder-3B-Instruct.BF16.gguf"
            q4 = sibling_dir / "Qwen2.5-Coder-3B-Instruct.Q4_K_M.gguf"
            bf16.write_bytes(b"bf16" * 100)
            q4.write_bytes(b"q4km" * 50)
            final_gguf = export_dir / "veraxus-coder-3b-q4_k_m.gguf"

            cands = find_exported_ggufs(
                [export_dir, pathlib.Path(f"{raw_dir}_gguf")],
                final_gguf,
                export_quant="q4_k_m",
            )
            self.assertEqual(len(cands), 1)
            self.assertEqual(cands[0].name, "Qwen2.5-Coder-3B-Instruct.Q4_K_M.gguf")


if __name__ == "__main__":
    unittest.main()
