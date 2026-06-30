/**
 * B站/抖音直播监控 - Cloudflare Worker
 * Cron Triggers: 每10分钟 (0/10 * * * *)
 * 仓库 rooms.json 管理监控列表，Worker 自动读取
 * 状态写入仓库的 status.json / state.json / history.json
 */

const GH_OWNER = "racheko-lab";
const GH_REPO = "blive-monitor";
const GH_BRANCH = "master";

export default {
  // Cron 触发
  async scheduled(event, env, ctx) {
    ctx.waitUntil(checkAll(env));
  },

  // 手动测试访问
  async fetch(request, env) {
    const result = await checkAll(env);
    return new Response(JSON.stringify(result, null, 2), {
      headers: { "Content-Type": "application/json" }
    });
  },
};

async function checkAll(env) {
  const token = env.GH_TOKEN;
  const sendkey = env.SENDKEY;
  const now = new Date();
  // 转北京时间 UTC+8
  const bjTime = new Date(now.getTime() + 8 * 3600 * 1000);
  const nowStr = bjTime.toISOString().replace("T", " ").substring(0, 19);

  // 1. 从 GitHub 读取 rooms.json
  const rooms = await ghGetFile(token, "rooms.json");
  if (!rooms || rooms.length === 0) {
    return { ok: false, error: "no rooms", time: nowStr };
  }

  // 2. 读取上次状态
  let prevState = {};
  try {
    prevState = await ghGetFile(token, "state.json") || {};
  } catch (e) {}

  // 3. 读取历史日志
  let history = [];
  try {
    history = await ghGetFile(token, "history.json") || [];
  } catch (e) {}

  // 4. 检测每个房间
  const statusList = [];
  const logEntries = [];
  const newState = {};

  for (const room of rooms) {
    const platform = room.platform || "bilibili";
    const rid = room.id;
    const name = room.name || rid;
    const key = `${platform}_${rid}`;
    let result, pushResult = null;

    try {
      if (platform === "bilibili") {
        result = await checkBilibili(rid);
      } else {
        result = await checkDouyin(rid);
      }
    } catch (e) {
      result = { status: "error", title: String(e), online: 0, area: "" };
      pushResult = "error";
    }

    // 抖音自动取昵称
    let displayName = name;
    if (platform === "douyin" && result.nickname && result.nickname !== name && result.nickname !== "$undefined") {
      displayName = result.nickname;
    }

    newState[key] = result.status;
    statusList.push({
      platform, id: rid, name: displayName,
      status: result.status,
      title: result.title || "",
      online: result.online || 0,
      area: result.area || "",
      time: nowStr,
    });

    // 状态变化检测
    const prev = prevState[key];
    const changed = (prev !== undefined && prev !== result.status);

    if (changed && shouldPush(prev, result.status)) {
      const title = formatPushTitle(displayName, result);
      const desp = formatPushDesp(displayName, platform, rid, result, nowStr);
      try {
        if (sendkey) {
          const ok = await sendWechat(sendkey, title, desp);
          pushResult = ok ? "pushed_ok" : "pushed_fail";
        } else {
          pushResult = "no_sendkey";
        }
      } catch (e) {
        pushResult = "push_error";
      }
    } else if (prev === undefined && result.status === "live") {
      const title = formatPushTitle(displayName, result);
      const desp = formatPushDesp(displayName, platform, rid, result, nowStr);
      try {
        if (sendkey) {
          const ok = await sendWechat(sendkey, title, desp);
          pushResult = ok ? "first_live_ok" : "first_live_fail";
        }
      } catch (e) {
        pushResult = "push_error";
      }
    }

    logEntries.push({
      time: nowStr,
      name: displayName,
      platform,
      status: result.status,
      title: result.title || "",
      changed,
      prev: changed ? prev : null,
      push: pushResult,
    });
  }

  // 5. 写回 GitHub
  await ghPutFile(token, "state.json", newState);
  await ghPutFile(token, "status.json", { updated: nowStr, rooms: statusList });

  // 6. 更新日志（保留200条）
  const allLog = [...history, ...logEntries].slice(-200);
  await ghPutFile(token, "history.json", allLog);

  return { ok: true, time: nowStr, rooms: statusList.length };
}

// ============ B站检测 ============
async function checkBilibili(roomId) {
  const resp = await fetch(
    `https://api.live.bilibili.com/room/v1/Room/get_info?room_id=${roomId}`,
    { headers: { "User-Agent": "Mozilla/5.0", "Referer": "https://live.bilibili.com/" } }
  );
  const data = await resp.json();
  if (data.code !== 0) throw new Error(`B站API code=${data.code}`);
  const d = data.data;
  const statusMap = { 0: "offline", 1: "live", 2: "replay" };
  return {
    status: statusMap[d.live_status] || "unknown",
    title: d.title || "",
    online: d.online || 0,
    area: `${d.parent_area_name || ""}·${d.area_name || ""}`.replace(/^·|·$/g, ""),
  };
}

// ============ 抖音检测 ============
async function checkDouyin(webRid) {
  const resp = await fetch(`https://live.douyin.com/${webRid}`, {
    headers: {
      "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
      "Accept": "text/html",
      "Accept-Language": "zh-CN,zh;q=0.9",
    },
  });
  const html = await resp.text();

  // 提取房间数据
  const roomMatch = html.match(/\\"id_str\\":\\"(\d+)\\",\\"status\\":(\d+),\\"status_str\\":\\"(\d+)\\",\\"title\\":\\"([^"]*)\\".*?\\"user_count_str\\":\\"(\d+)\\"/);
  
  // 提取昵称（跳过 $undefined）
  let nickname = "";
  const nickMatches = html.matchAll(/\\"nickname\\":\\"([^"\\]+)\\"/g);
  for (const m of nickMatches) {
    if (m[1] && m[1] !== "$undefined") { nickname = m[1]; break; }
  }

  if (roomMatch) {
    const statusCode = parseInt(roomMatch[2]);
    return {
      status: statusCode === 2 ? "live" : "offline",
      title: roomMatch[4],
      online: parseInt(roomMatch[5]),
      area: "",
      nickname,
    };
  }

  // 兜底
  if (html.includes("直播已结束")) {
    return { status: "offline", title: "", online: 0, area: "", nickname };
  }
  const shareMatch = html.match(/shareDesc["\s]*value=["\s]*([^"]+)/);
  if (shareMatch && shareMatch[1].includes("正在直播")) {
    const titleMatch = html.match(/shareTitle["\s]*value=["\s]*([^"]+)/);
    return { status: "live", title: titleMatch ? titleMatch[1].replace("的直播", "") : "", online: 0, area: "", nickname };
  }
  return { status: "offline", title: "", online: 0, area: "", nickname };
}

// ============ Server酱推送 ============
async function sendWechat(sendkey, title, desp) {
  const resp = await fetch(`https://sctapi.ftqq.com/${sendkey}.send`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: `title=${encodeURIComponent(title)}&desp=${encodeURIComponent(desp.substring(0, 10000))}`,
  });
  const data = await resp.json();
  return data.code === 0 || data.errno === 0;
}

// ============ GitHub 文件操作 ============
async function ghGetFile(token, path) {
  const resp = await fetch(
    `https://api.github.com/repos/${GH_OWNER}/${GH_REPO}/contents/${path}?ref=${GH_BRANCH}`,
    { headers: { Authorization: `Bearer ${token}`, Accept: "application/vnd.github+json" } }
  );
  if (!resp.ok) return null;
  const data = await resp.json();
  const content = atob(data.content.replace(/\n/g, ""));
  return JSON.parse(content);
}

async function ghPutFile(token, path, content) {
  // 先获取当前文件的 sha
  const resp = await fetch(
    `https://api.github.com/repos/${GH_OWNER}/${GH_REPO}/contents/${path}?ref=${GH_BRANCH}`,
    { headers: { Authorization: `Bearer ${token}`, Accept: "application/vnd.github+json" } }
  );
  let sha = null;
  if (resp.ok) {
    const data = await resp.json();
    sha = data.sha;
  }

  // 写入新内容
  const jsonStr = JSON.stringify(content, null, 2);
  const encoded = btoa(String.fromCharCode(...new TextEncoder().encode(jsonStr)));
  
  const body = {
    message: `📡 Update ${path}`,
    content: encoded,
    branch: GH_BRANCH,
  };
  if (sha) body.sha = sha;

  const putResp = await fetch(
    `https://api.github.com/repos/${GH_OWNER}/${GH_REPO}/contents/${path}`,
    {
      method: "PUT",
      headers: { Authorization: `Bearer ${token}`, Accept: "application/vnd.github+json" },
      body: JSON.stringify(body),
    }
  );
  return putResp.ok;
}

// ============ 工具函数 ============
function shouldPush(prev, curr) {
  if (curr === "offline") return false;
  if (prev === "offline" && curr === "live") return true;
  if (prev === "replay" && curr === "live") return true;
  if (prev === "offline" && curr === "replay") return true;
  return false;
}

function formatPushTitle(name, result) {
  return result.status === "live" ? `🔴 ${name} 开播了！` : `▶️ ${name} 轮播/回放中`;
}

function formatPushDesp(name, platform, rid, result, nowStr) {
  const label = platform === "bilibili" ? "B站" : "抖音";
  const url = platform === "bilibili" ? `https://live.bilibili.com/${rid}` : `https://live.douyin.com/${rid}`;
  const lines = [
    result.status === "live" ? `## 🎬 ${name} 开播了！` : `## ▶️ ${name} 轮播/回放中`,
    "",
    `**平台**: ${label}`,
    `**标题**: ${result.title || "-"}`,
  ];
  if (result.area) lines.push(`**分区**: ${result.area}`);
  if (result.online) lines.push(`**人气**: ${result.online}`);
  lines.push("", `👉 [进入直播间](${url})`, "", `---`, `检测时间: ${nowStr}`);
  return lines.join("\n");
}
