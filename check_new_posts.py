#!/usr/bin/env python3
"""
抖音新作品检测
- sec_uid 由 check_status.py 写入 tracking.json（key: douyin_webrid）
- 本脚本从 tracking.json 读取 sec_uid，检查是否有新作品
- 通过 Server酱 推送通知
"""
import json, os, re, urllib.request, urllib.parse
from datetime import datetime, timezone, timedelta

REPO_DIR = os.path.dirname(os.path.abspath(__file__))
ROOMS_FILE = os.path.join(REPO_DIR, "rooms.json")
TRACKING_FILE = os.path.join(REPO_DIR, "tracking.json")

def bjnow():
    return datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=8)

def get_latest_aweme(sec_uid):
    """获取用户最新作品信息"""
    apis = [
        f"https://www.iesdouyin.com/web/api/v2/aweme/post/?sec_uid={sec_uid}&count=2&max_cursor=0",
        f"https://www.douyin.com/aweme/v1/web/aweme/post/?sec_user_id={sec_uid}&count=2&max_cursor=0",
    ]
    for api_url in apis:
        try:
            req = urllib.request.Request(api_url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Referer": f"https://www.douyin.com/user/{sec_uid}",
            })
            with urllib.request.urlopen(req, timeout=10) as r:
                data = json.loads(r.read())
            aweme_list = data.get("aweme_list", [])
            if aweme_list:
                latest = aweme_list[0]
                return {
                    "aweme_id": str(latest["aweme_id"]),
                    "desc": latest.get("desc", ""),
                    "video_url": f"https://www.douyin.com/video/{latest['aweme_id']}",
                }
        except Exception:
            continue
    return None

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
    # 通过环境变量控制是否启用
    if os.environ.get("ENABLE_POST_CHECK", "").lower() != "true":
        print("Post check disabled (set ENABLE_POST_CHECK=true to enable)")
        return
    raw = os.environ.get("BLIVE_CONFIG", "{}")
    try:
        cfg = json.loads(raw)
        sendkey = cfg.get("sendkey", "")
    except:
        pass

    rooms = []
    if os.path.exists(ROOMS_FILE):
        with open(ROOMS_FILE) as f:
            rooms = json.load(f)

    douyin_rooms = [r for r in rooms if r.get("platform") == "douyin"]
    if not douyin_rooms:
        print("No douyin rooms configured")
        return

    # tracking.json 由 check_status.py 维护，key 为 douyin_webrid
    tracking = {}
    if os.path.exists(TRACKING_FILE):
        try:
            with open(TRACKING_FILE) as f:
                tracking = json.load(f)
        except:
            pass

    now_str = bjnow().strftime("%Y-%m-%d %H:%M:%S")
    post_changed = False

    print(f"Checking {len(douyin_rooms)} douyin users for new posts...")

    for room in douyin_rooms:
        web_rid = room["id"]
        name = room.get("name", web_rid)
        key = f"douyin_{web_rid}"
        t = tracking.get(key, {})

        # sec_uid 由 check_status.py 写入
        sec_uid = t.get("sec_uid", "")
        if not sec_uid:
            print(f"  [{name}] No sec_uid yet, waiting for live check...")
            continue

        aweme = get_latest_aweme(sec_uid)
        if not aweme:
            print(f"  [{name}] Failed to get posts, skip")
            continue

        prev_id = t.get("latest_aweme_id", "")
        print(f"  [{name}] Latest: {aweme['aweme_id']} (prev: {prev_id or 'none'})")

        if prev_id and prev_id != aweme["aweme_id"]:
            desc = aweme.get("desc", "") or "[无描述]"
            print(f"  [{name}] 🆕 New post: {desc[:40]}")
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
                    print(f"    → Push {'OK' if ok else 'FAILED'}")
                except Exception as e:
                    print(f"    → Push error: {e}")

        t["latest_aweme_id"] = aweme["aweme_id"]
        t["latest_desc"] = aweme.get("desc", "")
        tracking[key] = t
        post_changed = True

    if post_changed:
        with open(TRACKING_FILE, "w") as f:
            json.dump(tracking, f, ensure_ascii=False, indent=2)

    print("Done.")

if __name__ == "__main__":
    main()
