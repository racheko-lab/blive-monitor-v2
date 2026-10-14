#!/usr/bin/env python3
"""斗鱼分享链接 → 真实房间号解析器。

## 为什么需要它

斗鱼 App 点「分享」生成的链接形如：

    https://m.douyu.com/15000?dyshid=0-5479c1bd948419d83382baf4000917p1&dyshci=124

**URL 路径里的数字（15000）不一定是房间号**。实测（2026-10-03）该链接打开后
SSR 渲染出的是：

    "roomId":"15000"     <- 照抄 URL
    "rid":796449         <- 真实房间号
    "nickname":"宁波小骚骚0oO"

拿 15000 去查公开接口 `open.douyucdn.cn/api/RoomApi/room/15000`，返回的是另一个
**已注销**的房间（owner_name="用户已注销"、start_time=1970-01-01）——完全不是用户
想监控的那个。

所以：斗鱼分享链接必须以页面 SSR 的 ``"rid"`` 为准，不能信 URL 路径。

## 用法

    python3 tools/douyu_resolve.py "https://m.douyu.com/15000?dyshid=..."
    python3 tools/douyu_resolve.py 796449

输出（人类可读 + 机器可读 ``--json``）：

    输入   : https://m.douyu.com/15000?dyshid=...
    URL 路径: 15000        <- 不可信
    真实房间: 796449       <- 以页面 rid 为准
    主播    : 宁波小骚骚0oO
    标题    : 感谢bbbb的总榜一！！
    状态    : 直播中
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from typing import Any, Dict, Optional

UA_MOBILE = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)

#: SSR 里真实房间号字段。注意与 `"roomId":"15000"`（照抄 URL）区分开。
RE_RID = re.compile(r'"rid"\s*:\s*"?(\d+)')
#: 兜底：URL 路径里的数字（不可信，仅在页面解析失败时使用并标注）
RE_PATH_ID = re.compile(r"(?:m|www)\.douyu\.com/(\d+)")


def http_get(url: str, timeout: int = 15) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA_MOBILE})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def extract_rid(html: str) -> Optional[str]:
    """从 SSR HTML 提取真实房间号（``"rid":<数字>``）。"""
    m = RE_RID.search(html)
    return m.group(1) if m else None


def normalize_input(raw: str) -> str:
    """把「分享链接 / 裸房间号 / www 链接」统一成 m.douyu.com 页面 URL。"""
    s = (raw or "").strip()
    if s.isdigit():
        return f"https://m.douyu.com/{s}"
    if s.startswith("//"):
        s = "https:" + s
    if not s.startswith("http"):
        s = "https://" + s
    return s


def resolve(raw: str, timeout: int = 15) -> Dict[str, Any]:
    """解析斗鱼输入，返回 {url, path_id, room_id, source, ...}。

    ``source`` 说明房间号来自哪里：
      - ``"ssr_rid"``  页面 ``"rid"``（可信，首选）
      - ``"url_path"`` SSR 解析失败，退回 URL 路径（**不可信**，需人工确认）
    """
    url = normalize_input(raw)
    path_id = None
    m = RE_PATH_ID.search(url)
    if m:
        path_id = m.group(1)

    out: Dict[str, Any] = {
        "input": raw,
        "url": url,
        "path_id": path_id,
        "room_id": None,
        "source": None,
        "nickname": "",
        "title": "",
        "error": "",
    }

    try:
        html = http_get(url, timeout=timeout)
    except Exception as e:  # noqa: BLE001
        out["error"] = f"页面抓取失败: {e}"
        out["room_id"] = path_id
        out["source"] = "url_path"
        return out

    rid = extract_rid(html)
    if rid:
        out["room_id"] = rid
        out["source"] = "ssr_rid"
    else:
        out["room_id"] = path_id
        out["source"] = "url_path"
        out["error"] = "页面未解析到 \"rid\"，已退回 URL 路径（可能不是房间号）"

    m = re.search(r'"nickname":"([^"]{0,60})"', html)
    if m:
        out["nickname"] = m.group(1)
    m = re.search(r'"roomName":"([^"]{0,120})"', html)
    if m:
        out["title"] = m.group(1)
    return out


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description="斗鱼分享链接 → 真实房间号")
    ap.add_argument("target", help="斗鱼分享链接或房间号")
    ap.add_argument("--json", action="store_true", help="以 JSON 输出")
    args = ap.parse_args(argv)

    r = resolve(args.target)
    if args.json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
    else:
        print(f"输入    : {r['input']}")
        print(f"URL 路径 : {r['path_id'] or '-'}")
        if r["source"] == "url_path":
            print(f"真实房间 : {r['room_id'] or '-'}   ⚠️ 来源不可信（URL 路径兜底）")
        else:
            print(f"真实房间 : {r['room_id'] or '-'}   ✅ 来源：页面 SSR \"rid\"")
        if r["nickname"]:
            print(f"主播    : {r['nickname']}")
        if r["title"]:
            print(f"标题    : {r['title']}")
        if r["error"]:
            print(f"⚠️ {r['error']}")
        if r["path_id"] and r["room_id"] and r["path_id"] != r["room_id"]:
            print()
            print("注意：URL 路径与真实房间号不一致 —— 这是斗鱼分享链接的正常现象，")
            print("      添加监控请用「真实房间」，否则会监控到另一个（可能已注销的）房间。")
    return 0 if r["room_id"] else 1


if __name__ == "__main__":
    sys.exit(main())
