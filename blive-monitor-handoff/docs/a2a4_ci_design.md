# A2/A4 CI 侧打通设计文档（dispatch_event + 分组投递 + 模板渲染）

> 阶段：阶段二 A2/A4 的 **CI 侧消费**（前端 schema 已在 2b 落库，本任务只改 CI Python）
> 作者：高见远（架构师 Bob）
> 约束：**只改 CI 侧 Python**（`push_utils.py` / `check_status.py` / `check_new_posts.py` / `auto_summary.py`），**不改 `monitor.html`**；不动现有静默拦截（A3）与单通道降级路径；**向后兼容是硬约束**（无 `routes`/`channels` 时行为必须逐字节一致）。
> 本文件为设计文档，**不含实现代码**，只给签名、逻辑与契约，交给工程师落地。

---

## 1. 实现方案概述

**目标**：让 CI 推送「按路由选通道、按模板渲染」，同时保证 legacy 单通道配置行为不变。

### 1.1 三件核心改动

1. **统一入口 `push_utils.dispatch_event(cfg_all, ctx, title, desp) -> SendResult`**
   - 内部 `ch = resolve_channel(cfg_all, ctx)`（已存在于 `common.py`，与 JS 逐字节一致）。
   - `pcfg = channel_to_push_cfg(ch)`（新增 flatten：把 `{id,type,fields}` 压成 `{type, **fields}`；legacy 扁平 dict 原样透传）。
   - `return dispatch_push(pcfg, title, desp)`（复用既有重试/分类/结构化结果）。
   - 无 `routes`/`channels` 时 `resolve_channel` 退化返回 `cfg['push']`（扁平）→ `dispatch_event` 与当前 `dispatch_push(load_push_cfg(raw), ...)` 等价。

2. **分组投递（仅 `check_status` 的开播事件聚合；新作品按房间路由）**
   - `live_on`：遍历 `newly_live`，每房间构造 `ctx={platform,tag,event:'live_on'}` → `resolve_channel` → 按 `ch.id` 分组；**同通道房间合为一条消息**（各自用模板渲染正文后拼接），不同通道各发一条。
   - `new_post`：每房间独立构造 `ctx={platform,tag,event:'new_post'}` → `dispatch_event` 路由到其通道（**不做跨房间聚合**，以保 legacy 逐房间行为）。
   - `summary`：`auto_summary` 调 `dispatch_event(cfg_all, {event:'summary'}, title, desp)`，无 summary 路由时退化默认/legacy 通道。

3. **模板渲染（A4）**
   - 仅当 `cfg_all['templates'][event]` 存在时，用 `render_template(tpl, tpl_ctx)` 渲染 **正文（desp）** 替代 `format_push_desp`；否则沿用 `format_push_desp`（legacy 行为）。
   - **标题维持现状**（`format_push_title` 单房间 / `🔴 N位主播开播：names` 聚合），不模板化（理由与替代方案见 §5）。

### 1.2 向后兼容保证（硬约束落地方式）

| 维度 | legacy（无 `channels`/`routes`，仅 `push`） | multi-channel（有 `channels`/`routes`） |
|---|---|---|
| `resolve_channel` | 退化返回 `cfg['push']` | 按 routes 匹配 → 具体通道 |
| 消息构造 | 复用 `format_push_title`/`format_push_desp`，**无模板** | 同函数；仅当 `templates[event]` 存在才替换正文 |
| `check_status` 聚合 | 全部房间 = 1 组 → 1 条聚合消息（与当前逐字节一致） | 按通道分组，每组内聚合 |
| `check_new_posts` | 每房间独立 `dispatch_event`（= 当前每房间 `dispatch_push`） | 每房间路由到其通道，仍独立发送 |
| `auto_summary` | `dispatch_event` 退化到 legacy 通道 | 可经 `{event:'summary'}` 路由 |

**关键**：legacy 配置**没有 `templates`**，因此正文永远走 `format_push_desp`；且单通道下分组只产生 1 组 = 全量房间 → 与当前 monolithic 代码产出的 `title`/`desp` 完全相同。`dispatch_event` 退化为 `dispatch_push(legacy_push_cfg, ...)`。集成测试（§6）断言此等价性。

---

## 2. 文件列表与改动点

| 文件 | 改动 | 优先级 |
|---|---|---|
| `push_utils.py` | 新增 `channel_to_push_cfg(ch) -> Dict` 与 `dispatch_event(cfg_all, ctx, title, desp) -> SendResult`；复用已有 `resolve_channel`/`render_template`/`dispatch_push`/`load_push_cfg`。**不改**现有任何函数。 | P0 |
| `check_status.py` | 改造 `load_config()` 额外返回 `cfg_all`（BLIVE_CONFIG 解析后的完整 dict）；改造 Step 3 通知段：遍历房间按通道分组（live_on 组内聚合 + 可选模板正文）→ 调 `dispatch_event`。保留静默拦截（A3）与 `dedup_record` 房间级去重原逻辑。 | P0 |
| `check_new_posts.py` | 改造通知段：把 `dispatch_push(push_cfg, title, desp)` 改为 `dispatch_event(cfg_all, ctx, title, desp)`（`ctx={platform:'douyin', tag:primary_tag(room), event:'new_post'}`）；`cfg_all` 由本文件解析 BLIVE_CONFIG 得到。其余（静默、去重、错误日志）零改动。 | P0 |
| `auto_summary.py` | 把 `push_cfg = load_push_cfg(raw); dispatch_push(push_cfg, title, desp)` 改为：先 `ch = resolve_channel(cfg_all, {event:'summary'})`；`pcfg = channel_to_push_cfg(ch)`；无有效 `type` 则 `sys.exit(0)`；否则 `dispatch_event(cfg_all, {event:'summary'}, title, desp)`。 | P1 |
| `tests/test_a2a4_ci.py` | **新增**：`channel_to_push_cfg` / `dispatch_event` 单测 + `check_status` 集成（legacy 不变 / 多通道分组 / tag 匹配 / 模板渲染 / 静默 / 去重）+ 跨语言对照回归。 | P0 |

> 注：本任务**不触及** `common.py`（`resolve_channel`/`render_template` 已是确定实现，与 JS 逐字节一致，仅消费）；不触及 `monitor.html`；不触及 A3 静默逻辑与单通道降级路径（`resolve_channel` 退化分支即降级路径，保留）。

---

## 3. 任务分解（有序 + 依赖，标 P0/P1）

| Task | 名称 | 源文件 | 依赖 | 优先级 |
|---|---|---|---|---|
| **T01** | `push_utils` 新增 `channel_to_push_cfg` + `dispatch_event` | `push_utils.py` | 无（依赖既有 `common.resolve_channel`/`render_template`/`dispatch_push`） | P0 |
| **T02** | `check_status` 通知段改造（分组投递 + 可选模板正文 + `dispatch_event` + 保留 legacy/A3/去重） | `check_status.py` | T01 | P0 |
| **T03** | `check_new_posts` 通知段改造（per-post `dispatch_event` 路由） | `check_new_posts.py` | T01 | P0 |
| **T04** | `auto_summary` 改用 `dispatch_event`（summary 路由） | `auto_summary.py` | T01 | P1 |
| **T05** | 新增 `tests/test_a2a4_ci.py`（单测 + 集成 + 跨语言对照） | `tests/test_a2a4_ci.py` | T01, T02, T03（T04 可选补） | P0 |

**执行顺序建议**：T01 →（T02 ∥ T03）→ T04 → T05（T05 可随 T02/T03 增量补充）。

> 设计原则：每个任务是一个**独立可测**的模块改造；T01 是基础能力，T02/T03 是两大通知源接入，T04 是摘要收尾，T05 用 monkeypatch 锁住 legacy 等价性与多通道分组行为。

---

## 4. 共享约定（工程师必须遵守）

### 4.1 `channel_to_push_cfg` flatten 规则
- 输入 `ch` 来自 `resolve_channel`，可能是两种形状：
  - 新通道：`{"id": "c1", "type": "wecom", "fields": {"webhook": "..."}}`
  - legacy 退化：`cfg['push']` 即扁平 `{"type": "wecom", "webhook": "..."}`
- 输出（供 `dispatch_push`）：
  - 含 `fields` → `{"type": ch["type"], **(ch.get("fields") or {})}`
  - 不含 `fields`（已扁平）→ 原样 `dict(ch)` 透传
- 空 `ch`（`{}`）→ 返回 `{}`（`dispatch_push` 内部判空返回失败 `SendResult`，不抛）。

### 4.2 `ctx` 字段约定
- **路由维度**（`resolve_channel` 消费）：`{platform, tag, event}`
  - `platform`：`'bilibili'` / `'douyin'`（房间原始平台键）。
  - `event`：`'live_on'` / `'new_post'` / `'summary'`。
  - `tag`：见 §5「tag 匹配语义」主理人默认（当前 = `room['tags'][0]` 标量；无 tag 则 `None`）。
- **模板维度**（`render_template` 消费，仅渲染正文时用）：`{name, title, platform, time, url}`
  - `name`：房间显示名；`title`：直播标题（开播事件）；`platform`：**原始键**（`'bilibili'`/`'douyin'`）；`time`：检测时间（`bjnow().strftime("%Y-%m-%d %H:%M:%S")`）；`url`：直播间链接。
  - 建议同时注入 `platform_name`（中文标签 `'B站'`/`'抖音'`）作为可选占位符，便于模板写「{platform_name}」而不暴露原始键；缺省 `{platform}` 渲染原始键。

### 4.3 tag 匹配语义
- `resolve_channel` 内部用**标量相等**（`m.tag !== tag`），与 JS `resolveChannel` 逐字节一致。
- 主理人默认：`ctx['tag'] = (room.get('tags') or [])[0]`（房间首个 tag，标量）；多 tag 房间按「主 tag」路由。
- 替代方案（若需「房间 tags 包含 match.tag」）：把 `ctx['tag']` 传为 **list**，并给 `common.resolve_channel` 增加 list 包含分支（`isinstance(tag, list) and m.tag in tag`）——此为 A 方案之外的小幅扩展，需同步 `monitor.html` JS（本任务范围外，见 §5）。

### 4.4 模板占位符集合（A4 契约）
- 官方集合：`{name}` `{title}` `{platform}` `{time}` `{url}`（与 `test_phase2_a4_templates.py` 一致）。
- **不含** `{duration}`（主理人拍板 #4，UI 与引擎均不强制扩展；`render_template` 为通用正则，若 ctx 误带 `{duration}` 也会替换，但配置层不鼓励）。
- 缺字段保留原占位符不崩（`render_template` 既有行为）。

### 4.5 去重维度
- 维持**房间级去重**（沿用 `notify_dedup` 既有 `live:{platform}_{rid}` / `post:{sec_uid}:count:{n}` 键）。
- 理由：路由结果是**确定性单通道**（每个房间每事件只解析到一个通道），同房间不会在同一次 run 发往多通道，故无需 `(房间, 通道)` 复合去重。分组发送成功后，对组内每房间 `dedup_record`（失败不标记，下一轮可补推）。

### 4.6 「未配置通道」守卫（保 legacy 跳过语义）
- 当前 `check_status` 有 `elif newly_live and push_cfg:` 分支：无推送配置时仅 `logger.info("未配置推送渠道")` 并跳过，**不报错**。
- 统一 `dispatch_event` 路径下，若某 `ctx` 解析出的通道 `channel_to_push_cfg(ch)` 无 `type`（即 `cfg` 既无 `channels`/`routes` 也无 `push`），**不得**调用发送，应等价于「未配置」：记 `push='no_sendkey'` 并 `logger.info` 跳过，避免产生 `ok=False` 的伪失败 error 日志。
- 实现建议：分组/路由前先算 `pcfg = channel_to_push_cfg(resolve_channel(cfg_all, ctx))`；`if not pcfg or not pcfg.get("type"):` → 按未配置处理（与现 `no_sendkey` 分支一致）。

### 4.7 错误/日志约定
- 沿用 `dispatch_push` 返回的 `SendResult`：`res.ok` / `res.attempts` / `res.last_error`。
- 失败写 `error` 级统一日志（含 `channel` + `last_error`），下一轮 CI 可补推——与当前 check_status/check_new_posts 错误处理结构一致。
- 静默拦截（`should_skip_by_silence`）位置不变：在所有 `dispatch_event` 之前、`newly_live`/`notify` 标记之后，把 `queued` 改 `silenced`。

---

## 5. 待明确事项（每项给「主理人默认」）

> 以下为设计拍板点；已给推荐默认，若与主理人意图冲突请回传修正，工程师按默认先行。

### Q1. 标题是否模板化？模板作用于标题还是正文？
- **现状**：A4 `templates` schema 形如 `live_on:'🔴 {name} 开播了：{title}'`、`new_post:'🆕 {name} 发布了新作品'`——带 emoji 且简短，形态接近「标题」。但任务简报 design 要点写「**正文**用 render_template(...)` 拼装」。
- **主理人默认**：**模板渲染正文（desp）；标题维持现状**（`format_push_title` 单房间 / `🔴 N位主播开播：names` 聚合）。即按简报字面执行——`desp = render_template(templates[event], tpl_ctx)`，组内多房间各自渲染后拼接。
- **副作用提示**：单房间通知将出现「标题 `🔴 X 开播了！` + 正文 `🔴 X 开播了：今晚联动`」的 emoji 前缀重复。若主理人认为冗余，改选替代方案：**模板渲染标题**（desp 保留富格式 `format_push_desp`），信息更丰富且不重复。两者均为小改，本任务先按默认（渲染正文）实现，模板字符串所有权在配置层，可随时调。
- **聚合标题**：多房间组标题固定用 legacy `🔴 N位主播开播：{names}`（模板为单房间形态，无法聚合），不参与模板。

### Q2. tag 匹配：标量主 tag 还是 list 包含？
- **主理人默认**：`ctx.tag = room['tags'][0]`（标量，相等匹配），`common.resolve_channel` **零改动**，与 JS 逐字节一致、既有 `test_phase2_a2_routes.py` 标量用例全绿。
- **替代（意图更贴合「房间 tags 包含 match.tag」）**：`ctx.tag` 传 list + `resolve_channel` 增加包含分支（约 2 行），多 tag 房间可命中任意 tag 路由；代价是 `monitor.html` JS 需同步（本任务范围外，记为后续 action）。
- **当前 prod `rooms.json` 无 `tags` 字段**，两种方案均向前兼容；路由仅在配置含 `tags` 后生效。

### Q3. 去重维度：房间级还是 (房间,通道) 复合？
- **主理人默认**：**房间级**（沿用现有键）。路由确定单通道，无需复合键（见 §4.5）。

### Q4. 无 `routes`/`channels` 时是否仍走 `dispatch_event`？
- **主理人默认**：**统一走 `dispatch_event`**（不保留独立 legacy 分支）。`resolve_channel` 退化返回 `cfg['push']` → `channel_to_push_cfg` 透传 → `dispatch_push`，与当前 `load_push_cfg`+`dispatch_push` 等价；legacy 无 `templates` → 正文走 `format_push_desp`，逐字节一致。由 §6 集成测试锁死等价性。
- **替代（零分歧风险但重复代码）**：保留独立 legacy 分支（当前代码原样），仅 `channels`/`routes` 存在时走新分组路径。若主理人要求「legacy 代码路径一字不改」，选此；否则选默认（DRY + 测试护航）。

### Q5. `new_post` 是否跨房间聚合？
- **主理人默认**：**不聚合**，每新作品独立 `dispatch_event` 路由到其通道（与当前 per-room 行为一致，保 legacy 逐房间等价）。
- **替代**：同通道新作品合为一条（更贴近 design 要点「分组投递」 generality）。代价：legacy 单通道下行为从「每作品一条」变为「一次 run 聚合一条」，违反逐字节一致——故不默认。

### Q6. summary 路由
- **主理人默认**：`auto_summary` 调 `dispatch_event(cfg_all, {event:'summary'}, title, desp)`；无 `{event:'summary'}` 路由时 `resolve_channel` 退化默认/legacy 通道，与现行为一致。可在 `BLIVE_CONFIG.routes` 增 `{match:{event:'summary'}, channelId:'cX'}` 定向摘要通道（可选增强）。

### Q7. `check_new_posts` 的 `ctx.tag` 来源
- **主理人默认**：与 `check_status` 一致取 `room['tags'][0]`；当前 `post_rooms.json` 亦无 `tags`，故默认 `None`（按 platform/event 路由）。

---

## 6. 测试契约（交给工程师落地）

### 6.1 跨语言对照（已有，回归守护，不重写）
- `tests/test_phase2_a2_routes.py`：`common.resolve_channel` 与 `monitor.html` `resolveChannel` 语义一致（最具体优先 / default 兜底 / legacy `push` 退化）。**本任务不得破坏这些用例。**
- `tests/test_phase2_a4_templates.py`：`common.render_template` 与 `monitor.html` `renderTemplate` 一致（占位符集合 / 缺字段保留）。**本任务不得破坏。**

### 6.2 `push_utils.channel_to_push_cfg`（新增单测）
- 新通道 dict → `{"type": ch["type"], **fields}`（字段拍平到顶层）。
- legacy 扁平 dict（`{"type":"wecom","webhook":...}`）→ 原样透传。
- 空 `{}` → `{}`。

### 6.3 `push_utils.dispatch_event`（新增单测，monkeypatch `send_via_*`）
1. **单通道退化**：`cfg_all` 仅含 `{"push":{"type":"bark","url":"U"}}` → `dispatch_event` 实际调用 bark 且 `pcfg` 等于 `load_push_cfg(raw)` 结果。
2. **多通道路由**：`cfg_all` 含 `channels`+`routes`（按 `platform`/`tag`/`event` 匹配）→ 不同 `ctx` 命中不同 `pcfg.type`；断言 `send_via_*` 收到的 `push_cfg` 类型正确。
3. **默认通道**：无具体路由命中 → 走 `match:{}` 默认通道；无默认且无 routes → 退化 `cfg['push']`。
4. **空/无 type**：`ch={}` → `dispatch_event` 返回 `ok=False`（不抛）。

### 6.4 `check_status` 集成（`tests/test_a2a4_ci.py`，monkeypatch `push_utils.dispatch_push` 或 `dispatch_event` 捕获调用）
- **legacy 不变**：`BLIVE_CONFIG` 仅含 `push`（无 `channels`/`routes`/`templates`），多房间开播 → 断言**恰好一次**调用，捕获的 `(title, desp, pcfg)` 与当前 monolithic 逻辑逐字节相同（`title` 含 `🔴 N位主播开播：names`，`desp` 为 `format_push_desp` 拼接，`pcfg.type` = legacy）。
- **多通道分组**：`routes` 按 `platform` 分流（bilibili→wecom / douyin→bark）→ 断言**两次**调用，分组正确、各自聚合。
- **tag 匹配**：`routes` 含 `{match:{tag:'game'}}` → 带 `tags:['game']` 的房间进对应通道，其余进默认。
- **模板渲染**：`templates.live_on='🔴 {name} 开播了：{title}'` → 断言捕获 `desp` 经 `render_template` 渲染（含 `{title}` 已替换、无残留占位符）；无 `templates` 时 `desp` 为 `format_push_desp`。
- **静默**：`silence.enabled=true` 且当前在北京静默区间 → 零调用，日志标记 `silenced`。
- **去重**：某房间在 `notify_dedup` 冷却内 → 不进入任何分组；成功组对组内每房间 `dedup_record`。

### 6.5 `check_new_posts` 集成（monkeypatch `dispatch_push`）
- legacy 配置下多新作品 → 每作品一次 `dispatch_event`，`pcfg` 等于 legacy；行为与当前 per-room 逐字节一致。
- 多通道配置下 → 每作品按其 `ctx`（含 `event:'new_post'`）路由到对应通道；**不跨房间聚合**。

### 6.6 `auto_summary` 集成
- legacy：摘要经 `dispatch_event` 退化通道投递，等价于当前 `load_push_cfg`+`dispatch_push`（可复用 `tests/test_auto_summary.py` 的 monkeypatch 模式，断言 `push_cfg` 等价）。
- 无有效通道（`resolve_channel` 返回无 `type`）→ `sys.exit(0)` 不写冷却。

---

## 7. 风险与回滚

- **回归风险面**：仅通知发送层；状态抓取 / 历史 / 静默 / 去重账本逻辑零改动。
- **回滚**：任一脚本通知段改造若出问题，因改动局限在「构造 `title/desp` + 调 `dispatch_event`」这一段，可单独 revert 该文件；`push_utils.dispatch_event` 为纯增量（不改旧函数），不影响既有 `load_push_cfg`/`dispatch_push` 调用方。
- **灰度**：建议先合 T01+T03（`check_new_posts` 改动最小、纯路由），再合 T02（`check_status` 分组），最后 T04；每步以 §6 测试护航。

---

## 附：序列图与类图（另存 `.mermaid` 文件）

- `docs/a2a4_sequence.mermaid`：`check_status` 开播通知（legacy 退化 vs 多通道分组）调用流。
- `docs/a2a4_class.mermaid`：`push_utils` / `common` / 三个 CI 脚本的依赖与新增 API 关系。
