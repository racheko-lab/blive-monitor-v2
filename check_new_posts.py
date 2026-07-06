#!/usr/bin/env python3
"""
抖音新作品检测（GitHub Actions 用）

实现说明：
- 抖音作品列表接口（aweme/post）需要 X-Bogus + msToken 签名，纯服务端 urllib 无法获取；
  用户主页 SSR 又是 JS 反爬墙，服务端裸抓拿不到内容。
- 因此本脚本改用无头 Chromium（Playwright）加载用户主页，由浏览器原生完成签名/挑战，
  直接读取渲染后的视频列表，取用户「作品」里最新的一条。
- sec_uid 由 check_status.py 写入 tracking.json（key: sec_uid），本脚本读取它拼主页 URL。
- 通过 Server酱 推送通知；通过环境变量 ENABLE_POST_CHECK=true 启用。
"""

import json
import os
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any

# ==================== 常量配置 ====================

# 北京时间（UTC+8）
BEIJING_TZ = timezone(timedelta(hours=8))

# 文件路径
REPO_DIR = os.path.dirname(os.path.abspath(__file__))
ROOMS_FILE = os.path.join(REPO_DIR, "rooms.json")
TRACKING_FILE = os.path.join(REPO_DIR, "tracking.json")

# 浏览器配置
BROWSER_TIMEOUT = 30000       # 页面加载超时（ms）
SELECTOR_TIMEOUT = 20000      # 等待视频卡片超时（ms）
SETTLE_WAIT = 2500            # 卡片出现后额外等待懒加载（ms）

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


# ==================== 浏览器抓取 ====================

def get_latest_aweme(context, sec_uid: str) -> Optional[Dict[str, str]]:
    """用无头浏览器加载用户主页，取用户最新作品

    Args:
        context: Playwright BrowserContext（复用，避免每房间重启浏览器）
        sec_uid: 抖音用户 sec_uid

    Returns:
        最新作品信息字典，失败返回 None
    """
    url = f"https://www.douyin.com/user/{sec_uid}"
    page = context.new_page()
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=BROWSER_TIMEOUT)
        # 等待视频卡片渲染
        try:
            page.wait_for_selector('a[href*="/video/"]', timeout=SELECTOR_TIMEOUT)
        except Exception:
            logger.warning("  [%s] 未等到视频卡片（可能触发验证或账号无作品）", sec_uid[:12])
            return None
        page.wait_for_timeout(SETTLE_WAIT)

        # 切到「作品」标签页（默认也可能混有「猜你喜欢」推荐流）
        for sel in [
            '[role="tab"]:has-text("作品")',
            'a:has-text("作品")',
            'div:has-text("作品")',
        ]:
            try:
                el = page.locator(sel).first
                if el.count() and el.is_visible():
                    el.click(timeout=5000)
                    break
            except Exception:
                pass

        # 滚动若干次，触发作品网格懒加载（推荐流有时抢先渲染）
        for _ in range(4):
            page.mouse.wheel(0, 1000)
            page.wait_for_timeout(900)

        # 提取视频卡片：id + 描述 + 原始 href
        cards = page.eval_on_selector_all(
            'a[href*="/video/"]',
            """els => els.slice(0, 20).map(a => {
                const href = a.getAttribute('href') || '';
                const m = href.match(/\\/video\\/(\\d+)/);
                const id = m ? m[1] : '';
                const txt = (a.innerText || a.getAttribute('aria-label') || '').trim().replace(/\\s+/g, ' ');
                return { href, id, txt: txt.slice(0, 200) };
            })""",
        )

        # 过滤掉抖音「推荐流」（带 source= 的是推荐，不是该用户本人作品）
        own = [c for c in cards if c.get("id") and "source=" not in c["href"]]
        if not own:
            # 只看到推荐流、没拿到用户本人作品：宁可跳过本轮，也不误把推荐当新作品推送
            logger.warning("  [%s] 未解析到用户本人作品（可能作品网格未加载/触发验证），本轮跳过", sec_uid[:12])
            return None

        latest = own[0]
        return {
            "aweme_id": latest["id"],
            "desc": latest.get("txt", ""),
            "video_url": f"https://www.douyin.com/video/{latest['id']}",
        }
    except Exception as e:
        logger.warning("  [%s] 获取作品异常: %s", sec_uid[:12], e)
        return None
    finally:
        page.close()


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

    # 启动无头浏览器（整个检测只启动一次，逐房间复用）
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

        context.close()
        browser.close()

    # 保存追踪数据
    if post_changed:
        save_json_file(TRACKING_FILE, tracking)

    logger.info("新作品检测完成")


if __name__ == "__main__":
    main()
