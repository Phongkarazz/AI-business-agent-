"""
Outlier and anomaly detection using IQR (Interquartile Range).
"""

import pandas as pd


def detect_outliers(df: pd.DataFrame, y_col: str) -> pd.DataFrame:
    """Phát hiện các điểm bất thường (outlier) theo phương pháp IQR trên cột số được chọn."""
    if df is None or df.empty or y_col not in df.columns:
        return pd.DataFrame()

    try:
        numeric_series = pd.to_numeric(df[y_col], errors="coerce").dropna()
        if len(numeric_series) < 4:
            return df.iloc[0:0]

        q1, q3 = numeric_series.quantile([0.25, 0.75])
        iqr = q3 - q1
        if iqr == 0:
            return df.iloc[0:0]

        lower, upper = q1 - 1.5 * iqr, q3 + 1.5 * iqr
        return df[(df[y_col] < lower) | (df[y_col] > upper)]
    except Exception:
        return df.iloc[0:0]
