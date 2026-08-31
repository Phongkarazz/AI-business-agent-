"""
Analytics package for column heuristics, statistical forecasting, anomaly detection, language detection,
starter prompts, and multi-format reporting export (Excel, PNG, PDF).
"""

from .heuristics import (
    is_id_like,
    find_time_column,
    has_time_dimension,
    get_axis_columns,
    get_row_identity_column,
    get_best_name_column,
    pick_label_column,
    generate_starter_prompts,
    detect_query_language,
)
from .forecasting import forecast_series
from .anomaly import detect_outliers, analyze_data_anomalies
from .export_reports import export_to_excel, export_to_png, export_to_pdf

__all__ = [
    "is_id_like",
    "find_time_column",
    "has_time_dimension",
    "get_axis_columns",
    "get_row_identity_column",
    "get_best_name_column",
    "pick_label_column",
    "generate_starter_prompts",
    "detect_query_language",
    "forecast_series",
    "detect_outliers",
    "analyze_data_anomalies",
    "export_to_excel",
    "export_to_png",
    "export_to_pdf",
]
