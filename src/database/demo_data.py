"""
Demo SQLite database in-memory generator for instant testing.
"""

import numpy as np
import pandas as pd
import streamlit as st
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool


@st.cache_resource(show_spinner=False)
def build_demo_engine():
    """Tạo 1 SQLite in-memory với dữ liệu mẫu kinh doanh chocolate 2023,
    để bất kỳ ai cũng test được ngay mà không cần MySQL riêng."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool
    )
    rng = np.random.default_rng(42)

    geo_df = pd.DataFrame({
        "GeoID": ["G1", "G2", "G3"],
        "Geo": ["Ha Noi", "Da Nang", "Ho Chi Minh"],
        "Region": ["North", "Central", "South"],
    })

    people_df = pd.DataFrame({
        "SPID": [f"P{i}" for i in range(1, 7)],
        "Salesperson": ["An", "Binh", "Chi", "Dung", "Em", "Phong"],
        "Team": ["Alpha", "Alpha", "Beta", "Beta", "Gamma", "Gamma"],
        "Location": ["Ha Noi", "Ha Noi", "Da Nang", "Da Nang", "Ho Chi Minh", "Ho Chi Minh"],
    })

    products_df = pd.DataFrame({
        "PID": [f"PR{i}" for i in range(1, 7)],
        "Product": ["Dark 70%", "Milk Classic", "White Choco", "Hazelnut", "Almond", "Orange Zest"],
        "Category": ["Dark", "Milk", "White", "Milk", "Dark", "White"],
        "Size": ["Small", "Medium", "Large", "Medium", "Small", "Medium"],
        "Cost_per_box": [3.5, 2.8, 3.0, 3.2, 3.8, 3.1],
    })

    dates = pd.date_range("2023-01-01", "2023-12-31", freq="3D")
    n = len(dates)
    sales_df = pd.DataFrame({
        "SPID": rng.choice(people_df["SPID"], n),
        "GeoID": rng.choice(geo_df["GeoID"], n),
        "PID": rng.choice(products_df["PID"], n),
        "SaleDate": dates,
        "Amount": rng.integers(2000, 15000, n),
        "Customers": rng.integers(5, 60, n),
        "Boxes": rng.integers(10, 200, n),
    })

    # Tạo 1 điểm bất thường có chủ đích (tháng 6) để test tính năng giải thích outlier
    sales_df.loc[sales_df["SaleDate"].dt.month == 6, "Amount"] *= 3

    geo_df.to_sql("geo", engine, index=False, if_exists="replace")
    people_df.to_sql("people", engine, index=False, if_exists="replace")
    products_df.to_sql("products", engine, index=False, if_exists="replace")
    sales_df.to_sql("sales", engine, index=False, if_exists="replace")
    return engine
