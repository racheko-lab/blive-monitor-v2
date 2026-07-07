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
"""

import json
import logging
import urllib.request
import urllib.parse
from typing import Any, Dict

logger = logging.getLogger(__name__)


# ==================== 单渠道发送 ====================

def send_via_serverchan(sendkey: str, title: str, desp: str) -> bool:
    """通过 Server酱 发送微信推送"""
    if not sendkey:
        return False
    url = f"https://sctapi.ftqq.com/{sendkey}.send"
    data = urllib.parse.urlencode({"title": title, "desp": desp[:10000]}).encode("utf-8")
    try:
        req = urllib.request.Request(
            url, data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
        return result.get("code") == 0 or result.get("errno") == 0
    except Exception as e:
        logger.error("微信推送失败: %s", e)
        return False


def send_via_wecom(webhook: str, title: str, desp: str) -> bool:
    """企业微信群机器人 Webhook 推送（免费、无每日上限）"""
    if not webhook:
        return False
    content = f"{title}\n\n{desp}"[:2000]  # 企业微信文本消息上限 2048 字节
    payload = json.dumps({"msgtype": "text", "text": {"content": content}}).encode("utf-8")
    try:
        req = urllib.request.Request(
            webhook, data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
        return result.get("errcode") == 0
    except Exception as e:
        logger.error("企业微信推送失败: %s", e)
        return False


def send_via_pushplus(token: str, title: str, desp: str, topic: str = "") -> bool:
    """推送加 PushPlus（个人微信，免费档额度高于方糖）"""
    if not token:
        return False
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
        return result.get("code") == 200
    except Exception as e:
        logger.error("PushPlus 推送失败: %s", e)
        return False


def send_via_bark(base: str, title: str, desp: str, group: str = "") -> bool:
    """Bark 推送（iPhone 通知，无限；base 形如 https://api.day.app/KEY 或自建地址）

    group: 可选，Bark 分组名（在 App 里折叠/归类通知）。
    使用 POST + JSON：标题含 emoji / 正文含 Markdown 与链接时，GET 路径方式偶发 404，
    POST 更稳定。
    """
    if not base:
        return False
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
        return result.get("code") == 200
    except Exception as e:
        logger.error("Bark 推送失败: %s", e)
        return False


def send_via_telegram(token: str, chat: str, title: str, desp: str) -> bool:
    """Telegram Bot 推送（无限）"""
    if not token or not chat:
        return False
    text = f"{title}\n\n{desp}"
    url = (
        f"https://api.telegram.org/bot{token}/sendMessage"
        f"?chat_id={urllib.parse.quote(chat)}&text={urllib.parse.quote(text)}"
    )
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
        return result.get("ok") is True
    except Exception as e:
        logger.error("Telegram 推送失败: %s", e)
        return False


# ==================== 分发 ====================

def dispatch_push(push_cfg: Dict[str, Any], title: str, desp: str) -> bool:
    """按配置分发推送；返回是否成功"""
    if not push_cfg:
        return False
    ptype = (push_cfg.get("type") or "").lower()
    try:
        if ptype in ("serverchan", "ftqq"):
            return send_via_serverchan(
                push_cfg.get("sendkey") or push_cfg.get("key", ""), title, desp)
        if ptype == "wecom":
            return send_via_wecom(push_cfg.get("webhook", ""), title, desp)
        if ptype == "pushplus":
            return send_via_pushplus(
                push_cfg.get("token", ""), title, desp, push_cfg.get("topic", ""))
        if ptype == "bark":
            return send_via_bark(
                push_cfg.get("url") or push_cfg.get("base", ""),
                title, desp, push_cfg.get("group", ""))
        if ptype == "telegram":
            return send_via_telegram(
                push_cfg.get("token", ""),
                push_cfg.get("chat") or push_cfg.get("chat_id", ""),
                title, desp)
        logger.warning("未知推送渠道: %s（跳过推送）", ptype)
        return False
    except Exception as e:
        logger.error("推送分发异常: %s", e)
        return False


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
    if not push_cfg:
        sendkey = cfg.get("sendkey") or fallback_sendkey
        if sendkey:
            push_cfg = {"type": "serverchan", "sendkey": sendkey}
    return push_cfg
