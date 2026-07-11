"""Config API：BLIVE_CONFIG 读写。前缀 /config（挂载于 /api/v1）。"""

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..config_store import ConfigStore
from .deps import get_db_session, require_auth

router = APIRouter(prefix="/config", tags=["config"])


@router.get("")
def get_config(db: Session = Depends(get_db_session)) -> Any:
    return ConfigStore().get_config()


@router.put("", dependencies=[Depends(require_auth)])
def put_config(payload: dict):
    updated_at = ConfigStore().put_config(payload)
    return {"updated_at": updated_at}
