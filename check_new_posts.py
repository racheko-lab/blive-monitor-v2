#!/usr/bin/env python3
"""
抖音新作品检测
- 对每个监控中的抖音账号，检测是否有新作品发布
- 通过 Server酱 推送通知
- 状态保存在 post_tracking.json
"""
import json, os, re, urllib.request, urllib.parse
from datetime import datetime, timezone, timedelta

REPO_DIR = os.path.dirname(os.path.abspath(__file__))
ROOMS_FILE = os.path.join(REPO_DIR, "rooms.json")
TRACKING_FILE = os.path.join(REPO_DIR, "post_tracking.json")

def bjnow():
    return datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=8)

def fetch_page(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "zh-CN,zh;q=0.9",
    })
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.read().decode("utf-8", errors="replace")

def extract_sec_uid(web_rid):
    """从抖音直播间页面提取 sec_uid"""
    try:
        html = fetch_page(f"https://live.douyin.com/{web_rid}")
        # 方法1: 查找 \\"sec_uid\\":\\"...\\"
        m = re.search(r'\\"sec_uid\\":\\"([^"\\]+)\\"', html)
        if m and m.group(1):
            return m.group(1)
        # 方法2: 连接重定向
        # 方法3: 用分享链接中的信息
    except Exception:
        pass
    return None

def get_latest_aweme(sec_uid):
    """获取用户最新作品信息"""
    # 尝试多个 API
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
                    "create_time": latest.get("create_time", 0),
                    "video_url": f"https://www.douyin.com/video/{latest['aweme_id']}",
                }
        except Exception:
            continue
    
    # 方法3: 抓取用户页面 HTML，提取第一个视频 ID
    try:
        html = fetch_page(f"https://www.douyin.com/user/{sec_uid}")
        # 找 aweme_id
        m = re.search(r'"aweme_id":\s*"(\d+)"', html)
        if m:
            return {
                "aweme_id": m.group(1),
                "desc": "",
                "create_time": 0,
                "video_url": f"https://www.douyin.com/video/{m.group(1)}",
            }
    except Exception:
        pass
    
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
    # 读取配置
    sendkey = ""
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
    
    # 读取追踪数据
    tracking = {}
    if os.path.exists(TRACKING_FILE):
        try:
            with open(TRACKING_FILE) as f:
                tracking = json.load(f)
        except:
            pass
    
    now_str = bjnow().strftime("%Y-%m-%d %H:%M:%S")
    changed = False
    
    print(f"Checking {len(douyin_rooms)} douyin users for new posts...")
    
    for room in douyin_rooms:
        web_rid = room["id"]
        name = room.get("name", web_rid)
        t = tracking.get(web_rid, {})
        
        # 获取或使用已有的 sec_uid
        sec_uid = t.get("sec_uid", "")
        if not sec_uid:
            print(f"  [{name}] Extracting sec_uid...")
            sec_uid = extract_sec_uid(web_rid)
            if not sec_uid:
                print(f"  [{name}] Failed to get sec_uid, skip")
                continue
            t["sec_uid"] = sec_uid
            changed = True
        
        # 获取最新作品
        print(f"  [{name}] Checking posts...")
        aweme = get_latest_aweme(sec_uid)
        if not aweme:
            print(f"  [{name}] Failed to get posts, skip")
            continue
        
        prev_id = t.get("latest_aweme_id", "")
        print(f"  [{name}] Latest: {aweme['aweme_id']} (prev: {prev_id or 'none'})")
        
        if prev_id and prev_id != aweme["aweme_id"]:
            # 新作品！
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
        if "nickname" not in t and room.get("name"):
            t["nickname"] = room["name"]
        tracking[web_rid] = t
        changed = True
    
    # 保存
    if changed:
        with open(TRACKING_FILE, "w") as f:
            json.dump(tracking, f, ensure_ascii=False, indent=2)
    
    print("Done.")

if __name__ == "__main__":
    main()
