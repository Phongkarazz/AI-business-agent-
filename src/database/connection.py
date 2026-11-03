"""
Database connection management for MySQL and other SQLAlchemy-supported databases.
"""

from urllib.parse import quote_plus
from sqlalchemy import create_engine, text
from src.config import LOCAL_HOST_ALIASES


def try_connect_single(host: str, port_int: int, user: str, pw: str, name: str, use_ssl: bool):
    """Thử kết nối tới một host/port MySQL cụ thể."""
    connect_args = {"connection_timeout": 6}
    if use_ssl:
        connect_args["ssl_disabled"] = False
    engine = create_engine(
        f"mysql+mysqlconnector://{user}:{quote_plus(pw)}@{host}:{port_int}/{name}",
        connect_args=connect_args,
        pool_pre_ping=True,
        pool_recycle=3600,
    )
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return engine


def try_connect(host: str, port: str, user: str, pw: str, name: str, use_ssl: bool, run_local: bool = False):
    """Kết nối MySQL có hỗ trợ thử lại với các alias localhost khi chạy môi trường local/docker."""
    host = (host or "").strip()
    port_str = "".join(ch for ch in str(port) if ch.isdigit())
    if not port_str:
        raise ValueError(f"Port không hợp lệ: '{port}'. Vui lòng chỉ nhập số (VD: 3306).")
    port_int = int(port_str)

    # Thử lần lượt các alias khi run_local bật hoặc khi host là localhost / trống
    if run_local or not host or host.lower() in ("localhost", "127.0.0.1"):
        candidate_hosts = ["localhost", "127.0.0.1"]
        # Chỉ bổ sung host.docker.internal nếu host được chỉ định tường minh hoặc đang chạy trong container Docker
        import os
        if host == "host.docker.internal" or os.path.exists("/.dockerenv") or os.environ.get("IS_DOCKER"):
            candidate_hosts.append("host.docker.internal")
        if host and host not in candidate_hosts:
            candidate_hosts = [host] + candidate_hosts
    else:
        candidate_hosts = [host]

    last_error = None
    for candidate in candidate_hosts:
        try:
            return try_connect_single(candidate, port_int, user, pw, name, use_ssl)
        except Exception as e:
            err_msg = str(e)
            # 1049: Unknown database - CSDL chưa được tạo trong MySQL
            if "1049" in err_msg or "unknown database" in err_msg.lower():
                raise RuntimeError(
                    f"Cơ sở dữ liệu '{name}' chưa tồn tại trong MySQL ({candidate}:{port_int}). "
                    f"Vui lòng tạo database '{name}' và nạp dữ liệu trước (hoặc chạy lệnh: python3 import_yen_sao_mysql.py)."
                ) from e
            # 1045: Access denied - Sai user hoặc password
            if "1045" in err_msg or "access denied" in err_msg.lower():
                raise RuntimeError(
                    f"Sai tên tài khoản hoặc mật khẩu MySQL (User: '{user}'). "
                    f"Vui lòng kiểm tra lại mật khẩu kết nối."
                ) from e
            last_error = e
            continue

    if last_error:
        err_str = str(last_error)
        if "2003" in err_str or "2005" in err_str or "can't connect" in err_str.lower() or "unknown mysql server" in err_str.lower():
            raise RuntimeError(
                f"Không thể kết nối tới MySQL server tại '{host or 'localhost'}:{port_int}'. "
                f"Vui lòng kiểm tra dịch vụ MySQL đã được bật chưa (ví dụ: brew services start mysql hoặc kiểm tra Docker/XAMPP)."
            ) from last_error
    raise last_error

