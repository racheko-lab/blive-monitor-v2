"""Silence API：静默状态读写。前缀 /silence/state（挂载于 /api/v1）。"""

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import schemas
from ..config_store import ConfigStore
from .deps import get_db_session, require_auth

router = APIRouter(prefix="/silence", tags=["silence"])


@router.get("/state", response_model=schemas.SilenceStateOut)
def get_silence_state(db: Session = Depends(get_db_session)):
    state = ConfigStore().get_silence_state()
    return schemas.SilenceStateOut(**state)


@router.put("/state", response_model=schemas.SilenceStateOut, dependencies=[Depends(require_auth)])
def put_silence_state(payload: dict):
    state = ConfigStore().put_silence_state(payload)
    return schemas.SilenceStateOut(**state)
