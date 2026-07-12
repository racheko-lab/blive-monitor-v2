# 阶段二交付报告 — blive-monitor（B站/抖音直播 + 抖音新作监控）

| 项 | 内容 |
|---|---|
| 项目 | `racheko-lab/blive-monitor` |
| 阶段 | 阶段二（Phase 2）全量收尾 |
| 交付日期 | 2026-07-11 |
| 主理人 | 齐活林（Qi）· 交付总监 |
| 协作团队 | 许清楚（PM）/ 高见远（Architect）/ 寇豆码（Engineer）/ 严过关（QA） |
| 仓库状态 | 5 条波次提交全部推送 `origin/master`，与远端同步（0/0） |
| 测试基线 | **pytest 456 passed**（41 个测试文件 / 432 个 `test_` 函数，含参数化用例） |

---

## 1. TL;DR

阶段二围绕「**监控体验增强 + 推送精细化 + 无人值守投递**」三条主线，分 5 个波次（2a → 2b → 2c → A1 → A2/A4）完整交付：

- **定时摘要 / 批量增删 / 封面转存**（2a）
- **静默 / 标签 / 启停 / 排序 / 多通道前端 / 模板前端**（2b）
- **开播时长 / 趋势 / 详情弹层 / 写回增强 / CSV 导出**（2c）
- **定时摘要自动投递（CI job）**（A1）
- **CI 侧多通道路由 + 模板渲染打通**（A2/A4）

全部通过工程师实现 + QA 独立黑盒验证 + 主理人抽查闭环，已推送 `master`。

---

## 2. 波次总览

| 波次 | 提交 | 主题 | 关键交付 | 测试 | QA 结论 |
|---|---|---|---|---|---|
| **2a** | `52c09bc` | 摘要 + 批量 + 封面 | 定时摘要 A1、批量增删 B1、封面转存 D1 | 6 测试文件 | PASS |
| **2b** | `3112e36` | 精细化推送前端 | 静默 A3、标签 B2、启停 B3、排序 B4、多通道 A2(前端)、模板 A4(前端) | 6 测试文件 | PASS |
| **2c** | `ee5ff64` | 数据可视化增强 | 开播时长 C1、更长趋势 C2、详情弹层 C3、写回增强 D2、CSV 导出 C4 | 5 测试文件 | PASS（推翻 1 误报） |
| **A1** | `8d186a7` | 自动投递 | `auto_summary.py` 无人值守 CI job | `test_auto_summary.py` 19 用例 | PASS（修复 1 真 Bug） |
| **A2/A4** | `046a75c` | CI 路由+模板 | `dispatch_event`/`channel_to_push_cfg`，check_status/check_new_posts/auto_summary 改造 | `test_a2a4_ci.py` 23 用例 | PASS |

> 测试数字演进：`414`(2c Python 基线) → `430`(A1 新增 16) → `433`(A1 修复补 3) → `456`(A2/A4 新增 23)。

---

## 3. 各波次交付详情

### 3.1 波次 2a — `52c09bc`（定时摘要 + 批量增删 + 封面转存）

- **定时摘要 A1**：`monitor.html` 新增摘要配置 UI 与 `summary_state.json` 落库；前端计算 `computeSince`/`computeSummary`（北京时口径）。
- **批量增删 B1**：房间/新作列表批量勾选增删，含 UI 与后端批量接口。
- **封面转存 D1**：`transcode_covers.py`（+180 行）把外链封面转存为仓库内资源，CI 每轮执行。
- **CI**：`check.yml` 新增封面转存 step。
- **测试**：`test_phase2_a1_summary` / `test_phase2_a1_ui` / `test_phase2_b1_batch` / `test_phase2_b1_ui` / `test_phase2_common` / `test_phase2_d1_covers`。
- **规模**：10 文件，+1465 行。

### 3.2 波次 2b — `3112e36`（精细化推送前端）

- **静默 A3**：`common.py` 新增 `load_silence_cfg`/`should_skip_by_silence` + `silence_state.json`；按平台/标签静默。
- **分组标签 B2**：房间标签管理与 `resolve_channel` 路由基础（前端）。
- **批量启停 B3 / 排序 B4**：列表启停与排序控制。
- **多通道 A2（前端）/ 模板 A4（前端）**：`monitor.html` 新增 `channels`/`routes`/`templates` 配置 UI（schema 落库，CI 消费在 A2/A4 完成）。
- **`common.py`**：+141 行，承载 `resolve_channel` / `render_template` 核心函数（与前端 JS 逐字节一致）。
- **测试**：`test_phase2_a2_routes` / `a3_silence` / `a4_templates` / `b2_tags` / `b3_enabled` / `b4_sort`。
- **规模**：12 文件，+1460 行。

### 3.3 波次 2c — `ee5ff64`（数据可视化增强）

- **开播时长 C1**：`computeLiveDuration` / `computeLiveDurationAll` / `fmtDuration` / `renderDurationCard`；进行中 session 计入累计（符合设计文档 line 315「仅计入累计」）。
- **更长趋势 C2**：`applyTrendRange` / `daysCovered` 支持更长窗口。
- **详情弹层 C3**：`openRoomDetail` / `renderRoomDetail` / `closeRoomDetail`。
- **写回增强 D2**：`enhancedMerge` 合并本地意图与远端 state。
- **CSV 导出 C4**：`exportReport` / `csvField`。
- **QA 黑盒**：`qa_blackbox_2c.js`（抽取真实 `monitor.html` 内联 JS 跑 node vm）。
- **规模**：8 文件，+1865 行。
- **QA 结论**：初报 1 失败（「进行中误计入累计」）→ **主理人核查 `phase2c-design.md` line 315 原文「进行中…仅计入累计」，判定为 QA 验证准则记反，推翻误报**；另 `ghp_` 字面量命中属既有可接受机制（见 §6），非 2c 回归。定稿 **PASS**。

### 3.4 波次 A1 — `8d186a7`（定时摘要自动投递）

- **`auto_summary.py`**（+295 行）：`compute_since` / `compute_summary` / `format_summary` / `should_deliver`（五态 disabled/too_early/already_sent/cooldown/deliver）/ `load_summary_state` / `save_summary_state` / `main`。
- **CI**：`check.yml` 新增「Auto-deliver summary」step（位于封面转存后、persist 前，`continue-on-error`），persist 的 TMPD 暂存循环 6 处全部追加 `summary_state.json`（防 `git reset --hard` 冲掉 `lastSent`）。
- **`common.py`**：新增 `parse_beijing(s)`（北京时换算，`calendar.timegm((y,mo,d,h,mi,se,0,0,0)) - 8*3600`）。
- **设计文档**：`docs/a1_summary_design.md` + 类图/时序图 mermaid。
- **QA 结论**：**抓出真 Bug-A1-1** —— `main()` 成功分支 `save_summary_state` 合并语义无法删键，导致 `lastFailedAt/lastFailedSince` 落盘残留。工程师修复（增 `remove` 参数），补 3 回归用例 → **433 passed**。主理人亲跑 `test_integration_success_clears_cooldown_fields` 确证。
- **规模**：8 文件，+1516 行。

### 3.5 波次 A2/A4 — `046a75c`（CI 多通道路由 + 模板渲染打通）

- **`push_utils.py`**（+70 行）：新增 `channel_to_push_cfg(ch)`（拍平 `fields` 为 `dispatch_push` 配置）、`dispatch_event(cfg_all, ctx, title, desp)`（`resolve_channel` 选通道 → 拍平 → `dispatch_push`）。
- **`check_status.py`**（+202/-71）：开播通知按 `{platform, tag, event}` 路由，同通道多房间聚合为单条，render_body 有模板走 `render_template` 否则 legacy `format_push_desp`。
- **`check_new_posts.py`**（+56）：新作通知接入 `dispatch_event`（保留模块级薄封装兼容测试拦截点）。
- **`auto_summary.py`**（+12）：摘要投递改用多通道路由。
- **向后兼容硬约束**：legacy 仅旧 `push` 配置下 `title`/`desp` 逐字节一致、单 call、无配置优雅跳过（集成测试锁死）。
- **设计文档**：`docs/a2a4_ci_design.md`（7 项待明确默认全批准）+ 类图/时序图。
- **QA 结论**：**独立黑盒 PASS**（真实代码非镜像）。关键确认：①向后兼容锁死 ②多通道分组正确（bilibili×2→wecom 一条、douyin→bark，dispatch_push 调 2 次）③tag 标量匹配与 JS `resolveChannel` 逐字节一致 ④A4 模板渲染正确 ⑤no-config 守卫 ⑥JS↔Python 跨语言对照一致 ⑦`monitor.html`/`common.py` 零改动、无新依赖。**456 passed**。
- **规模**：9 文件，+1230 行。

---

## 4. 架构与关键技术决策

### 4.1 BLIVE_CONFIG schema 演进

阶段二最终形态：

```jsonc
{
  "push": { "type": "...", ... },          // 旧单通道（向后兼容退化路径）
  "channels": [ { "id": "wecom1", "type": "wecom", "name": "...", "fields": { "sendkey": "..." } } ],
  "routes": [ { "match": { "platform?": "bilibili", "tag?": "xxx", "event?": "live_on" }, "channelId": "wecom1" } ],
  "templates": { "live_on": "...", "new_post": "..." },
  "silence": { ... },
  "summary": { "enabled": true, "freq": "daily", "channel": "push", "sendTime": "09:00", "lastSent": 0 }
}
```

### 4.2 路由 / 模板函数（Python ↔ JS 逐字节一致）

- `common.resolve_channel(cfg_all, ctx{platform,tag,event})`：最具体优先（platform+tag+event 计分），无命中 → 默认 → 退化 `cfg['push']`。
- `common.render_template(tpl, ctx)`：替换 `{name}/{title}/{platform}/{time}/{url}`，缺字段保留占位符。
- 与 `monitor.html` 内联 JS `resolveChannel`/`renderTemplate` 逐字节一致（跨语言对照测试锁死）。

### 4.3 北京时换算

- `parse_beijing(s)`（Python）/ `parseBeijing`（JS）：`calendar.timegm((y,mo,d,h,mi,se,0,0,0)) - 8*3600`，时区无关；正则 `^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2}):(\d{2})$`；`compute_since` daily=北京今午夜、weekly=北京周一午夜。

### 4.4 CI persist 机制

- `check.yml` 每 5 分钟 `schedule` 抢推 state；`concurrency: live-check` 串行。
- `Persist state` step 用 `git reset --hard origin/master` + TMPD 暂存循环保护 `summary_state.json` 等状态文件不被重置冲掉。

---

## 5. 质量与测试总览

| 指标 | 数值 |
|---|---|
| 全量测试文件 | 41 |
| `test_` 函数数 | 432（参数化后用例 **456 passed**） |
| 阶段二新增测试文件 | 2a×6、2b×6、2c×5、A1×1、A2/A4×1，共 19 |
| QA 模式 | 独立黑盒（真实代码 + node vm 抽 JS），非工程师自测镜像 |
| 主理人抽查 | 每波次「信任但验证」——核查硬事实、纠正 QA/工程师盲区 |

**QA 关键判定记录**

| 波次 | 事件 | 处置 |
|---|---|---|
| 2c | QA 报「进行中误计入累计」 | 主理人核查设计文档 line 315「仅计入累计」→ **推翻误报**，定稿 PASS |
| 2c | `ghp_` 字面量命中 | 判定既有可接受机制、单串令牌命中 0 → 不阻断 |
| A1 | Bug-A1-1（冷却字段落盘残留） | QA 抓真 Bug → 工程师修复 + 3 回归 → PASS |
| A2/A4 | `check_new_posts` 本地重复 `dispatch_event` | 非阻塞观察项（见 §6），不阻断交付 |

---

## 6. 已知问题与观察项

| # | 项 | 状态 | 说明 |
|---|---|---|---|
| 1 | 2c 进行中口径 | ✅ 已裁定 | 设计文档 line 315「仅计入累计」为准，代码符合，误报已推翻 |
| 2 | A1 冷却字段残留 | ✅ 已修复 | `save_summary_state` 增 `remove` 参数，433 passed |
| 3 | A2/A4 `check_new_posts` 本地 `dispatch_event` 薄封装 | ⚠️ 非阻塞 | 与 `push_utils.dispatch_event` 等价，仅为兼容既有测试 monkeypatch 拦截点；建议后续收敛为统一引用 |
| 4 | 内置 PAT 暴露公开源码 | ℹ️ 已接受 | 用户已接受；`ghp_` 完整令牌单串命中契约恒为 0（推送保护仅拦过 QA 脚本明文，已移出提交） |

---

## 7. 交付物文件清单

### 源码（已推送 master）

| 文件 | 波次 | 变更 |
|---|---|---|
| `monitor.html` | 2a/2b/2c | +1865（摘要/静默/标签/启停/排序/多通道/模板/时长/趋势/详情/CSV） |
| `common.py` | 2b/A1 | +168（`resolve_channel`/`render_template`/`parse_beijing` 等） |
| `push_utils.py` | 2b/A2/A4 | +84（`dispatch_event`/`channel_to_push_cfg`） |
| `check_status.py` | 2b/A2/A4 | +230（路由分组/模板渲染） |
| `check_new_posts.py` | 2b/A2/A4 | +77（新作接入 `dispatch_event`） |
| `auto_summary.py` | A1/A2/A4 | +307（自动投递 + 多通道路由） |
| `transcode_covers.py` | 2a | +180（封面转存） |
| `.github/workflows/check.yml` | 2a/A1 | 封面转存 + Auto-deliver summary + persist 保护 |

### 测试（已推送 master）

`tests/` 下 41 个文件，阶段二新增：`test_phase2_a1_*`(2)、`test_phase2_b1_*`(2)、`test_phase2_common`、`test_phase2_d1_covers`、`test_phase2_a2_routes`/`a3_silence`/`a4_templates`/`b2_tags`/`b3_enabled`/`b4_sort`、`test_phase2_c1_duration`/`c2_trend`/`c3_detail`/`c4_export`/`d2_writeback`、`test_auto_summary`、`test_a2a4_ci`。

### 设计 / QA 文档（已推送 master）

- `docs/a1_summary_design.md` + `a1_summary_class.mermaid` + `a1_summary_sequence.mermaid`
- `docs/a2a4_ci_design.md` + `a2a4_class.mermaid` + `a2a4_sequence.mermaid`
- `qa_report_2c.md` / `qa_report_a1.md` / `qa_report_a2a4.md`
- `qa_blackbox_2c.js`（2c 黑盒脚本）
- `/workspace/phase2c-design.md`（2c 签发设计，含 line 315 口径裁定）

---

## 8. 用户下一步建议

1. **验收 A2/A4**：在 `monitor.html` 配置 `channels`/`routes`/`templates`，触发一次开播/新作，确认 CI 按路由投递到对应通道、模板正文生效。
2. **收敛观察项 #3**：将 `check_new_posts.py` 的本地 `dispatch_event` 改为直接引用 `push_utils.dispatch_event`（同步调整测试拦截点）。
3. **阶段三（多平台）**：扩展更多直播/短视频平台接入与能力。
4. **阶段四（后端 + DB）**：引入后端服务与持久化存储，替代纯静态前端直连 GitHub API 的架构。
5. **监控看板**：`docs/` 下已有 P0 健康看板/列表检索/通知可靠性等设计文档，可作为后续平台化基础。

---

> 本报告由主理人齐活林汇总，数据均取自真实仓库提交、测试运行与 QA 黑盒报告。阶段二 P0/P1/P2 全量闭环，已推送 `origin/master`。
