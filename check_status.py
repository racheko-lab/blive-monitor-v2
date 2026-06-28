#!/usr/bin/env python3
"""
B站/抖音直播状态检测（GitHub Actions 用）
- 通过 B站/抖音 API 直接检测（服务端无 CORS）
- 比较上次状态，变化时通过 Server酱 推送微信通知
- 更新 state.json 和 status.json
"""
import json, os, sys, urllib.request, urllib.parse
from datetime import datetime

REPO_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(REPO_DIR, "state.json")
STATUS_FILE = os.path.join(REPO_DIR, "status.json")
HISTORY_FILE = os.path.join(REPO_DIR, "history.json")
ROOMS_FILE = os.path.join(REPO_DIR, "rooms.json")

def load_config():
    # rooms 从仓库文件读取, sendkey 从 Secret 读取
    rooms = []
    if os.path.exists(ROOMS_FILE):
        with open(ROOMS_FILE) as f:
            rooms = json.load(f)
    raw = os.environ.get("BLIVE_CONFIG", "{}")
    cfg = json.loads(raw)
    return {"sendkey": cfg.get("sendkey", ""), "rooms": rooms}

def fetch_bilibili(room_id):
    url = f"https://api.live.bilibili.com/room/v1/Room/get_info?room_id={room_id}"
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0", "Referer": "https://live.bilibili.com/"
    })
    with urllib.request.urlopen(req, timeout=10) as r:
        data = json.loads(r.read())
    if data["code"] != 0:
        raise Exception(f"B站API错误: code={data['code']}")
    d = data["data"]
    status = {0: "offline", 1: "live", 2: "replay"}.get(d["live_status"], "unknown")
    return {
        "status": status,
        "title": d.get("title", ""),
        "online": d.get("online", 0),
        "area": f"{d.get('parent_area_name','')}·{d.get('area_name','')}",
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

def fetch_douyin(web_rid):
    url = f"https://live.douyin.com/{web_rid}"
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36"
    })
    with urllib.request.urlopen(req, timeout=10) as r:
        html = r.read().decode("utf-8", errors="replace")
    
    if "直播已结束" in html:
        return {"status": "offline", "title": "", "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    
    # 检查分享描述中的"正在直播"
    import re
    share_match = re.search(r'shareDesc["\s]*value=["\s]*([^"]+)', html)
    if share_match and "正在直播" in share_match.group(1):
        title_match = re.search(r'shareTitle["\s]*value=["\s]*([^"]+)', html)
        title = title_match.group(1).replace("的直播", "") if title_match else ""
        return {"status": "live", "title": title, "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    
    return {"status": "offline", "title": "", "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

def send_wechat_push(sendkey, title, desp):
    url = f"https://sctapi.ftqq.com/{sendkey}.send"
    data = urllib.parse.urlencode({"title": title, "desp": desp[:10000]}).encode()
    req = urllib.request.Request(url, data=data, headers={
        "Content-Type": "application/x-www-form-urlencoded"
    })
    with urllib.request.urlopen(req, timeout=10) as r:
        result = json.loads(r.read())
    return result.get("code") == 0 or result.get("errno") == 0

def main():
    cfg = load_config()
    rooms = cfg.get("rooms", [])
    sendkey = cfg.get("sendkey", "")
    
    if not rooms:
        print("No rooms configured")
        return
    
    # 读取上次状态
    prev_state = {}
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            prev_state = json.load(f)
    
    new_state = {}
    status_list = []
    log_entries = []
    now = datetime.now()
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")
    
    print(f"[{now:%H:%M:%S}] Checking {len(rooms)} rooms...")
    
    for room in rooms:
        platform = room.get("platform", "bilibili")
        rid = room.get("id", "")
        name = room.get("name", f"{platform}-{rid}")
        key = f"{platform}_{rid}"
        
        try:
            if platform == "bilibili":
                result = fetch_bilibili(rid)
            else:
                result = fetch_douyin(rid)
        except Exception as e:
            print(f"  [{name}] Error: {e}")
            result = {"status": "error", "title": str(e), "time": now.strftime("%Y-%m-%d %H:%M:%S")}
        
        print(f"  [{name}] {result['status']} - {result.get('title','')}")
        
        new_state[key] = result["status"]
        status_list.append({
            "platform": platform, "id": rid, "name": name,
            "status": result["status"],
            "title": result.get("title", ""),
            "online": result.get("online", 0),
            "area": result.get("area", ""),
            "time": result.get("time", ""),
        })
        
        # 记录日志
        prev = prev_state.get(key)
        changed = (prev is not None and prev != result["status"])
        log_entries.append({
            "time": now_str,
            "name": name,
            "platform": platform,
            "status": result["status"],
            "title": result.get("title", ""),
            "changed": changed,
            "prev": prev if changed else None,
        })
        
        # 状态变化 → 推送
        prev_status = prev_state.get(key)
        if prev_status and prev_status != result["status"]:
            if should_push(prev_status, result["status"]):
                push_title = format_push_title(name, platform, result)
                push_desp = format_push_desp(name, platform, rid, result)
                print(f"    → Pushing notification...")
                try:
                    if sendkey:
                        ok = send_wechat_push(sendkey, push_title, push_desp)
                        print(f"    → Push {'OK' if ok else 'FAILED'}")
                    else:
                        print(f"    → No sendkey configured, skip push")
                except Exception as e:
                    print(f"    → Push error: {e}")
        elif prev_status is None and result["status"] == "live":
            # 首次检测到开播也推送
            push_title = format_push_title(name, platform, result)
            push_desp = format_push_desp(name, platform, rid, result)
            print(f"    → First detection of LIVE, pushing...")
            try:
                if sendkey:
                    send_wechat_push(sendkey, push_title, push_desp)
            except Exception as e:
                print(f"    → Push error: {e}")
    
    # 保存
    with open(STATE_FILE, "w") as f:
        json.dump(new_state, f, ensure_ascii=False, indent=2)
    with open(STATUS_FILE, "w") as f:
        json.dump({"updated": now.strftime("%Y-%m-%d %H:%M:%S"), "rooms": status_list}, f, ensure_ascii=False, indent=2)
    
    # 更新日志（保留最近 200 条）
    old_log = []
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE) as f:
            old_log = json.load(f)
    all_log = old_log + log_entries
    if len(all_log) > 200:
        all_log = all_log[-200:]
    with open(HISTORY_FILE, "w") as f:
        json.dump(all_log, f, ensure_ascii=False, indent=2)
    
    print(f"[{now:%H:%M:%S}] Done. Status updated.")

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

def format_push_title(name, platform, result):
    platform_label = "B站" if platform == "bilibili" else "抖音"
    if result["status"] == "live":
        return f"🔴 {name} 开播了！"
    return f"▶️ {name} 轮播/回放中"

def format_push_desp(name, platform, rid, result):
    platform_label = "B站" if platform == "bilibili" else "抖音"
    live_url = f"https://live.bilibili.com/{rid}" if platform == "bilibili" else f"https://live.douyin.com/{rid}"
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
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

if __name__ == "__main__":
    main()
