"""Events API：历史事件查询。前缀 /events（挂载于 /api/v1）。"""

from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import schemas
from ..core.persistence import Persistence
from .deps import get_db_session

router = APIRouter(prefix="/events", tags=["events"])


@router.get("", response_model=schemas.PagedEvents)
def list_events(
    room_id: Optional[int] = None,
    platform: Optional[str] = None,
    event_type: Optional[str] = None,
    frm: Optional[str] = None,
    to: Optional[str] = None,
    limit: int = 200,
    offset: int = 0,
    db: Session = Depends(get_db_session),
):
    pers = Persistence()
    items = pers.list_events(
        room_id=room_id, platform=platform, event_type=event_type,
        frm=frm, to=to, limit=limit, offset=offset,
    )
    total = pers.count_events(
        room_id=room_id, platform=platform, event_type=event_type, frm=frm, to=to
    )
    return schemas.PagedEvents(total=total, items=[schemas.EventOut.model_validate(e) for e in items])
