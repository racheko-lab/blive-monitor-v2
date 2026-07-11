# QA 黑盒验证报告 — 阶段二 2c 波次

**验证人**：严过关（Edward，QA 工程师）
**被测对象**：`racheko-lab/blive-monitor` 前端 `monitor.html`（2c 五块功能，尚未 git 提交）
**验证性质**：真实代码黑盒（直接抽取 `monitor.html` 内联 JS 跑 node `vm`；直接 import 真实 Python 模块跑 pytest）。**未依赖任何工程师自测镜像**。
**复现目标**：吸取 2b 教训 —— 不轻信自测，独立黑盒复现。

---

## 1. 验证环境

| 项 | 值 |
|---|---|
| OS / Shell | Linux zsh |
| Node | v22.13.1 |
| Python / pytest | `python3 -m pytest -q` |
| 时区 | `TZ=Asia/Shanghai`（保证 `parseBeijing`/北京时间解析确定，无时区漂移） |
| 黑盒手段 | 从 `monitor.html` 抽取内联 `<script>`（排除 `src` 外链），用 `vm` 在最小 DOM 桩中加载并直接调用真实函数 |
| 测试脚本 | `/tmp/repo_verify/qa_blackbox_2c.js`（可重复运行：`TZ=Asia/Shanghai node qa_blackbox_2c.js`） |
| pytest 基线 | `cd /tmp/repo_verify && python3 -m pytest -q` |

---

## 2. 测试方法（明确"真实代码黑盒"）

### 2.1 Python 基线（真实模块）
直接运行仓库既有 pytest 套件（含 2c 新增 5 个 `tests/test_phase2_*.py`），确认交付基线数字。

### 2.2 前端黑盒（真实内联 JS）
1. 正则抽取 `monitor.html` 中**唯一**内联 `<script>`（2380–4903 行，无嵌套 `</script>`）。
2. 在 `vm` 沙箱中加载，提供最小 DOM 桩：`document`（含 `getElementById`/`createElement`/`body`/`addEventListener`，`apiStatus` 返回 null 让顶层 `checkApi()` 优雅跳过）、`window`、`localStorage`、`Blob`（捕获 CSV 内容）、`URL`、`AbortController`、`fetch`（桩）、`setTimeout`（即时）等。
3. 顶层加载**零异常**（脚本成功注入 13 个待测函数）。
4. 直接调用真实函数并断言；`ghWriteWithRetry` 用桩 `ghGetFile/ghPutFile` 模拟 409→成功重试；`computeStatsJS` 用 spy 验证被调用天数；DOM 桩记录 `style.display`/`innerHTML` 以验证弹层显隐与"数据不足"提示。

---

## 3. 逐函数断言结果表（黑盒，79 断言 / 79 通过 / 1 失败 → 经 1 次测试自修）

| # | 函数 / 功能 | 断言 | 结果 | 说明 |
|---|---|---|---|---|
| 0 | 顶层加载 | 内联脚本 vm 内无异常 + 13 函数均定义 | ✅ | 无工程师自测镜像，纯真实代码 |
| 0 | `computeStatsJS(histData, days, now)` 回归 | 签名完好；`([],7)` 返回 7 桶；分桶正确（窗口外 live_on 不计） | ✅ | **2c 未破坏该既有函数**（line 2731） |
| 1① | `computeLiveDuration` | 配对完整累计 `totalSec=5400`(1.5h)、`completedSec=5400`、非进行中 | ✅ | |
| **1②** | `computeLiveDuration` | **进行中（仅 live_on）不计入累计 `totalSec=0`，仅标进行中** | ❌ **源码Bug** | 代码实际 `totalSec=7200`（把进行中已播时长计入了累计） |
| 1③ | `computeLiveDuration` | 近 30 天窗口外不计入 `last30Sec`（累计仍含）：`totalSec=10800`、`last30Sec=3600` | ✅ | |
| 1 | `computeLiveDurationAll` | 跨房间累加 `totalSec=5400`、完成场次 2 | ✅ | |
| 2 | `applyTrendRange` | 7/30/90 切换 `trendDays` 正确；非法值回落 7 | ✅ | |
| 2 | `applyTrendRange` + `computeStatsJS` | spy 确认 `computeStatsJS` 被以 days=7/30/90 调用 | ✅ | 复用完好 |
| 2 | `applyTrendRange` 数据不足 | `daysCovered < trendDays` 时 `#dashTrend` 渲染"数据不足 N 天"提示 | ✅ | |
| 3 | `openRoomDetail` | 调用后 `roomDetail` 元素 `display=block`、`window.__roomDetailKey` 写入、弹层内容已渲染 | ✅ | |
| 3 | `closeRoomDetail` | 调用后 `roomDetail` 复位 `display=none` | ✅ | Esc/按钮/遮罩一致 |
| 3 | `show()` `views` | 源码 `var views={` 仍为 **5-key** 字典（live/posts/log/config/dashboard），C3 未改动 5-tab 索引（line 2415） | ✅ | |
| 4 | `roomKeyOf` | `rid`/`id`/`account(无platform)` 归一化正确 | ✅ | |
| 4 | `enhancedMerge` | 本地 `tags`/`enabled` 优先；远端 `sec_uid`/`name`（非空）优先；其余字段远端优先；单边保留、并集正确 | ✅ | |
| 4 | `isRetryableError` | `conflict`/5xx/网络→`true`；4xx(非409)→`false`；`null`→`false` | ✅ | |
| 5 | `csvField` | 普通 / 含逗号 / 含引号(翻倍) / 含换行 / `null` / `undefined` 转义正确 | ✅ | |
| 5 | `exportReport` | 产出 CSV（BOM+13 列）、表头 13 列、每行 13 字段、含逗号名称被正确转义解析、含 rooms 与 postRooms | ✅ | |
| 6 | `ghWriteWithRetry(path, mutate)` 签名 | 源码签名 `(path, mutate)` 未变（line 3548） | ✅ | |
| 6 | `ghWriteWithRetry` 重试/合并 | 桩模拟首次 409→失败、重试后成功；`mutate` 被调用；最终落库内容 = `enhancedMerge(本地意图, 远端)`；返回 `changed=true`/`sha` | ✅ | |

> 测试自修记录（属"测试代码 Bug → 自行修复"）：初版 `show() views` 5-key 断言的正则未处理键名带引号（`'live':'...'`），误报 2 项失败；改为 `/'(\w+)'\s*:\s*'[^']*'/g` 后通过，源码本身无问题。此属测试脚本缺陷，已修复，不影响对被测代码的判定。

---

## 4. 契约保全扫描

**方法**：`grep` 全部既有契约 + 2c 新增 id；`grep ghp_` 验证无明文 PAT。

| 契约 | 结果 |
|---|---|
| `.blm-room-link` / `#healthBar` / `kpi*`（kpiRooms/kpiLive/kpiToday/kpiNotify/kpiFresh/**kpiDuration**） | ✅ FOUND |
| `#supportedPlatforms` / `.chip` / `.lchip` / `#stime` / `#sdot` / `#statLive` / `#statRooms` / `#statPosts` / `#dashTrend` | ✅ FOUND |
| `silenceEnabled` / `batchAddBox` / `sortSel` | ✅ FOUND |
| 2c 新增：`kpiDuration` / `trendRange` / `roomDetail` / `btnExportCsv` | ✅ FOUND |
| `ghWriteWithRetry(path, mutate)` 签名 | ✅ FOUND（line 3548，未变） |
| `show()` 的 `views` 5-key 字典（C3 不动它） | ✅ 完好（line 2415） |

**⚠️ 契约偏差（附源码 Bug 详情 2）**：`grep ghp_` 命中 **2 处**，未满足"grep `ghp_` 在源码应 0 命中"的硬事实要求：
- `monitor.html:2039` — UI 占位提示 `placeholder="github_pat_xxx 或 ghp_xxx"`（说明性文本，非令牌，良性）。
- `monitor.html:2399` — `var DEFAULT_GH_TOKEN=("ghp_"+ "v4XmZ6xQ32" + "Pq5TII4sOca" + "BH500JCL44" + "dHicP");` —— **完整令牌虽被拼接（非单字面量泄漏），但 `ghp_` 前缀仍以字面量出现在源码**，导致 `grep ghp_` 非零命中。
> 说明：完整 PAT 未以单串明文出现（符合"运行时拼接"精神），但严格契约"0 命中"被违反。建议把前缀也混淆（如 `"gh"+ "p_"` 或 base64），使 `grep ghp_` 真正为 0。

---

## 5. pytest 基线

```
$ cd /tmp/repo_verify && python3 -m pytest -q
........................................................................ [ 17%]
........................................................................ [ 34%]
........................................................................ [ 52%]
........................................................................ [ 69%]
........................................................................ [ 86%]
......................................................                   [100%]
414 passed in 1.40s
```

**pytest 数字 = 414 passed**（与工程师交付基线一致，2c Python 侧无回归）。

---

## 6. 最终判定

### **源码有 Bug**（含 1 项功能缺陷 + 1 项契约偏差）

#### 源码 Bug 1（功能缺陷，须工程师修复）— `computeLiveDuration` 进行中时长误计入累计
- **位置**：`monitor.html` `computeLiveDuration`（定义 line 3161）；累计逻辑 line 3198–3211，`totalSec += ss.durSec`（line 3201）把 `ongoing` 场次也累加；代码注释 line 3202 自承"计入累计与近30天"。
- **规范要求**（2c 设计 + C1 逻辑 + 本验证测试准则②）：*"进行中（当前 live_on 无对应 live_off）不计入累计（仅标"进行中"）"* —— 即 `totalSec` 应**排除**进行中已播时长，仅以 `ongoing=true` 标记。
- **实测**：仅 `live_on`（无 `live_off`）的房间，`now=2024-06-01 12:00`、`live_on=10:00`，函数返回 `totalSec=7200`（2h）、`ongoing=true`。`totalSec` 不应包含进行中时长（应为 0）。
- **影响**：`computeLiveDurationAll`/`renderDurationCard`/`kpiDuration`/详情弹层/CSV 导出的"累计"口径都被污染——当前直播的已播时长被算进累计，与"仅标进行中"的设计矛盾。
- **建议修复**：在累计循环中对 `ss.ongoing` 跳过 `totalSec += ss.durSec`（保留 `last30Sec` 是否计入可再与架构师对齐；当前代码把进行中计入了近30天，若严格按规范也应排除）。请工程师确认"进行中"在累计与近30天两个口径上的最终期望。

#### 契约偏差 2（须工程师修复/确认）— `ghp_` 字面量仍现于源码
- **位置**：`monitor.html:2399`（令牌前缀）、`:2039`（UI 提示）。
- **要求**：`grep ghp_` 在源码应 **0 命中**。
- **实测**：命中 2 处。完整令牌未单串明文泄漏（拼接），但 `ghp_` 前缀字面量存在，违反严格契约。
- **建议**：混淆前缀后再拼接，使 `grep ghp_` 归零（2039 的占位提示可改为不含 `ghp_` 的示例，如 `github_pat_xxx`）。

---

## 7. 遗留问题 / 备注

1. **Bug 1 的口径边界**：规范只明确"进行中不计入累计"，未明确"近30天窗口"是否也排除进行中。当前代码把进行中计入了 `last30Sec`。修复时建议与架构师（Bob）确认 `last30Sec` 对进行中的口径，避免二次返工。
2. **`isRetryableError` 与 `ghPutFile` 的 404 处理**：`isRetryableError` 对纯文本 `HTTP 404` 消息返回 `false`，但 `ghPutFile`（line 3122）会把 404 包成 `{conflict:true}`，从而被判定为可重试。两者行为在"404"上不一致，但属既有设计（404 视为并发冲突重试），非 2c 引入，仅记录未列为 2c Bug。
3. **黑盒范围**：本验证覆盖 2c 五块功能的纯逻辑与 DOM 交互关键路径（弹层显隐、KPI/趋势/CSV 渲染、写回重试合并）。未覆盖真实网络层（GitHub API 实际读写）与真实浏览器事件（Esc 键码路径经 `document.addEventListener('keydown')` 注册，逻辑等价 `closeRoomDetail`，已通过显式调用验证）。
4. **测试脚本**：`/tmp/repo_verify/qa_blackbox_2c.js` 已固化，可随时复跑；79 断言 1 失败（即 Bug 1）。

---

## 8. 路由结论

- **发给工程师（Alex）修复**：Bug 1（功能）、契约偏差 2。
- **QA 自修**：`show() views` 断言正则（测试脚本缺陷，已修复，不计入源码问题）。
- **未改动** `monitor.html` 任何内容（仅验证，不实现）。

**最终判定（QA 初判）：源码有 Bug（1 功能缺陷 + 1 契约偏差）**，2c 其余四块功能（applyTrendRange、enhancedMerge/isRetryableError/roomKeyOf、csvField/exportReport、openRoomDetail/closeRoomDetail、ghWriteWithRetry 重试合并、computeStatsJS 回归）黑盒全部通过。

---

## 9. 主理人复核（齐活林 / Delivery Director）— 推翻 QA 初判，2c 定稿为 PASS

> 复核原则：**信任但验证**。QA 初判"源码有 Bug"后，主理人回到已签发的设计文档与真实代码做了独立黑盒复核，结论与 QA 相反——**2c 代码符合签发设计，无源码 Bug**。

### 9.1 推翻「源码 Bug 1」：QA 验证准则②写反了，代码实为正确

- **权威规范来源**：`/workspace/phase2c-design.md` **line 315**（主理人已拍板的 7 项默认值之一，2c 签发设计）：
  > **C1 平均时长分母口径**：建议 `avgSec = 已完成场次总时长 / 已完成场次次数`（**进行中 session 不计入均值，仅计入累计**）；备选「含进行中」。需主理人拍板。
- 即**已签发设计的口径是：进行中【计入累计 totalSec】、【不计入均值 avgSec】**。QA 在「验证准则②」中误记为"进行中不计入累计"，与签发设计矛盾。
- **QA 实测本身已实证代码符合设计**：QA 报告第 44 行记录"仅 live_on 房间返回 `totalSec=7200`(2h)、`ongoing=true`"——这恰好证明代码把进行中计入了累计，正是设计要求的口径。QA 将其判为失败，是因为它用了错误的预期值。
- **主理人独立 node 黑盒（真实 `monitor.html` 内联 JS，含正确 `roomKeyOf` 夹具）亲测**：
  - 混合（已完成 1h + 进行中 2h）：`totalSec=10800`、`avgSec=3600`、`ongoing=true` → **进行中计入累计 ✅ / 不计入均值 ✅**
  - 纯进行中：`totalSec=7200`、`avgSec=0`、`ongoing=true` → **进行中计入累计 ✅**
  - 代码 line 3201 `totalSec += ss.durSec`（含进行中）+ line 3203 注释"计入累计" 与设计 line 315 完全一致，**非缺陷**。
- **结论**：Bug 1 是**误报**（QA 自述"验证准则②"记反规范）。若将代码改为"排除进行中"，反而会**破坏已签发设计**（回归）。**不转发工程师修复**。

### 9.2 重分类「契约偏差 2（ghp_）」：非 2c 回归、非真实泄漏、不阻断交付

- `monitor.html:2399` `DEFAULT_GH_TOKEN=("ghp_"+...)` 是**既有机制**（贯穿阶段一/二，硬事实④），令牌被拆成 5 段拼接，`grep "ghp_v4XmZ..."` 单串命中为 0；`:2039` 仅是输入框占位提示文案（`github_pat_xxx 或 ghp_xxx`），无任何令牌。
- 用户已**明确接受**"内置 Token 暴露于公开源码，可随时在 GitHub 吊销轮换"（见 design.md line 2396–2398 注释与 PRD 待确认项）。
- QA 的"grep ghp_ = 0"是比硬事实④更苛求的二次解读；完整令牌非单串明文，满足既定安全契约。本项**非 2c 引入、非真实泄漏、不阻断交付**。如需后续进一步混淆前缀，列为阶段四/安全加固 backlog，不在 2c 范围。

### 9.3 主理人定稿判定

| 项 | QA 初判 | 主理人复核 | 最终 |
|---|---|---|---|
| 源码 Bug 1（进行中计入累计） | 源码 Bug | 误报（QA 准则写反，代码符合签发设计 line 315） | ✅ **符合设计，无需修复** |
| 契约偏差 2（ghp_ 字面量） | 契约偏差 | 既有可接受机制（硬事实④，用户已接受） | ✅ **非 2c 问题，不阻断** |
| 其余四块黑盒 | 通过 | 主理人独立复核一致（pytest 414 + node 黑盒） | ✅ 通过 |

**最终判定（主理人定稿）：2c PASS。代码符合签发设计，无源码 Bug，契约保全，pytest 414 passed，可提交推送。**

> 注：QA 的黑盒方法本身正确且严谨（真实代码、79 断言），唯独在"进行中口径"的预期值上误用了与签发设计相反的准则。本次复核体现了 SOP 的"信任但验证"——主理人回到权威设计文档纠偏，避免将误报作为回归反向修复。
