# P0-4 列表批量搜索 · 简单 PRD（本轮聚焦「纯前端文本搜索」）

> 产品经理：许清楚（Alice）｜ 模块：blive-monitor 前端 `monitor.html`
> 关联：阶段 2（列表管理）｜ 上游：`docs/product_analysis.md` P0-4
> 范围：本轮**只做 P0 纯前端文本搜索**，批量操作 / 持久化 / 状态筛选回退为 P1/P2
> 语言：中文

---

## 一、项目信息

| 项 | 内容 |
|---|---|
| 原始需求复述 | 直播 tab 与新作 tab 的房间/抖音号列表只靠平台 chip 过滤，无文本搜索；名单增长（当前已 10 个，未来更多）后无法快速定位某个主播/抖音号。需在两个列表加入文本搜索。 |
| 全局状态（已核对 L317） | `var stat=null,rooms=[],hist=[],postRooms=[],postTrack={},fl='all';` |
| 改动文件 | `monitor.html`（加搜索框 HTML + 全局 `q` + 在 `renderLive`/`renderPosts` 内应用过滤 + 输入事件）；可加少量 CSS；新增 `tests/test_list_search.py` |
| 不改动 | 后端 / Python 检测脚本；既有 chip 平台筛选；P0-1 健康条与定时刷新（`ld()`） |
| 技术栈 | 纯静态前端，原生 HTML/JS（与仓库现有 `monitor.html` 一致，无框架） |

---

## 二、产品目标（Product Goals）

1. **快速定位**：用户能在直播/新作列表中按名字或 ID 即时搜索，10+ 乃至百级名单下也能秒级找到目标主播/抖音号。
2. **筛选可叠加**：文本搜索与既有平台 chip（全部/B站/抖音）**逻辑 AND**，选「抖音」再搜「小猪」只命中抖音里叫小猪的，不串台。
3. **零干扰**：搜索是纯前端对已加载数据的即时重渲染，不触发任何网络请求、不触碰健康条、不影响定时刷新；清空即恢复。

---

## 三、用户故事（User Stories）

- 作为**多账号监控用户**，我想在直播列表里输入主播名/房间号直接过滤，以便从 10+ 房间中快速找到我想看的那一个。
- 作为**抖音新作监控用户**，我想按备注名/抖音号/主页昵称搜索，以便快速定位某个抖音号（昵称来自 `postTrack['douyin_'+id].nickname`）。
- 作为**已筛选平台的用户**，我选了「哔哩哔哩」后搜索，期望结果只在 B 站内匹配，不被抖音账号污染。
- 作为**搜索无结果的用户**，我希望看到「未找到匹配「xxx」」而非「暂无监控房间」，以免误以为自己没在监控任何房间。

---

## 四、需求池（Requirements Pool）

### P0（必须有，纯前端）

| ID | 需求 | 验收标准 |
|---|---|---|
| P0-1 | **直播 tab 文本搜索**：在 chip 旁（panel-head 下新增一行 `.searchbar`）加搜索框（输入框 + 清除 ✕ 按钮），输入即按 `name`/`id` 做**大小写不敏感子串匹配**过滤 `rooms` | `oninput` 实时过滤；匹配 `r.name` 与 `String(r.id)`；`r.name` 为空时仍能按 id 命中 |
| P0-2 | **新作 tab 文本搜索**：`#view-posts` 同理加搜索框，按 `name`/`id`/`nickname` 过滤 `postRooms` | 匹配 `r.name`、`String(r.id)`、`postTrack['douyin_'+id].nickname`；三者任一命中即显示 |
| P0-3 | **搜索与平台筛选叠加（AND）**：选平台 chip 后搜索，结果同时满足平台过滤与文本过滤 | `fil('douyin')` + 搜「小猪」→ 仅抖音内匹配；`fl` 与 `q` 在 `renderLive`/`renderPosts` 内先后 `filter`，不互相覆盖 |
| P0-4 | **搜索态空结果文案**：过滤后为空且 `q` 非空时显示「未找到匹配「xxx」」 | 不显示「暂无监控房间」/「暂无监控的抖音号」造成误解；与「列表真为空」状态区分 |
| P0-5 | **全局 `q` + 输入即重渲染**：搜索词存全局 `q`（与 `fl` 并列）；清空恢复全部 | 全局 `var q='';`；清除 ✕ 把 `q` 置空并清空输入框、`renderLive()`/`renderPosts()` 恢复全部（仍受当前 `fl` 约束）；`ld()` 不重置 `q`，故 90s 定时刷新后搜索词仍保留 |
| P0-6 | **不触碰健康条 / 定时刷新**：搜索只重渲染列表 body，不调用 `ld()`、不重算新鲜度 | `renderLive()` 改完仍只写 `#liveBody`；`renderPosts()` 只写 `#postsBody`；`#healthBar` 不受影响；搜索无网络请求 |
| P0-7 | **测试 `tests/test_list_search.py`**（CI 跑 Python） | ① 结构断言：`monitor.html` 含 `id="liveSearch"`、`id="postsSearch"`、全局 `q`、`未找到匹配` 模板；② 纯 Python 参考实现 `match_text(haystacks, q)` 做大小写不敏感子串，对房间/抖音号夹具数据验证匹配与 AND-`fl` 行为 |

### P1（可选，本轮回否，写进 PRD 但不默认做）

| ID | 需求 | 说明 |
|---|---|---|
| P1-1 | **批量操作**：多选 + 批量移除监控 | 涉及选择态、checkbox、批量 GitHub API 调用，改动较大；建议独立成轮 |
| P1-2 | **筛选态持久化**：刷新/URL 参数记住搜索词 | `ld()` 已不重置 `q`（90s 内保留）；跨整页 reload 需 URL `?q=` 或 localStorage |

### P2（可选，本轮回否）

| ID | 需求 | 说明 |
|---|---|---|
| P2-1 | **按状态筛选**：直播中/未开播 额外 chip | 在现有平台 chip 旁再加一组状态 chip，叠加规则同 `q`（AND） |

---

## 五、关键设计取舍（Key Design Trade-offs）

### 5.1 搜索词 `q` 与现有 `fl` 如何叠加

- **新增全局变量**：在 L317 处改为 `var stat=null,rooms=[],hist=[],postRooms=[],postTrack={},fl='all',q='';`。
- **叠加方式 = 顺序 filter（AND）**：
  - `renderLive()`：先按 `fl` 过滤平台（`fl==='bilibili'`/`'douyin'`），再对结果按 `q` 过滤 `name`/`id`；两个 filter 先后执行、取交集。
  - `renderPosts()`：直接对 `postRooms` 按 `q` 过滤 `name`/`id`/`nickname`（新作 tab 无平台 chip，不涉及 `fl`）。
- **为什么 AND 而非覆盖**：用户心智是「先选平台再搜名」，覆盖会让平台选择失效、结果串台；AND 符合既有 `fil()` 与日志模块 `applyFilters()` 的多条件叠加范式（L467-499）。
- **`ld()` 不重置 `q`**：`ld()` 只刷新 `rooms`/`postRooms` 数据源，刷新后调 `renderLive()`/`renderPosts()` 仍带 `q`，搜索词在 90s 定时刷新后保留——天然满足「刷新不丢搜索」的轻量持久化（完整跨 reload 持久化见 P1-2）。

### 5.2 匹配字段与大小写

- **大小写不敏感子串**：统一 `hay.toLowerCase().includes(q.toLowerCase())`，用户输入「XIAOZHU」「小猪」「XiaoZhu」均命中「小猪」。
- **直播匹配字段**：`r.name`（可能为空，显示时回退 `id`）与 `String(r.id)`。二者任一命中即显示，避免「只填了 id 没填名」的房间搜不到。
- **新作匹配字段**：`r.name`、`String(r.id)`、`(postTrack['douyin_'+id]||{}).nickname`。因显示名优先级为 `name > nickname > id`（L407），搜索须覆盖三者，用户用备注名/抖音号/真实昵称任一种都能找到。

### 5.3 搜索框位置与样式

- **位置**：每个 tab 的 `.panel-head` 下新增一行 `.searchbar`（`<div class="searchbar">…</div>`），不挤占标题与 chip 的 `space-between` 布局。
  - 直播：`#view-live` 的 `panel-head`（L179-186）下方、`#addWrap`（L187）上方插入。
  - 新作：`#view-posts` 的 `panel-head`（L204）下方、`#postAddWrap`（L205）上方插入。
- **结构**（每 tab 一份）：
  ```html
  <div class="searchbar">
    <input id="liveSearch" class="ainput" placeholder="搜索 名称/ID…" autocomplete="off" oninput="onLiveSearch()">
    <button class="rmbtn" id="liveClear" style="display:none" onclick="clearLiveSearch()">✕</button>
  </div>
  ```
- **样式复用**：输入框用既有 `.ainput`（L105，已含聚焦描边）；清除按钮复用 `.rmbtn`（L110-111，圆角 ✕）。新增少量 CSS：`.searchbar{display:flex;gap:8px;margin:0 2px 10px;position:relative}`、清除按钮 `flex-shrink:0`。整体视觉与现有添加表单（`.addform`/`.ainput`）一致，不引入新设计语言。
- **✕ 显隐**：仅当 `q` 非空时显示清除按钮；点击置空 `q`、清空输入框并 `renderLive()`/`renderPosts()`。

### 5.4 空结果文案（避免误解）

| 场景 | 现状（L353/L365/L400） | 本轮目标 |
|---|---|---|
| 列表真为空（无监控） | 直播「📭 暂无监控房间」/ 新作「⌛ 暂无监控的抖音号」 | **保持不变** |
| 平台过滤后为空（无 `q`） | 直播「该平台暂无房间」 | **保持不变** |
| 搜索后为空（有 `q`） | （误显示上面的「暂无…」） | **改为**「未找到匹配「xxx」」，`xxx` = 当前搜索词 |

- 实现：在 `renderLive`/`renderPosts` 的最终空分支，判断 `q.trim()!==''` → 渲染 `未找到匹配「${e(q)}」`；否则走原空状态文案。这样既区分「真没数据」与「搜不到」，也不破坏无监控时的提示。

### 5.5 如何触发重渲染且不影响 P0-1 健康条 / 定时刷新

- **搜索输入事件**（`onLiveSearch`/`onPostsSearch`）：仅 `q=this.value.trim()` → `renderLive()` / `renderPosts()`。
- **不调用 `ld()`**：`ld()` 会重新 `fetch` 各 JSON 并调用 `renderHealthBar(calcFreshness())` 刷新健康条（L1126-1128）。搜索若调 `ld()` 会无谓请求网络、可能闪烁健康条。**严禁在搜索路径调用 `ld()`。**
- **健康条隔离**：`renderLive`/`renderPosts` 只改写 `#liveBody`/`#postsBody` 的 `innerHTML`，与 `#healthBar` 零耦合；P0-1 的四态渲染逻辑完全不受影响。
- **定时刷新兼容**：`ld()` 每 90s 跑一次，末尾 `renderLive()`/`renderPosts()` 已带 `q` 过滤，搜索词跨刷新保留；新拉到的 `rooms`/`postRooms` 也会立即按当前 `q` 过滤显示。
- **回车即过滤**：用 `oninput`（输入即过滤），无需额外监听回车；满足「输入即过滤 / 回车也过滤」的体验要求。

---

## 六、待确认问题（Open Questions）

1. **是否本轮回退批量操作？**（建议：**回退**，列为 P1-1 独立成轮）
   批量多选 + 批量移除涉及选择态/checkbox/批量 GitHub API 调用，与「纯前端搜索」正交，混入会放大本轮改动面与回归风险。建议本轮只交付搜索，批量操作后续单独排期。

2. **是否要防抖（debounce）？**（建议：**本轮回否**）
   当前名单 10 个、`oninput` 直接 `filter` 开销极小，实时过滤足够顺滑。若未来名单到百级，可加 150ms 防抖；本轮保持简单，不加。请主理人确认是否需要预埋防抖钩子。

3. **搜索框跨 tab 共用一个 `q` 还是各 tab 独立？**（当前决定：**单全局 `q`，两 tab 各一个输入框但共享 `q`**）
   需求明确「搜索词存为全局 `q`（与 `fl` 并列）」，故采用单一 `q`：直播输入框与新作输入框是**两个 DOM 元素**，但都读写同一全局 `q`；切 tab 时把对方输入框的值同步为 `q`。后果：在直播 tab 搜「bili」后切到新作 tab，新作也会按「bili」过滤（新作全抖音，通常无结果）。若希望两 tab 搜索互不干扰，则需改为 `qLive`/`qPosts` 两个变量——请主理人确认沿用单 `q` 还是拆分。

---

*—— 简单 PRD 结束。仅此一份文件，不改动代码、不提交 git。*
