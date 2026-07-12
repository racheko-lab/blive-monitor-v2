# blive-monitor「日志模块功能性重写」架构设计 + 任务分解

> 架构师：高见远（Bob）｜ 范围：日志模块三支柱功能性补全（前端查看器功能化 / 日志分级+错误可见 / 统计与视图整合）
> 前置：上轮结构性重构 `docs/system_design.md`（已合并：`log_utils.py` / `state_prune.py` / history 加 `rid` / `HISTORY_MAX=500` 单一来源）
> 配套图：`docs/functional_class.mermaid`（类图）、`docs/functional_sequence.mermaid`（时序）
> 约束：**纯 Python 标准库 + 原生 HTML/JS/CSS，不引入任何新依赖**；新功能必须复用 `log_utils` / `state_prune`，不得另起炉灶；不破坏 `check.yml` CI。

---

## 0. 设计前提（主理人已确认采用 PM 全部默认）

1. 新作品事件进统一 `history.json`（`check_new_posts.py` 检测命中时 `append` 一条 `type=new_post`）。
2. 四视图合并为 **Option A**：`monitor.html` 为唯一 canonical 主视图，通过 `?view=` 预选 tab；`monitor-dashboard/feed/hero.html` 改为**重定向**到 `monitor.html?view=xxx`，删除各自重复渲染。
3. 后端错误节流：**同 `rid+type` 30 分钟内不重复写** history（防刷屏）；缺 `id`/`sec_uid` 时降级为 `system` 类型、跳过不刷屏。
4. 存量 398 条 history **一次性迁移写回 `type`**（按 `status` 推导），保证统计口径准确，脚本幂等可重跑。
5. `level` 二级落地（`info/warn/error`）；按账号视图用「下拉+抽屉」形态（P1）。

---

## 1. 实现方案 + 框架选型

### 技术难点
- **错误可见且防刷屏**：CI 每 5 分钟一轮、串行执行（`concurrency.group`），若无节流，同一账号的持续失败会每轮写一条，迅速刷爆 history。节流必须在"跨进程、跨脚本"维度生效——磁盘 `history.json` 是唯一真相源。
- **统一模型向后兼容**：新增 `type/level/detail/account` 字段，存量 398 条无 `type`；前端必须"忽略未知字段即兼容"，不能因缺字段报错。
- **四视图收敛**：三个兄弟 HTML 各有一套 `renderLog/renderFeed/renderLogBox`，逻辑分裂且筛选残缺；需收敛到一份渲染逻辑，同时保留四个入口（靠重定向）。
- **统计口径**：stats bar 依赖存量条目带 `type`；迁移前口径失真。

### 框架选型（保持纯标准库 + 原生前端，无新依赖）
- 后端：沿用 Python 标准库（`logging` / `json` / `os`）+ 既有 `log_utils` / `state_prune` / `common`。**新增纯函数** `should_suppress` / `dedupe_by_throttle` / `compute_stats` 与常量 `EVENT_TYPES` / `LEVELS` / `ERROR_THROTTLE_MINUTES` / `STATUS_TO_TYPE` / `TYPE_TO_LEVEL`，全部落在 `log_utils.py`（单一收口）。
- 节流状态存储：**不新增文件**，基于磁盘 `history.json` 末尾扫描（`should_suppress` 读 `load_history` 尾部 N 条做 `rid+type` + 时间窗判断）；本运行内 pending 列表一并参与判断（同轮多账号失败也互相抑制）。
- 前端：纯原生 HTML/JS/CSS，**复用现有 CSS 变量**（`--bili/--dy/--live/--card2/--line/--text3/--yellow/--error`），不引框架；stats 在前端 **JS 内现算**（无后端新接口），其语义必须与 `log_utils.compute_stats` 一致（以单测锚定同一份期望）。
- 架构模式：保持「脚本 + JSON 状态文件」；所有 history 写入统一经 `log_utils.append_history`（原子写 + 上限裁剪），禁止散落直写。

---

## 2. 文件列表（新增 / 修改，含前端）

### 新增
- `tools/migrate_history_types.py` — 存量 history 按 `status` 推导补 `type`（幂等；可重跑）。
- `tests/test_log_functional.py` — 端到端功能测试：模拟 `check_new_posts` 写入 `new_post` / `error` / `cookie_warn` 到临时 history，断言节流与字段正确。
- `tests/test_migrate_history_types.py` — 迁移推导与边界单测（live/offline/replay/error/缺失 → 对应 type）。
- `tests/test_frontend_log.py` — 结构性测试：`monitor.html` 含 `#logStats` / `#logFilter` / 加载更早处理器，且**不再含**硬编码 `-80` 截断。
- `docs/functional_design.md` / `docs/functional_class.mermaid` / `docs/functional_sequence.mermaid` — 本交付物。

### 修改
- `log_utils.py` — 加常量 + `type_from_status` / `level_from_type` / `should_suppress` / `dedupe_by_throttle` / `compute_stats`。
- `check_status.py` — 每个 log 条目标注 `type`（live→`live_on`、offline/replay→`live_off`、error→`error`、unknown→`system`）；error 路径经 `dedupe_by_throttle` 节流；统一 `append_history`。
- `check_new_posts.py` — 新作品命中写 `type=new_post`；`sec_uid` 解析失败 / 接口风控(`aweme=None`) / fetch 异常写 `cookie_warn`/`error`；缺 `id`/不可解析降级 `system`；均经 `append_history` 且错误类节流。
- `monitor.html` — 重建「日志」tab：stats bar + 筛选栏 + 分页/加载更早 + 排序 + 点击展开 + 账号下拉；支持 `?view=` 预选。
- `monitor-dashboard.html` / `monitor-feed.html` / `monitor-hero.html` — **改为重定向壳**（删除各自重复日志渲染代码）。
- `state_prune.py` — 本轮**不改**（上轮已收口；`prune_history_orphans` 已按 `rid` 裁剪，对新 `type` 字段透明）。
- `tests/test_log_utils.py` — 扩展 `should_suppress` / `dedupe_by_throttle` / `compute_stats` 用例。
- `tests/test_check_status.py` — 扩展 type 写入与 error 节流用例。
- `tests/test_check_new_posts.py` — 扩展 new_post / cookie_warn / error 历史写入用例。
- `tests/test_merge_state.py` — 验证带 `type` 的 history 经 `merge_history` 并集合并后字段无损透传。
- `README.md` — 更新四个视图入口说明（统一指向 `monitor.html`，旧入口重定向兼容）。

---

## 3. 数据结构与接口（classDiagram → `docs/functional_class.mermaid`）

要点（函数签名级，不写实现体）：

- **HistoryEntry（数据模型，dict）**：`{time, name, platform, status, title, changed, prev, push, rid, type, level, detail, account}`
  - 新增 `type`（枚举见下）、`level`（`info|warn|error`，可选）、`detail`（自由文本）、`account`（==rid，供按账号视图）。
  - 前端忽略未知字段即兼容；无 `type` 时按 `status` 懒推导图标。
- **type 枚举**：`live_on` / `live_off` / `new_post` / `error` / `cookie_warn` / `system`。
- **level**：`info` / `warn` / `error`。
- `log_utils.EVENT_TYPES: frozenset` — type 合法值集合。
- `log_utils.LEVELS: frozenset` — level 合法值集合。
- `log_utils.ERROR_THROTTLE_MINUTES: int = 30` — 节流窗口（单一来源；P1-2 可后续抽为可配置）。
- `log_utils.STATUS_TO_TYPE: dict` — `{"live":"live_on","offline":"live_off","replay":"live_off","error":"error"}`，缺省 `"system"`。
- `log_utils.TYPE_TO_LEVEL: dict` — `live_on/live_off/new_post/system→info`、`cookie_warn→warn`、`error→error`（缺省 `info`）。
- `log_utils.HISTORY_MAX: int = 500` — 上限（沿用既有单一来源）。
- `type_from_status(status: str) -> str`：返回 `STATUS_TO_TYPE.get(status, "system")`。
- `level_from_type(t: str) -> str`：返回 `TYPE_TO_LEVEL.get(t, "info")`。
- `should_suppress(rid, etype, now, history_path=None, in_memory=None, window_minutes=ERROR_THROTTLE_MINUTES) -> bool`：合并 `in_memory`（本运行 pending）+ 磁盘 `history.json` 末尾 N（建议 50）条，若存在同 `rid+type` 且 `time` 距 `now` < 窗口则返回 `True`。
- `dedupe_by_throttle(entries, now, history_path=None, in_memory=None) -> List[dict]`：对 `type∈{error,cookie_warn}` 的条目调用 `should_suppress` 剔除重复（info/new_post/system 始终保留）；维护 running `in_memory` 使同轮内也抑制。
- `compute_stats(history, days=7, now=None) -> dict`：按 `type` + `time`（北京时间日期部分）聚合到天，返回 `{days:[日期标签...], new_post:[...], live_on:[...], error:[...], cookie_warn:[...], totals:{...}}`；`now` 缺省取 `common.bjnow()`。
- 既有 `load_history` / `append_history` / `cap_history` / `init_runtime_logging` / `get_logger` 保持不变（统一原子写入口）。
- `state_prune.prune_history_orphans` / `prune_tracking_orphans` / `merge_post_rooms_fields`：本轮不改动。

---

## 4. 程序调用流程（sequenceDiagram → `docs/functional_sequence.mermaid`）

含 4 条时序：
1. **状态变更 → 写分级日志（带节流）**：`check_status` 检测 → 标 `type` → `dedupe_by_throttle`（仅 error/cookie_warn）→ `append_history` → `state_prune` 裁孤儿。
2. **新作品 → 写 new_post + 推送；错误 → 写 error/cookie_warn**：`check_new_posts` 命中真实新作品 → 推送 → `append_event(type=new_post)`；`sec_uid` 失败/风控/`fetch` 异常 → `append_event(type=cookie_warn|error)`（经 `should_suppress` 节流）；缺 `id`/不可解析 → `system` 跳过。
3. **前端：筛选 / 分页 / 统计 / 展开渲染**：`monitor.html` 加载 `history.json` → `computeStatsJS` 出 stats bar → `applyFilters` 按 `logState` → `renderLogList(前50)` → 加载更早增量 / 点击展开 / 切换排序账号。
4. **四视图重定向**：`dashboard/feed/hero` → `location.replace('monitor.html?view=xxx')` → `monitor.html` `readViewParam` → `show('log')` + 预置筛选。

---

## 5. 有序任务列表（6 个，T01 基础设施 → T02–T05 并行/顺序 → T06 联调）

> 说明：本交付物按主理人要求采用 **5–8 个任务**（覆盖三支柱 + 迁移 + 联调）；仍遵循"T01 必为基础设施、按功能分组、任务内 ≥3 文件、末位联调"的 SOP 精神。T02/T03/T04/T05 仅依赖 T01 且相互独立（T05 迁移与 T02/T03 写入解耦，可并行；T04 前端渲染依赖数据字段但可并行开发）。

### T01 — 基础设施：log_utils 扩展 + 常量 + 迁移工具骨架 + 设计/图文档（P0）
- **Source Files**：`log_utils.py`(MODIFY：加 EVENT_TYPES/LEVELS/ERROR_THROTTLE_MINUTES/STATUS_TO_TYPE/TYPE_TO_LEVEL + `type_from_status`/`level_from_type`/`should_suppress`/`dedupe_by_throttle`/`compute_stats`)、`tools/migrate_history_types.py`(NEW：幂等迁移脚本)、`tests/test_log_utils.py`(MODIFY：扩 should_suppress/dedupe_by_throttle/compute_stats)、`docs/functional_design.md` + `docs/functional_class.mermaid` + `docs/functional_sequence.mermaid`(NEW)
- **Dependencies**：无
- **Priority**：P0
- **说明**：搭好统一契约与节流/统计纯函数；定义 type/level 枚举常量单一来源；给出迁移工具骨架。所有后续写入方与前端均引用此处。

### T02 — 后端：直播状态分级写入（check_status.py + 测试 + 合并透传验证）（P0）
- **Source Files**：`check_status.py`(MODIFY：每条 log 标 `type=type_from_status(status)`、`level=level_from_type(type)`；error 类经 `dedupe_by_throttle` 节流；统一 `append_history`)、`tests/test_check_status.py`(MODIFY：扩 type 写入 + error 节流)、`tests/test_merge_state.py`(MODIFY：验证带 type 的 history 经 `merge_history` 字段无损透传)
- **Dependencies**：T01
- **Priority**：P0
- **说明**：实现支柱2 直播侧（live_on/live_off/error）。注意 `bili_batch_failed` 沿用上次的 `unknown` 状态 → `type=system`（不刷屏）。`state_prune` 本轮不改。

### T03 — 后端：新作品 + 错误可见写入（check_new_posts.py + 测试）（P0）
- **Source Files**：`check_new_posts.py`(MODIFY：导入 `log_utils.append_history/should_suppress/type_from_status` 等；定义 `HISTORY_FILE`；新作品命中写 `type=new_post`；`sec_uid` 解析失败/接口风控(`aweme=None`)/`fetch` 异常写 `cookie_warn`/`error` 并经节流；缺 `id`/不可解析降级 `system`)、`tests/test_check_new_posts.py`(MODIFY：扩 new_post/cookie_warn/error 历史写入)、`tests/test_log_functional.py`(NEW：端到端功能测试)
- **Dependencies**：T01
- **Priority**：P0
- **说明**：实现支柱2 新作品侧与运行时错误可见。新作品仅在 api 模式且 `candidate=true`（确为新作品）时写 `new_post`（与推送去重解耦）；count 退化模式不写 `new_post`（已写 `cookie_warn` 提示）。

### T04 — 前端：统一日志面板功能化 + 四视图重定向（P0）
- **Source Files**：`monitor.html`(MODIFY：重建「日志」tab = stats bar + 筛选栏[搜索/类型chip/平台chip/账号下拉/日期/排序] + 日志列表[默认50·加载更早步长50·点击展开·按账号视图]；`?view=` 解析)、`monitor-dashboard.html`(MODIFY→重定向壳)、`monitor-feed.html`(MODIFY→重定向壳)、`monitor-hero.html`(MODIFY→重定向壳)、`tests/test_frontend_log.py`(NEW：结构性断言)
- **Dependencies**：T01（渲染逻辑独立于写入，可与 T02/T03 并行开发）
- **Priority**：P0
- **说明**：实现支柱1（前端查看器功能化）+ 支柱3（视图整合）。三兄弟仅保留 `<meta http-equiv="refresh">` + JS `location.replace('monitor.html?view=xxx')` 重定向壳，删除各自重复渲染（见 §9 D类）。`?view=dashboard|feed|hero` 均打开日志 tab 并可选预置筛选（feed 预置新作品优先、hero 在播置顶为轻增强）。

### T05 — 存量迁移执行 + 迁移测试（P0）
- **Source Files**：`tools/migrate_history_types.py`(运行：对仓库 `history.json` 幂等补 `type`)、`tests/test_migrate_history_types.py`(NEW：status→type 推导与边界)、`tests/test_merge_state.py`(MODIFY：迁移后 history 仍正确合并)
- **Dependencies**：T01
- **Priority**：P0
- **说明**：支柱3 统计口径前提。脚本仅对缺 `type` 的条目补写（已存在不覆盖），可重复运行；同时回填 `level`（由 type 推导）保证一致。执行一次即可（CI 不需常驻）。

### T06 — 联调 + 全量测试 + check.yml 校验 + 文档收尾（P1）
- **Source Files**：`.github/workflows/check.yml`(VERIFY：`python3 check_status.py` / `python3 check_new_posts.py` 调用顺序与 `concurrency` 组不变)、`docs/functional_design.md`(FINALIZE：交叉引用校对)、`README.md`(UPDATE：四视图入口说明统一指向 `monitor.html`)、全量 `tests/*`(联调)
- **Dependencies**：T02、T03、T04、T05
- **Priority**：P1
- **说明**：集成验证；跑全量 `pytest`；确认 history.json 经 `merge_state` 并集合并字段无损；确认前端在本地静态服务下渲染正常（手动核对 stats/filter/分页/展开）。

---

## 6. 依赖包列表（Required Packages）

> **无新增依赖**，全部 Python 标准库 + 既有依赖。

```
- logging / logging.handlers / json / os (stdlib) : 运行时日志 + history 读写
- common (repo)                                 : bjnow / save_json_file / load_json_file
- log_utils (repo, 本轮扩展)                    : 常量 + should_suppress/dedupe_by_throttle/compute_stats
- state_prune (repo, 本轮不改)                  : 级联清理
# 既有（不变）：
- playwright==1.58.0 (requirements.txt)         : 抖音作品抓取（非本模块新增）
- pytest>=8.0       (requirements-dev.txt)      : 测试
# 前端：无框架，纯原生 HTML/JS/CSS
```

---

## 7. 跨文件共享约定（Shared Knowledge）

- **type 枚举常量唯一来源**：`log_utils.EVENT_TYPES` / `STATUS_TO_TYPE` / `TYPE_TO_LEVEL` 为权威定义；后端写入方一律用 `type_from_status()` 推导，**禁止**在脚本里硬编码 `"live_on"` 字符串映射。前端 JS 维护自己的标签映射，但**字符串值必须与 `EVENT_TYPES` 完全一致**（`live_on|live_off|new_post|error|cookie_warn|system`）。
- **level 二级**：一律由 `level_from_type()` 推导（可选字段）；写入方**不**手动设 level（除非有特殊覆盖需求），前端缺省按 type 推导显示。
- **节流状态存储**：**不新增文件**；`should_suppress` 读磁盘 `history.json` 末尾 N 条 + 本运行 `in_memory` pending 列表联合判断；`ERROR_THROTTLE_MINUTES=30` 在 `log_utils` 单一来源（P1-2 后续可抽为 `BLIVE_CONFIG` 可配置）。仅 `error`/`cookie_warn` 受节流，`new_post`/`system`/`live_*` 始终写入。
- **append_history 统一入口**：所有 history 写入（两脚本 + 迁移后的运行）必须走 `log_utils.append_history`（`.tmp`+`os.replace` + `cap_history(HISTORY_MAX)`）；**禁止**任何地方 `open().write` 直写 `history.json`。
- **前端筛选状态管理**：单一 `logState` 对象 `{search, type, platform, account, dateFrom, dateTo, sort, visible}`；`applyFilters()` 为纯函数（输入全量 hist → 输出过滤+排序后列表）；`renderLogList()` 仅渲染前 `logState.visible`（默认 50，步长 50）条；"加载更早"只增 `visible`。各筛选项可叠加。
- **向后兼容字段规则**：前端**忽略未知字段即兼容**；无 `type` 时按 `status` 懒推导图标（`live🔴/replay▶️/offline⚫/error❌`）；无 `level` 时按 type 推导；无 `detail`/`account` 时对应 UI 占位为空。
- **account 字段**：直播条目 `account = rid`；新作品条目 `account = rid`（douyin）；按账号视图按 `rid/account` 过滤（下拉取 `rooms.json`+`post_rooms.json`+历史出现过的 `rid`）。
- **合并无损**：`merge_state.merge_history` 按 `(time,name,platform)` 去重并透传整条 dict，新增字段自动随条目保留；T02/T05 测试锚定此不变式。

---

## 8. 待明确事项（Anything UNCLEAR）

1. **new_post 写入时机**：本设计采用"检测到即写（api 模式 `candidate=true` 即写 `new_post`），与推送去重解耦"。若主理人希望"仅推送成功才写"，改为仅在 `notify=True` 时写。默认采用"检测到即写"（更贴合"新作品事件进统一日志"）。
2. **ERROR_THROTTLE_MINUTES 可配置化**：本期为常量 30；P1-2 若要抽成 `BLIVE_CONFIG` 可配置，需新增解析（不破坏默认）。
3. **四视图重定向后的外部引用**：旧 `dashboard/feed/hero` 可能被 README/书签引用；重定向保证兼容，但建议 T06 同步更新 `README.md` 入口说明。
4. **按账号视图"抽屉/迷你统计"（P1-1）**：本设计 P0 先落地"账号下拉过滤"（即进入按账号单独视图）；抽屉 + 该账号迷你统计作为 P1 同任务内增量（可选，不阻塞 P0-7）。
5. **time 字段格式稳定性**：`compute_stats` 依赖 `time` 为 `"YYYY-MM-DD HH:MM:SS"`（北京时间）字符串；确认 `check_status`/`check_new_posts` 写入的 `now_str` 格式稳定（当前一致）。
6. **存量 history 是否已被 `.gitignore`**：当前 `history.json` 由 `check.yml` 用 `git add -f` 提交，故迁移写回会被提交（符合 PRD Open Q4 默认"直接改 history.json"）。无需改 `.gitignore`。

---

## 9. 明确标注「该删」（D 类）

| 项 | 落点 | 说明（删除/收敛） |
|----|------|------|
| **D1 三视图重复日志渲染代码** | `monitor-dashboard.html`(`renderLog`+专属 CSS) / `monitor-feed.html`(`renderFeed`+专属 CSS) / `monitor-hero.html`(`renderLogBox`+专属 CSS) | 全部删除，三文件改为重定向壳（`location.replace('monitor.html?view=xxx')`），仅维护一份渲染逻辑。 |
| **D2 硬编码 80 条截断** | `monitor.html` `renderLog()` 的 `for(i=hist.length-1; i>=Math.max(0,hist.length-80); i--)` | 删除固定 80 截断，改为 `logState.visible`（默认 50、步长 50）分页；`monitor-hero.html` 的硬编码 60 截断一并随 D1 删除。 |
| **D3 存量无 type 历史** | `history.json`（398 条） | 经 `tools/migrate_history_types.py` 写回 `type`（按 status 推导），数据层消除"无 type"；脚本幂等可重跑。 |
| **D4 错误不可见于前端** | `check_new_posts.py` 原"仅 `logger.warning/error`、不写 history"的静默错误路径 | 改为同时 `append` 到 history（`cookie_warn`/`error`），并节流；删除"错误对用户不可见"的旧行为（增补写入，非删代码）。 |
| **D5 重复状态文案** | 两脚本中多处重复 `logger.warning("...获取作品失败/被风控")` | 节流后控制台仍输出（不丢调试信息）；可选在 T03 顺带归并语义重复的日志语句（不阻塞）。 |

---

### 交付物清单
- `docs/functional_design.md`（本文）
- `docs/functional_class.mermaid`
- `docs/functional_sequence.mermaid`
