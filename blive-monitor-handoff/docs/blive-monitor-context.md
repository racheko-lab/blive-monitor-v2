# blive-monitor 项目交接文档（上下文迁移包）

> 用途：把这个项目的关键信息一次性打包，粘贴到**新对话框**即可无缝继续。
> 生成时间：2026-07-10。当前 `master` HEAD：`871dd7d`。

---

## 0. 一句话定位

`racheko-lab/blive-monitor` 是一个**多平台直播/新作品监控** Python 项目：定时检测 **B站 / 抖音** 的主播是否开播（及抖音是否有新作品），有变化就推送到通知渠道（Server酱、企业微信、Telegram 等）。靠 **GitHub Actions (check.yml)** 每轮跑检测并自动把状态文件推回 master。

> 平台范围说明：本项目当前**仅支持 B站、抖音**的直播监控与抖音新作品检测。**小红书直播监控已于 2026-07-10 从代码中移除，当前未支持**（详见 §3）。

---

## 1. 仓库与本地路径

| 项 | 值 |
|----|----|
| GitHub 仓库 | `racheko-lab/blive-monitor` |
| 本地仓库（已克隆） | `/tmp/repo_verify` |
| 本地未推送前端变体 | `/workspace/blive-monitor`（monitor-tabs.html 的 Cloudflare 变体，不在仓库 tracked 文件） |
| 当前分支 / HEAD | `master` / `871dd7d`（工作区 clean） |
| 默认测试 | `pytest`（见 `tests/`；无小红书相关测试） |

**克隆/恢复命令**（沙箱内 github.com 直连被 TCP 重置，必须走 ghproxy + PAT）：
```bash
git clone "https://<PAT>@ghproxy.net/https://github.com/racheko-lab/blive-monitor.git" /tmp/repo_verify
cd /tmp/repo_verify
```

---

## 2. 核心文件职责

| 文件 | 作用 |
|------|------|
| `check_status.py` | 直播状态检测主逻辑（B站 / 抖音） |
| `check_new_posts.py` | 抖音新作品检测 |
| `monitor.html` | 主前端（B站 / 抖音 房间管理 + 状态展示；Token 由用户在前端「配置」页填入并存于 localStorage） |
| `monitor-feed.html` / `monitor-hero.html` / `monitor-dashboard.html` | 前端变体（B站 / 抖音） |
| `monitor-tabs.html` | 仅本地 `/workspace`，Cloudflare 变体，**未推送** |
| `rooms.json` | 监控房间列表（当前为 B站 / 抖音，见 §4） |
| `tests/` | 各模块单测（`test_check_status.py`、`test_check_new_posts.py`、`test_common.py`、`test_push_utils.py`、`test_merge_state.py`、`test_log_*.py` 等） |
| `.github/workflows/check.yml` | CI：每轮检测 + 推回状态；含 douyin 房间时自动装 Playwright Chromium |
| `docs/` | 本项目自身设计文档（class-diagram.mermaid / sequence-diagram.mermaid / system_design.md / functional_design.md 等），**不是外部参考项目** |
| `README.md` | 项目说明，支持平台为 B站 / 抖音 |

---

## 3. 小红书监控：当前未支持（已于 2026-07-10 移除）

### 3.1 历史背景与技术结论（调研结论，非本仓库当前实现）
- 小红书直播真实状态**不在**服务端 HTML / `__INITIAL_STATE__` 里。SSR 是空模板（`roomId=0`、`roomStatus=-1`、`liveStatus='success'` 仅表示页面加载成功）。
- 真实数据由客户端 JS 经**签名 API**（`x-s`/`x-t`）填充，**且不回写 `<script>` 标签**。
- 因此"纯 HTTP 拿 JSON 判断是否开播"对直播基本走不通。数据中心 IP 访问 explore/profile 页会触发风控页。
- 同类项目（如 `aio-dynamic-push`）小红书开播检测也明确标 ❌（只做动态/笔记检测）。

### 3.2 曾被尝试的方案（已移除）
曾尝试用**无头 Chromium 渲染真实直播间 URL + 检测播放器 class**（`xgplayer-is-live` / `xhsplayer-skin-live`）来实现开播检测。但该方案存在以下问题，维护成本过高：
- 小红书每次开播短链都会变，需反复解析 `xhslink.com/m/xxx`；
- 数据中心 IP 触发风控页，误判/漏推难根除。

**结论**：小红书直播监控已于 2026-07-10 从 `check_status.py` 中移除，**当前未支持**。如需恢复，需重新评估上述成本；本仓库当前聚焦 B站 / 抖音。

---

## 4. rooms.json 当前状态

当前 `rooms.json` 仅含 B站 / 抖音 房间（历史上曾临时加入过 1 个小红书直播间示例条目，已移除）：

```json
[
  {"platform":"bilibili","id":"22230707","name":"峰哥亡命天涯"},
  {"platform":"douyin","id":"wsyzxz6688","name":"小猪装机"},
  {"platform":"douyin","id":"83134194400","name":"27～"},
  {"platform":"douyin","id":"jiubugaosuni315","name":"jiubugaosuni315"},
  {"platform":"douyin","id":"dy571881","name":"dy571881"},
  {"platform":"douyin","id":"81197422897","name":"81197422897"}
]
```
> 实际条目以仓库内 `rooms.json` 为准（会随 CI 推回变化）。`platform` 取值仅 `bilibili` / `douyin`。

---

## 5. 沙箱网络环境限制（务必注意）

- 外部 HTTPS 被透明代理拦截；`github.com` / `api.github.com` 被 TCP 重置。
- **唯一能转发 git 协议**：`ghproxy.net`，PAT 嵌入 URL：
  `https://<PAT>@ghproxy.net/https://github.com/racheko-lab/blive-monitor.git`
- `xiaohongshu.com` / `xhslink.com` 用 `curl` 可直连（302/200），但数据中心 IP 触发风控页（这也是小红书检测难做的原因之一）。
- **zsh 坑**：`$UID` 是只读变量，脚本里用它做普通变量会报 `bad math expression`，改用 `XUID` 等。
- **CI 抢推**：`check.yml` 每轮提交状态文件并推回 master；普通 push 前必须先 `git pull --rebase <remote> master` 再 push。

---

## 6. Token / PAT 安全告警（重要）

- 前端 `monitor.html` **不再内置任何 GitHub Token**（历史上曾硬编码一个全权限 PAT 在源码中，已泄露在公开仓库，已彻底移除）。
- GitHub REST API 写回（`rooms.json` 增删）所需的 Token **由用户在前端「⚙️ 配置」页自行填入**，仅存于本机 `localStorage`，不会进入源码或 git 历史。
- 请使用你自己的**细粒度 Token**（仅本仓库 `Contents: read/write` 权限即可），不要使用全量 `repo`/`workflow` 权限 PAT。
- 功能稳定后建议去 GitHub **revoke 并轮换** Token，避免长时间明文暴露。

---

## 7. 待办 / 未决事项

| 事项 | 状态 | 备注 |
|------|------|------|
| 删除 `kkkkkkkk_` 的 profile uid 条目 | ✅ 已完成（本会话 commit `871dd7d`） | 避免每轮降级告警 |
| `monitor-tabs.html` 本地变体推送 | ⏸ 未做 | 如需可 cp 回仓库再提交 |
| 中毒防护 bug：`test_main_poison_guard_skips_wrong_account` | ⚠ 1/135 失败 | 与平台无关，可选修 |
| 内存价格监控 | 💡 仅思路 | 京东 `p.3.cn` 比价；用户要求"先别写代码" |
| Token 轮换 | ⚠ 待办 | 见 §6（前端已不再内置 PAT） |
| 小红书直播监控 | ❌ 当前未支持 | 已于 2026-07-10 移除；详见 §3 |

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
| **本仓库** | 多平台**直播状态**监控（B站 / 抖音） | **未支持** | B站官方 API / 抖音服务端 HTML 多策略 |

> 两条主流路线：① 签名 API 逆向（`x-s`/`x-t`，轻量但需维护、需 Cookie）；② 无头浏览器渲染（抗改版、更重）。直播场景因 SSR 空模板，纯服务端拿开播态很困难——这也是小红书开播检测难做的根因。

---

## 9. 新对话框开场白模板（直接复制粘贴）

```
继续维护 racheko-lab/blive-monitor（多平台直播/新作品监控 Python 项目，本地在 /tmp/repo_verify，master HEAD 871dd7d）。

环境约束：
- 沙箱内 github.com 直连被 TCP 重置，git 必须走 ghproxy+PAT：git clone "https://<PAT>@ghproxy.net/https://github.com/racheko-lab/blive-monitor.git"
- push 前先 git pull --rebase，避免被 CI 抢推覆盖
- zsh 里 $UID 是只读变量，别当普通变量用

平台范围：当前仅支持 B站 / 抖音 直播监控 + 抖音新作品检测；小红书直播监控已于 2026-07-10 移除，未支持。
前端 monitor.html 不再内置任何 GitHub Token，写回所需的 Token 由用户在「配置」页填入并存在 localStorage；请使用细粒度（仅 Contents 读写）Token。

待办：monitor-tabs.html 本地变体未推送；中毒防护单测 1 个失败（与平台无关）；内存价格监控仅思路未写代码。

完整上下文见本仓库 `docs/blive-monitor-context.md`
```

---

*文档结束。把以上全部（或直接指向此文件）交给新对话框即可。*
