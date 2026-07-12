"""Posts API：新作列表查询 + 记录。前缀 /posts（挂载于 /api/v1）。"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import schemas
from ..core.persistence import Persistence
from .deps import get_db_session, require_auth

router = APIRouter(prefix="/posts", tags=["posts"])


@router.get("", response_model=schemas.PagedPosts)
def list_posts(
    platform: Optional[str] = None,
    author: Optional[str] = None,
    since: Optional[str] = None,
    limit: int = 200,
    offset: int = 0,
    db: Session = Depends(get_db_session),
):
    pers = Persistence()
    items = pers.list_posts(platform=platform, author=author, since=since, limit=limit, offset=offset)
    total = pers.count_posts(platform=platform, author=author, since=since)
    return schemas.PagedPosts(total=total, items=[schemas.PostOut.model_validate(p) for p in items])


@router.post("", response_model=schemas.PostOut, status_code=200, dependencies=[Depends(require_auth)])
def create_post(payload: schemas.PostCreate):
    pers = Persistence()
    data = payload.model_dump(exclude_none=True)
    data["post_id"] = str(data["post_id"])
    post = pers.upsert_post(data)
    return schemas.PostOut.model_validate(post)
