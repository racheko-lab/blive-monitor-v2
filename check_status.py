#!/usr/bin/env python3
"""
B站/抖音直播状态检测（GitHub Actions 用）

功能说明：
- B站: 官方 API 批量查询
- 抖音: 页面 SSR 数据提取（多种策略兜底）
- 状态变化时通过多通道推送（Bark / Server酱 / 企业微信 / PushPlus / Telegram）
- 更新 status.json / state.json / history.json / tracking.json
"""

import json
import os
import re
import time
import logging
import urllib.request
import urllib.parse
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any

# 公共工具（时间/JSON 读写），避免与 check_new_posts.py 重复定义
from common import bjnow, load_json_file, save_json_file, DEFAULT_USER_AGENT, BEIJING_TZ
# 多通道推送（与 check_new_posts.py 共用 push_utils.py）
from push_utils import dispatch_push, load_push_cfg
# 通知去重账本：与状态持久化解耦的独立防线，杜绝重复推送
from notify_dedup import should_notify as dedup_should_notify, record as dedup_record, prune as dedup_prune

# ==================== 常量配置 ====================

# 文件路径
REPO_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(REPO_DIR, "state.json")
STATUS_FILE = os.path.join(REPO_DIR, "status.json")
HISTORY_FILE = os.path.join(REPO_DIR, "history.json")
TRACKING_FILE = os.path.join(REPO_DIR, "tracking.json")
ROOMS_FILE = os.path.join(REPO_DIR, "rooms.json")

# 历史日志保留条数
HISTORY_MAX_ENTRIES = 200

# HTTP 请求默认配置（DEFAULT_USER_AGENT 定义在 common.py，两脚本共用）
DEFAULT_TIMEOUT = 10
DEFAULT_RETRIES = 2

# 抖音状态码
DOUYIN_STATUS_LIVE = 2
DOUYIN_STATUS_OFFLINE = 4

# B站状态码映射
BILIBILI_STATUS_MAP = {
    0: "offline",
    1: "live",
    2: "replay",
}

# ==================== 日志配置 ====================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


# ==================== 工具函数 ====================
# bjnow / load_json_file / save_json_file 见 common.py（与 check_new_posts.py 共用）

# ==================== 配置加载 ====================

def load_config() -> Dict[str, Any]:
    """加载配置（rooms.json + 环境变量 BLIVE_CONFIG）"""
    # 从 rooms.json 加载房间列表
    rooms: List[Dict[str, str]] = []
    if os.path.exists(ROOMS_FILE):
        try:
            with open(ROOMS_FILE, "r", encoding="utf-8") as f:
                rooms = json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.error("加载 rooms.json 失败: %s", e)

    # 推送配置：多通道（serverchan/wecom/pushplus/bark/telegram），兼容旧 sendkey
    raw_config = os.environ.get("BLIVE_CONFIG", "{}")
    push_cfg = load_push_cfg(raw_config)

    return {
        "push_cfg": push_cfg,
        "rooms": rooms,
    }


# ==================== HTTP 请求 ====================

def fetch_with_retry(
    url: str,
    headers: Optional[Dict[str, str]] = None,
    retries: int = DEFAULT_RETRIES,
    timeout: int = DEFAULT_TIMEOUT,
) -> bytes:
    """带重试的 HTTP 请求

    Args:
        url: 请求 URL
        headers: 请求头
        retries: 重试次数
        timeout: 超时时间（秒）

    Returns:
        响应内容 bytes

    Raises:
        Exception: 所有重试都失败时抛出最后一次异常
    """
    last_err: Optional[Exception] = None
    base_headers = {"User-Agent": DEFAULT_USER_AGENT}
    if headers:
        base_headers.update(headers)

    for i in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=base_headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except Exception as e:
            last_err = e
            if i < retries:
                logger.debug("请求失败，%d秒后重试 (%d/%d): %s", 1, i + 1, retries, e)
                time.sleep(1)

    assert last_err is not None
    raise last_err


# ==================== B站 API ====================

def fetch_bilibili_batch(room_ids: List[str]) -> Dict[str, Dict[str, Any]]:
    """B站直播间批量检测 - getRoomBaseInfo 接口

    Args:
        room_ids: 直播间 ID 列表

    Returns:
        {room_id_str: {live_status, title, uname, online, ...}}

    Raises:
        Exception: API 返回错误时抛出
    """
    params = [("req_biz", "web_room_componet")]
    for rid in room_ids:
        params.append(("room_ids", rid))

    url = (
        "https://api.live.bilibili.com/xlive/web-room/v1/index/getRoomBaseInfo?"
        + urllib.parse.urlencode(params)
    )

    raw = fetch_with_retry(
        url,
        headers={
            "Referer": "https://live.bilibili.com/",
        },
    )

    data = json.loads(raw)
    if data.get("code") != 0:
        raise Exception(f"B站批量接口错误: code={data.get('code')}, msg={data.get('message')}")

    return data["data"]["by_room_ids"]


# ==================== 抖音数据提取（多种策略） ====================

def _extract_douyin_from_render_data(html: str) -> Optional[Dict[str, Any]]:
    """策略1: 从 RENDER_DATA 中提取房间数据"""
    # 尝试匹配房间状态数据（多种格式变体）
    patterns = [
        # 标准格式
        r'\\"id_str\\":\\"(\d+)\\",\\"status\\":(\d+),\\"status_str\\":\\"(\d+)\\",\\"title\\":\\"([^"\\]*)\\".*?\\"user_count_str\\":\\"(\d+)\\"',
        # 不带 status_str
        r'\\"id_str\\":\\"(\d+)\\",\\"status\\":(\d+),\\"title\\":\\"([^"\\]*)\\".*?\\"user_count_str\\":\\"(\d+)\\"',
        # user_count 是数字
        r'\\"id_str\\":\\"(\d+)\\",\\"status\\":(\d+),\\"title\\":\\"([^"\\]*)\\".*?\\"user_count\\":(\d+)',
    ]

    for pattern in patterns:
        match = re.search(pattern, html)
        if match:
            groups = match.groups()
            # 根据匹配组数解析
            if len(groups) == 5:
                _, status_code, _, title, user_count = groups
            elif len(groups) == 4:
                _, status_code, title, user_count = groups
            else:
                continue

            try:
                status_code_int = int(status_code)
                user_count_int = int(user_count)
            except (ValueError, TypeError):
                continue

            status = "live" if status_code_int == DOUYIN_STATUS_LIVE else "offline"
            return {
                "status": status,
                "title": title,
                "online": user_count_int,
            }

    return None


def _extract_douyin_from_share_meta(html: str) -> Optional[Dict[str, Any]]:
    """策略2: 从分享 meta 标签提取"""
    # 检查是否直播中
    share_desc_match = re.search(
        r'shareDesc["\s]*value=["\s]*([^"]+)', html
    )
    if share_desc_match and "正在直播" in share_desc_match.group(1):
        title_match = re.search(
            r'shareTitle["\s]*value=["\s]*([^"]+)', html
        )
        title = title_match.group(1).replace("的直播", "") if title_match else ""
        return {
            "status": "live",
            "title": title,
            "online": 0,
        }

    # 检查是否已结束
    if "直播已结束" in html:
        return {
            "status": "offline",
            "title": "",
            "online": 0,
        }

    return None


def _extract_douyin_from_page_text(html: str) -> Optional[Dict[str, Any]]:
    """策略3: 从页面文本关键词推断"""
    # 直播中的特征文本
    live_indicators = ["正在直播", "直播中", "观看人数"]
    offline_indicators = ["直播已结束", "该主播暂无直播", "主播不在"]

    live_count = sum(1 for indicator in live_indicators if indicator in html)
    offline_count = sum(1 for indicator in offline_indicators if indicator in html)

    if live_count > offline_count and live_count >= 2:
        return {"status": "live", "title": "", "online": 0}
    if offline_count >= 1:
        return {"status": "offline", "title": "", "online": 0}

    return None


def _extract_douyin_nickname(html: str) -> str:
    """提取主播昵称"""
    # 从 nickname 字段提取
    for match in re.finditer(r'\\"nickname\\":\\"([^"\\]+)\\"', html):
        val = match.group(1)
        if val and val != "$undefined" and not val.startswith("$"):
            return val

    # 从 og:title 提取
    og_title_match = re.search(r'<meta[^>]*property="og:title"[^>]*content="([^"]+)"', html)
    if og_title_match:
        title = og_title_match.group(1)
        if "的直播" in title:
            return title.replace("的直播", "").strip()
        return title.strip()

    return ""


def _extract_douyin_sec_uid(html: str) -> str:
    """提取 sec_uid"""
    # 方法1: 直接查找 sec_uid 字段
    idx = html.find('sec_uid')
    if idx >= 0:
        start = html.find('\\"', idx + 10)
        if start >= 0:
            end = html.find('\\"', start + 2)
            if end >= 0 and end - start < 200:
                return html[start + 2 : end]

    # 方法2: 正则匹配
    match = re.search(r'\\"sec_uid\\":\\"([^"\\]+)\\"', html)
    if match:
        return match.group(1)

    return ""


def fetch_douyin(web_rid: str) -> Dict[str, Any]:
    """抖音直播间检测 - 多种策略兜底提取

    Args:
        web_rid: 直播间 web_rid

    Returns:
        直播间状态字典
    """
    url = f"https://live.douyin.com/{web_rid}"
    now_str = bjnow().strftime("%Y-%m-%d %H:%M:%S")

    try:
        raw = fetch_with_retry(
            url,
            headers={
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "zh-CN,zh;q=0.9",
            },
        )
        html = raw.decode("utf-8", errors="replace")
    except Exception as e:
        logger.warning("获取抖音页面失败 (%s): %s", web_rid, e)
        return {
            "status": "error",
            "title": f"获取失败: {str(e)}",
            "online": 0,
            "area": "",
            "nickname": "",
            "sec_uid": "",
            "time": now_str,
        }

    # 提取公共字段
    nickname = _extract_douyin_nickname(html)
    sec_uid = _extract_douyin_sec_uid(html)

    # 策略1: 从 RENDER_DATA 提取（最准确）
    result = _extract_douyin_from_render_data(html)
    if result:
        result.update(
            {
                "area": "",
                "nickname": nickname,
                "sec_uid": sec_uid,
                "time": now_str,
            }
        )
        logger.debug("抖音策略1成功 (RENDER_DATA): %s", web_rid)
        return result

    # 策略2: 从分享 meta 提取
    result = _extract_douyin_from_share_meta(html)
    if result:
        result.update(
            {
                "area": "",
                "nickname": nickname,
                "sec_uid": sec_uid,
                "time": now_str,
            }
        )
        logger.debug("抖音策略2成功 (share_meta): %s", web_rid)
        return result

    # 策略3: 页面文本关键词推断（兜底）
    result = _extract_douyin_from_page_text(html)
    if result:
        result.update(
            {
                "area": "",
                "nickname": nickname,
                "sec_uid": sec_uid,
                "time": now_str,
            }
        )
        logger.debug("抖音策略3成功 (page_text): %s", web_rid)
        return result

    # 所有策略都失败，默认返回离线状态
    logger.warning("抖音所有提取策略都失败: %s", web_rid)
    return {
        "status": "offline",
        "title": "",
        "online": 0,
        "area": "",
        "nickname": nickname,
        "sec_uid": sec_uid,
        "time": now_str,
    }


# ==================== 微信推送 ====================

def should_push(prev_status: Optional[str], curr_status: str) -> bool:
    """判断是否需要推送通知

    Args:
        prev_status: 之前的状态
        curr_status: 当前状态

    Returns:
        是否需要推送
    """
    if curr_status == "offline" or curr_status == "error":
        return False
    if prev_status is None:
        return curr_status in ("live", "replay")

    # 只有从「离线」状态变为「直播/回放」才推送（error 状态不触发，避免检测失败导致反复推送）
    if prev_status == "offline" and curr_status in ("live", "replay"):
        return True
    # 从回放变为直播，需要推送
    if prev_status == "replay" and curr_status == "live":
        return True

    return False


def bili_status_on_batch_failure(prev_status: Optional[str]) -> str:
    """B站批量接口整体失败时，沿用上次已知状态；首次检测则记为 unknown。

    避免把整批房间误标为 error（既污染历史，又因 error→live 不推送而漏报恢复开播）。
    """
    return prev_status or "unknown"


def format_push_title(name: str, result: Dict[str, Any]) -> str:
    """格式化推送标题"""
    if result["status"] == "live":
        return f"🔴 {name} 开播了！"
    return f"▶️ {name} 轮播/回放中"


def format_push_desp(
    name: str, platform: str, rid: str, result: Dict[str, Any]
) -> str:
    """格式化推送内容"""
    platform_label = "B站" if platform == "bilibili" else "抖音"
    live_url = (
        f"https://live.bilibili.com/{rid}"
        if platform == "bilibili"
        else f"https://live.douyin.com/{rid}"
    )
    now = bjnow().strftime("%Y-%m-%d %H:%M:%S")

    lines = [
        f"## 🎬 {name} 开播了！"
        if result["status"] == "live"
        else f"## ▶️ {name} 轮播/回放中",
        "",
        f"**平台**: {platform_label}",
        f"**标题**: {result.get('title', '-')}",
    ]

    if result.get("area"):
        lines.append(f"**分区**: {result['area']}")
    if result.get("online"):
        lines.append(f"**人气**: {result['online']}")

    lines.extend(
        [
            "",
            f"👉 [进入直播间]({live_url})",
            "",
            f"---",
            f"检测时间: {now}",
        ]
    )

    return "\n".join(lines)


# ==================== 直播时长计算 ====================

def calculate_duration(start_str: str, now_dt: datetime) -> str:
    """计算直播时长

    Args:
        start_str: 开始时间字符串 "%Y-%m-%d %H:%M:%S"
        now_dt: 当前时间

    Returns:
        格式化的时长字符串，如 "1h30min" 或 "45min"
    """
    try:
        start_dt = datetime.strptime(start_str, "%Y-%m-%d %H:%M:%S")
        secs = int((now_dt - start_dt).total_seconds())
        if secs < 0:
            return ""
        h, m = divmod(secs, 3600)
        m, _ = divmod(m, 60)
        return f"{h}h{m}min" if h > 0 else f"{m}min"
    except (ValueError, TypeError):
        return ""


# ==================== 主逻辑 ====================

def main() -> None:
    """主函数"""
    cfg = load_config()
    rooms = cfg.get("rooms", [])
    push_cfg = cfg.get("push_cfg", {})

    if not rooms:
        logger.info("没有配置监控房间")
        return

    # 加载之前的状态
    prev_state: Dict[str, str] = load_json_file(STATE_FILE, {})
    tracking: Dict[str, Dict[str, Any]] = load_json_file(TRACKING_FILE, {})

    # 加载上一次写入 status.json 的完整房间信息，用于在 B站批量接口整体失败时
    # 继承 title/online/area，避免看板在故障期间把房间信息清空。
    prev_status_full: Dict[str, Dict[str, Any]] = {}
    _prev_doc = load_json_file(STATUS_FILE, {})
    for _it in _prev_doc.get("rooms", []) or []:
        _pk = f"{_it.get('platform', 'bilibili')}_{_it.get('id', '')}"
        prev_status_full[_pk] = _it

    new_state: Dict[str, str] = {}
    status_list: List[Dict[str, Any]] = []
    log_entries: List[Dict[str, Any]] = []
    newly_live: List[Dict[str, Any]] = []

    now = bjnow()
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")

    logger.info("开始检测 %d 个房间...", len(rooms))

    # Step 1: 批量查询所有 B站房间
    bili_rooms = [(r, i) for i, r in enumerate(rooms) if r.get("platform", "bilibili") == "bilibili"]
    bili_data: Dict[str, Dict[str, Any]] = {}

    bili_batch_failed = False
    if bili_rooms:
        try:
            bili_ids = [r["id"] for r, _ in bili_rooms]
            bili_data = fetch_bilibili_batch(bili_ids)
            logger.info("B站批量查询成功，获取 %d 个房间数据", len(bili_data))
        except Exception as e:
            logger.error("B站批量查询失败: %s", e)
            bili_batch_failed = True

    # Step 2: 逐个检测所有房间
    for room in rooms:
        platform = room.get("platform", "bilibili")
        rid = room.get("id", "")
        name = room.get("name", f"{platform}-{rid}")
        key = f"{platform}_{rid}"
        push_result: Optional[str] = None

        # 获取当前状态
        try:
            if platform == "bilibili":
                d = bili_data.get(str(rid))
                if not d:
                    if bili_batch_failed:
                        # 批量接口整体失败：沿用上次已知状态，不误标为 error
                        # （避免污染历史；且 error→live 不推送会漏报恢复开播）
                        prev = prev_state.get(key)
                        prev_full = prev_status_full.get(key, {})
                        logger.warning("[%s] B站批量查询失败，沿用上次状态: %s", name, prev)
                        result = {
                            "status": bili_status_on_batch_failure(prev),
                            "title": prev_full.get("title", ""),
                            "online": prev_full.get("online", 0),
                            "area": prev_full.get("area", ""),
                        }
                    else:
                        raise Exception(f"批量接口未返回房间 {rid} 的数据")
                else:
                    status_code = d.get("live_status", 0)
                    result = {
                        "status": BILIBILI_STATUS_MAP.get(status_code, "unknown"),
                        "title": d.get("title", ""),
                        "online": d.get("online", 0),
                        "area": (
                            f"{d.get('parent_area_name', '')}·{d.get('area_name', '')}".strip("·")
                            or ""
                        ),
                    }
            else:  # douyin
                result = fetch_douyin(rid)

        except Exception as e:
            logger.warning("[%s] 检测失败: %s", name, e)
            result = {
                "status": "error",
                "title": str(e),
                "online": 0,
                "area": "",
                "time": now_str,
            }
            push_result = "error"

        # 显示名称处理
        display_name = name
        if platform == "douyin" and result.get("nickname") and result["nickname"] != name:
            display_name = result["nickname"]

        logger.info(
            "  [%s] %s - %s",
            display_name,
            result["status"],
            result.get("title", "")[:30],
        )

        # 更新状态
        new_state[key] = result["status"]

        # 开播追踪
        t = tracking.get(key, {})
        last_live = t.get("last_live", "")
        live_start_str = t.get("live_start", "")
        live_duration = ""

        if result["status"] == "live":
            if not live_start_str:
                live_start_str = now_str
            else:
                live_duration = calculate_duration(live_start_str, now)
        elif live_start_str:
            # 刚下播，记录上次直播信息
            last_live = live_start_str
            t["last_duration"] = calculate_duration(live_start_str, now)
            live_start_str = ""

        t["last_live"] = last_live
        t["live_start"] = live_start_str
        if live_duration:
            t["live_duration"] = live_duration
        if platform == "douyin" and result.get("sec_uid"):
            t["sec_uid"] = result["sec_uid"]
        tracking[key] = t

        # 构建状态列表项
        status_item = {
            "platform": platform,
            "id": rid,
            "name": display_name,
            "status": result["status"],
            "title": result.get("title", ""),
            "online": result.get("online", 0),
            "area": result.get("area", ""),
            "time": result.get("time", now_str),
            "sec_uid": result.get("sec_uid", ""),
            "last_live": last_live,
            "live_duration": live_duration,
        }
        status_list.append(status_item)

        # 状态变化检测
        prev_status = prev_state.get(key)
        changed = prev_status is not None and prev_status != result["status"]

        if should_push(prev_status, result["status"]):
            dkey = f"live:{key}"
            if dedup_should_notify(dkey):
                newly_live.append(
                    {
                        "name": display_name,
                        "platform": platform,
                        "rid": rid,
                        "result": result,
                    }
                )
                push_result = "queued"
            else:
                # 冷却期内已推送过（闪烁 / 状态文件短暂丢失后的重复首检），跳过
                logger.info(
                    "[%s] 去重跳过：开播通知 %s 在冷却期内已发送", display_name, dkey
                )
                push_result = "deduped"

        # 记录日志
        log_entries.append(
            {
                "time": now_str,
                "name": display_name,
                "platform": platform,
                "status": result["status"],
                "title": result.get("title", ""),
                "changed": changed,
                "prev": prev_status if changed else None,
                "push": push_result,
            }
        )

    # Step 3: 合并推送（多通道：serverchan/wecom/pushplus/bark/telegram）
    if newly_live and push_cfg:
        try:
            if len(newly_live) == 1:
                s = newly_live[0]
                title = format_push_title(s["name"], s["result"])
                desp = format_push_desp(s["name"], s["platform"], s["rid"], s["result"])
            else:
                names = "、".join(s["name"] for s in newly_live)
                title = f"🔴 {len(newly_live)}位主播开播：{names}"
                desp_lines = [
                    format_push_desp(s["name"], s["platform"], s["rid"], s["result"])
                    for s in newly_live
                ]
                desp = "\n\n---\n\n".join(desp_lines)

            ok = dispatch_push(push_cfg, title, desp)
            push_tag = "pushed_ok" if ok else "pushed_fail"
            logger.info("推送%s: %s", "成功" if ok else "失败", title)

            # 推送成功后才记录去重（失败则不标记，下一轮可补推）
            if ok:
                for s in newly_live:
                    dedup_record(f"live:{s['platform']}_{s['rid']}")

            # 更新日志里的推送标记
            for le in log_entries:
                if le["push"] == "queued":
                    le["push"] = push_tag
        except Exception as e:
            logger.error("推送异常: %s", e)
            for le in log_entries:
                if le["push"] == "queued":
                    le["push"] = "push_error"
    elif newly_live:
        logger.info("%d 个房间状态变化，但未配置推送渠道", len(newly_live))
        for le in log_entries:
            if le["push"] == "queued":
                le["push"] = "no_sendkey"

    # 保存状态文件
    save_json_file(STATE_FILE, new_state)
    save_json_file(
        STATUS_FILE,
        {"updated": now_str, "rooms": status_list},
    )
    save_json_file(TRACKING_FILE, tracking)

    # 更新历史日志
    old_log: List[Dict[str, Any]] = load_json_file(HISTORY_FILE, [])
    all_log = old_log + log_entries
    if len(all_log) > HISTORY_MAX_ENTRIES:
        all_log = all_log[-HISTORY_MAX_ENTRIES:]
    save_json_file(HISTORY_FILE, all_log)

    # 裁剪去重账本（丢弃过期 live: key，post: key 永久保留）
    try:
        dedup_prune()
    except Exception as e:
        logger.warning("裁剪去重账本失败（不影响主流程）: %s", e)

    logger.info("检测完成，状态已更新")


if __name__ == "__main__":
    main()
