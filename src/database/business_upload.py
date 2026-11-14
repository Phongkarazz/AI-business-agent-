"""Helpers for loading CSV/Excel/SQLite business workspaces into Veraxus with DataMate hardening."""

from __future__ import annotations

import pathlib
import re
import shutil
import sqlite3
from typing import Iterable, Optional, Tuple

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool

from datamate.loader import (
    BusinessWorkspace,
    _profile_existing_sqlite,
    load_business_workspace,
    normalize_nfc,
)
from datamate.schema_context import WorkspaceKnowledge, build_workspace_knowledge
from datamate.sql_executor import norm_vn, round_half_up

_PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
UPLOAD_WORKSPACES_ROOT = _PROJECT_ROOT / "data" / "uploaded_workspaces"
WORKSPACE_CACHE_ROOT = UPLOAD_WORKSPACES_ROOT / "_sqlite_cache"
ALLOWED_UPLOAD_EXTENSIONS = {".csv", ".xlsx", ".sqlite", ".db", ".md"}


def attach_datamate_sqlite_udfs(engine: Engine) -> Engine:
    """Register NORM_VN and ROUND_HALF_UP SQLite UDFs on a SQLAlchemy SQLite engine."""
    if engine is None or "sqlite" not in str(engine.url).lower():
        return engine
    if getattr(engine, "_datamate_udfs_attached", False):
        return engine

    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_conn, _conn_record):  # pragma: no cover - verified via query execution
        try:
            dbapi_conn.create_function("NORM_VN", 1, lambda s: norm_vn(str(s)) if s is not None else "")
            dbapi_conn.create_function("ROUND_HALF_UP", 2, round_half_up)
        except sqlite3.Error:
            pass

    setattr(engine, "_datamate_udfs_attached", True)
    return engine


def _slugify_name(name: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "_", (name or "").strip()).strip("_").lower()
    return cleaned or "custom_business"


def save_uploaded_business_files(
    uploaded_files: Iterable,
    workspace_name: str = "uploaded_business",
) -> pathlib.Path:
    """Persist Streamlit uploaded CSV/XLSX/SQLite/README files cleanly into data/uploaded_workspaces/."""
    slug = _slugify_name(workspace_name)
    target_dir = UPLOAD_WORKSPACES_ROOT / slug
    if target_dir.exists():
        shutil.rmtree(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    saved_count = 0
    for fobj in uploaded_files or []:
        raw_name = pathlib.Path(str(getattr(fobj, "name", ""))).name
        if not raw_name:
            continue
        ext = pathlib.Path(raw_name).suffix.lower()
        if ext not in ALLOWED_UPLOAD_EXTENSIONS:
            continue
        data = fobj.getvalue() if hasattr(fobj, "getvalue") else fobj.read()
        (target_dir / raw_name).write_bytes(data)
        saved_count += 1

    if saved_count == 0:
        raise ValueError("Không có file hợp lệ (.csv, .xlsx, .sqlite, .db, .md) được tải lên.")
    return target_dir


def build_datamate_workspace_engine(
    workspace_dir: str | pathlib.Path,
    force_rebuild: bool = False,
) -> Tuple[Engine, WorkspaceKnowledge]:
    """
    Ingest a business directory (CSV/XLSX/SQLite + optional README.md) via DataMate loader,
    build a read-queryable SQLAlchemy SQLite engine with UDFs, and profile WorkspaceKnowledge.
    """
    bdir = pathlib.Path(workspace_dir)
    if not bdir.exists() or not bdir.is_dir():
        raise FileNotFoundError(f"Thư mục dữ liệu không tồn tại: {bdir}")

    WORKSPACE_CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    ws = load_business_workspace(bdir, cache_dir=WORKSPACE_CACHE_ROOT, force_rebuild=force_rebuild)
    if not ws.tables:
        raise ValueError(f"Không tìm thấy bảng dữ liệu hợp lệ nào trong `{bdir.name}`.")

    knowledge = build_workspace_knowledge(ws)
    engine = create_engine(
        f"sqlite:///{ws.db_path}",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    attach_datamate_sqlite_udfs(engine)
    return engine, knowledge


def build_knowledge_from_sqlite_path(
    db_path: str | pathlib.Path,
    readme_text: str = "",
) -> Optional[WorkspaceKnowledge]:
    """Profile an existing standalone SQLite file (e.g., data/yen_sao.db) into WorkspaceKnowledge."""
    p = pathlib.Path(db_path)
    if not p.exists():
        return None
    profiles = _profile_existing_sqlite(
        p,
        source_files=[normalize_nfc(p.name)],
        notes=["sqlite_direct"],
    )
    if not profiles:
        return None
    ws = BusinessWorkspace(
        business_id=p.stem,
        business_dir=p.parent,
        db_path=p,
        readme_text=readme_text,
        tables=profiles,
        source_kind="sqlite_direct",
    )
    return build_workspace_knowledge(ws)


def describe_database_target(
    *,
    use_demo: bool,
    db_host: str,
    db_port: str,
    db_name: str,
    custom_workspace_dir: str = "",
) -> str:
    """Return a user-friendly label for the selected database connection target."""
    ws_dir = (custom_workspace_dir or "").strip()
    if ws_dir:
        return f"DataMate Workspace ({pathlib.Path(ws_dir).name})"
    if use_demo:
        demo_type = "yen_sao" if "yen" in (db_name or "").lower() else "chocolate"
        return "SQLite Yến Sào Demo" if demo_type == "yen_sao" else "SQLite In-Memory Demo"
    return f"MySQL ({db_host}:{db_port})"


def compose_connection_schema(
    extracted_schema: str,
    schema_context_input: str = "",
    knowledge: Optional[WorkspaceKnowledge] = None,
) -> str:
    """Merge extracted SQL schema, optional business notes, and DataMate semantic knowledge."""
    final_schema = extracted_schema
    custom_notes = (schema_context_input or "").strip()
    if (
        custom_notes
        and not custom_notes.startswith("Cơ sở dữ liệu bao gồm")
        and custom_notes != extracted_schema
    ):
        final_schema = f"{final_schema}\n\n=== GHI CHÚ NGHIỆP VỤ BỔ SUNG ===\n{custom_notes}"
    if knowledge is not None and getattr(knowledge, "semantic_summary", ""):
        final_schema = f"{final_schema}\n\n=== DATAMATE SEMANTIC KNOWLEDGE ===\n{knowledge.semantic_summary}"
    return final_schema


def resolve_database_connection(
    *,
    use_demo: bool,
    db_host: str,
    db_port: str,
    db_user: str,
    db_pass: str,
    db_name: str,
    use_ssl: bool,
    run_local: bool = False,
    custom_workspace_dir: str = "",
) -> Tuple[Engine, Optional[WorkspaceKnowledge], str, str, bool]:
    """
    Shared connector resolving either an uploaded DataMate workspace, a built-in SQLite demo,
    or a live MySQL database. Returns (engine, knowledge, dialect, description, is_demo).
    """
    desc = describe_database_target(
        use_demo=use_demo,
        db_host=db_host,
        db_port=db_port,
        db_name=db_name,
        custom_workspace_dir=custom_workspace_dir,
    )
    ws_dir = (custom_workspace_dir or "").strip()
    if ws_dir:
        engine, knowledge = build_datamate_workspace_engine(ws_dir)
        return engine, knowledge, "SQLite", desc, False

    if use_demo:
        from src.database.demo_data import build_demo_engine

        demo_type = "yen_sao" if "yen" in (db_name or "").lower() else "chocolate"
        engine = build_demo_engine(demo_type=demo_type)
        if demo_type == "yen_sao":
            yen_path = _PROJECT_ROOT / "data" / "yen_sao.db"
            knowledge = build_knowledge_from_sqlite_path(
                yen_path,
                readme_text="Cơ sở dữ liệu kinh doanh Yến Sào Khánh Hòa (sản phẩm, khách hàng, đơn hàng, chi tiết đơn hàng).",
            )
            return engine, knowledge, "SQLite", desc, True
        return engine, None, "SQLite", desc, True

    from src.database.connection import try_connect

    engine = try_connect(db_host, db_port, db_user, db_pass, db_name, use_ssl, run_local=run_local)
    return engine, None, "MySQL", desc, False

