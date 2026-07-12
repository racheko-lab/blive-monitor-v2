#!/usr/bin/env python3
"""JSON → SQLite 迁移脚本（阶段四 T03）。

幂等可重跑：所有写入按 PK / UNIQUE 做 upsert；events_history 采用「清空 + 重插」
以保证重跑结果确定（等同同一份 JSON 的输入产出一致）。字段映射见 docs/phase4_design.md §7.6。

用法：
    python tools/import_json_to_db.py [--repo-root .] [--db data/blive.db]

说明：
  - 读取仓库根下的 rooms.json / status.json / state.json / tracking.json /
    post_rooms.json / post_tracking.json / history.json / notify_dedup.json /
    summary_state.json / silence_state.json（任一缺失则跳过该项，不报错）。
  - 环境变量 BLIVE_CONFIG（JSON 字符串）若存在，则写入 ConfigKV(key='blive_config')，
    使后端 /config 立即可用。
  - 建议在「后端尚未对外服务 / 全新 blive.db」上运行。
"""

import argparse
import json
import logging
import os
import sys
from typing import Any, Dict, Optional

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("import_json_to_db")


def _load(repo_root: str, name: str) -> Any:
    path = os.path.join(repo_root, name)
    if not os.path.exists(path):
        logger.info("跳过（文件不存在）: %s", name)
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        logger.warning("解析 %s 失败: %s", name, e)
        return None


def _split_key(key: str):
    """'douyin_601914453' -> ('douyin', '601914453')。"""
    if "_" in key:
        p, rid = key.split("_", 1)
        return p, rid
    return "", key


def main() -> int:
    parser = argparse.ArgumentParser(description="Import repo JSON state into SQLite")
    parser.add_argument("--repo-root", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    parser.add_argument("--db", default=None, help="blive.db 路径（默认用 backend.config.DB_PATH）")
    args = parser.parse_args()

    repo_root = os.path.abspath(args.repo_root)
    if args.db:
        os.environ["BLIVE_DB_PATH"] = os.path.abspath(args.db)

    # 让 backend 包可被导入（repo_root 即仓库根）。
    sys.path.insert(0, repo_root)
    from backend.db import init_db  # noqa: E402
    from backend.core.persistence import Persistence  # noqa: E402
    from backend.core.dedup import DedupService  # noqa: E402
    from backend.models import EventHistory, Room  # noqa: E402
    from backend import db as backend_db  # noqa: E402

    init_db()
    pers = Persistence()
    dedup = DedupService()

    # 预加载 JSON
    rooms_json = _load(repo_root, "rooms.json") or []
    status_json = _load(repo_root, "status.json") or {}
    state_json = _load(repo_root, "state.json") or {}
    tracking_json = _load(repo_root, "tracking.json") or {}
    post_rooms_json = _load(repo_root, "post_rooms.json") or []
    post_tracking_json = _load(repo_root, "post_tracking.json") or {}
    history_json = _load(repo_root, "history.json") or []
    notify_dedup_json = _load(repo_root, "notify_dedup.json") or {}
    summary_state_json = _load(repo_root, "summary_state.json") or {}
    silence_state_json = _load(repo_root, "silence_state.json") or {}
    blive_config_env = os.environ.get("BLIVE_CONFIG", "")

    # ============ 1) 直播 Room（kind='live'）============
    # status.json 的房间索引：key -> item
    status_by_key: Dict[str, Dict[str, Any]] = {}
    for it in status_json.get("rooms", []) or []:
        pk = f"{it.get('platform','bilibili')}_{it.get('id','')}"
        status_by_key[pk] = it

    for r in rooms_json:
        platform = r.get("platform", "bilibili")
        rid = str(r.get("id", ""))
        key = f"{platform}_{rid}"
        st = status_by_key.get(key, {})
        meta: Dict[str, Any] = dict(tracking_json.get(key, {}))
        # status.json 字段回填到 meta（直播基线）
        if st.get("last_live"):
            meta["last_live"] = st["last_live"]
        if st.get("live_duration"):
            meta["live_duration"] = st["live_duration"]
        if st.get("sec_uid"):
            meta["sec_uid"] = st["sec_uid"]
        # live_start 来自 tracking 基线
        if "live_start" in meta:
            pass
        pers.upsert_room({
            "platform": platform,
            "external_id": rid,
            "kind": "live",
            "name": r.get("name") or st.get("name", ""),
            "live_status": state_json.get(key) or st.get("status"),
            "current_title": st.get("title", ""),
            "online": int(st.get("online", 0) or 0),
            "area": st.get("area", ""),
            "last_checked_at": st.get("time"),
            "last_live_at": st.get("last_live"),
            "live_started_at": meta.get("live_start") or None,
            "live_duration": st.get("live_duration"),
            "meta": meta,
        })
    logger.info("直播 Room 导入完成：%d 个", len(rooms_json))

    # ============ 2) 新作 Room（kind='post'）============
    for r in post_rooms_json:
        rid = str(r.get("id", ""))
        meta = dict(post_tracking_json.get(f"douyin_{rid}", {}))
        if r.get("sec_uid"):
            meta["sec_uid"] = r["sec_uid"]
        pers.upsert_room({
            "platform": "douyin",
            "external_id": rid,
            "kind": "post",
            "name": r.get("name", ""),
            "meta": meta,
        })
    logger.info("新作 Room 导入完成：%d 个", len(post_rooms_json))

    # ============ 3) Posts 种子（来自 post_tracking 的 latest_aweme_id）============
    post_count = 0
    for key, t in post_tracking_json.items():
        aweme_id = str(t.get("latest_aweme_id", "") or "")
        if not aweme_id or aweme_id.startswith("count:"):
            continue  # 退化计数模式无具体作品
        pers.upsert_post({
            "platform": "douyin",
            "post_id": aweme_id,
            "author": t.get("nickname"),
            "url": t.get("latest_url"),
            "cover": t.get("latest_cover"),
            "published_at": None,
        })
        post_count += 1
    logger.info("Posts 种子导入完成：%d 条", post_count)

    # ============ 4) events_history（清空 + 重插，保证幂等）============
    from common import parse_beijing  # noqa: E402
    # 建立 (platform, external_id, kind) -> room_id 索引，用于回填 room_id
    room_index: Dict[tuple, int] = {}
    with backend_db.SessionLocal() as s:
        for rm in s.query(Room).all():
            room_index[(rm.platform, rm.external_id, rm.kind)] = rm.id

    def resolve_room_id(rid: str, event_type: Optional[str]):
        p, ext = _split_key(rid)
        if not p:
            return None
        kind = "post" if event_type == "new_post" else "live"
        return room_index.get((p, ext, kind))

    event_count = 0
    with backend_db.WRITER_LOCK:
        with backend_db.SessionLocal() as s:
            s.query(EventHistory).delete()
            s.commit()
        for e in history_json:
            etype = e.get("type") or e.get("status")
            rid = e.get("rid") or e.get("account") or ""
            ts = parse_beijing(e.get("time")) if e.get("time") else None
            ev = EventHistory(
                room_id=resolve_room_id(rid, etype),
                raw_rid=rid,
                account=e.get("account") or rid,
                platform=e.get("platform"),
                event_type=etype,
                name=e.get("name"),
                title=e.get("title"),
                detail=e.get("detail"),
                level=e.get("level"),
                changed=bool(e.get("changed", False)),
                prev=e.get("prev"),
                push=e.get("push"),
                occurred_at=e.get("time"),
                occurred_ts=int(ts) if ts is not None else None,
            )
            with backend_db.SessionLocal() as s:
                s.add(ev)
                s.commit()
            event_count += 1
    logger.info("events_history 导入完成：%d 条", event_count)

    # ============ 5) notify_dedup ============
    for key, val in notify_dedup_json.items():
        ts = (val or {}).get("ts", 0)
        dedup.record(key, now=float(ts) if ts else None)
    logger.info("notify_dedup 导入完成：%d 条", len(notify_dedup_json))

    # ============ 6) summary_state / silence_state ============
    if summary_state_json:
        pers  # 通过 ConfigStore 原子写入
        from backend.config_store import ConfigStore
        ConfigStore().put_summary_state(summary_state_json)
    if silence_state_json:
        from backend.config_store import ConfigStore
        ConfigStore().put_silence_state(silence_state_json)
    logger.info("summary/silence 状态导入完成")

    # ============ 7) BLIVE_CONFIG（来自环境变量）============
    if blive_config_env:
        try:
            cfg = json.loads(blive_config_env)
            from backend.config_store import ConfigStore
            ConfigStore().put_config(cfg)
            logger.info("BLIVE_CONFIG 已写入 ConfigKV")
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning("BLIVE_CONFIG 解析失败，跳过: %s", e)

    logger.info("迁移完成。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
