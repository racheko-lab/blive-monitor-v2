# P0-3 通知精细化（轻量版）· 简单 PRD

> 本文档为「继续阶段1」第三棒：在 P0-1 自检心跳、P0-2 通知可靠性完成后，补齐**通知精细化**中的轻量可落地部分（@提及 + 分组/标签），将「定时摘要」「多通道路由」回退至后续迭代。

## 1. 项目信息

| 项 | 内容 |
|---|---|
| Language | 中文 |
| Programming Language | Python 3（推送/检测脚本，仅用标准库）+ 前端原生 HTML/JS（`monitor.html`，不引入框架） |
| Project Name | `p0_notify_refine` |
| 关联阶段 | 阶段1（P0-3 通知精细化子集） |
| 改动文件（预计 <10） | `push_utils.py`、`check_status.py`、`check_new_posts.py`、`monitor.html`(PUSH_FIELDS)、`tests/test_push_utils.py`（+ 可能新增 notify refine 测试） |
| 原始需求复述 | 直播/新作开播通知目前「无 @提及、分组标签弱（仅 Bark 有 group）」，重要开播易被淹没、多主播通知难以区分。需在保持现有 5 渠道语义前提下，新增 `mention` 字段与补齐 `group` 能力：wecom 支持 `<@userid>`、telegram 支持 `@username`、不支持渠道优雅降级（不报错、不破坏推送）；前端仅在对应渠道展示 mention/group 输入。定时摘要、多通道按平台路由本轮回退。 |

## 2. 产品目标

1. **重要开播可定向提醒**：用户能在开播通知里 @特定成员（值班号/群友），避免重要开播被其他消息淹没。
2. **通知可识别与可归类**：每条通知能带上「分组/标签」，使 App 内可折叠、肉眼可区分来自哪个主播/平台/账号。
3. **零破坏、零回归**：新增字段在任意渠道不得引发推送失败或报错；不支持的渠道静默降级，P0-1/P0-2 既有的健康条与可靠性能力不受影响。

## 3. 用户故事

- **As a 监控使用者**，I want 在开播通知里 @值班同事，so that 他不会漏看重要主播开播。
- **As a 多主播观察者**，I want 不同主播/平台的通知带不同标签，so that 我在 Bark/微信里能快速分辨是谁、在哪一平台开播。
- **As a 配置者**，I want 前端只在对应渠道显示 mention/group 输入框，so that 我不会误填 Bark 不支持的 @提及。
- **As a Server酱用户**，I want 即使渠道没有真提及能力，配置 mention/group 也不报错，so that 我切换渠道时无需重配。

## 4. 需求池

### P0（必须有）

| 编号 | 需求 | 验收标准 |
|---|---|---|
| P0-1 | `push_cfg` 新增 `mention` 字段；`dispatch_push` 按渠道注入 | 见 §5.1 注入矩阵；不支持渠道必须**不报错、不破坏推送** |
| P0-2 | 分组/标签轻量补齐：Bark 已有 `group`（原生）；文本渠道（wecom/telegram/serverchan/pushplus）用标题前缀 `[分组名]` 实现标签 | 配置 `group` 后，非 Bark 渠道标题变为 `[分组名] 🔴 xxx 开播了！`；Bark 仍走原生 `group` 字段 |
| P0-3 | 前端 `PUSH_FIELDS` 为支持渠道加 `mention`/`group` 输入项，且**仅在对应渠道显示** | 见 §5.3；非支持渠道不渲染输入框 |
| P0-4 | 调用方透传确认：`check_status.py` / `check_new_posts.py` 已 `dispatch_push(push_cfg, ...)` 透传完整 `push_cfg`，本 PRD 确认 `mention`/`group` 不被剥离、由 `dispatch_push` 消费 | 代码审查确认无字段裁剪；补充断言测试 |
| P0-5 | 单元测试覆盖 mention 注入、group 前缀、各渠道降级、push_cfg 透传 | 扩展 `test_push_utils.py`，覆盖 §5.1/§5.2 矩阵 |

### P1（可选，本轮回退，写进 PRD 但不默认做）

- **P1-1 定时摘要**：聚合多次开播/新作为一条周期推送（需聚合状态 + 定时触发，架构较重）。
- **P1-2 多通道按平台/账号路由**：`push_cfg` 由单 dict 变为 list，按 `platform`/`rid` 选通道（架构变动大）。
- **P1-3 关键字提及定向**：仅当标题含白名单关键字才 @提及（来自产品分析 P1-3，需与过滤体系耦合，本轮回退）。

### P2（可选，本轮回退）

- **P2-1 去重可视化**：前端展示哪些通知被去重/冷却（来自 P1-4）。

## 5. 关键设计取舍

### 5.1 @提及注入矩阵（mention 字段）

| 渠道 | mention 取值 | 注入行为 | 降级策略 |
|---|---|---|---|
| **wecom** | 企业微信 `userid`（如 `zhangsan`） | 在文本消息 content 开头注入 `<@zhangsan>`，企微内高亮提醒 | — |
| **telegram** | `@username` 或 `username` | 在文本开头注入 `@username`（Telegram 自动识别为提及） | — |
| **bark** | 任意 | **原生无提及能力** | 忽略（不报错）；前端不展示 mention 输入 |
| **serverchan** | 任意 | **无真提及** | 退化为可见文字（如正文追加一行 `提及：@xxx`），无高亮；不报错 |
| **pushplus** | 任意 | **无真提及** | 同 serverchan 退化为文字；不报错 |

**设计要点**
- 注入位置统一在 `dispatch_push` 进入重试前、或在各 `send_via_*` 内完成（推荐后者，使渠道语义局部化）：`_build_send_fn` 捕获 `mention` 并传入对应 `send_via_*`，由渠道函数决定包裹方式。
- **多提及**：`mention` 支持逗号分隔（如 `zhangsan,lisi`），注入时逐个包裹（`<@zhangsan> <@lisi>` / `@a @b`）。
- **合并推送**（多主播同轮开播）：`mention` 仅注入一次（整条消息级），不做逐主播重复提及。
- **优雅降级铁律**：任意渠道解析 `mention` 失败/为空，行为等同「无 mention」；**绝不抛异常、绝不中断 `dispatch_push`**。

### 5.2 分组/标签语义（group 字段）

| 渠道 | group 行为 |
|---|---|
| **bark** | 原生 `group` 字段，App 内折叠归类（已有，保持） |
| **wecom / telegram / serverchan / pushplus** | 标题前缀 `[{group}] `（如 `[B站] 🔴 xxx 开播了！`），纯文本标签，肉眼可区分、Bark 外渠道可折叠归类 |

**设计要点**
- `group` 为空 → 不加前缀、不传 bark group（向后兼容现有配置）。
- 合并推送时 `group` 取**首个主播的 group**（或全局固定值，见待确认 Q3）；不逐条拼接。
- 前缀格式统一为 `[分组名]`（方括号），避免与标题 emoji 冲突。

### 5.3 配置字段透传与前端展示

- **透传路径（无需改签名）**：`BLIVE_CONFIG`(secret) → `load_push_cfg` → `push_cfg` → `check_status/check_new_posts` 直接 `dispatch_push(push_cfg, title, desp)`。`mention`/`group` 作为 `push_cfg` 普通字段随配置自然到达 `dispatch_push`，调用方**无需新增参数**（P0-4 仅做代码审查确认无裁剪）。
- **前端 `PUSH_FIELDS` 调整**（monitor.html ~1192）：

| 渠道 | 新增输入项 | 标签建议 | 说明 |
|---|---|---|---|
| bark | （保持 `group`） | 分组名（App 内归类） | 不展示 mention |
| wecom | `mention` + `group` | mention: 提及成员 UserID（如 zhangsan，企微内高亮）；group: 分组标签（内容前缀 `[分组名]`） | 两个都支持 |
| telegram | `mention` + `group` | mention: 提及 @username；group: 分组标签（标题前缀） | 两个都支持 |
| serverchan | `group` | 分组标签（标题前缀，降级为文字） | 仅 group；不展示 mention |
| pushplus | `group` | 分组标签（标题前缀，降级为文字） | 仅 group；不展示 mention |

- `buildPushConfig()` 已对任意 `PUSH_FIELDS` 字段自动合并进 `cfg`，故新增 `mention`/`group` 后**无需改写入逻辑**；`mention`/`group` 均设为非必填（不影响 `req` 校验）。
- 旧配置无 `mention`/`group` 时，行为完全等同现状（向后兼容）。

### 5.4 对统一日志 / 健康条 / 去重的影响

| 既有能力 | 是否受影响 | 说明 |
|---|---|---|
| P0-1 健康条 / 自检心跳 | **否** | 本 PRD 不新增运行时状态、不改 `selfcheck`；mention/group 为配置驱动，无新健康指标 |
| P0-2 通知可靠性（SendResult / 重试 / 失败对账） | **否** | `dispatch_push` 仍返回 `SendResult`；注入在重试前完成，注入异常被 `dispatch_push` 兜底 `try/except` 收敛为 `ok=False`（与现有行为一致），不引入新失败类别 |
| 去重账本（notify_dedup） | **否** | mention/group 不改变去重 key（仍为 `live:platform_rid` / `post:...`），去重可视化不在本轮 |
| 统一日志模型（type/level/account） | **否（仅可选 debug）** | 可选在降级时 `logger.debug("mention 渠道不支持，已降级: %s", ptype)`；不新增日志 type |

## 6. 待确认问题（Open Questions）

1. **mention 语法差异**：wecom 用户应填纯 `userid`（`zhangsan`）还是完整 `<@zhangsan>`？telegram 是否允许不带 `@` 的纯 `username`？是否支持多提及（逗号分隔）？→ 影响注入包裹逻辑与前端 placeholder。
2. **本轮回退确认**：定时摘要（P1-1）、多通道路由（P1-2）、关键字提及（P1-3）是否确认本轮回退至后续迭代？（默认回退，本轮只交付 P0。）
3. **group 文案格式**：前缀用 `[分组名]` 还是 `#分组名` / `【分组名】`？合并推送时 `group` 取值策略（首个主播 / 全局固定 / 留空）？
4. **mention 降级形态**：bark/serverchan/pushplus 上是**彻底忽略**还是**退化为可见文字「@xxx」（无高亮）**？决定前端是否在这些渠道展示 mention 输入（当前 PRD 设计为「不展示」）。
5. **多主播合并推送的 mention/group**：mention 是否只注入一次、多人逗号拼接？group 合并策略（见 Q3）？
6. **serverchan/pushplus 是否展示 group 输入**：二者无原生 group，但标题前缀 `[分组名]` 作为文字仍有效；是否向用户暴露该输入（当前 PRD 设计为「暴露 group、不暴露 mention」）？

## 7. 范围与约束（重申）

- 保持现有 5 渠道语义不变；@提及在不支持渠道必须优雅降级（不报错、不破坏推送）。
- 前端仅在对应渠道显示 mention/group 输入（见 §5.3）。
- 改动文件预计 `push_utils.py` + `check_status.py` + `check_new_posts.py` + `monitor.html`(PUSH_FIELDS) + 测试，<10 文件。
- 不引入前端框架、不改动 CI 调度周期、不改动去重/健康条核心逻辑。
