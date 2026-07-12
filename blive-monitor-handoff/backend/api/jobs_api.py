"""Jobs API：手动触发一轮检测（P1）。前缀 /jobs（挂载于 /api/v1）。"""

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .. import schemas
from ..jobs.registry import get_scheduler
from .deps import get_db_session, require_auth

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post("/check", response_model=schemas.JobTriggerOut, status_code=202,
             dependencies=[Depends(require_auth)])
def trigger_check(type: str = Query("live", pattern="^(live|post|all)$")):
    scheduler = get_scheduler()
    if scheduler is None:
        raise HTTPException(status_code=503, detail="scheduler not running")
    scheduler.trigger(type)
    return schemas.JobTriggerOut(job_id=uuid.uuid4().hex, type=type, status="accepted")


@router.get("/status")
def jobs_status(db: Session = Depends(get_db_session)):
    from ..jobs.scheduler import RUNNING_FLAGS

    return {
        "running": dict(RUNNING_FLAGS),
        "scheduler": get_scheduler() is not None,
    }
