"""transcode_job：抖音新作封面转存后端化（复用 transcode_covers 逻辑，P1）。

设计 §8.6：复用 ``transcode_covers.download_cover`` / ``_raw_url``，仅把「读 post_tracking.json /
写 manifest」改为读 ``Room(kind='post').meta`` + 落 ``Post.cover``。封面落 ``assets/covers/``
（Docker 挂载卷持久化）。
"""

import logging
import os
from typing import Any, Dict

from .. import config
from ..core.persistence import Persistence
from transcode_covers import _raw_url, download_cover, _sha256  # noqa: E402  (repo 根模块)

logger = logging.getLogger(__name__)


def _key(platform: str, external_id: str) -> str:
    return f"{platform}_{external_id}"


def run() -> Dict[str, Any]:
    """遍历 post 房间，对 meta.latest_cover（CDN URL）转存到仓库 raw URL。

    Returns:
        {"total", "changed", "downloaded"} 统计。
    """
    pers = Persistence()
    rooms = pers.list_rooms(kind="post", enabled=None)
    total = 0
    changed = 0
    downloaded = 0

    os.makedirs(config.COVERS_DIR, exist_ok=True)

    for room in rooms:
        meta = dict(room.meta or {})
        src = meta.get("latest_cover")
        if not src or not isinstance(src, str):
            continue  # 无封面源（count 退化 / 尚未抓到作品）
        if src.startswith(_raw_url(config.GITHUB_OWNER, config.GITHUB_REPO, config.GITHUB_BRANCH, config.COVERS_DIR)):
            # 已转存为 raw URL，跳过
            continue
        total += 1
        key = _key(room.platform, room.external_id)
        dest = os.path.join(config.COVERS_DIR, f"{key}.jpg")
        raw = _raw_url(config.GITHUB_OWNER, config.GITHUB_REPO, config.GITHUB_BRANCH, config.COVERS_DIR)
        if download_cover(src, dest):
            meta["latest_cover"] = raw
            pers.set_room_status(
                platform=room.platform, external_id=room.external_id, kind="post",
                meta_update={"latest_cover": raw},
            )
            # 同步更新 Post.cover（若存在对应 aweme_id）
            aweme_id = str(meta.get("latest_aweme_id") or "")
            if aweme_id and not aweme_id.startswith("count:"):
                pers.upsert_post({
                    "platform": room.platform,
                    "post_id": aweme_id,
                    "cover": raw,
                })
            changed += 1
            downloaded += 1
            logger.info("[transcode] 已转存封面: %s", key)
        else:
            logger.warning("[transcode] 封面下载失败（保留 CDN URL，下轮重试）: %s", key)

    logger.info("[transcode] total=%d changed=%d downloaded=%d", total, changed, downloaded)
    return {"total": total, "changed": changed, "downloaded": downloaded}
