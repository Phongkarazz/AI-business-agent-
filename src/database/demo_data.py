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
    """Tạo 1 SQLite in-memory với dữ liệu mẫu kinh doanh chocolate 2021-2023 đầy đủ,
    để bất kỳ ai cũng test được ngay các câu hỏi Top 10, phân tích theo thị trường (India, USA...),
    team (Yummies, Delish, Jucies), dòng sản phẩm mà không cần MySQL riêng."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool
    )
    rng = np.random.default_rng(42)

    geo_df = pd.DataFrame({
        "GeoID": ["G1", "G2", "G3", "G4", "G5", "G6"],
        "Geo": ["India", "USA", "UK", "Canada", "Australia", "New Zealand"],
        "Region": ["APAC", "Americas", "Europe", "Americas", "APAC", "APAC"],
    })

    people_df = pd.DataFrame({
        "SPID": [f"SP{i:02d}" for i in range(1, 19)],
        "Salesperson": [
            "Barr Faughnan", "Dennison Crosswaite", "Gunar Cockshoot", "Wilone O'Kielt", "Gigi Bohling",
            "Curtice Advani", "Kaine Padly", "Ches Bonnell", "Andria Kimpton", "Brien Boise",
            "Husein Augar", "Ovis Cure", "Mallorie Waber", "Karlen McCaffrey", "Marques Humpage",
            "Van Tuxill", "Maddalena Tripe", "Rafaelita Blaksley"
        ],
        "Team": [
            "Yummies", "Yummies", "Yummies", "Delish", "Delish",
            "Delish", "Delish", "", "Jucies", "Jucies",
            "Jucies", "Delish", "Delish", "Delish", "Delish",
            "Delish", "Yummies", "Yummies"
        ],
        "Location": [
            "Hyderabad", "Hyderabad", "Hyderabad", "Hyderabad", "Hyderabad",
            "Hyderabad", "Hyderabad", "Hyderabad", "Hyderabad", "Wellington",
            "Wellington", "Wellington", "Wellington", "Wellington", "Wellington",
            "Wellington", "Wellington", "Wellington"
        ],
    })

    products_df = pd.DataFrame({
        "PID": [f"P{i:02d}" for i in range(1, 23)],
        "Product": [
            "85% Dark Bars", "70% Dark Bites", "Milk Bars", "Mint Chip Choco", "White Choco",
            "Hazelnut Bites", "Almond Choco", "Orange Zest", "Caramel Stuffed", "Organic Dark",
            "Peanut Butter Bites", "Eclairs", "Fruit & Nut", "Spicy Dark", "Strawberry Bites",
            "Coconut Crunch", "Raspberry Dark", "Sea Salt Caramel", "Toffee Crunch", "Choco Fudge",
            "Dark Truffles", "Vanilla White"
        ],
        "Category": [
            "Bars", "Bites", "Bars", "Other", "Other",
            "Bites", "Other", "Other", "Bars", "Bars",
            "Bites", "Other", "Bars", "Bars", "Bites",
            "Bites", "Bars", "Other", "Bites", "Bars",
            "Other", "Other"
        ],
        "Size": [
            "Large", "Small", "Medium", "Small", "Large",
            "Small", "Medium", "Medium", "Large", "Medium",
            "Small", "Large", "Medium", "Small", "Small",
            "Small", "Medium", "Medium", "Small", "Large",
            "Small", "Medium"
        ],
        "Cost_per_box": [
            3.5, 2.8, 3.0, 3.2, 3.8,
            3.1, 4.0, 2.9, 3.6, 4.2,
            2.5, 3.4, 3.7, 3.9, 2.7,
            3.3, 4.1, 3.5, 2.6, 4.5,
            5.0, 3.0
        ],
    })

    dates = pd.date_range("2021-01-01", "2023-12-31", freq="D")
    n = len(dates) * 3  # ~3,285 transactions
    sales_df = pd.DataFrame({
        "SPID": rng.choice(people_df["SPID"], n),
        "GeoID": rng.choice(geo_df["GeoID"], n),
        "PID": rng.choice(products_df["PID"], n),
        "SaleDate": rng.choice(dates, n),
        "Amount": rng.integers(1500, 18000, n),
        "Customers": rng.integers(5, 75, n),
        "Boxes": rng.integers(15, 350, n),
    }).sort_values("SaleDate").reset_index(drop=True)

    # Điểm bất thường có chủ đích (tháng 6/2021 và tháng 11/2022) để test tính năng outlier / anomaly detection
    sales_df.loc[(sales_df["SaleDate"].dt.year == 2021) & (sales_df["SaleDate"].dt.month == 6), "Amount"] *= 2
    sales_df.loc[(sales_df["SaleDate"].dt.year == 2022) & (sales_df["SaleDate"].dt.month == 11), "Amount"] *= 2

    geo_df.to_sql("geo", engine, index=False, if_exists="replace")
    people_df.to_sql("people", engine, index=False, if_exists="replace")
    products_df.to_sql("products", engine, index=False, if_exists="replace")
    sales_df.to_sql("sales", engine, index=False, if_exists="replace")
    return engine
