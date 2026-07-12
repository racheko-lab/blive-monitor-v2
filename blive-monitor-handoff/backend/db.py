"""SQLite 访问层（WAL + 全局写锁串行化写）。

设计要点（见 docs/phase4_design.md §1.2 / §7.8）：
  - 同步 SQLAlchemy 2.0 ORM（与现有同步检测逻辑同语言、零冲突）。
  - 启用 WAL + synchronous=NORMAL + foreign_keys=ON。
  - 所有写操作必须持 ``WRITER_LOCK``，杜绝 SQLite 单写者 ``database is locked``。
  - ``get_db()`` 以生成器形式提供每请求 session（session per request）。
"""

import os
import threading
from typing import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker, declarative_base

from . import config


def _make_engine() -> Engine:
    db_path = config.DB_PATH
    parent = os.path.dirname(db_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    # check_same_thread=False 配合 WRITER_LOCK 允许跨线程访问（scheduler 后台线程 + API 线程）。
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
        future=True,
        pool_pre_ping=False,
    )
    return engine


engine: Engine = _make_engine()

# session per request；expire_on_commit=False 避免跨线程/延迟访问触发懒加载异常。
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)

# 所有 ORM 模型基类。
Base = declarative_base()

# 全局写锁：所有 INSERT/UPDATE/DELETE 必须持此锁（见 §7.8）。
WRITER_LOCK = threading.Lock()


def _apply_pragmas(dbapi_conn, _conn_record) -> None:
    """连接建立时应用 PRAGMA（WAL / NORMAL / 外键）。"""
    cur = dbapi_conn.cursor()
    try:
        cur.execute("PRAGMA journal_mode=WAL;")
        cur.execute("PRAGMA synchronous=NORMAL;")
        cur.execute("PRAGMA foreign_keys=ON;")
    finally:
        cur.close()


event.listen(engine, "connect", _apply_pragmas)


def init_db() -> None:
    """建表（幂等）。必须在导入 models 之后调用。"""
    # 延迟导入，避免 models <-> db 的循环导入。
    from . import models  # noqa: F401

    Base.metadata.create_all(engine)


def get_db() -> Iterator:
    """FastAPI 依赖：每请求一个 Session，用完关闭。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
