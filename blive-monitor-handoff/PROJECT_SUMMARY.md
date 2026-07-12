# blive-monitor 项目整合总结（交付包说明）

> 本文档为本项目整合包 `blive-monitor-handoff/` 的**总览与批判式总结**。
> 重点放在两件事：**① 需求 / 雇主侧的不合理之处**；**② UI 侧的不合理之处**。
> 目标：让拿到本包的其他工具 / 协作者，能快速理解"为什么这个项目看起来乱、改起来别扭"，并避开雷区。

---

## 0. 一句话定位

一个 **B站 / 抖音 直播 + 新作监控**工具：Python（GitHub Actions CI）每 5 分钟检测开播 / 新作，结果写进仓库 JSON，前端 `monitor.html` 是**单文件 SPA 直连 GitHub Contents API** 渲染，开播 / 新作时多渠道（Bark / Server 酱 / 企业微信 / PushPlus / Telegram）推送通知。

---

## 1. 项目整体结构

```
blive-monitor/
├── monitor.html            # 前端单文件 SPA（4959 行 / 319 个 <div>）★ 用户重点吐槽对象
├── index.html              # 首页重定向
├── monitor-*.html          # 3 份早期原型（hero/feed/dashboard，遗留未清理）
├── check_status.py         # 直播检测主脚本
├── check_new_posts.py      # 抖音新作检测
├── auto_summary.py         # 定时摘要
├── push_utils.py           # 推送 + 事件分发（dispatch_event）
├── common.py / log_utils.py / merge_state.py / state_prune.py / transcode_covers.py
├── backend/                # 阶段四新增：FastAPI + SQLAlchemy + APScheduler（39 文件）
├── adapters/ (backend/adapters) # 阶段三：快手/视频号/小红书/淘宝直播 适配器
├── tools/import_json_to_db.py    # 旧 JSON → 新 DB 迁移
├── docs/                   # 24 份设计 / 分析 / 交付文档
├── tests/                  # 53 个测试文件，约 511 个测试用例
├── .github/workflows/check.yml  # CI 每 5 分钟检测
├── Dockerfile / docker-compose.yml   # 阶段四后端部署
├── config/ platforms.example.json    # 阶段三多平台凭证示例
└── *.json                  # 运行时状态（rooms/status/state/tracking/history/post_*…）
```

**规模**：前端 4959 行单文件；后端 39 文件；测试 511 例；设计文档 24 份。
**技术栈**：后端 Python 标准库 +（阶段四）FastAPI/SQLAlchemy/APScheduler；前端原生 HTML/JS，无构建步骤；部署 GitHub Pages（纯静态）+ Actions。

---

## 2. 发展历程（多阶段堆叠，是"乱"的根源之一）

| 阶段 | 内容 | 备注 |
|------|------|------|
| 阶段 0（P0-1~P0-7） | 基础直播监控、平台定位、列表搜索、健康仪表盘 | 奠定"前端直连 GitHub"架构 |
| 阶段 2（A1~D2） | 定时摘要、批量增删、分组标签、批量启停、排序、静默、开播时长、趋势、详情弹层、CSV 导出 | 在旧骨架上继续堆叠 |
| 阶段 3 | 多平台适配器：快手 / 视频号 / 小红书 / 淘宝直播（建在阶段四地基上） | "结构 + 优雅降级 + 待凭证"，新平台并未真跑通 |
| 阶段 4 | 后端 + DB：FastAPI + SQLAlchemy(SQLite WAL) + APScheduler + Docker | 与前端是两套并存体系 |
| UI 换肤（commit `cb505d4`） | 集成暗色移动端 `.blm-*` 设计系统（"新皮 + 旧脑"） | **设计系统早已落地**，但用户仍反馈"整体乱" |

> 关键背景：你（雇主）说"前端太庞杂、布局混乱"时，`.blm-*` 暗色设计系统**其实已经集成在仓库里**了。你看到的"乱"极可能是**桌面端 430px 窄条 + 真实数据密度**（见 §4），而非"没有设计系统"。

---

## 3. ⚠️ 雇主 / 需求侧的不合理之处（重点）

> 以下是从"接需求 / 做交付"角度，认为**约束或决策本身不合理**、导致项目难维护、改不动的地方。

### 3.1 单文件 SPA + "无构建步骤" 的硬约束
- 前端被锁死为**一个 4959 行、319 个 `<div>` 的 `monitor.html`**，所有 CSS/JS/视图都在一个文件里。
- "无构建、直连 GitHub"是核心卖点，但也意味着**无法用组件化、模块化、CSS 预处理器**来治理复杂度。
- 结果：任何一处改动都牵动全局，代码评审和重构成本极高。

### 3.2 "契约保全"铁律把 UI 重构绑死
- 反复强调：重构 UI **不得破坏 511 个测试、不得改动任何 JS 函数逻辑、不得改动任何元素 id、必须保留遗留 CSS 变量别名与 Phase-1 类**。
- 大量测试是 **`grep` 源码字符串**（如 `#healthBar`、`kpiFresh`、`.blm-room-link`、`supportedPlatforms` 文案）。
- 后果：**UI 重构只能"换 CSS class 名 + 改 render 输出的 HTML 模板字符串"，不能动结构与语义**。这等于只允许"化妆"，不允许"整骨"——当用户要的是"整体布局重构"时，这套约束直接打架。

### 3.3 前端直连 GitHub Contents API
- 每次打开页面拉一堆 JSON（`status/rooms/history/post_*`…），受 GitHub API **限流、CORS、私密性**制约；离线 / 限流即整页空白。
- "零后端"很轻，但把"数据源"和"前端"硬绑，难以做聚合 / 缓存 / 鉴权。

### 3.4 内置默认 PAT 硬编码进前端（严重安全债）
- `monitor.html` 曾/现硬编码一个**全 `repo` + `workflow` 权限的默认 GitHub Token**（`DEFAULT_GH_TOKEN`），只为"零配置增删监控"。
- 这是**暴露在公开源码里的全权限凭证**，任何看页面源码的人都能拿走、代你写仓库、触发工作流。
- 本交付包已将该 Token **脱敏移除**（见 `monitor.html` 第 2453 行注释）。真实工程中应：轮换并吊销该 Token、改为"用户自建细粒度 Token"、前端绝不内置凭据。

### 3.5 "整体都乱"的反馈出现在设计系统已落地之后 → 验收标准错位
- 设计系统 `cb505d4` 早已合入，但雇主仍主观判定"整体乱七八糟"。
- 反映出**缺乏可量化的 UI 验收标准**（什么是"不乱"？桌面？移动？哪个视图？），执行方做了 A，雇主脑子里是 B，沟通靠"你听不懂"收场。
- 这也是为什么最后走向"打包甩给其他工具"——需求方与执行方对"完成"的认知没对齐。

### 3.6 桌面端锁死 430px（最直观的"不合理"）
- `.mobile-container { max-width: 430px }`——一个明显被**运维 / 开发者在桌面浏览器使用**的监控面板，被做成手机框。
- 桌面下是一条窄栏漂浮在空白里，视觉上"破碎"。本轮已加响应式断点（≥1100px 放宽到 1080px + 多列），但这是补丁，不是根因修复。

### 3.7 阶段三"结构 + 优雅降级 + 待凭证"就交付
- 快手 / 视频号 / 小红书 / 淘宝直播 四个适配器以"结构就绪、凭证待填、运行时降级"状态交付。
- 即"看起来支持了，实际没真跑通"——对雇主是**虚假完成度**，后续填坑成本转嫁。

### 3.8 CI 每 5 分钟抢推 + 沙箱推送需 ghproxy 拼接令牌绕过
- CI 自动提交 `update state` 与人工提交频繁冲突，需 rebase；沙箱推送要走 `ghproxy.net` + 运行时拼接 PAT 绕过 GitHub 推送保护。
- 工程摩擦高，且**有把明文令牌写进本地脚本的事故前科**（`qa_verify_a2a4.py` 曾含完整明文 PAT，已从本包剔除）。

### 3.9 测试数量膨胀但护的是"字符串"而非"行为"
- 测试从 315 涨到 511，主体是 grep 契约测试。
- 这类测试保护的是**源码里恰好出现的字符串**，反而成为重构阻力：想改名 / 改结构就会"测试失败"，但功能未必坏。

---

## 4. ⚠️ UI 侧的不合理之处（重点）

> 从"用户实际看到并觉得乱"的角度，UI 自身的设计问题。

### 4.1 桌面端 430px 窄条（§3.6 同因）
- 1280px 屏幕上只显示 430px 一列，四周大片空白 → "布局混乱"的第一直观感受。已加响应式补丁，但根因是移动优先假设错配了使用场景。

### 4.2 单文件 4959 行 / 319 div 的"巨石"
- 即使设计系统统一（`.blm-*` 约 174 种类），**单文件体量本身**就让"布局"在源码层显得混乱；改一个视图要在这近 5000 行里翻找。

### 4.3 信息密度过高、缺视觉呼吸
- 直播 11 房间、新作 12 条、日志 **101 条** 同屏呈现；筛选栏 / 统计卡 / 表单 / 列表全堆在单列里。
- 日志视图 101 条**无虚拟滚动 / 无分页**（仅有 "加载更多"），长列表滚动疲劳。

### 4.4 配置视图是"表单堆砌"
- 配置 tab 实测 **100+ 个 `<div>`**，GitHub Token / 推送渠道 / 路由规则 / 文案模板 / 静默时段全部纵向堆在一个长页面，无分组折叠、无步骤引导。

### 4.5 无路由 / 无 URL 状态
- 5 个 tab 靠 `show('key')` 切换，**刷新即回到默认视图**，无法分享 / 书签某个视图；多视图状态不持久。

### 4.6 移动优先假设 vs 实际场景错配
- 设计语言是"暗色移动端仪表盘"，但工具的使用者大概率是**桌面端的运维 / 运营**。移动端审美套在桌面监控面板上，观感违和。

### 4.7 错误 / 空态体验弱
- 限流 / 离线时整页显示"加载失败"空态，缺乏重试入口与降级展示；真实数据缺失时页面"看起来坏了"。

---

## 5. 整合说明（给接手工具 / 协作者）

### 5.1 本包已做的处理
- ✅ 剔除 `.git` 历史（避免令牌随历史泄露）、`__pycache__` / `.pytest_cache` 缓存、`qa_verify_a2a4.py`（含明文完整 PAT）。
- ✅ **脱敏** `monitor.html` 内置默认 Token（第 2453 行改为空串 + 注释说明）。
- ✅ 保留全部源码 / 文档 / 测试 / 设计文档 / 配置示例。
- ⚠️ `README.md` / `docs/product_analysis.md` / 几份 QA 报告里仍**提到 `ghp_` 前缀**（讨论性质，非令牌），未改动。

### 5.2 雷区清单（动 UI 前必读）
1. **不要动这些 id**（测试 grep，缺则崩）：`stime, sdot, statLive, statRooms, statPosts, liveBody, postsBody, logBody, healthBar, view-* , supportedPlatforms, kpiRooms/Live/Today/Notify/Fresh, dashTrend/Rank/Platform/Notify, tokenInput, pushChannel…`
2. **不要动这些函数名 / 签名**：`ld, show, renderLive, renderPosts, renderLog, renderDashboard, renderHealthBar, computeStatsJS, matchQ, matchPostQ…`
3. **保留遗留 CSS 别名**：`--green --yellow --live --bili --dy --text --text2 --text3 --card --card2 --line --shadow --bili-soft --dy-soft --bg --radius`。
4. **保留 Phase-1 类**：`.health.*` `.pf.ok/.pf.bad` `.pt-*` `.toast*` `.empty` `.view` `.ld-*` `.chip` `.lchip` `.blm-room-link`。

### 5.3 建议的接手路径
- **若目标是"真正重构 UI"**：先与雇主对齐"不乱"的验收标准（桌面 / 移动？哪个视图？），并**松绑 §3.2 的契约铁律**（允许改测试、允许改结构）；优先考虑"拆多文件 + 引入构建（Vite/React）"或至少"桌面响应式优先"。
- **若目标是"安全整改"**：轮换并吊销内置 PAT、前端移除任何硬编码凭据、推送密钥改由用户自填。
- **若目标是"降噪"**：日志虚拟滚动 / 分页、配置视图分组折叠、空态重试入口——这些可在不改契约前提下做。

---

## 6. 关键入口文件（给其他工具快速上手）

| 想改什么 | 看哪里 |
|----------|--------|
| 前端布局 / 样式 | `monitor.html` 的 `<style id="theme-vars">`（约 line 8–1782）+ `<body>` 骨架（约 line 1784 起）+ `render*` 函数 |
| 前端契约 / 测试 | `tests/test_live_room_clickable.py` `test_platform_position.py` `test_dashboard.py` `test_selfcheck.py` |
| UI 重构蓝图（既有） | `docs/ui_reskin_design.md`（详尽，但偏"换皮不换骨"） |
| 后端 / API | `backend/app.py` + `backend/api/*.py` + `backend/jobs/*.py` |
| 多平台适配器 | `backend/adapters/*.py` + `config/platforms.example.json` |
| 部署 / CI | `README.md` `DEPLOYMENT.md` `.github/workflows/check.yml` `Dockerfile` |

---

*本总结由交付总监（主理人）基于项目实际状态整理，立场客观、包含对需求与 UI 两方面的批判。打包日期见交付包根目录文件时间戳。*
