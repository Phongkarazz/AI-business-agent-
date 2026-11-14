"""
DataMate isolated runner and tooling package inside Veraxus.

This package implements messy spreadsheet/SQLite ingestion, Vietnamese temporal
and solar-lunar calendar resolution, Penalized Accuracy (PA) evaluation, and the
headless DataMate agent without altering Veraxus's existing Streamlit UI or
core SQL pipeline.
"""

__all__ = [
    "agent",
    "evaluator_pa",
    "llm_backend",
    "loader",
    "run_eval",
    "schema_context",
    "splits",
    "sql_executor",
    "temporal",
]
