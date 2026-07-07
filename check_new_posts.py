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
# 注意：每次只取固定条数容易漏掉"刚发布、尚未被接口索引"的最新图文/视频；
# 因此实际请求时在代码里拼接 &max_cursor=&count=35，并做翻页 + 二次重试取并集。
AWEME_POST_API = (
    "https://www.douyin.com/aweme/v1/web/aweme/post/"
    "?device_platform=webapp&aid=6383&channel=channel_pc_web"
    "&sec_user_id={sec_uid}"
)

# 翻页 / 重试参数
MAX_POST_PAGES = 3        # 单个账号最多翻几页（作品很多的账号也能覆盖）
POST_PER_PAGE = 35        # 每页条数（20 偏小，曾实测漏抓作品）
POST_RETRY_SETTLE = 3000  # 二次请求前的额外等待（ms），给抖音索引最新作品一点时间

# 页面内 fetch 作品 API 的通用 JS（接收完整 URL）
_FETCH_POST_JS = """async (url) => {
    try {
        const r = await fetch(url, {credentials: 'include', headers: {'accept': 'application/json'}});
        const t = await r.text();
        return {status: r.status, body: t};
    } catch(e) { return {status: 0, body: '', err: String(e)}; }
}"""

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
    → 解析 JSON。为降低"刚发布、尚未被接口索引"的最新作品被漏抓的概率，做以下增强：
      1) 每页取 POST_PER_PAGE(35) 条（原 20 偏小，实测会漏作品）；
      2) 按 has_more 翻页，聚合全部作品；
      3) 二次请求取并集后再按发布时间(create_time)取真正最新的一条，
         规避置顶(is_top)作品排在列表最前但不是"最新"的情况。

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

        # 两次请求取并集（第二次前多等一会，给抖音索引最新作品的时间）
        seen: Dict[str, Dict] = {}
        for attempt in range(2):
            if attempt > 0:
                page.wait_for_timeout(POST_RETRY_SETTLE)
            cursor = 0
            for _ in range(MAX_POST_PAGES):
                url = AWEME_POST_API.format(sec_uid=sec_uid) + f"&max_cursor={cursor}&count={POST_PER_PAGE}"
                result = page.evaluate(_FETCH_POST_JS, url)
                status = result.get("status", 0)
                body = result.get("body", "") or ""
                if status != 200 or not body:
                    logger.warning("  [%s] 作品 API 异常 status=%s body_len=%d",
                                   sec_uid[:12], status, len(body))
                    break
                try:
                    data = json.loads(body)
                except json.JSONDecodeError:
                    logger.warning("  [%s] 作品 API 返回非 JSON", sec_uid[:12])
                    break
                aw_list = data.get("aweme_list", []) or []
                for w in aw_list:
                    aid = str(w.get("aweme_id", ""))
                    if aid:
                        seen[aid] = w
                if not data.get("has_more"):
                    break
                nxt = data.get("max_cursor")
                if nxt is None or nxt == cursor:
                    break
                cursor = nxt
                page.wait_for_timeout(1200)

        if not seen:
            logger.warning("  [%s] 作品列表为空", sec_uid[:12])
            return None

        # 按发布时间(create_time)取真正最新一条（置顶作品不计入"最新"）
        latest = max(seen.values(), key=lambda x: int(x.get("create_time", 0) or 0))
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
            "nickname": (latest.get("author") or {}).get("nickname", "") or "",
            "create_time": int(latest.get("create_time", 0) or 0),
        }
    except Exception as e:
        logger.warning("  [%s] 获取作品异常: %s", sec_uid[:12], e)
        return None
    finally:
        page.close()


# ==================== 消息推送（多通道，配置可切换）====================
# 推送实现见 push_utils.py（直播监控与新作品监控共用），在此直接复用。
from push_utils import dispatch_push, load_push_cfg

# ==================== 主逻辑 ====================

def main() -> None:
    """主函数"""
    if os.environ.get("ENABLE_POST_CHECK", "").lower() != "true":
        logger.info("新作品检测已禁用 (设置 ENABLE_POST_CHECK=true 启用)")
        return

    # 加载配置（推送渠道）：优先 BLIVE_CONFIG 环境变量，兼容旧 sendkey 写法
    raw_config = os.environ.get("BLIVE_CONFIG", "{}")
    push_cfg = load_push_cfg(raw_config)

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
            prev_ct = int(t.get("latest_ct", 0) or 0)
            new_ct = int(aweme.get("create_time", 0) or 0)
            logger.info(
                "  [%s] 接口取到最新作品: %s (上次基线: %s)",
                name, aweme["aweme_id"], prev_id or "无",
            )

            # 仅当接口返回的作品"确实比基线更新"时才视为新作品并推送。
            # 否则（接口返回的反而更旧，即抖音接口尚未收录我们已知的更新作品，
            # 属 feed 延迟）只静默保留已有基线，不误推送、也不回退显示。
            is_newer = (new_ct > prev_ct) if prev_ct else True
            if prev_id and prev_id != aweme["aweme_id"] and is_newer:
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

                if push_cfg:
                    try:
                        ok = dispatch_push(push_cfg, title, desp)
                        logger.info("    → 推送%s", "成功" if ok else "失败")
                    except Exception as e:
                        logger.error("    → 推送异常: %s", e)

            # 只有在"本次拿到的工作不比基线更旧"时才用接口结果覆盖基线，
            # 避免抖音接口延迟导致显示回退到旧作品（例如已知最新图文尚未被接口收录）。
            if not prev_ct or new_ct >= prev_ct:
                t["latest_aweme_id"] = aweme["aweme_id"]
                t["latest_desc"] = aweme.get("desc", "")
                t["latest_type"] = "图文" if aweme.get("is_note") else "视频"
                t["latest_url"] = aweme.get("video_url", "")
                t["latest_ct"] = new_ct
                t["nickname"] = aweme.get("nickname", "") or t.get("nickname", "")
            else:
                logger.info("  [%s] 接口返回作品较旧，保留已有基线（抖音接口延迟）", name)
            tracking[key] = t
            changed = True

        context.close()
        browser.close()

    # 清理已不在监控列表中的账号状态（避免历史残留）
    cur_keys = {f"douyin_{e.get('id', '')}" for e in post_rooms if e.get("id")}
    for k in [k for k in list(tracking.keys()) if k.startswith("douyin_") and k not in cur_keys]:
        del tracking[k]
        changed = True

    if changed:
        save_json_file(TRACKING_FILE, tracking)

    logger.info("新作品检测完成")


if __name__ == "__main__":
    main()
