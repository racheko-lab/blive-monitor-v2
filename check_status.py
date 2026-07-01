#!/usr/bin/env python3
"""
B站/抖音直播状态检测（GitHub Actions 用）
- B站: 官方 API
- 抖音: 页面 SSR 数据提取（RENDER_DATA + script 内嵌 JSON）
- 状态变化时通过 Server酱 推送微信通知
- 更新 status.json / state.json / history.json
"""
import json, os, re, sys, time, urllib.request, urllib.parse
from datetime import datetime, timezone, timedelta

# 北京时间（UTC+8）
def bjnow():
    return datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=8)

REPO_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(REPO_DIR, "state.json")
STATUS_FILE = os.path.join(REPO_DIR, "status.json")
HISTORY_FILE = os.path.join(REPO_DIR, "history.json")
TRACKING_FILE = os.path.join(REPO_DIR, "tracking.json")
ROOMS_FILE = os.path.join(REPO_DIR, "rooms.json")


def load_config():
    rooms = []
    if os.path.exists(ROOMS_FILE):
        with open(ROOMS_FILE) as f:
            rooms = json.load(f)
    raw = os.environ.get("BLIVE_CONFIG", "{}")
    cfg = json.loads(raw)
    return {"sendkey": cfg.get("sendkey", ""), "rooms": rooms}


def fetch_with_retry(url, headers=None, retries=2, timeout=10):
    """带重试的 HTTP 请求"""
    last_err = None
    for i in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=headers or {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            })
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:
            last_err = e
            if i < retries:
                time.sleep(1)
    raise last_err


def fetch_bilibili_batch(room_ids):
    """B站直播间批量检测 - getRoomBaseInfo 接口，一次查所有房间"""
    params = [("req_biz", "web_room_componet")]
    for rid in room_ids:
        params.append(("room_ids", rid))
    url = "https://api.live.bilibili.com/xlive/web-room/v1/index/getRoomBaseInfo?" + urllib.parse.urlencode(params)
    raw = fetch_with_retry(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Referer": "https://live.bilibili.com/",
    })
    data = json.loads(raw)
    if data.get("code") != 0:
        raise Exception(f"B站批量接口错误: {data}")
    return data["data"]["by_room_ids"]  # {room_id_str: {live_status, title, uname, online, ...}}


def fetch_douyin(web_rid):
    """抖音直播间检测 - 页面 SSR 数据提取"""
    url = f"https://live.douyin.com/{web_rid}"
    raw = fetch_with_retry(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "zh-CN,zh;q=0.9",
    })
    html = raw.decode("utf-8", errors="replace")

    # 方法1: 查找内嵌的房间数据 (status + user_count_str + title)
    # 数据格式: \"id_str\":\"数字\",\"status\":数字,\"status_str\":\"数字\",\"title\":\"标题\",...\"user_count_str\":\"数字\"
    room_match = re.search(
        r'\\"id_str\\":\\"(\d+)\\",\\"status\\":(\d+),\\"status_str\\":\\"(\d+)\\",\\"title\\":\\"([^"]*)\\".*?\\"user_count_str\\":\\"(\d+)\\"',
        html
    )

    # 提取昵称：页面上有多个 nickname 字段，前几个可能是 $undefined
    nickname = None
    for nick_match in re.finditer(r'\\"nickname\\":\\"([^"\\]+)\\"', html):
        val = nick_match.group(1)
        if val and val != "$undefined":
            nickname = val
            break

    # 提取 sec_uid
    sec_uid = ""
    idx = html.find('sec_uid')
    if idx >= 0:
        start = html.find('\\"', idx + 10)
        if start >= 0:
            end = html.find('\\"', start + 2)
            if end >= 0 and end - start < 200:
                sec_uid = html[start+2:end]

    web_rid_match = re.search(r'\\"web_rid\\":\\"([^"\\]+)\\"', html)
    actual_web_rid = web_rid_match.group(1) if web_rid_match else web_rid

    if room_match:
        status_code = int(room_match.group(2))
        # 抖音 status: 2=直播中, 4=已结束
        status = "live" if status_code == 2 else "offline"
        title = room_match.group(4)
        user_count = int(room_match.group(5))
        return {
            "status": status,
            "title": title,
            "online": user_count,
            "area": "",
            "nickname": nickname or "",
            "sec_uid": sec_uid,
            "time": bjnow().strftime("%Y-%m-%d %H:%M:%S"),
        }

    # 方法2: 兜底 - 关键词匹配
    if "直播已结束" in html:
        return {"status": "offline", "title": "", "online": 0, "area": "", "nickname": nickname or "", "sec_uid": sec_uid, "time": bjnow().strftime("%Y-%m-%d %H:%M:%S")}

    share_match = re.search(r'shareDesc["\s]*value=["\s]*([^"]+)', html)
    if share_match and "正在直播" in share_match.group(1):
        title_match = re.search(r'shareTitle["\s]*value=["\s]*([^"]+)', html)
        title = title_match.group(1).replace("的直播", "") if title_match else ""
        return {"status": "live", "title": title, "online": 0, "area": "", "nickname": nickname or "", "sec_uid": sec_uid, "time": bjnow().strftime("%Y-%m-%d %H:%M:%S")}

    return {"status": "offline", "title": "", "online": 0, "area": "", "nickname": nickname or "", "sec_uid": sec_uid, "time": bjnow().strftime("%Y-%m-%d %H:%M:%S")}


def send_wechat_push(sendkey, title, desp):
    url = f"https://sctapi.ftqq.com/{sendkey}.send"
    data = urllib.parse.urlencode({"title": title, "desp": desp[:10000]}).encode()
    req = urllib.request.Request(url, data=data, headers={
        "Content-Type": "application/x-www-form-urlencoded"
    })
    with urllib.request.urlopen(req, timeout=10) as r:
        result = json.loads(r.read())
    return result.get("code") == 0 or result.get("errno") == 0


def should_push(prev, curr):
    if curr == "offline":
        return False
    if prev == "offline" and curr == "live":
        return True
    if prev == "replay" and curr == "live":
        return True
    if prev == "offline" and curr == "replay":
        return True
    return False


def format_push_title(name, result):
    if result["status"] == "live":
        return f"🔴 {name} 开播了！"
    return f"▶️ {name} 轮播/回放中"


def format_push_desp(name, platform, rid, result):
    platform_label = "B站" if platform == "bilibili" else "抖音"
    live_url = f"https://live.bilibili.com/{rid}" if platform == "bilibili" else f"https://live.douyin.com/{rid}"
    now = bjnow().strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        f"## 🎬 {name} 开播了！" if result["status"] == "live" else f"## ▶️ {name} 轮播/回放中",
        "",
        f"**平台**: {platform_label}",
        f"**标题**: {result.get('title', '-')}",
    ]
    if result.get("area"):
        lines.append(f"**分区**: {result['area']}")
    if result.get("online"):
        lines.append(f"**人气**: {result['online']}")
    lines.extend([
        "",
        f"👉 [进入直播间]({live_url})",
        "",
        f"---",
        f"检测时间: {now}",
    ])
    return "\n".join(lines)


def main():
    cfg = load_config()
    rooms = cfg.get("rooms", [])
    sendkey = cfg.get("sendkey", "")

    if not rooms:
        print("No rooms configured")
        return

    prev_state = {}
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE) as f:
                prev_state = json.load(f)
        except:
            prev_state = {}

    new_state = {}
    status_list = []
    log_entries = []
    now = bjnow()
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")

    # 读取开播追踪数据
    tracking = {}
    if os.path.exists(TRACKING_FILE):
        try:
            with open(TRACKING_FILE) as f:
                tracking = json.load(f)
        except:
            tracking = {}

    print(f"[{now:%H:%M:%S}] Checking {len(rooms)} rooms...")

    # Step 1: 批量查询所有 B站房间
    bili_rooms = [(r, i) for i, r in enumerate(rooms) if r.get("platform", "bilibili") == "bilibili"]
    bili_data = {}
    if bili_rooms:
        try:
            bili_ids = [r["id"] for r, _ in bili_rooms]
            bili_data = fetch_bilibili_batch(bili_ids)
        except Exception as e:
            print(f"  B站批量查询失败: {e}")

    # Step 2: 逐个检测所有房间（B站取批量数据，抖音逐个抓）
    results = []  # 存每个房间的检测结果
    newly_live = []  # 用于合并推送

    for idx, room in enumerate(rooms):
        platform = room.get("platform", "bilibili")
        rid = room.get("id", "")
        name = room.get("name", f"{platform}-{rid}")
        key = f"{platform}_{rid}"
        push_result = None

        try:
            if platform == "bilibili":
                d = bili_data.get(str(rid))
                if not d:
                    raise Exception(f"批量接口未返回房间 {rid} 的数据")
                status_code = d.get("live_status", 0)
                result = {
                    "status": {0: "offline", 1: "live", 2: "replay"}.get(status_code, "unknown"),
                    "title": d.get("title", ""),
                    "online": d.get("online", 0),
                    "area": f"{d.get('parent_area_name', '')}·{d.get('area_name', '')}".strip("·") or "",
                }
            else:
                result = fetch_douyin(rid)
        except Exception as e:
            print(f"  [{name}] Error: {e}")
            result = {"status": "error", "title": str(e), "online": 0, "area": "", "time": now_str}
            push_result = "error"

        display_name = name
        if platform == "douyin" and result.get("nickname") and result["nickname"] != name:
            display_name = result["nickname"]

        print(f"  [{display_name}] {result['status']} - {result.get('title', '')}")

        new_state[key] = result["status"]
        status_list.append({
            "platform": platform, "id": rid, "name": display_name,
            "status": result["status"],
            "title": result.get("title", ""),
            "online": result.get("online", 0),
            "area": result.get("area", ""),
            "time": result.get("time", now_str),
            "sec_uid": result.get("sec_uid", ""),
        })

        # 开播追踪
        t = tracking.get(key, {})
        last_live = t.get("last_live", "")
        live_start_str = t.get("live_start", "")
        live_duration = ""

        if result["status"] == "live":
            if not live_start_str:
                live_start_str = now_str
            else:
                try:
                    start_dt = datetime.strptime(live_start_str, "%Y-%m-%d %H:%M:%S")
                    secs = int((now - start_dt).total_seconds())
                    h, m = divmod(secs, 3600)
                    m, s = divmod(m, 60)
                    live_duration = f"{h}h{m}min" if h > 0 else f"{m}min"
                except:
                    pass
        elif live_start_str:
            try:
                start_dt = datetime.strptime(live_start_str, "%Y-%m-%d %H:%M:%S")
                secs = int((now - start_dt).total_seconds())
                h, m = divmod(secs, 3600)
                m, s = divmod(m, 60)
                last_live = live_start_str
                t["last_duration"] = f"{h}h{m}min" if h > 0 else f"{m}min"
            except:
                pass
            live_start_str = ""

        t["last_live"] = last_live
        t["live_start"] = live_start_str
        if live_duration:
            t["live_duration"] = live_duration
        if platform == "douyin" and result.get("sec_uid"):
            t["sec_uid"] = result["sec_uid"]
        tracking[key] = t

        status_list[-1]["last_live"] = last_live
        status_list[-1]["live_duration"] = live_duration

        # 状态变化检测
        prev_status = prev_state.get(key)
        changed = (prev_status is not None and prev_status != result["status"])

        if changed and should_push(prev_status, result["status"]):
            newly_live.append({"name": display_name, "platform": platform, "rid": rid, "result": result})
            push_result = "queued"  # 待合并推送
        elif prev_status is None and result["status"] == "live":
            newly_live.append({"name": display_name, "platform": platform, "rid": rid, "result": result})
            push_result = "queued"

        # 记录日志
        log_entries.append({
            "time": now_str,
            "name": display_name,
            "platform": platform,
            "status": result["status"],
            "title": result.get("title", ""),
            "changed": changed,
            "prev": prev_status if changed else None,
            "push": push_result,
        })

    # Step 3: 合并推送
    if newly_live and sendkey:
        try:
            if len(newly_live) == 1:
                s = newly_live[0]
                title = format_push_title(s["name"], s["result"])
                desp = format_push_desp(s["name"], s["platform"], s["rid"], s["result"])
            else:
                names = "、".join(s["name"] for s in newly_live)
                title = f"🔴 {len(newly_live)}位主播开播：{names}"
                desp_lines = []
                for s in newly_live:
                    desp_lines.append(format_push_desp(s["name"], s["platform"], s["rid"], s["result"]))
                desp = "\n\n---\n\n".join(desp_lines)
            
            ok = send_wechat_push(sendkey, title, desp)
            push_tag = "pushed_ok" if ok else "pushed_fail"
            print(f"  → Push {'OK' if ok else 'FAILED'}: {title}")
            # 更新日志里的推送标记
            for le in log_entries:
                if le["push"] == "queued":
                    le["push"] = push_tag
        except Exception as e:
            print(f"  → Push error: {e}")
            for le in log_entries:
                if le["push"] == "queued":
                    le["push"] = "push_error"
    elif newly_live:
        print(f"  → {len(newly_live)} rooms changed but no SendKey configured")
        for le in log_entries:
            if le["push"] == "queued":
                le["push"] = "no_sendkey"

    # 保存状态
    with open(STATE_FILE, "w") as f:
        json.dump(new_state, f, ensure_ascii=False, indent=2)
    with open(STATUS_FILE, "w") as f:
        json.dump({"updated": now_str, "rooms": status_list}, f, ensure_ascii=False, indent=2)
    with open(TRACKING_FILE, "w") as f:
        json.dump(tracking, f, ensure_ascii=False, indent=2)

    # 更新日志（保留最近 200 条）
    old_log = []
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE) as f:
                old_log = json.load(f)
        except:
            old_log = []
    all_log = old_log + log_entries
    if len(all_log) > 200:
        all_log = all_log[-200:]
    with open(HISTORY_FILE, "w") as f:
        json.dump(all_log, f, ensure_ascii=False, indent=2)

    print(f"[{now:%H:%M:%S}] Done. Status updated.")


if __name__ == "__main__":
    main()
