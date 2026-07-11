"""Rooms API：监控目标 CRUD + 状态读写。前缀 /rooms（挂载于 /api/v1）。"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import schemas
from ..core.persistence import Persistence
from .deps import get_db_session, require_auth

router = APIRouter(prefix="/rooms", tags=["rooms"])


def _pagination(kind: Optional[str], platform: Optional[str], enabled: Optional[bool],
               q: Optional[str], limit: int, offset: int):
    pers = Persistence()
    items = pers.list_rooms(kind=kind, platform=platform, enabled=enabled,
                            q=q, limit=limit, offset=offset)
    total = pers.count_rooms(kind=kind, platform=platform, enabled=enabled, q=q)
    return schemas.PagedRooms(total=total, items=[schemas.RoomOut.model_validate(r) for r in items])


@router.get("", response_model=schemas.PagedRooms)
def list_rooms(
    kind: Optional[str] = None,
    platform: Optional[str] = None,
    enabled: Optional[bool] = None,
    q: Optional[str] = None,
    limit: int = 200,
    offset: int = 0,
    db: Session = Depends(get_db_session),
):
    return _pagination(kind, platform, enabled, q, limit, offset)


@router.post("", response_model=schemas.RoomOut, status_code=200, dependencies=[Depends(require_auth)])
def create_room(payload: schemas.RoomCreate):
    pers = Persistence()
    data = payload.model_dump(exclude_none=True)
    data["external_id"] = str(data["external_id"])
    room = pers.upsert_room(data)
    return schemas.RoomOut.model_validate(room)


@router.get("/{room_id}", response_model=schemas.RoomOut)
def get_room(room_id: int, db: Session = Depends(get_db_session)):
    pers = Persistence()
    room = pers.get_room(room_id)
    if room is None:
        raise HTTPException(status_code=404, detail="room not found")
    return schemas.RoomOut.model_validate(room)


@router.put("/{room_id}", response_model=schemas.RoomOut, dependencies=[Depends(require_auth)])
def update_room(room_id: int, payload: schemas.RoomUpdate):
    pers = Persistence()
    room = pers.update_room(room_id, payload.model_dump(exclude_none=True))
    if room is None:
        raise HTTPException(status_code=404, detail="room not found")
    return schemas.RoomOut.model_validate(room)


@router.delete("/{room_id}", status_code=204, dependencies=[Depends(require_auth)])
def delete_room(room_id: int):
    pers = Persistence()
    if not pers.delete_room(room_id):
        raise HTTPException(status_code=404, detail="room not found")
    return None


@router.get("/{room_id}/status", response_model=schemas.RoomStatusOut)
def get_room_status(room_id: int, db: Session = Depends(get_db_session)):
    pers = Persistence()
    room = pers.get_room(room_id)
    if room is None:
        raise HTTPException(status_code=404, detail="room not found")
    return schemas.RoomStatusOut(
        live_status=room.live_status,
        current_title=room.current_title,
        online=room.online,
        area=room.area,
        cover=room.cover,
        last_live_at=room.last_live_at,
        live_started_at=room.live_started_at,
        live_duration=room.live_duration,
        last_checked_at=room.last_checked_at,
    )


@router.put("/{room_id}/status", response_model=schemas.RoomStatusOut,
            dependencies=[Depends(require_auth)])
def put_room_status(room_id: int, payload: schemas.RoomStatusUpdate):
    pers = Persistence()
    room = pers.get_room(room_id)
    if room is None:
        raise HTTPException(status_code=404, detail="room not found")
    status_item = {
        "status": payload.live_status,
        "title": payload.title,
        "online": payload.online,
        "area": payload.area,
    }
    meta_update = {}
    if payload.cover is not None:
        meta_update["cover"] = payload.cover
    updated = pers.set_room_status(
        platform=room.platform,
        external_id=room.external_id,
        kind=room.kind,
        name=room.name,
        status_item=status_item,
        meta_update=meta_update,
    )
    room = pers.get_room(updated.id)
    return schemas.RoomStatusOut(
        live_status=room.live_status,
        current_title=room.current_title,
        online=room.online,
        area=room.area,
        cover=room.cover,
        last_live_at=room.last_live_at,
        live_started_at=room.live_started_at,
        live_duration=room.live_duration,
        last_checked_at=room.last_checked_at,
    )
