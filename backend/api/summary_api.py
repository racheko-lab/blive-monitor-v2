"""Summary API：摘要状态读写。前缀 /summary/state（挂载于 /api/v1）。"""

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import schemas
from ..config_store import ConfigStore
from .deps import get_db_session, require_auth

router = APIRouter(prefix="/summary", tags=["summary"])


@router.get("/state", response_model=schemas.SummaryStateOut)
def get_summary_state(db: Session = Depends(get_db_session)):
    state = ConfigStore().get_summary_state()
    return schemas.SummaryStateOut(**state)


@router.put("/state", response_model=schemas.SummaryStateOut, dependencies=[Depends(require_auth)])
def put_summary_state(payload: dict):
    state = ConfigStore().put_summary_state(payload)
    return schemas.SummaryStateOut(**state)
