#!/usr/bin/env python3
"""
抖音新作品检测（GitHub Actions 用，独立于直播监控）

设计说明：
- 本脚本与直播监控完全解耦：直播监控读 rooms.json、写 tracking.json/state.json；
  本脚本只读 post_rooms.json（独立的抖音号列表），写 post_tracking.json。
- 抖音作品列表接口需要 X-Bogus + msToken 签名，纯服务端 urllib 无法获取。但只要在
  已加载抖音页面的浏览器上下文里用 fetch 调用该接口，浏览器会自动带上签名/cookie，
  返回完整 JSON（含图文 note 和视频 video，按发布时间倒序）。本脚本据此实现：
  先用无头 Chromium 打开用户主页，再在页面内 fetch 作品 API，取最新一条。
- 每个账号的 sec_uid 在本脚本内自行解析（优先用已存值；否则从直播页提取），不依赖
  直播监控的任何产物。
- 通过 Server酱 推送通知；通过环境变量 ENABLE_POST_CHECK=true 启用。
"""

import json
import os
import re
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any

# ==================== 常量配置 ====================

# 北京时间（UTC+8）
BEIJING_TZ = timezone(timedelta(hours=8))

# 文件路径（与本脚本同目录）
REPO_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(REPO_DIR, "post_rooms.json")      # 作品监控的抖音号列表（独立）
TRACKING_FILE = os.path.join(REPO_DIR, "post_tracking.json")  # 作品监控状态（独立）

# 浏览器配置
BROWSER_TIMEOUT = 30000   # 页面加载超时（ms）
SETTLE_WAIT = 6000        # 主页加载后等待 SPA 渲染（ms）

# 抖音作品列表 API（在浏览器页面内 fetch，自动带签名/cookie）
AWEME_POST_API = (
    "https://www.douyin.com/aweme/v1/web/aweme/post/"
    "?device_platform=webapp&aid=6383&channel=channel_pc_web"
    "&sec_user_id={sec_uid}&max_cursor=0&count=20"
)

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


# ==================== sec_uid 解析 ====================

def resolve_sec_uid(context, entry_id: str) -> Optional[str]:
    """解析某抖音号的 sec_uid

    优先：entry_id 本身已是 sec_uid（MS4w 开头）则直接用；
    否则：打开该号的直播页，从页面 HTML 提取主人 sec_uid（直播中取主页链接，离线取首个 sec_uid）。

    Args:
        context: Playwright BrowserContext
        entry_id: post_rooms.json 里的 id（可能是 sec_uid 或直播房号 web_rid）

    Returns:
        sec_uid 字符串，失败返回 None
    """
    if entry_id.startswith("MS4w"):
        return entry_id

    url = f"https://live.douyin.com/{entry_id}"
    page = context.new_page()
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=BROWSER_TIMEOUT)
        page.wait_for_timeout(3000)
        # 优先：主播主页链接（直播中时出现，最可靠）
        links = page.eval_on_selector_all(
            'a[href*="/user/"]',
            "els => els.map(a => a.getAttribute('href') || '').filter(h => h.indexOf('/user/') >= 0)",
        )
        for h in links:
            if "/user/self" in h:
                continue
            m = re.search(r"/user/(MS4wLjABAAAA[A-Za-z0-9_\-]+)", h)
            if m:
                return m.group(1)
        # 兜底：从页面 HTML 取第一个 sec_uid（离线房间也能拿到房间主人）
        html = page.content()
        m = re.search(r"MS4wLjABAAAA[A-Za-z0-9_\-]+", html)
        if m:
            return m.group(0)
        logger.warning("  [%s] 直播页未找到 sec_uid", entry_id)
        return None
    except Exception as e:
        logger.warning("  [%s] 解析 sec_uid 失败: %s", entry_id, e)
        return None
    finally:
        page.close()


# ==================== 浏览器抓取 ====================

def get_latest_aweme(context, sec_uid: str) -> Optional[Dict[str, str]]:
    """在浏览器页面内 fetch 作品 API，取用户最新作品

    流程：打开用户主页（让浏览器拿到 cookie / 签名上下文）→ 在页面内 fetch 作品 API
    → 解析 JSON 取 aweme_list[0]。返回的 aweme_id 同时覆盖 video 和 note(图文)。

    Args:
        context: Playwright BrowserContext（复用，避免每房间重启浏览器）
        sec_uid: 抖音用户 sec_uid

    Returns:
        最新作品信息字典，失败返回 None
    """
    home = f"https://www.douyin.com/user/{sec_uid}"
    page = context.new_page()
    try:
        page.goto(home, wait_until="domcontentloaded", timeout=BROWSER_TIMEOUT)
        page.wait_for_timeout(SETTLE_WAIT)

        # 在页面上下文内 fetch 作品 API（浏览器自动带签名与 cookie）
        result = page.evaluate(
            """async (sec_uid) => {
                const url = 'https://www.douyin.com/aweme/v1/web/aweme/post/'
                    + '?device_platform=webapp&aid=6383&channel=channel_pc_web'
                    + '&sec_user_id=' + sec_uid + '&max_cursor=0&count=20';
                try {
                    const r = await fetch(url, {credentials: 'include', headers: {'accept': 'application/json'}});
                    const t = await r.text();
                    return {status: r.status, body: t};
                } catch(e) { return {status: 0, body: '', err: String(e)}; }
            }""",
            sec_uid,
        )

        status = result.get("status", 0)
        body = result.get("body", "") or ""
        if status != 200 or not body:
            logger.warning("  [%s] 作品 API 异常 status=%s body_len=%d", sec_uid[:12], status, len(body))
            return None

        data = json.loads(body)
        aw_list = data.get("aweme_list", []) or []
        if not aw_list:
            logger.warning("  [%s] 作品列表为空", sec_uid[:12])
            return None

        latest = aw_list[0]
        aid = str(latest.get("aweme_id", ""))
        if not aid:
            return None
        # 图文 note 的链接是 /note/{id}，视频是 /video/{id}
        is_note = bool(latest.get("images"))
        link_path = "note" if is_note else "video"
        return {
            "aweme_id": aid,
            "desc": latest.get("desc", "") or "",
            "video_url": f"https://www.douyin.com/{link_path}/{aid}",
            "is_note": is_note,
        }
    except Exception as e:
        logger.warning("  [%s] 获取作品异常: %s", sec_uid[:12], e)
        return None
    finally:
        page.close()


# ==================== 微信推送 ====================

def send_wechat_push(sendkey: str, title: str, desp: str) -> bool:
    """通过 Server酱 发送微信推送"""
    if not sendkey:
        return False

    import urllib.request
    import urllib.parse

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
    if os.environ.get("ENABLE_POST_CHECK", "").lower() != "true":
        logger.info("新作品检测已禁用 (设置 ENABLE_POST_CHECK=true 启用)")
        return

    # 加载配置（仅取 SendKey）
    raw_config = os.environ.get("BLIVE_CONFIG", "{}")
    try:
        cfg = json.loads(raw_config)
        sendkey = cfg.get("sendkey", "")
    except json.JSONDecodeError as e:
        logger.error("解析 BLIVE_CONFIG 失败: %s", e)
        sendkey = ""

    # 加载作品监控专属的抖音号列表
    post_rooms: List[Dict[str, str]] = load_json_file(CONFIG_FILE, [])
    if not post_rooms:
        logger.info("post_rooms.json 为空，没有需要监控新作品的抖音号")
        return

    # 加载作品监控状态
    tracking: Dict[str, Dict[str, Any]] = load_json_file(TRACKING_FILE, {})
    now_str = bjnow().strftime("%Y-%m-%d %H:%M:%S")
    changed = False

    logger.info("开始检测 %d 个抖音用户的新作品...", len(post_rooms))

    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
                "--disable-gpu",
            ],
        )
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 900},
            locale="zh-CN",
        )

        for entry in post_rooms:
            rid = entry.get("id", "")
            name = entry.get("name", rid)
            if not rid:
                continue
            key = f"douyin_{rid}"
            t = tracking.get(key, {})

            # 解析 sec_uid（优先用已存值，否则从直播页解析；解析成功即缓存）
            sec_uid = t.get("sec_uid") or resolve_sec_uid(context, rid)
            if not sec_uid:
                logger.warning("  [%s] 无法获取 sec_uid，跳过", name)
                continue
            t["sec_uid"] = sec_uid
            tracking[key] = t
            changed = True

            # 获取最新作品
            aweme = get_latest_aweme(context, sec_uid)
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

            # 检测是否有新作品（仅当此前已有基线且发生变化时才推送）
            if prev_id and prev_id != aweme["aweme_id"]:
                desc = aweme.get("desc", "") or "[无描述]"
                kind = "图文" if aweme.get("is_note") else "视频"
                logger.info("  [%s] 🆕 新作品(%s): %s", name, kind, desc[:40])

                title = f"🆕 {name} 发布了新作品"
                desp = (
                    f"## 🆕 {name} 发布了新作品\n\n"
                    f"**类型**: {kind}\n\n"
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

            t["latest_aweme_id"] = aweme["aweme_id"]
            t["latest_desc"] = aweme.get("desc", "")
            tracking[key] = t
            changed = True

        context.close()
        browser.close()

    if changed:
        save_json_file(TRACKING_FILE, tracking)

    logger.info("新作品检测完成")


if __name__ == "__main__":
    main()
