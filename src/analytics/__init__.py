"""
Analytics package for column heuristics, statistical forecasting, anomaly detection, and starter prompts.
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
)
from .forecasting import forecast_series
from .anomaly import detect_outliers, analyze_data_anomalies

__all__ = [
    "is_id_like",
    "find_time_column",
    "has_time_dimension",
    "get_axis_columns",
    "get_row_identity_column",
    "get_best_name_column",
    "pick_label_column",
    "generate_starter_prompts",
    "forecast_series",
    "detect_outliers",
    "analyze_data_anomalies",
]
