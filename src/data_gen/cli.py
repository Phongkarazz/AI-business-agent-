"""
Command-Line Interface (CLI) for Veraxus Data Generation.
Allows automated, batch synthetic dataset creation for fine-tuning & evaluation.

Usage:
    python -m src.data_gen.cli --samples 50 --masking --output data/synthetic_train
"""

import argparse
import sys
import time
from src.database.demo_data import build_demo_engine
from src.data_gen.generator import SyntheticDataGenerator
from src.data_gen.verifier import APIGenVerifier
from src.data_gen.masking import SchemaMasker
from src.data_gen.exporter import DatasetExporter


def main():
    parser = argparse.ArgumentParser(description="Veraxus Synthetic Data Generation Pipeline (APIGen + Hammer)")
    parser.add_argument("--samples", type=int, default=30, help="Số lượng mẫu cần sinh (mặc định: 30)")
    parser.add_argument("--masking", action="store_true", help="Bật Hammer Schema Masking để chống học vẹt")
    parser.add_argument("--output", type=str, default="data/synthetic_train", help="Thư mục xuất file dataset")
    args = parser.parse_args()

    print(f"\n🚀 [Veraxus Data Gen] Đang khởi chạy pipeline APIGen 3-Tier...")
    print(f"📊 Cấu hình: {args.samples} mẫu | Schema Masking: {args.masking} | Thư mục: {args.output}")

    engine = build_demo_engine()
    verifier = APIGenVerifier(engine)
    masker = SchemaMasker(engine)
    gen = SyntheticDataGenerator(engine, verifier=verifier, masker=masker)

    start_t = time.perf_counter()
    samples = gen.generate_batch(num_samples=args.samples, apply_masking=args.masking)
    elapsed = time.perf_counter() - start_t

    sft_file = f"{args.output}/sft_chatml.jsonl"
    dpo_file = f"{args.output}/dpo_preference.jsonl"

    n_sft = DatasetExporter.export_sft_chatml(samples, sft_file)
    n_dpo = DatasetExporter.export_dpo_preference(samples, dpo_file)
    manifest = DatasetExporter.export_summary_manifest(samples, args.output, execution_time_sec=elapsed)

    print(f"\n✅ [Hoàn tất trong {elapsed:.2f}s]!")
    print(f"  - Xuất {n_sft} mẫu SFT ChatML: {sft_file}")
    print(f"  - Xuất {n_dpo} mẫu DPO Preference: {dpo_file}")
    print(f"  - Thống kê tỷ lệ pass Tier 1 Syntax: {manifest['verification_metrics']['tier1_syntax_pass_rate']}")
    print(f"  - Thống kê tỷ lệ pass Tier 2 Sandbox: {manifest['verification_metrics']['tier2_execution_pass_rate']}")
    print(f"  - Thống kê tỷ lệ pass Tier 3 Semantic: {manifest['verification_metrics']['tier3_semantic_pass_rate']}")
    print(f"  - Chi tiết manifest lưu tại: {args.output}/manifest.json\n")


if __name__ == "__main__":
    main()
