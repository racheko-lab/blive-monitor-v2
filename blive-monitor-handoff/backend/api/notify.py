"""Notify API：通知账本记录 + 去重查询/标记。前缀 /notify（挂载于 /api/v1）。"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import schemas
from ..core.dedup import DedupService
from ..core.notify_log_store import NotifyLogStore
from ..core.persistence import Persistence
from .deps import get_db_session, require_auth

router = APIRouter(prefix="/notify", tags=["notify"])


@router.post("/log", response_model=schemas.NotifyLogOut, status_code=200,
             dependencies=[Depends(require_auth)])
def create_notify_log(payload: schemas.NotifyLogIn):
    store = NotifyLogStore()
    rec = store.log(
        channel_id=payload.channel_id,
        event_type=payload.event_type,
        content_hash=payload.content_hash,
        status=payload.status,
    )
    return schemas.NotifyLogOut.model_validate(rec)


@router.get("/dedup", response_model=schemas.DedupQueryOut)
def query_dedup(key: str, db: Session = Depends(get_db_session)):
    dedup = DedupService()
    # 用冷却=0 仅查询是否记录过（last_sent_at>0 即存在）。
    exists = not dedup.should_notify(key, cooldown=0.0)
    last = dedup.last_sent_at(key)
    return schemas.DedupQueryOut(exists=exists, last_sent_at=last)


@router.post("/dedup", response_model=dict, dependencies=[Depends(require_auth)])
def upsert_dedup(payload: schemas.DedupUpsert):
    dedup = DedupService()
    dedup.record(payload.key, meta=payload.meta)
    return {"recorded": True}
