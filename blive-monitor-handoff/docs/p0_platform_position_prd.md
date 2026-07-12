# P0 平台定位决策落地 PRD（P0-5）

> 阶段 0（commit `bbc123f`）已「正式放弃小红书」并完成主要文档/命名对齐；本 PRD 负责把这一**决策落地为前端可见的产品事实**，并清理残留幽灵引用。属阶段 1「继续」的 P0-5 收尾。

---

## 一、项目信息

| 项 | 内容 |
|---|---|
| Language | 中文 |
| 技术栈 | 前端 `monitor.html`（原生 HTML/CSS/JS，无框架）；CI `.github/workflows/check.yml`（GitHub Actions + Python 3.11） |
| Project Name | `blive-monitor`（仓库名本轮回退**不改**；目标是「对内对齐已完成 → 对外可见固化」） |
| 关联阶段 | P0-1/2/3/4 已完成；本轮 P0-5 收尾 |

**原始需求复述**：将「正式放弃小红书、仅支持 B站/抖音」这一已在阶段 0 完成的决策，固化到前端可见界面，并清理 workflow 中无用的小红书死代码；最终 grep 全仓确认无「小红书已实现/已验证/15 单测」等幽灵声明。轻量、可控、不改监控/推送逻辑。

---

## 二、产品定义

### 2.1 产品目标（Product Goals，3 个、正交）

1. **消除幽灵功能信任隐患**：让「支持 B站/抖音、小红书已放弃」成为用户打开页面即可确认的产品事实，而非仅存在于内部文档与代码注释。
2. **前端固化平台定位**：在配置页提供简洁、明确的「支持平台」矩阵，一眼可辨各平台支持状态，杜绝因仓库名 `blive-monitor` 与旧印象造成的对外误导。
3. **清理残留死代码、守住一致性**：移除 workflow 中无用的小红书判断步骤，并以自动化测试锁定全仓无自相矛盾的幽灵声明，防止未来回潮。

### 2.2 用户故事（User Stories）

- **访客 / 潜在使用者**：As a visitor，I want 打开页面就能看到「本项目支持哪些平台、小红书是否支持」，so that 我不会误以为它支持小红书而错误选用或质疑项目可信度。
- **仓库维护者**：As a maintainer，I want workflow 里没有「检查小红书房间」这类死代码与误导性注释，so that 未来不会因为加错字段而误触发 chromium 安装或让人误以为小红书可用。
- **贡献者**：As a contributor，I want 有一份明确、被测试守护的平台定位声明，so that 我提 PR 时不会误把小红书当作「待实现平台」去补解析器。

---

## 三、需求池（Requirements Pool）

### P0 — 必须有（前端可见固化 + 轻量清理 + 测试守护）

| ID | 需求 | 验收标准（可度量） | 影响面 |
|---|---|---|---|
| P0-1 | 前端「支持平台」区块固化 | `monitor.html` 配置页新增 `id="supportedPlatforms"` 卡片；含 B站/抖音「已支持」与小红书「已放弃，不计划支持」三行；文案不含「计划支持/即将支持」等歧义词 | 仅前端展示 |
| P0-2 | 清理 workflow 死代码 | `.github/workflows/check.yml` 移除 `Check xhs rooms` 步骤（id: xhslist）；同步移除 L57/L65 中对 `steps.xhslist.outputs.enabled` 的引用，Playwright 安装条件仅保留 `steps.postlist.outputs.enabled == 'true'` | 仅 CI |
| P0-3 | 一致性复核 + 自动化守护 | 新增 `tests/test_platform_position.py`：① 前端含支持平台区块与「已放弃」标记；② `rooms.json` 无 `platform=='xhs'`；③ `check.yml` 无 `Check xhs rooms`/`xhslist`；④ 全仓（除 `product_analysis.md` 分析文档）无「15 passed/15 单测/补了行业空白/已端到端验证/test_check_xhs」等幽灵声明 | 测试 |

### P1 — 可选（本期**不默认做**，写入 PRD 供后续决策）

| ID | 需求 | 说明 | ROI |
|---|---|---|---|
| P1-1 | 平台 adapter 扩展点 | 抽象 platform handler，为未来加平台留统一接口 | 当前仅 2 平台，抽象收益低，建议暂缓 |

### P2 — 不推荐

| ID | 需求 | 说明 |
|---|---|---|
| P2-1 | 小红书重做 | 移除理由（短链易变、IP 风控、维护成本高）成立，重做 ROI 存疑，**不推荐** |

---

## 四、关键设计取舍

### 4.1 支持平台区块放哪

- **主推方案**：放在「⚙️ 配置」页**顶部第一个 `.room` 卡片**（现有顺序：GitHub Token → 连接与检测 → 手动触发 → 推送渠道）。理由：配置页是「项目能力说明」最自然的归属，且改动最小、不与直播列表的过滤 chip 混淆。
- **备选（待确认）**：在「📺 直播」tab 顶部加一条常驻 banner 副本（更显眼，但可能增加首屏噪声）。
- **不建议**：复用现有直播过滤 chip（bilibili/douyin）旁加小红书——chip 是「筛选已有房间」语义，加「已放弃」平台会引发「为何筛不到」困惑。

### 4.2 文案如何表述「已放弃」不带歧义

- 核心原则：**只用终态词，不用过渡词**。明确写「**已放弃，不计划支持**」，禁用「计划支持 / 即将上线 / 敬请期待 / 开发中」。
- 对小红书行：标注「曾尝试（2026-07-10 已移除）」+ 一句根因（短链每次开播都变、数据中心 IP 触发风控、维护成本高），既说明「为什么没有」，又避免被误读为「即将补回」。
- B站/抖音行：用「✅ 已支持」明确正向状态，与小红书行形成强对比，消除「是不是都还在做」的模糊感。

### 4.3 workflow 死代码：直接删 vs 预留注释段

- **主推：直接移除**（主理人倾向）。`Check xhs rooms` 当前恒为 `enabled=false`（无 xhs 房间），是纯死代码；其唯一「价值」是「未来恢复小红书时自动装 chromium」，但既然已正式放弃且 P2 不推荐，该预留只会误导。移除后 Playwright 安装条件仅依赖 `postlist`。
- **备选**：改为明确注释的预留段（保留步骤但加 `## 预留：小红书已放弃，本段恒 false` 注释）。不推荐——保留死代码等于保留误导源，与「消除幽灵功能」目标相悖。

---

## 五、UI 设计草案（支持平台区块）

**位置**：配置页顶部，作为第一个 `.room` 卡片，`id="supportedPlatforms"`。
**复用样式**：沿用现有 `.room` / `.panel-head` 视觉，不引入新组件库；仅需少量内联/既有 CSS（如状态色 dot）。

**内容（建议文案，可直接落地）**：

```
📡 支持平台
本项目当前支持以下平台的直播监控。平台定位已正式确定，无隐藏能力。

  平台                | 监控范围            | 状态
  🟢 B站（哔哩哔哩）   | 直播开播            | 已支持
  🟢 抖音             | 直播开播 + 新作品    | 已支持
  🔴 小红书           | 直播（曾尝试）       | 已放弃，不计划支持

小红书直播监控已于 2026-07-10 从代码中移除：开播短链每次都变、数据中心 IP 触发风控，
维护成本高且误判/漏推难根除。当前专注 B站 / 抖音，如需恢复需重新评估上述成本。
```

**少量 CSS（可选，增强可读性）**：为状态列加 `.pf-dot` 圆点（绿/红），或复用现有 `--bili` / 红色变量；纯展示，不新增交互逻辑。

---

## 六、对现有监控 / 推送 / 健康条的影响

| 模块 | 影响 | 说明 |
|---|---|---|
| 监控逻辑（`check_status.py` / `check_new_posts.py`） | **无** | 支持平台区块纯展示，不改动任何检测/解析分支 |
| 推送逻辑（`push_utils.py` / `dispatch_push`） | **无** | 不涉及推送渠道与触发 |
| 健康条（P0-1 自检四态） | **无** | 区块位于配置页，不参与 `calcFreshness` 渲染；不影响 ok/warn/stale/fail |
| CI 运行 | **轻微正面** | 移除死代码后，`Install Playwright` 步骤条件更清晰，无无效判断 |
| 前端体积 | **可忽略** | 仅新增一个静态卡片 + 数行 CSS |

---

## 七、一致性复核与测试方案

**全仓 grep 复核口径**（本轮回退只复核 + 补漏，阶段 0 已改）：
- 重点排查幽灵声明 token：`15 passed` / `15 单测` / `补了行业空白` / `已端到端验证` / `test_check_xhs` / `已实现小红书`。
- **排除 `docs/product_analysis.md`**：该文档是「问题分析」，正文即以「实际这些全部不存在于当前代码」否定前述虚假声明，属于合法引用，不应被误判。
- 已确认现状：README、blive-monitor-context.md、live-monitor-detection-landscape.md 均仅以「未支持/已移除」语境提及小红书；check_status.py 的提及均为「已移除」标注。

**新增 `tests/test_platform_position.py` 断言项**：
1. `test_frontend_has_supported_platforms_block`：`monitor.html` 含 `id="supportedPlatforms"`，且同时含「已支持」（B站/抖音）与「已放弃，不计划支持」（小红书）标记。
2. `test_rooms_no_xhs`：`rooms.json` 无任何 `platform == 'xhs'` 条目。
3. `test_workflow_no_xhs_dead_step`：`check.yml` 不含 `Check xhs rooms` 与 `xhslist`（固化 P0-2 清理，防止回潮）。
4. `test_no_ghost_claims`：扫描 README + `docs/blive-monitor-context.md` + `docs/live-monitor-detection-landscape.md`（排除 product_analysis.md），不含上述幽灵声明 token。
5. `test_check_status_no_xhs_branch`（重申）：`check_status.py` 无 `fetch/parse/query_xiaohongshu` 等实现函数，且任何 xhs 提及均带「已移除/未支持」标注。

---

## 八、待确认问题（Open Questions）

1. **支持平台区块位置**：配置页顶部（推荐）？还是直播 tab 常驻 banner？或两者都加？——影响前端改动范围，需主理人拍板。
2. **是否本轮回退 P1-1 adapter 扩展点**：当前仅 2 平台，ROI 低，倾向暂缓；请确认本期只做 P0。
3. **小红书文案口径**：是否需附移除根因（短链易变/IP 风控）？——PRD 默认附一句，若嫌长可精简。
4. **workflow 直接删 vs 预留注释段**：主理人倾向直接删；请最终确认，以免实现时留预留段。

---

## 九、文件改动清单（约束：文件数 < 10）

| 文件 | 改动类型 | 说明 |
|---|---|---|
| `monitor.html` | 修改 | 配置页顶部新增支持平台区块（HTML + 少量 CSS） |
| `.github/workflows/check.yml` | 修改 | 移除 `Check xhs rooms` 步骤及两处引用（P0-2） |
| `tests/test_platform_position.py` | 新增 | 平台定位 + 无幽灵声明回归（P0-3） |
| `docs/p0_platform_position_prd.md` | 新增 | 本 PRD |

> 不改动：`check_status.py`、`check_new_posts.py`、`push_utils.py`、`rooms.json`（已干净）、`README.md`（已对齐）。本次**不提交 git、不改业务代码**。
