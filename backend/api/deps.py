"""API 共享依赖：鉴权 + DB session。

鉴权（设计 §8.7 / §3.3）：``AUTH_TOKEN`` 为空时放行（内网默认无鉴权）；非空时校验请求头
``X-Bearer-Token``。``/healthz`` 与读接口豁免（在各 router 的读路由上不挂本依赖）。
"""

from typing import Iterator

from fastapi import Depends, Header, HTTPException

from .. import config
from ..db import get_db

# 复用 db.get_db（session per request）。
get_db_session = get_db


def require_auth(x_bearer_token: str = Header(None, alias="X-Bearer-Token")) -> bool:
    """写接口鉴权依赖：AUTH_TOKEN 非空时校验 X-Bearer-Token。"""
    if not config.AUTH_TOKEN:
        return True
    if x_bearer_token != config.AUTH_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return True
