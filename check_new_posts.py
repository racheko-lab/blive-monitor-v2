#!/usr/bin/env python3
"""
抖音新作品检测（GitHub Actions 用，独立于直播监控）

设计说明：
- 本脚本与直播监控完全解耦：直播监控读 rooms.json、写 tracking.json/state.json；
  本脚本只读 post_rooms.json（独立的抖音号列表），写 post_tracking.json。
- 抖音的作品列表接口（aweme/v1/web/aweme/post/）现在强制要求 X-Bogus / a_bogus 签名 +
  WebID / 登录态，纯服务端 urllib 或无头浏览器裸调都会返回空列表（被风控）。
  因此本脚本采用「两层策略 + 优雅降级」：
    策略 1（首选，需登录 Cookie）：在无头浏览器里打开用户主页，拦截页面【自身】发出的、
            已带签名的 aweme/post 请求响应（浏览器自动生成 a_bogus/msToken/webid，无需逆向）。
            配置 douyin_cookie 后该响应返回真实作品列表（含 create_time/desc），
            可精确推送「X 发布了新作品」并链接到具体作品。
    策略 2（退化，无需 Cookie）：解析 user/profile/other 的 aweme_count。
            经验证该接口在【未登录】时仍返回真实作品总数（status_code:0），
            作品数增加时推测「可能有新作品」，推送一条带主页链接的提示请用户自行确认。
- 为什么不再用「主页 DOM 提取作品链接」：经验证，无登录态时用户主页几乎全是被推荐流占据，
  所谓「干净链接」（不带 source=Baiduspider）每次加载都会变化，无法可靠区分用户自身作品
  与他者推荐视频，据此推送会造成大量误报，故已弃用该策略。
- 两层都拿不到（被风控/未登录且 profile 接口也异常）时，明确打印提示并保留基线，不静默、不刷屏。
- 每个账号的 sec_uid 在本脚本内自行解析（优先用已存值 / post_rooms.json 直存值；否则从直播页
  的【房间主人 anchor】结构化字段提取，绝不取推荐流），不依赖直播监控产物。
  解析后对「实际账号」做中毒防护：用已捕获 profile 的 unique_id 校验 sec_uid 是否真对应本 handle，
  若被推荐流污染则跳过并清除毒值，避免误监控陌生人。
- 通过多渠道推送（见 push_utils），启用开关：环境变量 ENABLE_POST_CHECK=true。
"""

import json
import os
import re
import logging
from typing import Dict, List, Optional, Any, Tuple

# 公共工具（时间/JSON 读写），避免与 check_status.py 重复定义
from common import bjnow, load_json_file, save_json_file, BEIJING_TZ
# 推送实现见 push_utils.py（直播监控与新作品监控共用）
from push_utils import dispatch_push, load_push_cfg

# ==================== 常量配置 ====================

# 文件路径（与本脚本同目录）
REPO_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(REPO_DIR, "post_rooms.json")      # 作品监控的抖音号列表（独立）
TRACKING_FILE = os.path.join(REPO_DIR, "post_tracking.json")  # 作品监控状态（独立）

# 浏览器配置
BROWSER_TIMEOUT = 30000   # 页面加载超时（ms）
SETTLE_WAIT = 6000        # 主页加载后等待 SPA 渲染（ms）

# 移动端 UA / 视口：用于访问 m.douyin.com 的老接口 web/api/v2/aweme/post/，
# 该接口**无 Cookie 即返回真实作品列表**（含 aweme_id/desc/视频或图文链接），
# 是所有账号通用、无需登录的「精确检测」首选路径。
MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 "
    "Mobile/15E148 Safari/604.1"
)
MOBILE_VIEWPORT = {"width": 390, "height": 844}

# ==================== 日志配置 ====================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


# ==================== 新作品基线判定（纯函数，便于单测） ====================

def _post_is_newer(prev_id: str, prev_ct: int, new_id: str, new_ct: int) -> bool:
    """判断 new 是否比 prev 更新。

    优先用 create_time；若任一方缺 create_time（例如从 DOM 提取、或接口未返回），
    退化为按 aweme_id 数值比较——抖音作品 id 近似单调递增，新作品 id 更大。
    """
    if prev_ct and new_ct:
        return new_ct > prev_ct
    try:
        return int(new_id or 0) > int(prev_id or 0)
    except (ValueError, TypeError):
        return bool(new_id) and new_id != prev_id


def should_notify_new_post(
    prev_id: str, prev_ct: int, new_id: str, new_ct: int
) -> bool:
    """是否应就「新作品」推送。

    规则：
    - 首次（无基线 prev_id）仅建立基线，不推送（避免启用即轰炸）；
    - 同一作品（id 相同）不重复推送；
    - 仅当接口返回的作品「确实比基线更新」时才视为新作品并推送。
      否则（接口返回的反而更旧，即抖音接口尚未收录我们已知的更新作品，属 feed 延迟）
      只静默保留已有基线，不误推送、也不回退显示。
    """
    if not prev_id:
        return False
    if prev_id == new_id:
        return False
    return _post_is_newer(prev_id, prev_ct, new_id, new_ct)


def should_update_baseline(prev_id: str, prev_ct: int, new_id: str, new_ct: int) -> bool:
    """是否用本次结果覆盖基线。

    - 首次建立基线；
    - 同一作品（id 相同）：刷新 ct/desc；
    - 不同作品：仅当「更新」时覆盖基线（避免抖音接口延迟导致回退到旧作品，
      也避免 API→DOM 过渡时把更旧的 DOM 结果覆盖掉更优的 API 基线）。
    """
    if not prev_id:
        return True
    if prev_id == new_id:
        return True
    return _post_is_newer(prev_id, prev_ct, new_id, new_ct)


# ==================== 抖音 Cookie（可选，突破风控的关键） ====================

def load_douyin_cookie() -> str:
    """读取抖音登录 Cookie（可选）。

    优先环境变量 DOUYIN_COOKIE；其次 BLIVE_CONFIG 里的 douyin_cookie 字段。
    没有则返回空串——此时抖音接口会被风控，脚本会优雅降级（见 get_latest_aweme）。
    """
    env = os.environ.get("DOUYIN_COOKIE", "").strip()
    if env:
        return env
    raw = os.environ.get("BLIVE_CONFIG", "{}")
    try:
        cfg = json.loads(raw) if raw else {}
    except Exception:
        cfg = {}
    return (cfg.get("douyin_cookie") or "").strip()


def apply_douyin_cookie(context, cookie_str: str) -> None:
    """把 Cookie 字符串拆成单条写入浏览器上下文（仅当配置了才调用）。

    cookie_str 形如 "sessionid=xxx; passport_csrf_token=yyy; sid_tt=zz"
    """
    if not cookie_str:
        return
    cookies = []
    for part in cookie_str.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        k, v = part.split("=", 1)
        cookies.append({
            "name": k.strip(),
            "value": v.strip(),
            "domain": ".douyin.com",
            "path": "/",
        })
    if cookies:
        try:
            context.add_cookies(cookies)
            logger.info("已注入抖音登录 Cookie（%d 条），可突破作品接口风控", len(cookies))
        except Exception as e:
            logger.warning("注入抖音 Cookie 失败: %s", e)


# ==================== sec_uid 解析 ====================

# 房主 sec_uid 统一正则（供 extract_host_sec_uid / resolve_sec_uid 复用）
SEC_RE = re.compile(r"MS4wLjABAAAA[A-Za-z0-9_\-]+")


def is_sec_uid(s: str) -> bool:
    """判断字符串是否形如抖音 sec_uid（MS4w 开头）。"""
    return bool(s) and s.startswith("MS4w")


def looks_like_handle(s: str) -> bool:
    """判断字符串是否像抖音 handle（非纯数字、非 sec_uid）。

    用于「中毒防护」时决定是否用 profile 的 unique_id 反查校验：
    纯数字 id（如用户填的抖音数字号）无法与 unique_id 直接比对，此时信任直播页
    房主 anchor 解析出的 sec_uid，不做反查，避免误杀正确账号。
    """
    return bool(s) and not s.isdigit() and not is_sec_uid(s)


def extract_host_sec_uid(html: str) -> Optional[str]:
    """从直播页 HTML 提取【房主本人】的 sec_uid（纯函数，便于单测）。

    抖音直播页的房间主人信息嵌在结构化 JSON 中，形如::

        "anchor":{"id_str":"...","sec_uid":"MS4w...","nickname":"..."}

    该 ``anchor`` 字段始终位于推荐流之前，是房主本人。

    注意：**绝不可**对整页 HTML 用 ``re.search(r"MS4w...")`` 取「第一个 sec_uid」——
    离线页 / 推荐流里也充斥大量其他主播的 MS4w，会取到陌生人的 sec_uid，导致基线全错。
    旧版还曾用 ``a[href*="/user/"]`` 链接循环，但推荐流的 ``/user/`` 链接可能排在房主之前，
    同样会误取。这里只认房间主人的 ``anchor`` 结构化字段，确保拿到的是本人。

    Args:
        html: 直播页完整 HTML

    Returns:
        房主 sec_uid；取不到返回 None
    """
    if not html:
        return None
    # 房主结构化字段的 sec_uid 可能以两种形态出现：
    #   (A) 未转义 JSON：  "anchor":{"id_str":"...","sec_uid":"MS4w..."}
    #   (B) RENDER_DATA 转义形态（引号被转义，花括号不转义）：
    #                     \"anchor\":{\"id_str\":\"...\",\"sec_uid\":\"MS4w...\"}
    # 两种形态都只认「房间主人」字段（anchor / roomInfo / owner / or / anchorInfo），
    # 绝不对整页取「第一个 MS4w」——离线页/推荐流里充斥大量他者 sec_uid，会误取陌生人。
    # 注：用 [^{}]* 而非 [^}]*：anchor 对象内除 sec_uid 外无嵌套花括号，
    # 用 [^}]* 会贪婪吞掉 "sec_uid":"..." 导致匹配失败。
    SEC = r"(MS4wLjABAAAA[A-Za-z0-9_\-]+)"
    # 顺序：未转义优先，转义兜底；anchor 优先，其余结构化字段兜底。
    patterns = [
        # (A-1) 未转义 anchor（最精准，房主本人）
        r'"anchor"\s*:\s*\{[^{}]*?"sec_uid"\s*:\s*"' + SEC + r'"',
        # (A-2) 未转义 roomInfo/owner/or/anchorInfo/anchor
        r'"(?:roomInfo|owner|or|anchorInfo|anchor)"\s*:\s*\{[^{}]*?"sec_uid"\s*:\s*"' + SEC + r'"',
        # (B-1) 转义 anchor（RENDER_DATA 形态：\"anchor\":\{...\}）
        r'\\"anchor\\"\s*:\s*\{[^{}]*?\\"sec_uid\\"\s*:\s*\\"' + SEC + r'\\"',
        # (B-2) 转义 roomInfo/owner/or/anchorInfo/anchor
        r'\\"(?:roomInfo|owner|or|anchorInfo|anchor)\\"\s*:\s*\{[^{}]*?\\"sec_uid\\"\s*:\s*\\"' + SEC + r'\\"',
    ]
    for pat in patterns:
        m = re.search(pat, html)
        if m:
            return m.group(1)
    return None


def resolve_sec_uid(context, entry_id: str) -> Optional[str]:
    """解析某抖音号的真实 sec_uid（房主本人，绝不取推荐流）。

    解析顺序：
      1) entry_id 本身已是 sec_uid（MS4w 开头）→ 直接用；
      2) 打开直播页，从「房间主人 anchor」结构化字段提取（开播 / 离线均可，房主本人）；
      3) 兜底：拦截直播页自动发出的 user/profile/other 响应，取出房主 sec_uid；
      4) 都拿不到 → 返回 None（本次跳过该账号，避免监控陌生人）。

    说明：直播页的房主 anchor 字段在开播 / 离线两种状态下都会随页面下发
    （经验证，离线页的 RENDER_DATA 转义形态里同样含房主 sec_uid），因此该路径对
    「纯发视频、不直播」的账号也有效——这是前端网页添加的账号能正确解析的关键。

    Args:
        context: Playwright BrowserContext
        entry_id: post_rooms.json 里的 id（可能是 sec_uid、抖音 handle 或数字号 web_rid）

    Returns:
        sec_uid 字符串，失败返回 None
    """
    if is_sec_uid(entry_id):
        return entry_id

    url = f"https://live.douyin.com/{entry_id}"
    page = context.new_page()
    captured: Dict[str, str] = {}

    def on_resp(resp):
        # 兜底：直播页自动签发的 user/profile/other 响应里同时含 sec_uid 与 unique_id。
        # 仅当 unique_id 与 entry_id 一致（或页面未给 unique_id）时才采用，避免取错账号。
        u = resp.url
        if "user/profile/other" in u:
            try:
                body = resp.body().decode("utf-8", "replace")
                uid = parse_profile_handle(body)
                m = SEC_RE.search(body)
                if m and (not uid or uid == entry_id):
                    captured["profile"] = m.group(1)
            except Exception:
                pass

    try:
        page.on("response", on_resp)
        page.goto(url, wait_until="domcontentloaded", timeout=BROWSER_TIMEOUT)
        page.wait_for_timeout(3000)
        host = extract_host_sec_uid(page.content())
        if host:
            return host
        if captured.get("profile"):
            return captured["profile"]
        logger.warning("  [%s] 直播页未找到房主 sec_uid（可能页面未渲染，下次重试）", entry_id)
        return None
    except Exception as e:
        logger.warning("  [%s] 解析 sec_uid 失败: %s", entry_id, e)
        return None
    finally:
        page.close()


# ==================== 解析辅助（纯函数，便于单测） ====================

def parse_aweme_list(json_text: str) -> List[Dict[str, Any]]:
    """从 aweme/post 响应体解析作品列表，返回标准化 dict 列表。

    每个 dict: {aweme_id, desc, video_url, is_note, nickname, create_time}
    空/风控/异常返回 []。
    """
    if not json_text:
        return []
    try:
        data = json.loads(json_text)
    except Exception:
        return []
    # 风控/未登录：status_code 非 0 且无作品列表
    if data.get("status_code", 0) not in (0, None) and not data.get("aweme_list"):
        return []
    items = data.get("aweme_list") or []
    out: List[Dict[str, Any]] = []
    for w in items:
        aid = str(w.get("aweme_id", "") or "")
        if not aid:
            continue
        is_note = bool(w.get("images"))
        link = "note" if is_note else "video"
        out.append({
            "aweme_id": aid,
            "desc": w.get("desc", "") or "",
            "video_url": f"https://www.douyin.com/{link}/{aid}",
            "is_note": is_note,
            "nickname": (w.get("author") or {}).get("nickname", "") or "",
            "create_time": int(w.get("create_time", 0) or 0),
        })
    return out


def parse_aweme_count(profile_text: str) -> Optional[int]:
    """从 user/profile/other 响应体解析作品总数（aweme_count）。解析失败返回 None。"""
    if not profile_text:
        return None
    try:
        data = json.loads(profile_text)
    except Exception:
        return None
    user = data.get("user") or (data.get("data") or {}).get("user") or {}
    if not isinstance(user, dict):
        return None
    cnt = user.get("aweme_count")
    return int(cnt) if isinstance(cnt, int) else None


def parse_profile_handle(profile_text: str) -> Optional[str]:
    """从 user/profile/other 响应体解析账号唯一 handle（unique_id）。

    用于「中毒防护」：把拿到的 sec_uid 打开主页后，校验 profile 里的 unique_id 是否等于
    post_rooms.json 里期望的 handle。若不一致，说明该 sec_uid 来自推荐流陌生人，需清除重解。
    解析失败 / 无 unique_id 返回 None（交由上层决定是否跳过）。
    """
    if not profile_text:
        return None
    try:
        data = json.loads(profile_text)
    except Exception:
        return None
    user = data.get("user") or (data.get("data") or {}).get("user") or {}
    if not isinstance(user, dict):
        return None
    uid = user.get("unique_id")
    return uid if isinstance(uid, str) and uid else None


def _sort_key(it: Dict[str, Any]) -> Tuple[int, int]:
    """取最新作品：优先 create_time，缺失时退化为 aweme_id 数值（近似时间序）。"""
    ct = int(it.get("create_time") or 0)
    aid = int(it.get("aweme_id") or 0)
    return (ct, aid)


# ==================== 浏览器抓取（多策略） ====================

def get_latest_aweme(context, sec_uid: str) -> Optional[Dict[str, Any]]:
    """三层策略获取用户最新作品，返回标准化 dict（含 _conf 置信度）或 None。

    策略顺序（越靠前越精确）：
      0) 移动端老接口 m.douyin.com/web/api/v2/aweme/post/：**无 Cookie 即返回真实作品列表**
         （aweme_id / desc / 视频或图文链接），所有账号通用，作为首选精确检测；
      1) 桌面端 aweme/v1/web/aweme/post/（需登录 Cookie 才返回真实列表，含 create_time）；
      2) 退化 user/profile/other 的 aweme_count（无需 Cookie，作品数增加推测「可能有新作品」）。

    无论走哪条策略，都会额外在桌面端捕获 user/profile/other 拿到 unique_id，
    供 main() 做「中毒防护」校验 sec_uid 是否真对应本账号。

    注：移动端 v2 接口不返回 create_time，排序退化为按 aweme_id 数值（近似时间序，
    抖音作品 id 单调递增），_post_is_newer 已支持该降级。
    """
    # ---------- 策略 0：移动端 v2 接口（无 Cookie 直出真实作品）----------
    mctx = context.browser.new_context(
        user_agent=MOBILE_UA, viewport=MOBILE_VIEWPORT, is_mobile=True, locale="zh-CN",
    )
    mcap: Dict[str, str] = {}
    try:
        mpage = mctx.new_page()

        def on_m(resp):
            if "web/api/v2/aweme/post" in resp.url:
                try:
                    mcap["post"] = resp.body().decode("utf-8", "replace")
                except Exception:
                    pass

        mpage.on("response", on_m)
        mpage.goto(
            f"https://m.douyin.com/share/user/{sec_uid}",
            wait_until="domcontentloaded", timeout=BROWSER_TIMEOUT,
        )
        mpage.wait_for_timeout(SETTLE_WAIT)
    except Exception as e:
        logger.warning("  [%s] 移动端接口异常: %s", sec_uid[:12], e)
    finally:
        mctx.close()

    # ---------- 策略 1/2：桌面端（Cookie 精确接口 + 作品数/unique_id 兜底）----------
    page = context.new_page()
    dcap: Dict[str, str] = {}

    def on_resp(resp):
        u = resp.url
        try:
            if "/aweme/v1/web/aweme/post/" in u:
                dcap["post"] = resp.body().decode("utf-8", "replace")
            elif "user/profile/other" in u:
                dcap["profile"] = resp.body().decode("utf-8", "replace")
        except Exception:
            pass

    try:
        page.on("response", on_resp)
        page.goto(
            f"https://www.douyin.com/user/{sec_uid}",
            wait_until="domcontentloaded", timeout=BROWSER_TIMEOUT,
        )
        page.wait_for_timeout(SETTLE_WAIT)

        actual_uid = parse_profile_handle(dcap.get("profile"))

        # 策略 0 优先：移动端真实作品（无 Cookie）
        items = parse_aweme_list(mcap.get("post")) if mcap.get("post") else []
        if items:
            best = max(items, key=_sort_key)
            best["_conf"] = "api"
            best["_src"] = "mobile"
            best["actual_unique_id"] = actual_uid
            return best

        # 策略 1：桌面端 API 响应（需登录 Cookie）
        items = parse_aweme_list(dcap.get("post")) if dcap.get("post") else []
        if items:
            best = max(items, key=_sort_key)
            best["_conf"] = "api"
            best["_src"] = "desktop"
            best["actual_unique_id"] = actual_uid
            return best

        # 策略 2（退化）：作品数变化推测
        count = parse_aweme_count(dcap.get("profile"))
        if count is not None:
            return {
                "aweme_id": f"count:{count}",
                "desc": "（接口被风控/未登录，按作品数变化推测可能有新作品，请到主页确认）",
                "video_url": f"https://www.douyin.com/user/{sec_uid}",
                "is_note": False,
                "nickname": "",
                "create_time": count,
                "_conf": "count",
                "actual_unique_id": actual_uid,
            }
        return None
    except Exception as e:
        logger.warning("  [%s] 获取作品异常: %s", sec_uid[:12], e)
        return None
    finally:
        page.close()


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

    cookie = load_douyin_cookie()
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
        # 关键：注入登录 Cookie 可突破作品接口风控（可选，未配置则优雅降级）
        apply_douyin_cookie(context, cookie)

        gated_hint = False
        post_rooms_dirty = False
        for entry in post_rooms:
            rid = entry.get("id", "")
            name = entry.get("name", rid)
            if not rid:
                continue
            key = f"douyin_{rid}"
            t = tracking.get(key, {})

            # 解析 sec_uid：
            #  - 优先用已存值（tracking）或 post_rooms.json 直存值 → 视为「可信」，不再反查；
            #  - 否则从直播页解析（运行时解析，视为「不可信」，需 unique_id 反查校验）。
            stored_sec = t.get("sec_uid") or entry.get("sec_uid")
            if stored_sec:
                sec_uid = stored_sec
                sec_trusted = True
            else:
                sec_uid = resolve_sec_uid(context, rid)
                sec_trusted = False
            if not sec_uid:
                logger.warning("  [%s] 无法获取 sec_uid，跳过（建议开播时或配置 DOUYIN_COOKIE 后重试）", name)
                continue
            t["sec_uid"] = sec_uid
            tracking[key] = t
            changed = True

            # 获取最新作品（两层策略）
            aweme = get_latest_aweme(context, sec_uid)
            if not aweme:
                logger.warning("  [%s] 获取作品失败/被风控（建议配置 douyin_cookie）", name)
                gated_hint = True
                continue

            # 中毒防护：用已捕获 profile 的 unique_id 校验 sec_uid 是否真对应本 handle。
            #  - 仅当 rid 形如 handle（非纯数字、非 sec_uid）时才做反查，避免误杀数字号账号；
            #  - 可信（已存）sec_uid 即便反查不一致也保留并告警，绝不清除用户/历史沉淀的值；
            #  - 不可信（运行时解析）的若反查不一致，说明被推荐流污染，跳过并清除毒值，下次重解。
            actual_uid = aweme.get("actual_unique_id")
            if actual_uid and looks_like_handle(rid) and actual_uid != rid:
                if sec_trusted:
                    logger.warning(
                        "  [%s] ⚠️ 已存 sec_uid 指向账号(实际=%s)与填写 id(%s)不一致，"
                        "仍信任已存值继续监控", name, actual_uid, rid,
                    )
                else:
                    logger.warning(
                        "  [%s] ⚠️ 解析的 sec_uid 指向了错误账号(实际=%s≠%s)，"
                        "疑似被推荐流污染，本次跳过并清除该 sec_uid", name, actual_uid, rid,
                    )
                    t.pop("sec_uid", None)
                    tracking[key] = t
                    changed = True
                    continue

            # 写回：若本次 sec_uid 来自运行时解析（post_rooms.json 原本无），将其固化进
            # post_rooms.json，使该账号等价于「预存 sec_uid」的账号——此后即使直播页短暂
            # 取不到也不受影响。这正是让「前端网页添加的账号」与「预存 sec_uid 的账号」行为一致的关窍。
            if not entry.get("sec_uid") and sec_uid:
                entry["sec_uid"] = sec_uid
                post_rooms_dirty = True

            conf = aweme.get("_conf", "api")
            desc = aweme.get("desc", "") or "[无描述]"
            kind = "图文" if aweme.get("is_note") else "视频"
            prev_id = t.get("latest_aweme_id", "")
            prev_ct = int(t.get("latest_ct", 0) or 0)
            new_ct = int(aweme.get("create_time", 0) or 0)
            logger.info(
                "  [%s] 取到最新作品[%s]: %s (上次基线: %s)",
                name, conf, aweme["aweme_id"], prev_id or "无",
            )

            prev_mode = t.get("mode") or (
                "count" if (prev_id or "").startswith("count:") else ("api" if prev_id else "")
            )
            cur_mode = conf  # "api" 或 "count"

            notify = False
            do_update = True

            if conf == "api":
                # 精确：确有比基线更新的作品才推送；接口延迟返回更旧作品则保留基线
                notify = should_notify_new_post(prev_id, prev_ct, aweme["aweme_id"], new_ct)
                do_update = should_update_baseline(prev_id, prev_ct, aweme["aweme_id"], new_ct)
            else:  # conf == "count"：推测，仅当作品数确实增加且已有基线才提示
                if prev_mode and prev_mode != cur_mode:
                    # 模式切换（如从无 Cookie 计数推测切到有 Cookie 真实接口，或反之）：
                    # 无法确定其间是否真有新作品，仅静默重建基线，避免误报
                    notify = False
                    do_update = True
                else:
                    prev_count = int(t.get("latest_count", 0) or 0)
                    notify = bool(prev_count) and new_ct > prev_count
                    do_update = True

            if notify:
                if conf == "api":
                    logger.info("  [%s] 🆕 新作品(%s): %s", name, kind, desc[:40])
                    title = f"🆕 {name} 发布了新作品"
                    desp = (
                        f"## 🆕 {name} 发布了新作品\n\n"
                        f"**类型**: {kind}\n\n"
                        f"**描述**: {desc}\n\n"
                        f"👉 [查看作品]({aweme['video_url']})\n\n"
                        f"---\n检测时间: {now_str}"
                    )
                else:
                    prev_count = int(t.get("latest_count", 0) or 0)
                    logger.info("  [%s] 🔔 作品数 %d→%d，推测可能有新作品", name, prev_count, new_ct)
                    title = f"🔔 {name} 可能发布了新作品"
                    desp = (
                        f"## 🔔 {name} 可能发布了新作品\n\n"
                        f"**作品数变化**: {prev_count} → {new_ct}\n\n"
                        f"接口被风控/未登录，无法获取具体作品，请到主页确认：\n"
                        f"👉 [打开 {name} 的主页]({aweme['video_url']})\n\n"
                        f"---\n检测时间: {now_str}"
                    )
                if push_cfg:
                    try:
                        ok = dispatch_push(push_cfg, title, desp)
                        logger.info("    → 推送%s", "成功" if ok else "失败")
                    except Exception as e:
                        logger.error("    → 推送异常: %s", e)

            if do_update:
                t["latest_aweme_id"] = aweme["aweme_id"]
                t["latest_ct"] = new_ct
                t["mode"] = conf
                t["latest_count"] = new_ct
                if conf == "api":
                    t["latest_desc"] = aweme.get("desc", "")
                    t["latest_type"] = kind
                    t["latest_url"] = aweme.get("video_url", "")
                    t["nickname"] = aweme.get("nickname", "") or t.get("nickname", "")
            else:
                logger.info("  [%s] 接口返回作品较旧，保留已有基线（抖音接口延迟）", name)
            tracking[key] = t
            changed = True

        context.close()
        browser.close()

    if gated_hint:
        logger.warning(
            "部分账号作品接口被风控/未登录，新作品可能漏检。"
            "请在 BLIVE_CONFIG 增加 douyin_cookie（浏览器登录抖音后的 Cookie），"
            "或设置环境变量 DOUYIN_COOKIE 以突破风控。"
        )

    # 清理已不在监控列表中的账号状态（避免历史残留）
    cur_keys = {f"douyin_{e.get('id', '')}" for e in post_rooms if e.get("id")}
    for k in [k for k in list(tracking.keys()) if k.startswith("douyin_") and k not in cur_keys]:
        del tracking[k]
        changed = True

    # 固化本次运行时解析出的 sec_uid 回 post_rooms.json（使前端网页添加的账号等价于预存 sec_uid）
    if post_rooms_dirty:
        save_json_file(CONFIG_FILE, post_rooms)
        logger.info("已将 %d 个账号解析到的 sec_uid 写回 post_rooms.json",
                    sum(1 for e in post_rooms if e.get("sec_uid")))

    if changed:
        save_json_file(TRACKING_FILE, tracking)

    logger.info("新作品检测完成")


if __name__ == "__main__":
    main()
