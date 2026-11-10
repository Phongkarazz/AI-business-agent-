"""
Dataset Exporter for SFT & DPO Training Formats.
Exports verified synthetic data into standardized machine-learning formats:
- SFT ChatML (OpenAI messages format for Unsloth, LLaMA-Factory, Hugging Face TRL)
- SFT Alpaca (Instruction, Input, Output)
- DPO / ORPO Preference (Prompt, Chosen, Rejected) for When2Call Trilemma Alignment
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import List, Dict, Any
from src.data_gen.generator import SyntheticSample


class DatasetExporter:
    """Công cụ đóng gói và xuất dữ liệu huấn luyện tiêu chuẩn."""

    SYSTEM_PROMPT_DEFAULT = (
        "Bạn là Veraxus, Giám đốc Dữ liệu Điều hành (AI Business Analyst & Text-to-SQL Agent). "
        "Nhiệm vụ của bạn là phân tích câu hỏi kinh doanh, sinh truy vấn SQL chuẩn xác, "
        "chủ động hỏi lại khi thiếu thông tin quan trọng, và từ chối lịch sự khi ngoài phạm vi."
    )

    @classmethod
    def export_sft_chatml(cls, samples: List[SyntheticSample], output_path: str, system_prompt: str = "") -> int:
        """Xuất dữ liệu định dạng ChatML (OpenAI Messages) tiêu chuẩn cho Unsloth / SFTTrainer."""
        sys_p = system_prompt or cls.SYSTEM_PROMPT_DEFAULT
        count = 0
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

        with open(output_path, "w", encoding="utf-8") as f:
            for s in samples:
                # Trả lời của assistant tùy thuộc vào loại mẫu
                assistant_msg = s.target_sql if s.sample_type == "tool_sql" else s.expected_response
                if s.sample_type == "tool_sql" and not assistant_msg.startswith("```"):
                    assistant_msg = f"```sql\n{assistant_msg}\n```"

                record = {
                    "id": s.sample_id,
                    "type": s.sample_type,
                    "category": s.category,
                    "messages": [
                        {"role": "system", "content": sys_p},
                        {"role": "user", "content": s.query_vi},
                        {"role": "assistant", "content": assistant_msg}
                    ]
                }
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
                count += 1

        return count

    @classmethod
    def export_dpo_preference(cls, samples: List[SyntheticSample], output_path: str, system_prompt: str = "") -> int:
        """Xuất dữ liệu định dạng DPO / ORPO (Prompt, Chosen, Rejected) cho tối ưu hóa sở thích (*When2Call*)."""
        sys_p = system_prompt or cls.SYSTEM_PROMPT_DEFAULT
        count = 0
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

        with open(output_path, "w", encoding="utf-8") as f:
            for s in samples:
                # Chỉ xuất các mẫu có cặp chosen & rejected (Type B và Type C)
                if not s.rejected_response:
                    continue

                chosen = s.expected_response
                rejected = s.rejected_response

                record = {
                    "id": s.sample_id,
                    "type": s.sample_type,
                    "category": s.category,
                    "system": sys_p,
                    "prompt": s.query_vi,
                    "chosen": chosen,
                    "rejected": rejected
                }
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
                count += 1

        return count

    @classmethod
    def export_summary_manifest(
        cls,
        samples: List[SyntheticSample],
        output_dir: str,
        execution_time_sec: float = 0.0
    ) -> Dict[str, Any]:
        """Tạo tệp thống kê tổng quan (Manifest) về chất lượng và độ phủ của tập dữ liệu."""
        os.makedirs(output_dir, exist_ok=True)
        manifest_path = os.path.join(output_dir, "manifest.json")

        total = len(samples)
        by_type = {}
        t1_pass = 0
        t2_pass = 0
        t3_pass = 0

        for s in samples:
            by_type[s.sample_type] = by_type.get(s.sample_type, 0) + 1
            if s.verification:
                if s.verification.tier1_syntax_ok:
                    t1_pass += 1
                if s.verification.tier2_execution_ok:
                    t2_pass += 1
                if s.verification.tier3_semantic_ok:
                    t3_pass += 1

        manifest = {
            "created_at": datetime.now().isoformat(),
            "pipeline": "Veraxus APIGen 3-Tier + Hammer Masking Engine",
            "total_samples": total,
            "distribution_by_type": by_type,
            "verification_metrics": {
                "tier1_syntax_pass_rate": f"{(t1_pass / max(1, by_type.get('tool_sql', 1))) * 100:.1f}%",
                "tier2_execution_pass_rate": f"{(t2_pass / max(1, by_type.get('tool_sql', 1))) * 100:.1f}%",
                "tier3_semantic_pass_rate": f"{(t3_pass / max(1, by_type.get('tool_sql', 1))) * 100:.1f}%",
            },
            "generation_time_sec": round(execution_time_sec, 2)
        }

        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)

        return manifest

    @classmethod
    def inject_into_memory_bank(cls, samples: List[SyntheticSample]) -> int:
        """Nạp trực tiếp các mẫu dữ liệu đã qua kiểm định APIGen vào Ngân hàng Tri thức Động của Veraxus (agent_memory.db).
        
        Giúp Veraxus lập tức 'thông minh lên' ngay tại chỗ mà KHÔNG CẦN train lại mô hình!
        Các câu hỏi tiếp theo của người dùng trên Chat/Dashboard sẽ tự động trích xuất các mẫu này làm Dynamic Few-Shot Exemplars.
        """
        try:
            from src.llm.dynamic_memory import save_learned_case, infer_domain_from_context
            count = 0
            for s in samples:
                if s.sample_type == "tool_sql" and s.target_sql and s.verification and s.verification.is_valid:
                    domain = infer_domain_from_context(s.query_vi, s.target_sql)
                    save_learned_case(
                        user_query=s.query_vi,
                        sql_query=s.target_sql,
                        intent_explanation=f"APIGen Verified ({s.category})",
                        domain=domain,
                        source="apigen_datagen",
                        evaluator_score=100,
                        rating=1
                    )
                    count += 1
            return count
        except Exception:
            return 0

