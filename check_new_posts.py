#!/usr/bin/env python3
"""
抖音新作品检测

功能说明：
- sec_uid 由 check_status.py 写入 tracking.json（key: douyin_webrid）
- 本脚本从 tracking.json 读取 sec_uid，检查是否有新作品
- 通过 Server酱 推送通知
- 通过环境变量 ENABLE_POST_CHECK=true 启用
"""

import json
import os
import logging
import urllib.request
import urllib.parse
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any

# ==================== 常量配置 ====================

# 北京时间（UTC+8）
BEIJING_TZ = timezone(timedelta(hours=8))

# 文件路径
REPO_DIR = os.path.dirname(os.path.abspath(__file__))
ROOMS_FILE = os.path.join(REPO_DIR, "rooms.json")
TRACKING_FILE = os.path.join(REPO_DIR, "tracking.json")

# HTTP 请求默认配置
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)
DEFAULT_TIMEOUT = 10

# ==================== 日志配置 ====================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


# ==================== 工具函数 ====================

def bjnow() -> datetime:
    """获取当前北京时间"""
    return datetime.now(BEIJING_TZ).replace(tzinfo=None)


def load_json_file(filepath: str, default: Any = None) -> Any:
    """安全加载 JSON 文件"""
    if default is None:
        default = {}
    if not os.path.exists(filepath):
        return default
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        logger.warning("加载 %s 失败: %s", filepath, e)
        return default


def save_json_file(filepath: str, data: Any) -> None:
    """安全保存 JSON 文件"""
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except IOError as e:
        logger.error("保存 %s 失败: %s", filepath, e)


# ==================== 抖音 API ====================

def get_latest_aweme(sec_uid: str) -> Optional[Dict[str, str]]:
    """获取用户最新作品信息

    Args:
        sec_uid: 抖音用户 sec_uid

    Returns:
        最新作品信息字典，失败返回 None
    """
    # 多个 API 端点兜底
    apis = [
        f"https://www.iesdouyin.com/web/api/v2/aweme/post/?sec_uid={sec_uid}&count=2&max_cursor=0",
        f"https://www.douyin.com/aweme/v1/web/aweme/post/?sec_user_id={sec_uid}&count=2&max_cursor=0",
    ]

    for api_url in apis:
        try:
            req = urllib.request.Request(
                api_url,
                headers={
                    "User-Agent": DEFAULT_USER_AGENT,
                    "Referer": f"https://www.douyin.com/user/{sec_uid}",
                },
            )
            with urllib.request.urlopen(req, timeout=DEFAULT_TIMEOUT) as resp:
                data = json.loads(resp.read())

            aweme_list = data.get("aweme_list", [])
            if aweme_list:
                latest = aweme_list[0]
                return {
                    "aweme_id": str(latest["aweme_id"]),
                    "desc": latest.get("desc", ""),
                    "video_url": f"https://www.douyin.com/video/{latest['aweme_id']}",
                }
        except Exception as e:
            logger.debug("API 请求失败 (%s): %s", api_url[:50], e)
            continue

    return None


# ==================== 微信推送 ====================

def send_wechat_push(sendkey: str, title: str, desp: str) -> bool:
    """通过 Server酱 发送微信推送

    Args:
        sendkey: Server酱 SendKey
        title: 消息标题
        desp: 消息内容（Markdown）

    Returns:
        是否发送成功
    """
    if not sendkey:
        return False

    url = f"https://sctapi.ftqq.com/{sendkey}.send"
    data = urllib.parse.urlencode(
        {"title": title, "desp": desp[:10000]}
    ).encode("utf-8")

    try:
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
        return result.get("code") == 0 or result.get("errno") == 0
    except Exception as e:
        logger.error("微信推送失败: %s", e)
        return False


# ==================== 主逻辑 ====================

def main() -> None:
    """主函数"""
    # 通过环境变量控制是否启用
    if os.environ.get("ENABLE_POST_CHECK", "").lower() != "true":
        logger.info("新作品检测已禁用 (设置 ENABLE_POST_CHECK=true 启用)")
        return

    # 加载配置
    raw_config = os.environ.get("BLIVE_CONFIG", "{}")
    try:
        cfg = json.loads(raw_config)
        sendkey = cfg.get("sendkey", "")
    except json.JSONDecodeError as e:
        logger.error("解析 BLIVE_CONFIG 失败: %s", e)
        sendkey = ""

    # 加载房间列表
    rooms: List[Dict[str, str]] = load_json_file(ROOMS_FILE, [])
    douyin_rooms = [r for r in rooms if r.get("platform") == "douyin"]

    if not douyin_rooms:
        logger.info("没有配置抖音房间")
        return

    # 加载追踪数据
    tracking: Dict[str, Dict[str, Any]] = load_json_file(TRACKING_FILE, {})

    now_str = bjnow().strftime("%Y-%m-%d %H:%M:%S")
    post_changed = False

    logger.info("开始检测 %d 个抖音用户的新作品...", len(douyin_rooms))

    for room in douyin_rooms:
        web_rid = room["id"]
        name = room.get("name", web_rid)
        key = f"douyin_{web_rid}"
        t = tracking.get(key, {})

        # sec_uid 由 check_status.py 写入
        sec_uid = t.get("sec_uid", "")
        if not sec_uid:
            logger.info("  [%s] 暂无 sec_uid，等待直播检测...", name)
            continue

        # 获取最新作品
        aweme = get_latest_aweme(sec_uid)
        if not aweme:
            logger.warning("  [%s] 获取作品失败，跳过", name)
            continue

        prev_id = t.get("latest_aweme_id", "")
        logger.info(
            "  [%s] 最新作品: %s (上次: %s)",
            name,
            aweme["aweme_id"],
            prev_id or "无",
        )

        # 检测是否有新作品
        if prev_id and prev_id != aweme["aweme_id"]:
            desc = aweme.get("desc", "") or "[无描述]"
            logger.info("  [%s] 🆕 新作品: %s", name, desc[:40])

            title = f"🆕 {name} 发布了新作品"
            desp = (
                f"## 🆕 {name} 发布了新作品\n\n"
                f"**描述**: {desc}\n\n"
                f"👉 [查看作品]({aweme['video_url']})\n\n"
                f"---\n检测时间: {now_str}"
            )

            if sendkey:
                try:
                    ok = send_wechat_push(sendkey, title, desp)
                    logger.info("    → 推送%s", "成功" if ok else "失败")
                except Exception as e:
                    logger.error("    → 推送异常: %s", e)

        # 更新追踪数据
        t["latest_aweme_id"] = aweme["aweme_id"]
        t["latest_desc"] = aweme.get("desc", "")
        tracking[key] = t
        post_changed = True

    # 保存追踪数据
    if post_changed:
        save_json_file(TRACKING_FILE, tracking)

    logger.info("新作品检测完成")


if __name__ == "__main__":
    main()
