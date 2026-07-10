#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
小红书开播检测工具

监控指定小红书用户主页的直播状态,在「开播 / 下播」状态变化时通过 Bark 推送到手机。

使用方法:
  1. 填写同目录 config.json (xhs_user_url / xhs_cookie / bark_key)
  2. pip install -r requirements.txt
  3. python xhs_live_detector.py
  4. 停止: Ctrl+C

说明:
  - 小红书无公开 API,本工具通过抓取网页版主页 HTML、解析 window.__INITIAL_STATE__
    中的直播状态字段来判断是否开播,并辅以关键词兜底。
  - 网页版主页通常需要登录 Cookie 才能看到完整信息,请在 config.json 填入 xhs_cookie。
  - 状态会写入 state.json,避免重启后重复推送。
"""

import json
import os
import re
import sys
import time
import logging
from datetime import datetime

import requests

CONFIG_FILE = "config.json"
DEFAULT_CONFIG = {
    "xhs_user_url": "",
    "xhs_cookie": "",
    "bark_key": "",
    "bark_server": "https://api.day.app",
    "check_interval_seconds": 600,
    "remind_interval_seconds": 3600,
    "state_file": "state.json",
    "request_timeout": 15,
    "user_agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("xhs-live")


# ---------- 配置 & 状态 ----------

def load_config():
    # 优先用环境变量(GitHub Actions Secrets 注入),其次读 config.json
    merged = dict(DEFAULT_CONFIG)
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                merged.update(json.load(f))
        except Exception as e:
            log.warning("读取 %s 失败: %s", CONFIG_FILE, e)
    # 环境变量覆盖(适配 GitHub Actions / 任意 CI)
    env_map = {
        "XHS_USER_URL": "xhs_user_url",
        "XHS_COOKIE": "xhs_cookie",
        "BARK_KEY": "bark_key",
        "BARK_SERVER": "bark_server",
        "CHECK_INTERVAL_SECONDS": "check_interval_seconds",
        "REMIND_INTERVAL_SECONDS": "remind_interval_seconds",
        "STATE_FILE": "state_file",
        "REQUEST_TIMEOUT": "request_timeout",
        "USER_AGENT": "user_agent",
    }
    for env_key, cfg_key in env_map.items():
        val = os.environ.get(env_key)
        if val is None or val == "":
            continue
        # 数值字段转 int
        if cfg_key in ("check_interval_seconds", "remind_interval_seconds", "request_timeout"):
            try:
                val = int(val)
            except ValueError:
                pass
        merged[cfg_key] = val
    missing = []
    if not merged.get("xhs_user_url"):
        missing.append("xhs_user_url (或环境变量 XHS_USER_URL)")
    if not merged.get("bark_key"):
        missing.append("bark_key (或环境变量 BARK_KEY)")
    if missing:
        log.error("配置缺少必填项: %s", ", ".join(missing))
        sys.exit(1)
    return merged


def load_state(state_file):
    if os.path.exists(state_file):
        try:
            with open(state_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_state(state_file, state):
    try:
        with open(state_file, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        log.warning("保存状态文件失败: %s", e)


# ---------- 抓取 & 解析 ----------

def fetch_page(url, cookie, ua, timeout):
    headers = {
        "User-Agent": ua,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Referer": "https://www.xiaohongshu.com/",
    }
    if cookie:
        headers["Cookie"] = cookie
    resp = requests.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    # 小红书页面多为 utf-8
    resp.encoding = resp.apparent_encoding or "utf-8"
    return resp.text


def extract_initial_state(html):
    """从 HTML 中提取 window.__INITIAL_STATE__ 的 JSON 对象"""
    m = re.search(
        r"window\.__INITIAL_STATE__\s*=\s*(\{.*?\})\s*</script>",
        html,
        re.DOTALL,
    )
    if not m:
        m = re.search(
            r"window\.__INITIAL_STATE__\s*=\s*(\{.*?\})\s*$",
            html,
            re.DOTALL | re.MULTILINE,
        )
    if not m:
        return None
    raw = m.group(1)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # 小红书数据里偶有 undefined,替换为 null
        raw2 = re.sub(r"\bundefined\b", "null", raw)
        try:
            return json.loads(raw2)
        except json.JSONDecodeError:
            return None


# 可能表示「正在直播」的字段名(小写匹配)
LIVE_KEYS = {
    "livestatus", "livestatusinfo", "liveinfo", "isliving", "islive",
    "living", "live", "live_room_id", "livestreamstatus",
    "is_living", "live_status", "live_status_info", "livestreamid", "liveid",
}
# 字段值为这些时视为「正在直播」
LIVE_TRUE_VALUES = {True, 1, "1", "true", "True", "living", "live", "进行中", "直播中"}


def find_live_info(obj):
    """递归搜索对象中的直播状态字段。返回 (是否直播中, 直播信息dict)"""
    if isinstance(obj, dict):
        for k, v in obj.items():
            kl = k.lower()
            if kl in LIVE_KEYS:
                # 标量值表示正在直播(用 isinstance 守卫,避免 list/dict 进 set 报错)
                if isinstance(v, (bool, int, str)) and (
                    v in LIVE_TRUE_VALUES
                    or (isinstance(v, str) and v.lower() in ("live", "living", "true", "1"))
                ):
                    return True, obj
                # 直播间 id 有值 -> 视为直播中
                if isinstance(v, (bool, int, str)) and kl in ("live_room_id", "livestreamid", "liveid") and v not in (None, "", 0, "0"):
                    return True, {"room_id": v}
                # value 是 dict 时,交给下方递归判断内部字段,不直接认定为直播
        for v in obj.values():
            living, info = find_live_info(v)
            if living:
                return True, info
    elif isinstance(obj, list):
        for v in obj:
            living, info = find_live_info(v)
            if living:
                return True, info
    return False, None


def check_live_by_keywords(html):
    """结构化解析失败时的关键词兜底检测"""
    patterns = [
        r'"liveStatus"\s*:\s*1',
        r'"isLiving"\s*:\s*true',
        r'"living"\s*:\s*true',
        r'"live_room_id"\s*:\s*"[^"]+"',
        r'直播中',
    ]
    for p in patterns:
        if re.search(p, html):
            return True
    return False


def extract_nickname(state):
    """尝试从 state 中提取用户昵称"""
    try:
        user = state.get("user", {})
        info = (
            user.get("userPageData", {}).get("userInfo", {})
            or user.get("userInfo", {})
        )
        return info.get("nickname") or info.get("nickName") or "小红书用户"
    except Exception:
        return "小红书用户"


# ---------- Bark 推送 ----------

def send_bark(bark_server, bark_key, title, body, group="小红书开播"):
    url = f"{bark_server.rstrip('/')}/{bark_key}"
    payload = {
        "title": title,
        "body": body,
        "group": group,
        "sound": "bell",
        "icon": "https://www.xiaohongshu.com/favicon.ico",
    }
    try:
        resp = requests.post(url, json=payload, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            if data.get("code") == 200:
                log.info("Bark 推送成功: %s", title)
                return True
            log.warning("Bark 返回异常: %s", data)
        else:
            log.warning("Bark 推送失败 HTTP %s: %s", resp.status_code, resp.text[:200])
    except Exception as e:
        log.warning("Bark 推送异常: %s", e)
    return False


# ---------- 主流程 ----------

def check_once(cfg):
    url = cfg["xhs_user_url"]
    cookie = cfg.get("xhs_cookie", "")
    ua = cfg.get("user_agent")
    timeout = cfg.get("request_timeout", 15)

    html = fetch_page(url, cookie, ua, timeout)
    state = extract_initial_state(html)
    nickname = "小红书用户"
    living = False
    live_info = None

    if state:
        nickname = extract_nickname(state)
        living, live_info = find_live_info(state)
    if not living:
        living = check_live_by_keywords(html)

    return living, nickname, live_info


def run_once(cfg):
    """执行一次检测 + 推送 + 状态持久化。返回当前是否直播中。"""
    remind_interval = int(cfg.get("remind_interval_seconds", 3600))
    state_file = cfg.get("state_file", "state.json")
    state = load_state(state_file)
    was_living = state.get("living", False)
    last_notify_time = state.get("last_notify_time", 0)

    living, nickname, _ = check_once(cfg)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log.info("[%s] %s 直播状态: %s", now, nickname, "直播中" if living else "未开播")

    if living and not was_living:
        # 未播 -> 开播
        title = f"📢 {nickname} 开播啦"
        body = (
            f"{nickname} 正在小红书直播\n"
            f"时间: {now}\n"
            f"主页: {cfg['xhs_user_url']}"
        )
        send_bark(cfg["bark_server"], cfg["bark_key"], title, body)
        last_notify_time = time.time()
    elif living and was_living and (time.time() - last_notify_time) > remind_interval:
        # 持续直播提醒
        title = f"📺 {nickname} 仍在直播中"
        body = f"{nickname} 直播持续中\n时间: {now}"
        send_bark(cfg["bark_server"], cfg["bark_key"], title, body)
        last_notify_time = time.time()
    elif not living and was_living:
        # 开播 -> 下播
        title = f"💤 {nickname} 下播了"
        body = f"{nickname} 已结束直播\n时间: {now}"
        send_bark(cfg["bark_server"], cfg["bark_key"], title, body)

    state["living"] = living
    state["last_notify_time"] = last_notify_time
    state["last_check"] = now
    save_state(state_file, state)
    return living


def main():
    cfg = load_config()
    interval = int(cfg.get("check_interval_seconds", 600))

    # --once: 单次检测模式(GitHub Actions 等定时触发器使用)
    if "--once" in sys.argv:
        log.info("单次检测模式")
        try:
            run_once(cfg)
        except requests.HTTPError as e:
            log.error("请求失败: %s (可能 Cookie 失效或被风控,HTTP %s)", e, e.response.status_code if e.response else "?")
            sys.exit(1)
        except Exception as e:
            log.error("检测异常: %s", e)
            sys.exit(1)
        return

    # 默认: 本地长驻循环模式
    log.info("小红书开播检测已启动")
    log.info("监控主页: %s", cfg["xhs_user_url"])
    log.info("检测间隔: %d 秒", interval)
    while True:
        try:
            run_once(cfg)
        except requests.HTTPError as e:
            log.error("请求失败: %s (可能 Cookie 失效或被风控,HTTP %s)", e, e.response.status_code if e.response else "?")
        except Exception as e:
            log.error("检测异常: %s", e)
        time.sleep(interval)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log.info("已停止检测")
