"""
Analytics package for column heuristics, statistical forecasting, and anomaly detection.
"""

from .heuristics import (
    is_id_like,
    find_time_column,
    has_time_dimension,
    get_axis_columns,
    get_row_identity_column,
    pick_label_column,
)
from .forecasting import forecast_series
from .anomaly import detect_outliers

__all__ = [
    "is_id_like",
    "find_time_column",
    "has_time_dimension",
    "get_axis_columns",
    "get_row_identity_column",
    "pick_label_column",
    "forecast_series",
    "detect_outliers",
]
