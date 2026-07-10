# P0-7 统一健康仪表盘 · 简单 PRD（阶段1 收官）

> 产品经理：许清楚（Alice）｜ 模块：blive-monitor 前端 `monitor.html`
> 关联：阶段 2（原 P0-7）｜ 上游：`docs/product_analysis.md` P0-7「统一健康仪表盘」
> 本轮定位：**阶段 1 收官之作**——纯前端、零依赖、新增第 5 个「仪表盘」tab
> 范围：新增一个一屏聚合总览；不新增后端、不改 CI、不引入图表库
> 语言：中文

---

## 一、项目信息

| 项 | 内容 |
|---|---|
| 原始需求复述 | 用户打开页面只能看列表和日志，**没有一个一眼总览**：多少房间在监控、今天开了几场、哪个主播最活跃、通知有没有异常、数据新鲜度。数据都在，但散落在各 tab，缺少聚合视图。 |
| 全局状态（已核对） | `var stat=null,rooms=[],hist=[],postRooms=[],postTrack={},fl='all',q='';`（`ld()` 已把 `status.json/rooms.json/history.json` 载入全局 `stat/rooms/hist`） |
| 可复用资产（已核对） | ① `computeStatsJS(histData, days, now)`（monitor.html L642-661）算近 N 天分桶统计，已含 `live_on`/`new_post`/`error`/`cookie_warn`；② `calcFreshness(updated, now)`（L618-641）算数据新鲜度四态；③ `bjNow()`（L585）北京时间折算；④ 日志页 `renderStats()` 的 `.spark/.bar` CSS 条形画法（L126-131、L668-681）为零依赖图表范本 |
| 改动文件 | `monitor.html`（加第 5 个 tab 的 HTML/按钮/`renderDashboard()`，并在 `ld()` 与 `show('dashboard')` 时调用）；新增 `tests/test_dashboard.py` |
| 不改动 | 后端 / Python 检测脚本 / CI workflow；现有四 tab 逻辑；P0-1 健康条（`#healthBar`）与定时刷新（`ld()`） |
| 技术栈 | 纯静态前端，原生 HTML/JS（与仓库现有 `monitor.html` 一致，无框架）；图表一律 CSS/SVG 手绘，**零外部依赖** |

---

## 二、产品目标（Product Goals）

1. **一眼总览**：用户打开「仪表盘」tab，0 思考成本就能知道——在监控多少房间、当前几个在播、今天开了几场、谁最活跃、推送有没有异常、数据新不新鲜。把散落在直播/新作/日志/配置里的信息聚合到一屏。
2. **异常可发现**：通知健康（warn/error 级）与最近若干条异常直接陈列，让「推送失败 / cookie 风控」这类问题一眼可见，而非埋进 500 条日志里翻。
3. **零负担接入**：作为纯前端聚合视图，复用 `ld()` 已载入的 `hist/stat/rooms`，不新增数据源、不引入图表库、与现有四 tab 视觉风格一致，融入成本最低。

---

## 三、用户故事（User Stories）

- 作为**日常用户**，我想打开页面第一个 tab 就看到「在监控 N 个房间 / 当前 M 个在播 / 今天开了 K 场」，以便不进各列表也能掌握整体动态。
- 作为**追主播的用户**，我想看「开播排行 Top 5」知道谁最近最活跃，以便决定优先关注谁。
- 作为**关注推送可靠性的用户**，我想一眼看到「通知异常数 + 最近几条异常（含名称/平台/时间/原因）」，以便快速判断是不是 cookie 风控 / 推送通道挂了。
- 作为**多平台监控用户**，我想看 B站 vs 抖音的房间数 / 开播数对比，以便了解两个平台的覆盖与活跃差异。
- 作为**担心监控假死的用户**，我想在仪表盘也看到数据新鲜度（复用 P0-1），以便和健康条交叉确认数据没陈旧。

---

## 四、需求池（Requirements Pool）

### P0（必须有，纯前端，新增「仪表盘」tab）

| ID | 需求 | 验收标准 |
|---|---|---|
| **P0-1** | **第 5 个 tab「仪表盘」接入**：在底部 `.tabbar` 加 `<button class="tab" onclick="show('dashboard')">`；新增 `<section id="view-dashboard" class="view">`；同步改 `show()` 的两处索引（见 §五.1） | 点击「仪表盘」切到 `#view-dashboard` 且按钮高亮；其余四 tab 行为不变；`?view=dashboard` 直达本 tab（改 `readViewParam()` 由 `show('log')` 改为 `show('dashboard')`） |
| **P0-2** | **概览 KPI 卡（5 项）**：① 监控房间总数 `rooms.length`；② 当前直播中数 `stat.rooms.filter(r=>r.status==='live').length`；③ 今日开播次数 `hist` 中 `type==='live_on'` 且为**今天北京时间**的数量；④ 通知异常数 `hist` 中 `level==='warn'||'error'` 的计数（如 `cookie_warn`）；⑤ 数据新鲜度（复用 `calcFreshness()` 的 state + label） | KPI 口径见 §五.4；数值与现有 `.overview` 顶栏（直播中/监控房间/新作品号）口径一致或互补；空数据时显示 0 / 「—」而非报错 |
| **P0-3** | **开播趋势（近 7 天）**：用 CSS 条形（或内联 SVG）画近 7 天每天 `live_on` 次数；复用 `computeStatsJS(hist, 7)` 产出 `live_on[]` 与 `days[]` | 7 根条形高度按当日值 / 7 天最大值归一；悬停/标题显示 `MM-DD: N`；**不引入任何图表库**；视觉复用 `.spark/.bar` 风格 |
| **P0-4** | **主播开播排行（Top N）**：按 `name` 统计 `type==='live_on'` 次数，取 Top N（默认 5）列表，显示名次/名称/次数 | N 由常量定义（见 §五.6 待确认）；并列按次数降序、次数相同按最近开播时间；当前无数据显示空态 |
| **P0-5** | **平台分布**：bilibili vs douyin 的房间数（来自 `rooms`）+ 开播数（来自 `hist` 中 `type==='live_on'` 按 `platform` 分桶），用比例条或纯数字呈现 | 与 `rooms.json` 实际分布（当前 1 B站 / 9 抖音）吻合；比例条用既有 `--bili`/`--dy` 变量着色 |
| **P0-6** | **通知健康**：warn/error 级条目计数（与 P0-2④同口径，可复用）＋ 最近 N 条异常列表（字段：`name`/`platform`/`time`/`detail`），便于一眼发现推送问题 | 列表按 `time` 倒序；`detail` 为空时显示 `type` 或「—」；当前数据以 `cookie_warn`（level=warn）为主；点击可跳「日志」tab 的异常筛选（可选增强，非 P0 必做） |
| **P0-7** | **`renderDashboard()` 触发与渲染**：新增 `renderDashboard()`，在 `ld()` 末尾（与 `renderLive/renderPosts/renderLog` 并列）及 `show('dashboard')` 时调用；函数对 `hist/stat/rooms` 缺失做防御 | `ld()` 成功 → 渲染；切到仪表盘 tab → 渲染（不触发网络）；数据未载入时优雅降级（显示占位而非 JS 报错） |
| **P0-8** | **测试 `tests/test_dashboard.py`**（CI 跑 Python） | ① 结构断言：`monitor.html` 含 `id="view-dashboard"`、`onclick="show('dashboard')"`、`renderDashboard`、`computeStatsJS` 调用等；② 纯 Python 参考实现 `compute_dashboard_metrics(hist, stat, rooms, now_bj)` 计算 5 项 KPI + 7 天趋势 + 排行 + 平台分布 + 通知健康，对夹具数据（含「今日」边界、`level=warn`、多平台）验证口径正确 |

### P1（可选，本轮回否，写进 PRD 但不默认做）

| ID | 需求 | 说明 / 取舍 |
|---|---|---|
| P1-1 | **仪表盘自动定时刷新**：不依赖手动刷新，定时（如 60s）重算 KPI/趋势 | 与 `ld()` 的 90s 全量刷新不同，仪表盘可纯前端轻量重算（数据已载入）；但与 P0-1 健康条/90s 刷新可能重复触发，需协调。本轮回退（见 §五.6 待确认） |
| P1-2 | **更长周期趋势（30 天）**：在 7 天之外提供 30 天切换 | 受 `history.json` 上限 500 条约束，30 天可能不完整；`computeStatsJS(hist,30)` 直接可用，仅加 chip 切换 |
| P1-3 | **排行/趋势按平台下钻**：B站、抖音分别看 Top N 与趋势 | 复用 `computeStatsJS` 的 `base` 过滤（日志页已有按 `account` 过滤先例），加平台维度 |

### P2（可选，本轮回否）

| ID | 需求 | 说明 |
|---|---|---|
| P2-1 | **按账号 / 平台下钻详情页** | 从 KPI/排行点进对应日志或房间视图 |
| P2-2 | **数据导出（CSV/JSON）** | 导出当前聚合结果或原始 history，供复盘；与 `product_analysis.md` P1-7 合并 |
| P2-3 | **主播维度画像**（开播时段热力图、最佳开播时间） | 增值洞察，需较多历史，受 500 条约束 |

---

## 五、关键设计取舍（Key Design Trade-offs）

### 5.1 第 5 个 tab 如何接入 `show()`（精确改动点）

`show()` 当前有**两处**硬编码四 tab 索引，加第 5 个 tab 必须同步改两处，否则第 5 个按钮永远拿不到 `active` 高亮：

```js
// 改 1：views 字典加 dashboard
var views={'live':'view-live','posts':'view-posts','log':'view-log','config':'view-config','dashboard':'view-dashboard'};
// 改 2：tabs 索引数组加 'dashboard'（与 HTML 中 .tab 顺序一致）
tabs.forEach(function(b,i){b.classList.toggle('active',['live','posts','log','config','dashboard'][i]===t);});
```

- HTML 底部 `.tabbar` 在「配置」按钮后追加：
  ```html
  <button class="tab" onclick="show('dashboard')"><span class="ic">📊</span>仪表盘</button>
  ```
- HTML `<main>` 内在 `#view-config` `</section>` 后追加 `<section id="view-dashboard" class="view">…</section>`。
- `readViewParam()` 里 `dashboard` 分支当前是 `show('log')`，应改为 `show('dashboard')`（让 `monitor-dashboard.html` 壳页直达本 tab）。

> 风险提示：只加 `views` 不加索引数组，或数组与 HTML 按钮顺序错位，都会导致高亮错位——架构师务必两处并列修改并自测。

### 5.2 数据从哪来（全部复用 `ld()` 已载入全局变量，零新增请求）

| 仪表盘模块 | 数据源 | 处理方式 |
|---|---|---|
| 监控房间总数 | `rooms`（全局） | `rooms.length` |
| 当前直播中数 | `stat.rooms`（全局） | `filter(status==='live').length` |
| 今日开播次数 | `hist`（全局） | `filter(type==='live_on' && time前10位===今日北京时间)` |
| 通知异常数 | `hist` | `filter(level==='warn'||'error')` |
| 数据新鲜度 | `stat.updated` | `calcFreshness()`（P0-1 复用） |
| 开播趋势 | `hist` | `computeStatsJS(hist,7).live_on` |
| 开播排行 | `hist` | 按 `name` 聚合 `type==='live_on'` |
| 平台分布 | `rooms` + `hist` | `rooms` 按 `platform` 计数；`hist` 按 `platform` 分桶 `live_on` |

- **不调 `ld()`、不 `fetch`**：`renderDashboard()` 只读已载入的全局变量，与 P0-4 搜索「不触碰健康条/定时刷新」原则一致。
- **与现有 `.overview` 顶栏 3 卡的关系**：顶栏（直播中/监控房间/新作品号）常驻、跨 tab、瞬时可见，是「极小快照」；仪表盘 tab 是「更全的聚合」（多了今日开播、通知异常、趋势、排行、平台分布、新鲜度汇总）。两者口径互补不冲突，顶栏保留不动。

### 5.3 图表用 CSS/SVG，不引入图表库（零依赖约束）

- **开播趋势条形**：直接复用日志页 `renderStats()` 的范式——`.spark`（flex 容器，`align-items:flex-end`）内放若干 `.bar`（高度按 `值/最大值*100%`，背景用 `var(--live)`），无任何库。
- **平台分布比例条**：两个 `.bar` 按房间数比例设 `flex` 或宽度百分比，B站用 `var(--bili)`、抖音用 `var(--dy)`。
- **开播排行**：纯列表（名次 + 名称 + 次数 + 可选细条形），无需图形库。
- 约束红线：**禁止引入 Chart.js / ECharts / D3 等**；若需更复杂图形用内联 `<svg>` 手绘（本 P0 不需要）。

### 5.4 KPI 口径定义（明确、可测）

| KPI | 口径 | 边界说明 |
|---|---|---|
| 监控房间总数 | `rooms.length`（当前 10） | 含 B站/抖音；与顶栏「监控房间」一致 |
| 当前直播中数 | `stat.rooms.filter(r=>r.status==='live').length`（当前 `dy571881` 在播→1） | 实时性取决于 `status.json` 新鲜度（见 P0-1） |
| **今日开播次数** | `hist` 中 `type==='live_on'` 且 `l.time.substring(0,10) === 今日北京时间(YYYY-MM-DD)` | **「今日」按北京时间**，用 `bjNow()` 取年/月/日（与 `computeStatsJS` 一致），**严禁用本地时区 `new Date()`**；避免差 8 小时把昨天/今天算错 |
| 通知异常数 | `hist.filter(l=> l.level==='warn' || l.level==='error').length` | 当前数据：7 条 `cookie_warn`（level=warn）；schema 允许 `error`。若某条目缺 `level` 但 `type` 为 `error`/`cookie_warn`，按 `type` 兜底计入（保证不漏） |
| 数据新鲜度 | `calcFreshness()` → `{state,label}` | 四态 ok/warn/stale/loadfail，阈值 ≤10min 绿 / 10–30min 黄 / >30min 红（复用 P0-1） |
| **开播次数（通用）** | 一律按 `type==='live_on'` 计 | 与 `product_analysis.md` P0-7「开播」语义一致；`live_off` 是下播、不计入开播 |

### 5.5 与 P0-1 健康条的关系（仪表盘汇总 vs 健康条实时）

- **P0-1 健康条（`#healthBar`）**：常驻跨 tab、实时脉冲，单一职责 = **数据新鲜度四态告警**（绿/黄/红/灰），任何 `ld()` 后刷新，是「监控还活着吗」的即时信号。
- **P0-7 仪表盘**：进入 tab 才渲染的**聚合快照**，把「房间规模 / 在播 / 今日开播 / 排行 / 平台 / 通知健康 / 新鲜度」合到一屏；新鲜度只是其中一张 KPI 卡，**直接复用 `calcFreshness()`** 而非另算。
- **二者不重复、不冲突**：健康条负责「实时可信」的告警，仪表盘负责「整体态势」的浏览；仪表盘的 KPI 新鲜度卡与健康条同源，但前者是总览的一部分、后者是全局常驻告警。架构师无需为仪表盘重写新鲜度逻辑，调用 `calcFreshness()` 即可。

### 5.6 计算辅助（供架构师参考，纯前端）

```js
// 今日北京时间 YYYY-MM-DD（复用 bjNow 思路，谨防本地时区）
function todayBJ(){
  var d=bjNow(); // 已折算为北京时间墙钟的 Date
  function p(n){return (n<10?'0':'')+n;}
  return d.getFullYear()+'-'+p(d.getMonth()+1)+'-'+p(d.getDate());
}
// 今日开播次数
function liveOnToday(hist){
  var t=todayBJ();
  return hist.filter(function(l){return (l.type||l.status)==='live_on' && (l.time||'').substring(0,10)===t;}).length;
}
// 通知异常计数（level 优先，type 兜底）
function notifyAnomalyCount(hist){
  return hist.filter(function(l){
    var lv=l.level, tp=l.type||l.status;
    return lv==='warn'||lv==='error'||tp==='error'||tp==='cookie_warn';
  }).length;
}
// 开播排行 Top N
function liveOnRank(hist, n){
  var m={};
  hist.forEach(function(l){ if((l.type||l.status)==='live_on'){ m[l.name]=(m[l.name]||0)+1; } });
  return Object.keys(m).map(function(k){return {name:k,count:m[k]};})
    .sort(function(a,b){return b.count-a.count;}).slice(0,n);
}
```

---

## 六、UI 设计草稿（基础布局，与现有四 tab 风格一致）

```
┌──────────────────────────────────────────────────────────┐
│ 📊 仪表盘                                                    │  ← panel-head（同 .panel-head / h2）
├──────────────────────────────────────────────────────────┤
│ [监控房间 10] [直播中 1] [今日开播 K] [通知异常 7] [新鲜度💚] │  ← 5 张 KPI 卡（复用 .stat-card / .ostat 视觉）
├──────────────────────────────────────────────────────────┤
│ 开播趋势（近7天）                                            │
│  07-05 ▁  07-06 ▂  07-07 ▃  … 07-11 ▅  (CSS 条形)          │  ← 复用 .spark/.bar
├──────────────────────────────────────────────────────────┤
│ 主播开播排行 Top5            │ 平台分布                      │
│ 1. 披萨解说 …… 12           │ B站  1 (10%) ▓░░░             │
│ 2. 小猪装机 …… 9            │ 抖音  9 (90%) ▓▓▓▓▓▓▓▓        │
│ …                            │                               │
├──────────────────────────────────────────────────────────┤
│ 通知健康  ⚠ 7 条异常                                        │
│  • 小猪装机 · douyin · 07-10 21:52 · cookie 风控…          │  ← 最近 N 条（name/platform/time/detail）
│  • …                                                        │
└──────────────────────────────────────────────────────────┘
```

- 整体容器复用 `.view` + `.panel-head` + `max-width:760px` 布局；卡片复用 `.stat-card` / `.room` 视觉变量（`--card`/`--line`/`--bili`/`--dy`/`--live`/`--yellow`）。
- KPI 卡网格：用 `.logstats` 的 `grid-template-columns:repeat(3,1fr)` 或 `repeat(5,1fr)`（窄屏回退 2–3 列），保证移动端不溢出。
- 异常列表项复用 `.log-item` / `.log-dot.warn` / `.log-dot.err` 配色，与日志页视觉统一。

---

## 七、待确认问题（Open Questions）

1. **仪表盘 tab 放哪个位置？**（建议：**放第 5 个 / 最右**，或作为默认首屏）
   现状 tab 顺序「直播 / 新作 / 日志 / 配置」。仪表盘作为总览，理想位置是**第一个**（打开即看全局）；但改动首页默认 `active` 与 `ld()` 后的 `readViewParam()` 默认视图需同步。请主理人拍板：① 追加到第 5 位（最右）；② 提到第 1 位作为默认首屏（需把 `#view-live` 的 `active` 与 `show()` 默认 `t` 调整）。

2. **是否本轮回退「自动刷新」（P1-1）？**（建议：**回退**）
   仪表盘数据来自 `ld()`，而 `ld()` 已有 90s 定时全量刷新并会重渲染各 tab。若仪表盘也加独立 60s 定时器，可能与 90s 刷新重复触发、且浪费计算。建议：本轮回退自动刷新，直接**复用 `ld()` 的 90s 刷新**即可（切到 tab 时也渲染一次）。请确认是否接受「无独立定时器、跟随 `ld()` 刷新节奏」。

3. **Top N 取几？**（默认建议 **5**）
   开播排行默认 Top 5；当前 `live_on` 总量 71 条、覆盖主播有限，Top 5 足够。若名单扩大可提到 10。请确认 N=5 还是其他。

4. **「今日开播次数」与现存 `.overview` 顶栏是否重复呈现？**（建议：不重复，互补）
   顶栏已有「直播中 / 监控房间 / 新作品号」3 卡并常驻；仪表盘新增「今日开播 / 通知异常 / 新鲜度」等更丰富的卡。是否要把顶栏也扩展、还是保持顶栏现状仅由仪表盘承担更全口径？请确认保持顶栏不动（推荐）。

5. **通知异常数口径：按 `level` 还是按 `type`？**（默认：level 优先、type 兜底，见 §五.4）
   当前数据 `cookie_warn` 的 `level=warn`；若未来出现无 `level` 的 `error` 条目，按 `type` 兜底计入，确保不漏。请确认该兜底规则可接受。

6. **异常列表是否可点击跳日志 tab 的异常筛选？**（建议：P0 仅展示，跳转留 P1）
   P0-6 仅陈列最近 N 条异常；点击跳转到「日志 tab + 异常筛选」属于交互增强，建议本轮回退，避免与 `logState` 耦合放大改动面。

---

*—— 简单 PRD 结束。仅此一份文件，不改动代码、不提交 git，由主理人统一编排与提交。*
