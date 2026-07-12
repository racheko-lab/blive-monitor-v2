# 简单 PRD — 日志模块功能性重写（blive-monitor）

> 产品经理：许清楚（Alice）｜ 版本：v1.0（简单 PRD）
> 关联设计：上一轮结构性重构 `docs/system_design.md`（已合并）；本轮补「功能性」。

---

## 1. 项目信息

- **Language**：中文（与需求一致）
- **技术栈**：沿用原生 HTML/JS/CSS + Python 标准库；复用 `log_utils.py` / `state_prune.py`；**不引入任何新前端框架/新第三方依赖**。
- **Project Name**：`log_module_rewrite`
- **原始需求复述**：上一轮仅完成了日志模块的**结构性重构**（抽出 `log_utils.py`、`state_prune.py`，history 加 `rid`，`HISTORY_MAX=500` 单一来源），但用户批评"只重构没补功能"。本轮需补齐三大功能性支柱：① 前端查看器功能化（搜索/多维筛选/分页/排序/展开/按账号视图）；② 日志分级 + 把后端抓取失败、风控拦截等运行时错误也写入前端可见的日志面板；③ 统计（每日新作品数/开播次数）与四视图整合为带完整筛选的主视图。用户**未选**导出与归档（本次不做，预留扩展点）。

---

## 2. 产品定义

### 2.1 Product Goals（3 个清晰、正交的目标）

1. **G1 — 让日志"看得清"**：用户能在前端对全部监控事件（开播/下播/新作品/异常/风控/系统）做搜索、多维筛选、分页、排序与展开，不再被硬编码 80 条截断限制。
2. **G2 — 让错误"看得见"**：原本只打到 Python `logger` → CI 控制台的抓取失败、风控拦截、sec_uid 解析失败等运行时错误，统一进入前端可读的统一日志流，并做节流防止刷屏。
3. **G3 — 让数据"用得上"**：基于统一日志流做统计分析（近 7 天每日新作品数、开播次数等）并整合四个重复渲染日志的视图为唯一主视图，消除维护分裂。

### 2.2 User Stories（覆盖三支柱）

- **US1（查看器 / G1）**：作为一名运营者，我希望在日志面板里按账号/类型/平台/日期筛选并搜索关键词，且能分页"加载更早"、按时间排序、点击展开看完整详情，以便快速定位某次开播或某条异常。
- **US2（错误可见 / G2）**：作为一名维护者，我希望后端某账号抓取失败或抖音风控时，日志面板能出现一条红色 error / 黄色 cookie_warn 记录（含原因），而不是只有 CI 控制台能看到，以便第一时间发现监控失联。
- **US3（统一数据源 / G2）**：作为一名维护者，我希望新作品事件和直播状态变更、运行时错误都进入**同一份** `history.json` 且用 `type` 区分，以便前端一套渲染逻辑覆盖全部事件类型。
- **US4（统计 / G3）**：作为一名运营者，我希望在日志面板顶部看到"近 7 天每日新作品数 / 开播次数"的统计条，以便直观评估活跃度，而无需自己数。
- **US5（视图整合 / G3）**：作为一名用户，我希望无论从 dashboard / feed / hero 哪个入口进来，都能使用带完整筛选功能的统一主视图，而不必在四个长得差不多却功能残缺的页面间切换。

---

## 3. 产品决策（落地规格）

> 以下决策供架构师实现时遵循；每条都基于前置代码阅读得出，确保可落地。

### 3.1 统一日志模型（决策 1）

- **结论**：将「新作品」「后端错误/风控警告」也写入**统一的 `history.json`**；通过新增 `type` 字段区分事件类型。不另起新日志文件（避免双数据源、前端双渲染）。
- **新增字段**（追加在现有 `time/name/platform/status/title/changed/prev/push/rid` 之后，**全部可选、前端忽略未知字段即兼容**）：
  - `type`：事件类型枚举（见 3.2）。
  - `level`：严重级 `info|warn|error`（二级，便于按严重度过滤；可选，缺省按 type 推导）。
  - `detail`：自由文本，承载错误原因 / 新作品链接 / 风控提示等扩展信息（前端展开时显示）。
  - `account`：可选，账号唯一键（与 `rid` 同源），供按账号视图聚合。
- **写入责任**：
  - `check_status.py`：现有直播条目**补写 `type`**（`live`→`live_on`、`offline`→`live_off`、`replay`→`live_off`、`error`→`error`），其余照旧走 `log_utils.append_history`。
  - `check_new_posts.py`：**新增**对 `history.json` 的写入（当前完全不写 history，只写 `post_tracking.json` + Python logger）。新作品检测命中、风控退化、抓取失败、sec_uid 解析失败等场景追加对应 `type` 条目。
- **并发安全性（已核实）**：`check.yml` 中两个脚本在**同一 job 内顺序执行**，且设置了 `concurrency.group: live-check`（串行，不并发）；随后 `merge_state.py` 对 `history.json` 做**并集合并**。因此 `check_new_posts.py` 顺序追加 history 不会与 `check_status.py` 竞争，合并阶段并集保留全部条目。✅ 无需改合并逻辑。

### 3.2 分级分类法 Taxonomy（决策 2）

| `type` | 含义 | `level` | 图标 | 配色（沿用现有变量） | 可筛选 | 写入方 |
|---|---|---|---|---|---|---|
| `live_on` | 开播 | info | 🔴 | `--live` | ✅ | check_status |
| `live_off` | 下播/回放结束 | info | ⚫ | `--text3` | ✅ | check_status |
| `new_post` | 抖音新作品 | info | 🎬 | `--dy` | ✅ | check_new_posts |
| `error` | 检测异常/抓取失败 | error | ❌ | `--error`（红） | ✅ | 两个脚本 |
| `cookie_warn` | 风控拦截/需 Cookie/解析失败 | warn | ⚠️ | `--yellow` | ✅ | check_new_posts |
| `system` | 系统事件（账号增删/基线初始化/配置变更） | info | ⚙️ | `--text3` | ✅ | 两个脚本（未来） |

- 是否要 `level` 作二级：**要**，但**可选字段**。前端默认可按 `type` 过滤；另提供一个"仅看警告/错误"的严重度快捷筛选（内部映射 `warn→cookie_warn`、`error→error`）。存量无 `level` 时由原 `type` 推导，不强依赖。
- 前端图标/配色**全部复用**现有 CSS 变量（`--live/--dy/--yellow/--error/--text3` 等），不新增设计语言。

### 3.3 后端错误可见（决策 3）

- **触发点与条目**：
  - **抓取失败**（`fetch` 异常 / playwright 超时 / HTTP 非预期）：追加 `type=error, level=error, detail=<截断后的异常信息>`，`name`=账号显示名，`platform`=对应平台。
  - **风控拦截 / 接口退化**：抖音接口返回空或 `count:` 退化时追加 `type=cookie_warn, level=warn, detail="抖音接口被风控，配置 douyin_cookie 可获取具体作品"`。
  - **无法解析 sec_uid**：追加 `type=cookie_warn, level=warn, detail="sec_uid 解析失败，该账号可能无法检测新作品"`。
- **去重 / 节流**：同一 `rid + type` 在 `ERROR_THROTTLE_MINUTES`（**建议 30 分钟**，见 Open Question 3）窗口内**不重复写**。实现方式：写入前扫描 history 最近 N（建议 50）条，若存在同 `rid+type` 且 `time` 距现在 < 窗口，则跳过，仅保持 Python logger 原样输出（控制台仍可见，不丢调试信息）。
- **兜底**：
  - 空 `sec_uid` 或 `post_rooms.json` 条目缺 `id`：判定为配置不完整，**跳过该账号**、写一条 `type=system, detail="账号配置不完整（缺 id/sec_uid），已跳过"`（不写垃圾 error 刷屏）。
  - 批量查询整体失败（如 B 站接口 5xx）：写一条 `type=error, detail="B站批量查询失败: …"`，沿用现有 `logger.warning/error` 文案。
- **写入路径**：统一经 `log_utils.append_history(HISTORY_FILE, entries, HISTORY_MAX)`，复用原子写与上限裁剪；不自行 `open().write`。

### 3.4 前端筛选 / 搜索 / 分页 / 排序 / 展开 / 按账号视图（决策 4）

> 改造对象：`monitor.html` 的 `renderLog()`（当前 ~L383-398，硬编码 `hist.length-1 … -80`，无筛选）。

- **筛选栏（顶部，作用于日志列表）**：
  - **搜索框**：对 `name` + `title` + `detail` 做模糊（子串）匹配。
  - **类型多选 chips**：全部 / 开播 / 下播 / 新作品 / 异常 / 风控 / 系统（映射到 `type`；"异常+风控"可合并为"仅警告/错误"严重度快捷）。
  - **平台 chips**：全部 / 哔哩哔哩 / 抖音（沿用现有 `fil()` 的 `platform` 过滤模式）。
  - **账号下拉**：按 `rid/name` 选择单一账号 → 进入"按账号单独视图"（见下）。
  - **日期**：可选日期选择（按 `time` 的日期部分过滤）；默认"全部"。
- **分页 / 加载更早**：
  - 步长 **50**；默认显示**最近 50 条**（替代原有固定 80）。
  - "加载更早"按钮：增量向前追加前 50 条（移动端友好，沿用现有轻量风格），不一次性渲染全量。
  - 提供简单分页器或"加载更早"二选一；**推荐"加载更早"增量模式**（与现有交互一致、省流量）。
- **排序**：默认按 `time` **倒序**（新→旧）；提供正/倒序切换按钮。
- **展开详情**：点击任一条目展开内联详情面板，显示**完整字段**：`time`（含日期）、`platform`、`type`（含中文标签）、`name`、`title`、`push`（推送标记）、`detail`、`rid`。再次点击收起。
- **按账号单独视图**：选中账号后，日志列表仅显示该账号；可结合顶部 tab 或账号抽屉实现，进入时自动预置平台/账号筛选并显示该账号的迷你统计（复用 3.6 口径）。返回即清空账号筛选。

### 3.5 统计（决策 5）

- **展示位置**：日志面板顶部新增 **stats bar**（不侵入 live/posts 视图；与现有 `ostat` 卡片风格一致）。
- **口径**：从 `history.json` 全量（经 HISTORY_MAX 上限内的条目）按 `type + time(北京时间)` 聚合到"天"。
  - 「近 7 天每日新作品数」：`type=new_post` 按天计数。
  - 「近 7 天每日开播次数」：`type=live_on` 按天计数。
  - （P1 扩展）风控/异常计数：`type in (error, cookie_warn)` 按天计数。
- **形态**：7 天迷你柱状/数字卡片（原生 HTML/CSS，沿用 `--card2/--line` 变量），hover/点击某天可下钻过滤该日（P2 可选）。
- **依赖**：口径正确依赖存量条目已带 `type`（见 3.7 迁移）。

### 3.6 视图整合（决策 6）

- **现状重复度**：四个 HTML 均 `fetch('history.json')` 并各自渲染日志——
  - `monitor.html`：`renderLog()`（完整 80 条，含 push 标记）。
  - `monitor-dashboard.html`：`renderLog()` 与 monitor **逐字相同**（最高重复）。
  - `monitor-feed.html`：`renderFeed()` 把日志与新作品混排（变体）。
  - `monitor-hero.html`：`renderLogBox()` 日志折叠在 `<details>` 里（变体）。
  - 四者前端逻辑分裂、筛选能力都不完整。
- **整合方案（推荐 Option A）**：
  - **`monitor.html` 为唯一 canonical 主视图**，承载全部功能（live / posts / log(含筛选+统计+分页) / config），并支持 `?view=dashboard|feed|hero` 预设参数自动打开对应 tab / 预置筛选。
  - `monitor-dashboard.html` / `monitor-feed.html` / `monitor-hero.html` **降为轻量入口**：通过 JS `location.replace('monitor.html?view=xxx')`（或 `<meta http-equiv="refresh">`）重定向到主视图对应预设，**不再各自维护一套日志渲染**。
  - 这样四入口功能不丢、但只维护一份日志渲染逻辑。
- **备选 Option B（若保留四文件）**：抽取共享渲染到原生 `log-common.js`（无框架），四文件引用同一份 `renderLog` + 筛选/分页组件，消除逻辑分裂。维护成本高于 A。
- **取舍**：详见 Open Question 2。本 PRD 默认按 **Option A** 落地。

### 3.7 向后兼容与非功能约束（决策 7）

- **不破坏 `check.yml` CI**：两个脚本调用顺序、`concurrency` 组、`merge_state.py` 并集合并均不变；新作品/错误写 history 属顺序追加，安全。
- **不引入新前端框架**：保持原生 HTML/JS/CSS，沿用现有样式变量（`--bili/--dy/--live/--card2/--line/--text3/--yellow/--error` 等）。
- **`HISTORY_MAX=500` 仍生效**：导出/归档未选，保留简单截断（经 `log_utils.append_history`）。
- **前端忽略未知字段即兼容**：`type/level/detail/account` 为新增可选字段；存量条目无 `type` 时前端**懒推导**（按 `status` 映射图标），不报错。
- **存量迁移（398 条无 type）**：提供**一次性迁移**（脚本或 `load_history` 懒推导二选一；推荐写回一次以保证统计准确），按 `status` 推导默认 `type`：
  - `status=live`→`live_on`；`offline`→`live_off`；`replay`→`live_off`；`error`→`error`；其余（含无 `status`）→`system`。
  - 迁移脚本幂等：仅对缺 `type` 的条目补写，已存在 `type` 的不覆盖；可重复运行。
- **原子写与上限**：所有 history 写入统一走 `log_utils.append_history`（`.tmp`+`os.replace` + 上限裁剪），禁止散落直写。
- **预留扩展点**：导出/归档（CSV/JSON）本次不做，但 `detail` 字段与统一模型已为其留好结构；UI 可预留一个 disabled 的"导出"按钮位（P2）。

---

## 4. 需求池（Requirements Pool）

> 优先级：P0 必做（三支柱核心）/ P1 增强 / P2 可选。每条含编号、描述、验收标准。

### P0（核心必做）

| 编号 | 描述 | 验收标准 |
|---|---|---|
| **P0-1** | 统一日志模型：history.json 新增 `type`（+可选 `level`/`detail`/`account`）；`check_status.py` 直播条目补 `type`；`check_new_posts.py` 新作品写入 history。 | ① history 条目含 `type` 枚举值；② 新作品事件出现在 history（非仅 post_tracking）；③ 前端忽略未知字段不报错；④ 两脚本写入均经 `log_utils.append_history`。 |
| **P0-2** | 后端错误可见：抓取失败/风控/无法解析 sec_uid 时向 history 追加 `error`/`cookie_warn`，含节流去重 + 兜底。 | ① CI 控制台报错的同时 history 出现对应条目；② 同 `rid+type` 30min 内不重复写；③ 缺 `id/sec_uid` 的账号不写垃圾 error，改写 `system` 跳过记录；④ 不破坏 `check.yml`。 |
| **P0-3** | 前端筛选栏：搜索（name/title/detail）+ 类型多选 + 平台 + 账号 + 日期，可组合。 | ① 各筛选项独立且可叠加；② 组合无结果显示空态；③ 平台筛选沿用现有 `fil()` 行为。 |
| **P0-4** | 前端分页/加载更早 + 排序：默认倒序、步长 50、增量"加载更早"。 | ① 首屏 ≤50 条；② 点击"加载更早"追加前 50 条；③ 正/倒序切换正确；④ 不再硬编码 80 截断。 |
| **P0-5** | 前端展开详情：点击条目展开显示完整字段。 | ① 展开显示 time/platform/type/name/title/push/detail/rid；② 再次点击收起；③ 不影响列表其他项。 |
| **P0-6** | 统计条：近 7 天每日新作品数 / 开播次数，按 type+time 聚合。 | ① 日志面板顶部 stats bar 显示 7 天数据；② 口径正确（迁移后）；③ 纯原生 HTML/CSS，沿用现有变量。 |
| **P0-7** | 视图整合为主视图：monitor.html 承载全部功能；其余三降为入口/重定向。 | ① 从 dashboard/feed/hero 访问进入 monitor.html 对应预设；② 功能不丢；③ 仅维护一份日志渲染逻辑。 |

### P1（增强）

| 编号 | 描述 | 验收标准 |
|---|---|---|
| **P1-1** | 按账号单独视图（per-account 抽屉/页）：选中账号只看其日志 + 该账号迷你统计。 | ① 可进入按账号视图；② 显示该账号过滤后日志与统计；③ 可返回全部。 |
| **P1-2** | 错误节流调优：`ERROR_THROTTLE_MINUTES` 等抽为常量/可配置；提供"持续失败"汇总。 | ① 节流窗口可改；② 同账号同类错误在窗口内仅一条；③ 提供窗口外仍失败的心跳/汇总（可选）。 |
| **P1-3** | 统计扩展：增加风控/异常计数、累计开播时长（数据可用时）。 | ① stats bar 显示 error/cookie_warn 计数；② 口径文档化。 |
| **P1-4** | 共享渲染组件（若选 Option B）：抽 `log-common.js` 共享 renderLog + 筛选/分页。 | ① 四文件引用同一份；② 单点修改生效。 |
| **P1-5** | 迁移脚本幂等 + 测试：存量 398 条按 status 推导 type；单测覆盖推导与边界。 | ① 脚本可重复运行不破坏；② 单测覆盖 live/offline/replay/error/缺失 映射。 |

### P2（可选）

| 编号 | 描述 | 验收标准 |
|---|---|---|
| **P2-1** | 深色模式日志高亮：error 红、warn 黄、new_post 抖音色。 | ① 高亮仅用现有变量；② 不引入新主题文件。 |
| **P2-2** | 异常条目点击跳转到关联账号管理（live/posts 视图）。 | ① 点击 error/cookie_warn 可定位账号。 |
| **P2-3** | 时间范围快捷预设：今天 / 近 24h / 近 7 天。 | ① 一键预置日期筛选。 |
| **P2-4** | 错误详情展开显示截断后的原始异常堆栈。 | ① detail 含堆栈（截断至 N 字符）。 |
| **P2-5** | 预留导出扩展点：UI 占位"导出"按钮（disabled）+ 注释扩展接口。 | ① 不实现功能，仅留可扩展结构（CSV/JSON 导出/归档，未来）。 |

---

## 5. UI 设计稿

### 5.1 新的 monitor.html 日志面板布局（ASCII）

```
┌──────────────────────────────────────────────────────────────┐
│ topbar: 📡 状态   [刷新]                    [tab: 直播|作品|日志|设置] │
├──────────────────────────────────────────────────────────────┤
│ 📊 stats bar（P0-6，仅日志视图显示）                            │
│  ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐                  │
│  │ 近7天新作品                                            │ 数字/迷你柱 │
│  │ 每日: 3·5·2·0·4·1·6  (按 type=new_post 聚合)          │                  │
│  └────────┘ └────────┘ └────────┘ └────────┘                  │
│  (P1-3 可加: 开播次数 / 风控·异常计数)                        │
├──────────────────────────────────────────────────────────────┤
│ 🔍 筛选栏（P0-3）                                             │
│  [搜索 name/title/detail……        ]                          │
│  类型: [全部][开播][下播][新作品][异常][风控][系统]            │
│  平台: [全部][B站][抖音]   账号: [下拉: 全部账号 ▾]            │
│  日期: [全部][今天▾]   排序: [↓ 新→旧] [↑]                   │
├──────────────────────────────────────────────────────────────┤
│ 📋 日志列表（步长 50，P0-4 / P0-5）                            │
│  ┌────────────────────────────────────────────────────────┐ │
│  │ 🔴 张三 · 开播 · 14:23  [已推送]            (点击展开 ▾) │ │
│  │   └─ 展开: time 2025-07-10 14:23 · platform bilibili   │ │
│  │      type live_on · title "今晚联动" · push pushed_ok   │ │
│  │      detail "" · rid 12345                              │ │
│  ├────────────────────────────────────────────────────────┤ │
│  │ 🎬 抖音号A · 新作品 · 13:10                  (点击展开 ▾)│ │
│  │   └─ detail: 最新作品《xxx》 https://... (latest_url)   │ │
│  ├────────────────────────────────────────────────────────┤ │
│  │ ❌ 李四 · 检测异常 · 12:05                   (点击展开 ▾)│ │
│  │   └─ detail: 抓取失败: TimeoutError ...（截断）         │ │
│  ├────────────────────────────────────────────────────────┤ │
│  │ ⚠️ 抖音号B · 风控警告 · 11:40                (点击展开 ▾)│ │
│  │   └─ detail: 抖音接口被风控，配置 douyin_cookie 可获取… │ │
│  └────────────────────────────────────────────────────────┘ │
│  [加载更早 ↓]  (增量 50，P0-4)                                │
└──────────────────────────────────────────────────────────────┘
```

### 5.2 四个视图整合后的关系（mermaid）

```mermaid
graph LR
    A[monitor-dashboard.html] -->|重定向/入口| M[monitor.html ★canonical]
    B[monitor-feed.html] -->|重定向/入口| M
    C[monitor-hero.html] -->|重定向/入口| M
    M -->|?view=dashboard| T1[日志 tab + 预置筛选]
    M -->|?view=feed| T2[日志 tab + 新作品优先]
    M -->|?view=hero| T3[日志 tab + 在播置顶]
    M -->|默认| T0[直播|作品|日志|设置 四 tab]
    M -.复用.-> L[统一日志渲染: 筛选+统计+分页+展开]
    style M fill:#ff7a86,stroke:#fff,color:#fff
```

> 备选（Option B）：保留四文件但抽 `log-common.js` 共享渲染，四文件均引用同一份 `renderLog`+筛选/分页组件。

---

## 6. 待确认问题（Open Questions，需主理人/用户拍板）

1. **新作品是否进统一日志**：本 PRD 默认"是"（统一到 history.json，新增 `type=new_post`）。需确认是否接受 `check_new_posts.py` 开始写 `history.json`（当前完全不写），以及是否担心 history 增长更快（仍受 HISTORY_MAX=500 约束）。
2. **四视图是否全合并 vs 保留 monitor.html 为主**：默认 **Option A**（其余三降为重定向入口，`monitor.html` 为 canonical）。需确认是否接受"废弃" dashboard/feed/hero 的独立渲染，还是采用 Option B 保留四文件 + 共享组件。
3. **错误节流时间窗口取值**：默认 **30 分钟**（同 `rid+type` 窗口内不重复写）。需确认窗口长度；过短仍可能刷屏（CI 每 5 分钟一轮），过长可能掩盖持续失败。是否要"窗口外仍失败"的心跳汇总？
4. **存量 398 条迁移方式**：默认"一次性写回 `type` 字段"（保证统计准确）。是否接受直接改 history.json（受 `.gitignore`？需确认 history.json 是否被忽略——当前 CI 用 `git add -f history.json`，故会提交）；还是仅前端懒推导、不做迁移写回。
5. **`level` 二级是否落地**：默认"写可选 `level` 字段并按其提供'仅警告/错误'快捷筛选"。是否认为过度设计、仅用 `type` 即可。
6. **按账号单独视图形态**（P1-1）：是独立页面、还是顶部账号下拉 + 列表过滤 + 迷你统计抽屉？影响 P0-7 与 P1-1 的边界。

---

## 7. 范围边界（明确不做）

- **导出与归档**（CSV/JSON 导出、超限归档）本期不做；已通过 `detail` 字段与统一模型预留扩展点（见 P2-5）。
- 不引入新第三方前端框架 / 新 Python 依赖。
- 不改动 `check.yml` CI 调用顺序与 `concurrency` 设计（仅确认安全）。
- 不重构 `post_tracking.json` 时间线（新作品事件走 history，post_tracking 维持基线用途）。
