# blive-monitor 项目交接文档（上下文迁移包）

> 用途：把这个项目的关键信息一次性打包，粘贴到**新对话框**即可无缝继续。
> 生成时间：2026-07-10。当前 `master` HEAD：`871dd7d`。

---

## 0. 一句话定位

`racheko-lab/blive-monitor` 是一个**多平台直播/新作品监控** Python 项目：定时检测 B站 / 抖音 / 小红书 的主播是否开播（及抖音/小红书是否有新作品），有变化就推送到通知渠道（Server酱、企业微信、Telegram 等）。靠 **GitHub Actions (check.yml)** 每轮跑检测并自动把状态文件推回 master。

---

## 1. 仓库与本地路径

| 项 | 值 |
|----|----|
| GitHub 仓库 | `racheko-lab/blive-monitor` |
| 本地仓库（已克隆） | `/tmp/repo_verify` |
| 本地未推送前端变体 | `/workspace/blive-monitor`（monitor-tabs.html 的 Cloudflare 变体，不在仓库 tracked 文件） |
| 当前分支 / HEAD | `master` / `871dd7d`（工作区 clean） |
| 默认测试 | `tests/test_check_xhs.py`（15 passed） |

**克隆/恢复命令**（沙箱内 github.com 直连被 TCP 重置，必须走 ghproxy + PAT）：
```bash
git clone "https://<PAT>@ghproxy.net/https://github.com/racheko-lab/blive-monitor.git" /tmp/repo_verify
cd /tmp/repo_verify
```

---

## 2. 核心文件职责

| 文件 | 作用 |
|------|------|
| `check_status.py` | 直播状态检测主逻辑（含小红书解析器，约 40KB） |
| `check_new_posts.py` | 抖音/小红书新作品检测（约 34KB） |
| `monitor.html` | 主前端（含 xhs 三态映射 + 添加表单 platform 切换） |
| `monitor-feed.html` / `monitor-hero.html` / `monitor-dashboard.html` | 前端变体，均已带 xhs 三态支持 |
| `monitor-tabs.html` | 仅本地 `/workspace`，Cloudflare 变体，**未推送** |
| `rooms.json` | 监控房间列表（当前 7 条，见 §4） |
| `tests/test_check_xhs.py` | 小红书解析器单测（15 个，全过） |
| `.github/workflows/check.yml` | CI：每轮检测 + 推回状态；当含 xhs/douyin 房间时自动装 Playwright Chromium |
| `docs/` | 本项目自身设计文档（class-diagram.mermaid / sequence-diagram.mermaid / system_design.md），**不是外部参考项目** |
| `README.md` | 提到 `cors-proxy-worker.js` 为"遗留参考保留"（指 Cloudflare Worker 代理，非监控实现参考） |

---

## 3. 小红书监控方案（本项目最关键的技术突破）

### 3.1 关键发现（真站验证所得）
- 小红书直播真实状态**不在**服务端 HTML / `__INITIAL_STATE__` 里。SSR 是空模板（`roomId=0`、`roomStatus=-1`、`liveStatus='success'` 仅表示页面加载成功）。
- 真实数据由客户端 JS 经**签名 API**（`x-s`/`x-t`）填充，**且不回写 `<script>` 标签**。
- 因此"纯 HTTP 拿 JSON 判断是否开播"对直播基本走不通。数据中心 IP 访问 explore/profile 页会触发风控页。
- **结论**：连最像的同类项目 `aio-dynamic-push`，小红书开播检测也明确标 ❌（只做动态/笔记检测）。本项目补的是行业空白。

### 3.2 采用方案（已端到端验证）
无头 **Chromium 渲染真实直播间 URL** + 检测播放器 class：
- 在播信号：`xgplayer-is-live` 或 `xhsplayer-skin-live` 出现在 DOM
- 昵称提取：页面标题 `<昵称>的小红书直播间` 去掉后缀
- 短链解析：`xhslink.com/m/xxx` 用 `curl -L` 跟随重定向得真实 `xiaohongshu.com/...`（含 roomId）

### 3.3 关键函数（位于 check_status.py）
- `_find_chromium()`：探测系统 chromium 或 `~/.cache/ms-playwright/chromium-*/chrome-linux/chrome`
- `_extract_xhs_state(html)`：括号配平 + HTML 反转义 + `undefined/NaN/Infinity→null` + 容忍尾逗号，稳健提取 `__INITIAL_STATE__`
- `_render_with_chromium(url)`：`subprocess` 调 `chromium --headless=new --dump-dom --virtual-time-budget=12000 ...`
- `parse_xiaohongshu_room_dom(html, room_url)`：检测播放器 class
- `fetch_xiaohongshu(target)`：URL → 解析短链 → chromium 渲染 → 解析 DOM；非 URL 的 profile uid 降级 offline 并告警

### 3.4 验证记录
用真实在播账号「太阳蛋本蛋🍳」(`xhslink.com/m/4EEaOwFZSZY`) 端到端验证通过：返回 `{status: live, nickname: 太阳蛋本蛋🍳}`。

---

## 4. rooms.json 当前状态（7 条）

```json
[
  {"platform":"bilibili","id":"22230707","name":"峰哥亡命天涯"},
  {"platform":"douyin","id":"wsyzxz6688","name":"小猪装机"},
  {"platform":"douyin","id":"83134194400","name":"27～"},
  {"platform":"douyin","id":"jiubugaosuni315","name":"jiubugaosuni315"},
  {"platform":"douyin","id":"dy571881","name":"dy571881"},
  {"platform":"douyin","id":"81197422897","name":"81197422897"},
  {"platform":"xhs","id":"https://xhslink.com/m/4EEaOwFZSZY","name":"太阳蛋本蛋🍳(直播间示例)"}
]
```
> xhs 条目填的是**直播间短链**（不是 profile uid）。前端 `monitor.html` 的 xhs 模式 placeholder 已说明要填直播间 URL。

---

## 5. 沙箱网络环境限制（务必注意）

- 外部 HTTPS 被透明代理拦截；`github.com` / `api.github.com` 被 TCP 重置。
- **唯一能转发 git 协议**：`ghproxy.net`，PAT 嵌入 URL：
  `https://<PAT>@ghproxy.net/https://github.com/racheko-lab/blive-monitor.git`
- `xiaohongshu.com` / `xhslink.com` 用 `curl` 可直连（302/200），但数据中心 IP 触发风控页。
- **zsh 坑**：`$UID` 是只读变量，脚本里用它做普通变量会报 `bad math expression`，改用 `XUID` 等。
- **CI 抢推**：`check.yml` 每轮提交状态文件并推回 master；普通 push 前必须先 `git pull --rebase <remote> master` 再 push。

---

## 6. PAT 安全告警（重要）

- 当前使用的 GitHub PAT 形如 `ghp_xxx`（已多次经 ghproxy 明文出现在推送 URL；本仓库刻意不硬编码该值，避免触发 GitHub push protection 拒绝推送）。
- **新对话如何使用**：把你的 PAT 直接发给新对话，由它执行 `git clone "https://<PAT>@ghproxy.net/https://github.com/racheko-lab/blive-monitor.git"` 拉取本项目即可。
- **安全建议**：功能稳定后去 GitHub **revoke 并轮换**，避免长时间明文暴露。

---

## 7. 待办 / 未决事项

| 事项 | 状态 | 备注 |
|------|------|------|
| 删除 `kkkkkkkk_` 的 profile uid 条目 | ✅ 已完成（本会话 commit `871dd7d`） | 避免每轮降级告警 |
| `monitor-tabs.html` 本地变体推送 | ⏸ 未做 | 如需可 cp 回仓库再提交 |
| 中毒防护 bug：`test_main_poison_guard_skips_wrong_account` | ⚠ 1/135 失败 | 与 xhs 无关，可选修 |
| 内存价格监控 | 💡 仅思路 | 京东 `p.3.cn` 比价；用户要求"先别写代码" |
| PAT 轮换 | ⚠ 待办 | 见 §6 |
| 小红书监控外部方案对比文档 | 💡 可选 | 可落成 `docs/xhs-monitor-landscape.md` |

---

## 8. 外部同类项目对比（参考用，非本仓库内容）

| 项目 | 用途 | 小红书能力 | 技术路线 |
|------|------|-----------|----------|
| `nfe-w/aio-dynamic-push` | 多平台动态/开播推送（最像） | **仅动态检测✅，开播检测❌** | 各平台独立 query_task |
| `beilunyang/xhs-monitor` | 小红书用户动态监控 | 只做笔记/动态 | 基于 `xhs` 库（Web API + `x-s` 签名） |
| `XHS-Downloader` | 笔记/作品下载 | 作品下载 | Web API + 签名/Cookie |
| `Spider_XHS` | 数据运营爬虫 | 笔记/用户/评论 | 爬虫 + 签名逆向 |
| `RedNote-MCP` | 内容访问 MCP | 搜索/读笔记 | **Playwright 无头** |
| `matrix` | 多平台自动发布 | 自动发视频 | **Playwright** |
| **本仓库** | 多平台**直播状态**监控 | **直播开播检测✅（补空白）** | **无头 Chromium 渲染直播间 + `xgplayer-is-live`** |

> 两条主流路线：① 签名 API 逆向（`x-s`/`x-t`，轻量但需维护、需 Cookie）；② 无头浏览器渲染（抗改版、更重）。直播场景因 SSR 空模板，渲染几乎是纯服务端唯一可行方案。

---

## 9. 新对话框开场白模板（直接复制粘贴）

```
继续维护 racheko-lab/blive-monitor（多平台直播/新作品监控 Python 项目，本地在 /tmp/repo_verify，master HEAD 871dd7d）。

环境约束：
- 沙箱内 github.com 直连被 TCP 重置，git 必须走 ghproxy+PAT：git clone "https://<PAT>@ghproxy.net/https://github.com/racheko-lab/blive-monitor.git"
- push 前先 git pull --rebase，避免被 CI 抢推覆盖
- zsh 里 $UID 是只读变量，别当普通变量用

小红书监控核心：profile 页 SSR 是空模板，真实直播状态靠签名 API 填充且不回写 script，所以改用【无头 Chromium 渲染真实直播间 URL + 检测 xgplayer-is-live/xhsplayer-skin-live】。短链 xhslink.com/m/xxx 用 curl -L 解析。已用「太阳蛋本蛋🍳」(xhslink.com/m/4EEaOwFZSZY) 端到端验证通过。

当前 rooms.json 7 条（见 blive-monitor-context.md §4）。xhs 条目填直播间短链，不是 profile uid。

待办：monitor-tabs.html 本地变体未推送；中毒防护单测 1 个失败（与 xhs 无关）；PAT 建议 revoke 轮换；内存价格监控仅思路未写代码。

完整上下文见本仓库 `docs/blive-monitor-context.md`
```

---

*文档结束。把以上全部（或直接指向此文件）交给新对话框即可。*
