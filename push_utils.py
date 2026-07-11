#!/usr/bin/env python3
"""
多通道推送工具（直播监控 / 新作品监控共用）

支持渠道（BLIVE_CONFIG 环境变量 / blive_config.json 中的 "push" 段）：
  serverchan  -> 方糖 Server酱（个人微信，免费 5 条/天）
  wecom       -> 企业微信群机器人 Webhook（免费、无每日上限，推荐）
  pushplus    -> 推送加 PushPlus（个人微信，免费档额度更高）
  bark        -> Bark（iPhone 通知，无限，需 iOS；支持可选 group 分组）
  telegram    -> Telegram Bot（无限，需 BotFather 申请 token）

配置示例：
  {"push": {"type": "wecom", "webhook": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxxx"}}
  {"push": {"type": "bark", "url": "https://api.day.app/KEY", "group": "blive"}}
兼容旧配置：仅有 "sendkey" 时自动按 serverchan 处理。

P0-2 通知可靠性（本模块改动）：
  - 新增 ``SendResult``：单次/重试后聚合的结构化结果（ok/attempts/last_error/status_code）。
  - 新增 ``is_retryable``：失败分类（5xx/429/网络→重试；4xx/业务拒绝/配置缺失→放弃）。
  - 新增 ``send_with_retry``：指数退避重试（默认 3 次，2s/4s/8s）。
  - ``send_via_*`` 改为返回 ``SendResult``（捕获 HTTP 状态码 / 异常类别前缀）。
  - ``dispatch_push`` 返回 ``SendResult`` 并内置重试；``dispatch_push_ok`` 为兼容 bool 薄包装。
"""

import json
import logging
import time
import urllib.request
import urllib.parse
import urllib.error
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, Tuple

# A2/A4 预留：多通道选通道 + 模板拼接（CI 多通道消费留后续协调，本波不被 dispatch_push 调用）
from common import resolve_channel, render_template  # noqa: F401  (re-export，供 push_utils 命名空间下引用)

logger = logging.getLogger(__name__)


# ==================== 重试相关常量（集中配置，便于调参） ====================

# 最大尝试次数（含首次）；CI 单 run 额外 ≤14s，远低于 5min 周期。
PUSH_MAX_ATTEMPTS: int = 3
# 首跳退避秒数；退避序列 = BASE * 2**(i-1) => 2, 4, 8 ...
PUSH_BASE_DELAY: int = 2
# 失败事件 type（复用现有统一日志 "error"，零跨端改动）。
NOTIFY_FAIL_TYPE: str = "error"


# ==================== 结构化结果 ====================

@dataclass
class SendResult:
    """单次或重试后的结构化推送结果。

    Attributes:
        ok: 是否最终成功。
        attempts: 实际尝试次数（含首次）。
        last_error: 最后一次失败原因（含状态码 / 类别前缀，成功时为空串）。
        status_code: HTTP 状态码（网络 / 业务错误时为 ``None``）。
    """

    ok: bool
    attempts: int
    last_error: str
    status_code: Optional[int]


# ==================== 失败分类 ====================

def is_retryable(status_code: Optional[int], last_error: str) -> bool:
    """判断某次失败是否可重试（退避后重试）还是永久失败（立即放弃）。

    分类依据（仅看状态码 + last_error 类别前缀，不再持有原始 exc）：
      - 5xx / 429                           -> True（服务端抖动 / 限流，可重试）
      - 4xx（含 401/403/400/404）          -> False（鉴权 / 参数失效，重试无意义）
      - 网络 / 超时 / 连接错误               -> True（last_error 带 URLError / timeout 前缀）
      - 业务拒绝 / 配置缺失                  -> False（last_error 以 biz_reject / config /
                                               auth / empty 前缀）

    Note:
        任务简报曾写 ``is_retryable(exc, status_code)``，但 ``send_via_*`` 已把异常收敛进
        ``SendResult``（含 ``status_code`` 与带类别前缀的 ``last_error``），重试循环不再持有原始
        ``exc``。本实现采用 ``(status_code, last_error)``，分类信息无损且避免异常跨层透传
        （详见架构设计 §3.3）。

    Args:
        status_code: HTTP 状态码（网络 / 业务错误为 ``None``）。
        last_error: 失败原因字符串（带类别前缀）。

    Returns:
        ``True`` 表示可重试；``False`` 表示永久失败（不重试）。
    """
    if status_code is not None:
        return 500 <= status_code < 600 or status_code == 429
    le = (last_error or "").lower()
    if le.startswith(("biz_reject", "config", "auth", "empty")):
        return False
    # timeout / URLError / 未知网络错误一律视为可重试（保守兜底）
    return True


# ==================== 退避重试 ====================

def send_with_retry(
    send_fn: Callable[[str, str], SendResult],
    title: str,
    desp: str,
    max_attempts: int = PUSH_MAX_ATTEMPTS,
    base_delay: int = PUSH_BASE_DELAY,
) -> SendResult:
    """对 ``send_fn(title, desp) -> SendResult`` 做带指数退避的重试。

    行为：
      - 成功立即返回（``ok=True``，``attempts`` 为实际成功时的尝试序号）。
      - 失败且 ``is_retryable`` 为 False -> 立即返回（``ok=False``，不重试）。
      - 失败且可重试 -> ``time.sleep(base_delay * 2**(i-1))`` 后重试，最多 ``max_attempts`` 次。
      - 仅在「全部重试耗尽 / 永久失败」后返回 ``ok=False``。

    Args:
        send_fn: 单次发送函数，签名 ``(title, desp) -> SendResult``（如 ``send_via_wecom``）。
        title: 推送标题。
        desp: 推送正文。
        max_attempts: 最大尝试次数（含首次）。
        base_delay: 首跳退避秒数。

    Returns:
        聚合后的 ``SendResult``（``attempts`` 为实际尝试次数，``last_error`` 取最后一次）。
    """
    last: Optional[SendResult] = None
    for attempt in range(1, max_attempts + 1):
        res = send_fn(title, desp)  # SendResult(attempts=1)
        if res.ok:
            return SendResult(
                ok=True,
                attempts=attempt,
                last_error="",
                status_code=res.status_code,
            )
        last = res
        # 已达上限 或 永久失败 -> 立即返回，不重试
        if attempt >= max_attempts or not is_retryable(res.status_code, res.last_error):
            break
        time.sleep(base_delay * (2 ** (attempt - 1)))  # 2, 4, 8 ...
    if last is None:
        # send_fn 一次都没成功返回（理论上不会发生，兜底）
        return SendResult(ok=False, attempts=0, last_error="unknown", status_code=None)
    return SendResult(
        ok=False,
        attempts=attempt,
        last_error=last.last_error,
        status_code=last.status_code,
    )


# ==================== 单渠道发送（统一返回 SendResult，捕获状态码） ====================

def send_via_serverchan(sendkey: str, title: str, desp: str) -> SendResult:
    """通过 Server酱 发送微信推送，返回 ``SendResult``。"""
    if not sendkey:
        return SendResult(ok=False, attempts=1, last_error="config: empty sendkey", status_code=None)
    url = f"https://sctapi.ftqq.com/{sendkey}.send"
    data = urllib.parse.urlencode({"title": title, "desp": desp[:10000]}).encode("utf-8")
    try:
        req = urllib.request.Request(
            url, data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
        if result.get("code") == 0 or result.get("errno") == 0:
            return SendResult(ok=True, attempts=1, last_error="", status_code=None)
        # 渠道业务拒绝（HTTP 200 但业务失败：额度/鉴权）：不重试
        return SendResult(
            ok=False, attempts=1,
            last_error=f"biz_reject: code={result.get('code')} errno={result.get('errno')}",
            status_code=None,
        )
    except urllib.error.HTTPError as e:
        return SendResult(ok=False, attempts=1, last_error=f"HTTP {e.code}", status_code=e.code)
    except urllib.error.URLError as e:
        return SendResult(ok=False, attempts=1, last_error=f"URLError: {e.reason}", status_code=None)
    except Exception as e:  # 含 socket.timeout
        return SendResult(ok=False, attempts=1, last_error=f"error: {e}", status_code=None)


def send_via_wecom(webhook: str, title: str, desp: str) -> SendResult:
    """企业微信群机器人 Webhook 推送（免费、无每日上限），返回 ``SendResult``。"""
    if not webhook:
        return SendResult(ok=False, attempts=1, last_error="config: empty webhook", status_code=None)
    content = f"{title}\n\n{desp}"[:2000]  # 企业微信文本消息上限 2048 字节
    payload = json.dumps({"msgtype": "text", "text": {"content": content}}).encode("utf-8")
    try:
        req = urllib.request.Request(
            webhook, data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
        if result.get("errcode") == 0:
            return SendResult(ok=True, attempts=1, last_error="", status_code=None)
        # 渠道业务拒绝（HTTP 200 但业务失败）：不重试
        return SendResult(
            ok=False, attempts=1,
            last_error=f"biz_reject: errcode={result.get('errcode')}",
            status_code=None,
        )
    except urllib.error.HTTPError as e:
        return SendResult(ok=False, attempts=1, last_error=f"HTTP {e.code}", status_code=e.code)
    except urllib.error.URLError as e:
        return SendResult(ok=False, attempts=1, last_error=f"URLError: {e.reason}", status_code=None)
    except Exception as e:
        return SendResult(ok=False, attempts=1, last_error=f"error: {e}", status_code=None)


def send_via_pushplus(token: str, title: str, desp: str, topic: str = "") -> SendResult:
    """推送加 PushPlus（个人微信，免费档额度高于方糖），返回 ``SendResult``。"""
    if not token:
        return SendResult(ok=False, attempts=1, last_error="config: empty token", status_code=None)
    data = urllib.parse.urlencode({
        "token": token, "title": title, "content": desp[:20000],
        "template": "markdown", "topic": topic or "",
    }).encode("utf-8")
    try:
        req = urllib.request.Request(
            "https://www.pushplus.plus/send", data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
        if result.get("code") == 200:
            return SendResult(ok=True, attempts=1, last_error="", status_code=None)
        # 渠道业务拒绝（额度/鉴权/参数）：不重试
        return SendResult(
            ok=False, attempts=1,
            last_error=f"biz_reject: code={result.get('code')} msg={result.get('msg')}",
            status_code=None,
        )
    except urllib.error.HTTPError as e:
        return SendResult(ok=False, attempts=1, last_error=f"HTTP {e.code}", status_code=e.code)
    except urllib.error.URLError as e:
        return SendResult(ok=False, attempts=1, last_error=f"URLError: {e.reason}", status_code=None)
    except Exception as e:
        return SendResult(ok=False, attempts=1, last_error=f"error: {e}", status_code=None)


def send_via_bark(base: str, title: str, desp: str, group: str = "") -> SendResult:
    """Bark 推送（iPhone 通知，无限；base 形如 https://api.day.app/KEY 或自建地址）。

    group: 可选，Bark 分组名（在 App 里折叠/归类通知）。
    使用 POST + JSON：标题含 emoji / 正文含 Markdown 与链接时，GET 路径方式偶发 404，
    POST 更稳定。返回 ``SendResult``。
    """
    if not base:
        return SendResult(ok=False, attempts=1, last_error="config: empty base", status_code=None)
    payload = {"title": title, "body": desp}
    if group:
        payload["group"] = group
    try:
        req = urllib.request.Request(
            base.rstrip("/"),
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
        if result.get("code") == 200:
            return SendResult(ok=True, attempts=1, last_error="", status_code=None)
        # 渠道业务拒绝（token 失效 / 参数错误）：不重试
        return SendResult(
            ok=False, attempts=1,
            last_error=f"biz_reject: code={result.get('code')} msg={result.get('message')}",
            status_code=None,
        )
    except urllib.error.HTTPError as e:
        return SendResult(ok=False, attempts=1, last_error=f"HTTP {e.code}", status_code=e.code)
    except urllib.error.URLError as e:
        return SendResult(ok=False, attempts=1, last_error=f"URLError: {e.reason}", status_code=None)
    except Exception as e:
        return SendResult(ok=False, attempts=1, last_error=f"error: {e}", status_code=None)


def send_via_telegram(token: str, chat: str, title: str, desp: str) -> SendResult:
    """Telegram Bot 推送（无限），返回 ``SendResult``。

    使用 POST + JSON：原实现把整条消息塞进 GET 查询字符串，长文本（带 Markdown/
    链接）极易超出 URL 长度上限或遭遇编码问题而失败；POST 更稳，且 Telegram 会自动
    把纯文本里的裸 URL 识别为可点击链接。
    """
    if not token or not chat:
        return SendResult(ok=False, attempts=1, last_error="config: empty token/chat", status_code=None)
    text = f"{title}\n\n{desp}"
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat, "text": text}
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    try:
        req = urllib.request.Request(
            url, data=data,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
        if result.get("ok") is True:
            return SendResult(ok=True, attempts=1, last_error="", status_code=None)
        # 渠道业务拒绝（token/chat 失效）：不重试
        return SendResult(
            ok=False, attempts=1,
            last_error=f"biz_reject: ok={result.get('ok')} desc={result.get('description')}",
            status_code=None,
        )
    except urllib.error.HTTPError as e:
        return SendResult(ok=False, attempts=1, last_error=f"HTTP {e.code}", status_code=e.code)
    except urllib.error.URLError as e:
        return SendResult(ok=False, attempts=1, last_error=f"URLError: {e.reason}", status_code=None)
    except Exception as e:
        return SendResult(ok=False, attempts=1, last_error=f"error: {e}", status_code=None)


# ==================== 通知精细化装饰（mention / group 注入） ====================

def decorate(title: str, desp: str, push_cfg: Dict[str, Any]) -> Tuple[str, str]:
    """在发送前对 (title, desp) 注入 mention / group（装饰一次，重试不重复）。

    注入规则（按渠道类型 ``ptype = push_cfg["type"]``）：
      - group 标题前缀：当 group 非空且 ``ptype != "bark"`` 时，
        ``title = f"[{group}] {title}"``（Bark 走原生 group 参数，不改 title）。
      - mention 注入（仅 wecom / telegram；其余渠道忽略，优雅降级不报错）：
          * wecom    : 按逗号分隔，对每个非空 token 包 ``<@token>``，拼到 desp 开头。
          * telegram : 按逗号分隔，每个 token 确保以 ``@`` 开头（无则补 ``@``），拼到 desp 开头。
          * bark / serverchan / pushplus : 忽略 mention（不改变 desp）。
      - 多提及：mention 支持逗号分隔，逐个包裹后空格拼接；空项跳过。
      - 任意解析 / 拼接异常都吞掉，返回原 (title, desp)，绝不抛出。

    Note:
        由 ``dispatch_push`` 在「进入重试前、调用 ``send_with_retry`` 之前」调用一次，
        因此重试循环复用已装饰的 (title, desp)，不会重复装饰。

    Args:
        title: 推送标题（来自 format_push_title / 内联格式化）。
        desp: 推送正文。
        push_cfg: 透传的推送配置 dict（含 "type" / 可选 "mention" / "group"）。

    Returns:
        装饰后的 (title, desp)。Bark 的 group 不在 title 体现，仍由 send_via_bark 参数承载。
    """
    try:
        mention = (push_cfg.get("mention") or "").strip()
        group = (push_cfg.get("group") or "").strip()
        ptype = (push_cfg.get("type") or "").lower()
    except Exception:  # 配置异常：等价无装饰
        return title, desp

    # ---- group 标题前缀（非 Bark 文本渠道）----
    if group and ptype != "bark":
        title = f"[{group}] {title}"

    # ---- mention 注入（仅 wecom / telegram；其余渠道忽略）----
    if mention:
        try:
            users = [u.strip() for u in mention.split(",") if u.strip()]
            if users:
                if ptype == "wecom":
                    tags = " ".join(f"<@{u}>" for u in users)
                    desp = f"{tags}\n{desp}"
                elif ptype == "telegram":
                    # 每个 token 确保以 @ 开头（无则补 @）
                    tags = " ".join(
                        f"@{u[1:] if u.startswith('@') else u}" for u in users
                    )
                    desp = f"{tags}\n{desp}"
                # bark / serverchan / pushplus -> 忽略（优雅降级）
        except Exception:
            # 解析 / 拼接失败：保持原 desp，绝不中断推送
            pass
    return title, desp


# ==================== 分发 ====================

def _build_send_fn(ptype: str, push_cfg: Dict[str, Any]) -> Optional[Callable[[str, str], SendResult]]:
    """按渠道类型构造 ``send_fn(title, desp) -> SendResult``；未知/缺参返回 ``None``。

    Args:
        ptype: 渠道类型（小写）。
        push_cfg: 推送配置 dict。

    Returns:
        单次发送函数；无法识别时返回 ``None``。
    """
    if ptype in ("serverchan", "ftqq"):
        sendkey = push_cfg.get("sendkey") or push_cfg.get("key", "")
        return lambda title, desp: send_via_serverchan(sendkey, title, desp)
    if ptype == "wecom":
        webhook = push_cfg.get("webhook", "")
        return lambda title, desp: send_via_wecom(webhook, title, desp)
    if ptype == "pushplus":
        token = push_cfg.get("token", "")
        topic = push_cfg.get("topic", "")
        return lambda title, desp: send_via_pushplus(token, title, desp, topic)
    if ptype == "bark":
        base = push_cfg.get("url") or push_cfg.get("base", "")
        group = push_cfg.get("group", "")
        return lambda title, desp: send_via_bark(base, title, desp, group)
    if ptype == "telegram":
        token = push_cfg.get("token", "")
        chat = push_cfg.get("chat") or push_cfg.get("chat_id", "")
        return lambda title, desp: send_via_telegram(token, chat, title, desp)
    return None


def dispatch_push(push_cfg: Dict[str, Any], title: str, desp: str) -> SendResult:
    """按配置分发推送（含重试 + 分类）；返回聚合 ``SendResult``。

    重试完全在内部完成；调用方只拿到最终结果，因此去重 ``record()`` 永远在重试之后、
    且仅最终成功时由调用方调用一次（去重账本安全）。

    Args:
        push_cfg: 推送配置（含 "type"）；为空视为未配置。
        title: 推送标题。
        desp: 推送正文。

    Returns:
        聚合后的 ``SendResult``（成功 ``ok=True``；失败含 ``attempts`` / ``last_error``）。
    """
    try:
        if not push_cfg:
            return SendResult(ok=False, attempts=0, last_error="config: empty push_cfg", status_code=None)
        ptype = (push_cfg.get("type") or "").lower()
        fn = _build_send_fn(ptype, push_cfg)
        if fn is None:
            logger.warning("未知推送渠道: %s（跳过推送）", ptype)
            return SendResult(
                ok=False, attempts=0,
                last_error=f"config: unknown channel {ptype}", status_code=None,
            )
        # 进入重试前完成 mention/group 装饰（仅一次，重试不重复装饰）
        title, desp = decorate(title, desp, push_cfg)
        return send_with_retry(fn, title, desp)
    except Exception as e:
        # 兜底：分发层任何意外都收敛为 ok=False 的 SendResult，绝不抛出
        logger.error("推送分发异常: %s", e)
        return SendResult(ok=False, attempts=0, last_error=f"error: {e}", status_code=None)


def dispatch_push_ok(push_cfg: Dict[str, Any], title: str, desp: str) -> bool:
    """向后兼容薄包装：返回 ``bool``，内部已含重试。

    供任何未迁移的旧调用方 / 测试使用；新调用方应改用 ``dispatch_push`` 以取得
    ``attempts`` / ``last_error`` 做失败可见化。

    Args:
        push_cfg: 推送配置（含 "type"）。
        title: 推送标题。
        desp: 推送正文。

    Returns:
        ``True`` 表示最终推送成功；``False`` 表示失败。
    """
    return dispatch_push(push_cfg, title, desp).ok


def load_push_cfg(raw_config: str, fallback_sendkey: str = "") -> Dict[str, Any]:
    """从 BLIVE_CONFIG 原始字符串解析推送配置；兼容旧 sendkey 写法。

    Args:
        raw_config: BLIVE_CONFIG 环境变量内容（JSON 字符串）
        fallback_sendkey: 旧式 sendkey（当 raw_config 无 push 段且含 sendkey 时使用）

    Returns:
        推送配置 dict（含 "type"），或 {} 表示未配置
    """
    cfg: Dict[str, Any] = {}
    if raw_config:
        try:
            cfg = json.loads(raw_config) or {}
        except json.JSONDecodeError as e:
            logger.error("解析 BLIVE_CONFIG 失败: %s", e)
            cfg = {}
    push_cfg = cfg.get("push") or {}
    if not push_cfg and cfg.get("channels"):
        # 新结构（A2）：无 legacy push 段时，从首个通道推导出单通道配置，
        # 保证 dispatch_push（读 push_cfg["type"]）在「仅多通道」配置下仍可用。
        ch = cfg["channels"][0]
        if isinstance(ch, dict):
            ptype = ch.get("type", "")
            fields = ch.get("fields") or {}
            push_cfg = {"type": ptype}
            if isinstance(fields, dict):
                for k, v in fields.items():
                    push_cfg[k] = v
    if not push_cfg:
        sendkey = cfg.get("sendkey") or fallback_sendkey
        if sendkey:
            push_cfg = {"type": "serverchan", "sendkey": sendkey}
    return push_cfg
