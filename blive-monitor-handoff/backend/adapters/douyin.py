"""DouyinAdapter：封装既有 fetch_douyin / get_latest_aweme / resolve_sec_uid（零重写）。

直播：封装 check_status.fetch_douyin（SSR 多策略提取），返回 RoomModel。
新作：封装 check_new_posts 的 resolve_sec_uid + get_latest_aweme +
should_notify_new_post / should_update_baseline / looks_like_handle（全部既有纯函数），
复用其「三层策略 + 优雅降级 + 中毒防护」逻辑，仅将输出归一化为 PostModel[]，
并通过异常（AdapterSkip / AdapterGated）向编排层信号化「跳过 / 风控」语义。
"""

import logging
from typing import Any, Dict, List, Optional
from datetime import datetime

import check_new_posts
import check_status
from backend.adapters.base import (
    AdapterGated,
    AdapterSkip,
    PlatformAdapter,
    PostModel,
    RoomModel,
)

logger = logging.getLogger(__name__)


def _epoch_to_bj(sec: int) -> str:
    """epoch 秒 -> 北京时间字符串（与 history/state 逐字节一致）。"""
    try:
        return datetime.fromtimestamp(int(sec)).strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError, OverflowError, OSError):
        return ""


class DouyinAdapter(PlatformAdapter):
    platform = "douyin"
    supports_live = True
    supports_posts = True
    poll_interval = 300
    needs_context = True

    # ----------- 直播 -----------
    def fetch_room_status(self, room_id: str) -> RoomModel:
        raw = check_status.fetch_douyin(str(room_id))
        status = raw.get("status", "offline")
        if status == "error":
            # 页面抓取失败：上抛，由编排层 try/except 规范化 status="error"（与原行为一致）
            raise RuntimeError(raw.get("title") or "douyin 直播页抓取失败")
        return RoomModel(
            platform="douyin",
            room_id=str(room_id),
            name=raw.get("nickname", ""),
            title=raw.get("title", ""),
            live_status=(status == "live"),
            online=int(raw.get("online", 0) or 0),
            area=raw.get("area", ""),
            extra={"sec_uid": raw.get("sec_uid", ""), "status_str": status},
        )

    # ----------- 新作 -----------
    def fetch_new_posts(
        self,
        author_or_room: str,
        since: Optional[datetime] = None,
        baseline: Optional[Dict[str, Any]] = None,
        context: Any = None,
    ) -> List[PostModel]:
        # 复用 check_new_posts 既有纯函数，零重写检测逻辑。
        # 原地修改 baseline（调用方传入的 meta 字典），便于编排层持久化更新后的基线。
        t = baseline if isinstance(baseline, dict) else {}
        rid = str(author_or_room)

        # sec_uid 解析（复用 resolve_sec_uid；可信/不可信用于中毒防护）
        stored_sec = t.get("sec_uid") or None
        if stored_sec:
            sec_uid = stored_sec
            sec_trusted = True
        else:
            sec_uid = check_new_posts.resolve_sec_uid(context, rid)
            sec_trusted = False
        if not sec_uid:
            raise AdapterSkip("no_sec_uid", detail="账号配置不完整（缺 sec_uid），已跳过")
        t["sec_uid"] = sec_uid

        # 获取最新作品（复用 get_latest_aweme；异常上抛 -> 编排层记 error 事件）
        aweme = check_new_posts.get_latest_aweme(context, sec_uid)
        if not aweme:
            raise AdapterGated(detail="抖音接口被风控，配置 douyin_cookie 可获取具体作品")

        # 中毒防护（复用 looks_like_handle）
        actual_uid = aweme.get("actual_unique_id")
        if actual_uid and check_new_posts.looks_like_handle(rid) and actual_uid != rid:
            if not sec_trusted:
                t.pop("sec_uid", None)
                raise AdapterSkip("poisoned", detail="解析的 sec_uid 指向错误账号，已清除并跳过")
            logger.warning(
                "[douyin] 已存 sec_uid 指向账号(实际=%s)与填写 id(%s)不一致，仍信任", actual_uid, rid
            )

        conf = aweme.get("_conf", "api")
        prev_id = t.get("latest_aweme_id", "")
        prev_ct = int(t.get("latest_ct", 0) or 0)
        new_ct = int(aweme.get("create_time", 0) or 0)
        posts: List[PostModel] = []

        if conf == "api":
            candidate = check_new_posts.should_notify_new_post(prev_id, prev_ct, aweme["aweme_id"], new_ct)
            do_update = check_new_posts.should_update_baseline(prev_id, prev_ct, aweme["aweme_id"], new_ct)
            if candidate:
                posts.append(self._to_post(sec_uid, aweme, conf))
            if aweme.get("cover"):
                t["latest_cover"] = aweme["cover"]
        else:
            prev_mode = t.get("mode") or (
                "count" if str(prev_id).startswith("count:") else ("api" if prev_id else "")
            )
            if prev_mode and prev_mode != conf:
                do_update = True
            else:
                prev_count = int(t.get("latest_count", 0) or 0)
                candidate = bool(prev_count) and new_ct > prev_count
                if candidate:
                    posts.append(self._to_post(sec_uid, aweme, conf, prev_count=prev_count, new_count=new_ct))
                do_update = True

        if do_update:
            t["latest_aweme_id"] = aweme["aweme_id"]
            t["latest_ct"] = new_ct
            t["mode"] = conf
            t["latest_count"] = new_ct
            t["nickname"] = aweme.get("nickname") or t.get("nickname", "")
            if conf == "count":
                t["need_cookie"] = True
            else:
                t.pop("need_cookie", None)
            if conf == "api":
                t["latest_desc"] = aweme.get("desc", "")
                t["latest_type"] = "图文" if aweme.get("is_note") else "视频"
                t["latest_url"] = aweme.get("video_url", "")
        return posts

    @staticmethod
    def _to_post(sec_uid, aweme, conf, prev_count=None, new_count=None) -> PostModel:
        kind = "图文" if aweme.get("is_note") else "视频"
        if conf == "count":
            ct = int(aweme.get("create_time", 0) or 0)
            post_id = f"count:{ct}"
            url = aweme.get("video_url", "")
            dkey = f"post:{sec_uid}:count:{ct}"
        else:
            post_id = str(aweme["aweme_id"])
            url = aweme.get("video_url", "")
            dkey = f"post:{sec_uid}:{aweme['aweme_id']}"
        extra: Dict[str, Any] = {"conf": conf, "type": kind, "dedup_key": dkey}
        if conf == "count":
            extra["prev_count"] = prev_count
            extra["new_count"] = new_count
        return PostModel(
            platform="douyin",
            post_id=post_id,
            author=aweme.get("nickname", ""),
            url=url,
            cover=aweme.get("cover"),
            published_at=_epoch_to_bj(int(aweme.get("create_time", 0) or 0)),
            title=aweme.get("desc", "") or "[无描述]",
            extra=extra,
        )

    # ----------- 凭证注入 -----------
    def apply_credentials(self, context: Any) -> None:
        """注入抖音登录 Cookie 到 Playwright 上下文（突破作品接口风控）。"""
        try:
            cookie = self.credentials.get("cookie") or check_new_posts.load_douyin_cookie()
            check_new_posts.apply_douyin_cookie(context, cookie)
        except Exception as e:  # 凭证注入失败不应中断整轮
            logger.warning("[douyin] 注入 Cookie 失败: %s", e)
