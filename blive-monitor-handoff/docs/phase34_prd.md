# 阶段三 + 阶段四 合并 PRD（多平台扩展 + 后端重构）

> 产品经理：许清楚（Alice）｜ 版本：v1.0（阶段三 / 阶段四 合并）
> 关联：`docs/blive-monitor-context.md`、`docs/system_design.md`、`docs/a2a4_ci_design.md`
> 范围：阶段四（后端 + 持久化 DB，地基重构）+ 阶段三（多平台适配器，建在地基之上）
> 说明：用户要求"阶段三、阶段四一起做"。本合并文档按主理人（齐活林）的架构耦合提醒，**明确推荐"阶段四先打地基 → 阶段三在地基上长能力"的顺序**，并把依赖关系写清。默认采用"简单 PRD"风格；因阶段四偏后端，额外给出 API / 数据模型草图。

---

## 0. 项目信息

- **Language**：中文
- **Programming Language**：后端 Python（FastAPI / 轻量 ASGI，默认假设，待确认）；前端改造不在本 PRD 的 P0 范围
- **Project Name**：`phase34_backend_multiplatform`
- **原始需求复述**：用户要求把「阶段三（多平台扩展）」和「阶段四（后端 + DB）」一起做。当前架构为"静态前端 `monitor.html` 直连 GitHub API + 仓库内 JSON 当存储/传输 + CI 每 5 分钟抢推 state"。主理人提醒：阶段四是地基重构，阶段三是地基上的能力；若先铺阶段三再上阶段四，已写的平台适配器需整体改接后端 → 返工。建议顺序：阶段四先 → 阶段三后，二者解耦。

---

## 1. 两阶段依赖与推荐顺序（关键架构决策）

| 项 | 内容 |
|----|------|
| **阶段四 = 地基** | 用「后端服务 + 持久化 DB」替代「静态前端直连 GitHub API + 仓库 JSON 当存储/传输」。解决并发抢推冲突、状态容量上限、无查询能力三大痛点。 |
| **阶段三 = 能力** | 在阶段四后端之上接入更多直播/短视频平台，提供统一归一化模型与平台适配器接口。 |
| **推荐顺序** | **阶段四先 → 阶段三后**。理由：阶段三的适配器必须读写"状态 / 历史 / 配置"，这些在阶段四之后统一由后端 API/DB 提供；若先在旧静态架构上写一堆平台适配器，阶段四引入后端时这些适配器得整体改接 → 返工。 |
| **依赖关系** | 阶段三 **依赖** 阶段四（适配器输出归一化模型后，交给后端侧的 `check_status` / `check_new_posts` 等价逻辑落库；不能直接回退到仓库 JSON）。阶段四 **不依赖** 阶段三（地基可独立交付）。 |
| **解耦点** | 平台适配器全部定义/实现在"后端侧"；前端改造（静态页改调后端 API）单列后续，不在本 PRD P0。 |

> 决策结论：本合并 PRD 将阶段四列为 **P0 地基** 先行交付；阶段三的平台适配器作为"后端侧能力"在 NEW 地基上实现，二者解耦。

---

## 2. 阶段四 PRD（后端 + DB，地基）

### 2.1 产品目标

1. **摆脱 GitHub-API-as-DB 的局限**：消除 CI 每 5 分钟抢推 `state.json` 造成的并发冲突/丢失；解除仓库 JSON 无限膨胀的容量上限；提供按时间/平台/房间的历史查询能力（当前 `history.json` 仅追加、无检索）。
2. **提供稳定后端与持久化**：作为后续所有能力（含阶段三多平台）的统一地基，状态读写、历史存储、通知去重、配置管理全部走后端 API/DB。
3. **监控能力不降级**：开播/下播检测、新作检测、通知投递、摘要投递在后端等价实现，行为对齐现有 `check_status.py` / `check_new_posts.py` / `auto_summary.py`。

### 2.2 用户故事

- 作为**部署者**，我希望有一个可 Docker 部署的后端服务，以便不必依赖 GitHub Actions 抢推 JSON 来持久化状态。
- 作为**开发者**，我希望有稳定的 CRUD / 查询 API，以便前端和后续平台适配器都能统一读写状态，而不再手搓仓库 JSON。
- 作为**监控用户**，我希望能按"时间范围 / 平台 / 房间"回溯开播与推送历史，以便排查漏推/误推。
- 作为**系统**，我希望通知投递有记录与去重账本（等价现有 `notify_dedup.json`），以便避免重复推送。

### 2.3 合理默认假设（默认假设，待确认）

> 以下为推荐默认值，均需在"待确认问题"中由用户校准。

- **后端语言/框架**：Python + FastAPI（或同类轻量 ASGI 框架）。理由：与现有 Python 检测逻辑（`check_status.py` 等）同语言，可零成本迁移。
- **数据库**：SQLite（自托管零依赖、单机够用）**或** Postgres（规模化）。列为待确认项，默认推荐 SQLite 起步。
- **部署形态**：Docker 镜像 / 单文件可执行；反向代理（Nginx/Caddy）可选。
- **鉴权**：简单 token / 无（内网）。列为"待确认"，默认推荐内网部署 + 可选 Bearer token。
- **定时检测**：由后端自身 scheduler（如 APScheduler / 后台任务）跑检测，**替代** CI 抢推；GitHub 是否保留为兜底待确认。

### 2.4 核心能力 / API 草图（P0）

统一前缀 `/api/v1`。以下为草图，字段细节在实现期细化。

| 能力 | Method & Path | 说明 |
|------|---------------|------|
| 房间列表 | `GET /rooms?platform=&enabled=` | 列出监控房间（等价 `rooms.json` + `post_rooms.json` 合并视图） |
| 房间增 | `POST /rooms` | 新增监控房间 |
| 房间详情 | `GET /rooms/{id}` | 单房间详情 |
| 房间改 | `PUT /rooms/{id}` | 更新名称/标题/标签/启用态 |
| 房间删 | `DELETE /rooms/{id}` | 移除监控 |
| 状态读写 | `GET /rooms/{id}/status` | 开播/下播、最近一次开播/下播时间（等价 `state.json`） |
| 状态更新 | `PUT /rooms/{id}/status` | 写入 `live_status` / `title` / `cover` 等 |
| 新作列表 | `GET /posts?platform=&author=&since=` | 新作品列表（等价 `post_tracking.json`） |
| 新作写入 | `POST /posts` | 记录新作 |
| 历史查询 | `GET /events?room_id=&platform=&event_type=&from=&to=&limit=` | 历史记录存储与查询（时间范围/平台/房间） |
| 通知记录 | `POST /notify/log` | 通知投递记录（等价 `notify_dedup.json` 的发送账本） |
| 通知去重 | `GET /notify/dedup?key=` / `POST /notify/dedup` | 去重查询 / 标记（upsert） |
| 配置读写 | `GET /config` / `PUT /config` | `BLIVE_CONFIG` 等价物（channels/routes/templates/silence/summary） |
| 摘要状态 | `GET /summary/state` / `PUT /summary/state` | 无人值守摘要投递状态（等价 `summary_state.json`） |
| 静默状态 | `GET /silence/state` / `PUT /silence/state` | 静默期状态（等价 `silence_state.json`） |
| 手动触发 | `POST /jobs/check`（P1） | 手动触发一轮检测（替代手动跑 CI） |

### 2.5 数据模型草图（字段即可）

```text
rooms(
  id            PK,
  platform      TEXT,        -- bilibili / douyin / kuaishou / ...
  room_id       TEXT,        -- 平台侧外部 ID
  name          TEXT,
  title         TEXT,
  url           TEXT,
  tags          JSON,        -- 等价现有 tags
  enabled       BOOL,
  created_at    TS,
  updated_at    TS,
  UNIQUE(platform, room_id)
)

posts(
  id            PK,
  platform      TEXT,
  post_id       TEXT,
  author        TEXT,
  url           TEXT,
  cover         TEXT,
  published_at  TS,
  created_at    TS,
  UNIQUE(platform, post_id)
)

events_history(
  id            PK,
  room_id       FK -> rooms.id,
  platform      TEXT,
  event_type    TEXT,        -- live_on / live_off / new_post
  payload       JSON,        -- 标题/封面/摘要等快照
  occurred_at   TS
)

notify_log(
  id            PK,
  channel_id    TEXT,
  event_type    TEXT,
  target        TEXT,
  content_hash  TEXT,        -- 去重键
  sent_at       TS,
  status        TEXT         -- ok / fail
)

notify_dedup(
  key           PK,          -- 去重键（如 live:<rid> / post:<pid>）
  last_sent_at  TS,
  meta          JSON
)

config(
  key           PK,          -- 如 'blive_config'
  value         JSON,        -- channels/routes/templates/silence/summary + 阶段三 platforms
  updated_at    TS
)

summary_state( key PK, value JSON, updated_at TS )
silence_state( key PK, value JSON, updated_at TS )
```

### 2.6 迁移策略

1. **数据迁移**：一次性导入脚本 `tools/import_json_to_db.py`，读取现有 `state.json` / `history.json` / `tracking.json` / `post_tracking.json` / `post_rooms.json` / `notify_dedup.json` / `summary_state.json` / `silence_state.json` → 写入 DB（rooms / posts / events_history / notify_log / notify_dedup / config / summary_state / silence_state）。
2. **CI 改造**：`.github/workflows/check.yml` 改为"调用后端 API 触发检测"或**由后端 scheduler 自驱**（推荐后者，彻底摆脱 GitHub-API-as-DB）。CI 抢推逻辑（`merge_state.py` / `state_prune.py`）退役。
3. **前端改造（后续，不在本 PRD P0）**：`monitor.html` 及变体从"直连 GitHub API + localStorage Token"改为"调用后端 API"；前端改造单列后续阶段，本 PRD 仅定义后端契约。

### 2.7 需求池

#### P0（必须有，地基）

| 编号 | 需求 | 验收标准 |
|---|---|---|
| **P4-0.1** | 后端服务骨架（FastAPI/ASGI） | 可启动、提供 `/api/v1` 路由、含健康检查 `/healthz`。 |
| **P4-0.2** | DB 选型与建表 | 按 §2.5 建表；默认 SQLite 可跑通，Postgres 可选。 |
| **P4-0.3** | rooms CRUD | `GET/POST/PUT/DELETE /rooms` 行为对齐 `rooms.json` 增删改查。 |
| **P4-0.4** | 状态读写 | `GET/PUT /rooms/{id}/status` 等价 `state.json` 的 live_status / 最近一次。 |
| **P4-0.5** | 历史存储与查询 | `events_history` 落库；`GET /events` 支持时间范围/平台/房间过滤。 |
| **P4-0.6** | 通知记录与去重 | `notify_log` + `notify_dedup` 等价现有去重账本，去重语义不变。 |
| **P4-0.7** | 配置读写 | `GET/PUT /config` 承载 `BLIVE_CONFIG` 等价物（channels/routes/templates/silence/summary）。 |
| **P4-0.8** | 摘要/静默状态 | `summary_state` / `silence_state` 读写等价现有 JSON。 |
| **P4-0.9** | JSON→DB 迁移脚本 | `import_json_to_db.py` 一次性导入所有仓库 JSON，幂等可重跑。 |
| **P4-0.10** | 检测逻辑后端化 | `check_status` / `check_new_posts` / `auto_summary` 等价逻辑迁到后端并落库（行为不降级）。 |

#### P1（可选）

- **P4-1.1 鉴权**：Bearer token / 内网白名单。
- **P4-1.2 Docker 镜像 + 反向代理配置**：一键部署。
- **P4-1.3 前端 API 适配层**：`monitor.html` 改调后端（见 §2.6.3，列为后续）。
- **P4-1.4 手动触发接口**：`POST /jobs/check`。

#### P2（可选）

- **P4-2.1 Postgres 支持 / 多实例**：规模化与并发锁。
- **P4-2.2 健康检查与指标**：Prometheus 指标、慢查询日志。
- **P4-2.3 GitHub 兜底**：DB 不可用时回退写仓库 JSON（若保留 GitHub 作为兜底）。

#### 明确不做（本轮边界）

- 不写前端改造（P4-1.3 单列后续）。
- 不接入新平台（属阶段三）。
- 不引入与现有 `BLIVE_CONFIG` 不兼容的配置格式（保持等价迁移）。

### 2.8 待确认问题（阶段四）

1. **后端框架**：确认 FastAPI？还是 Flask / 自研 ASGI？
2. **DB 选型**：SQLite 起步，还是直接 Postgres？（影响迁移脚本与部署复杂度）
3. **部署目标**：Docker 镜像 / 单文件可执行 / 反向代理？
4. **鉴权方式**：内网无鉴权 / 简单 Bearer token / OAuth？
5. **定时检测归属**：后端 scheduler 自驱，还是保留 CI 调 API？
6. **是否保留 GitHub 作为兜底**：DB 故障时的回退策略？
7. **现有 JSON 兼容**：迁移后是否保留仓库 JSON 只读兼容，还是彻底退役？
8. **封面转存（transcode_covers）**：是否一并后端化（阶段三 P1 复用）？

---

## 3. 阶段三 PRD（多平台，建在地基上）

### 3.1 产品目标

1. **在阶段四后端之上接入更多直播/短视频平台**，提供统一归一化模型，新平台即插即用。
2. **平台适配器接口**：每个平台实现统一契约，输出归一化房间模型 / 新作模型，交给后端侧 `check_status` / `check_new_posts` 等价逻辑落库。
3. **复用现有检测逻辑**：B站/抖音现有检测经验（官方 API / 服务端 HTML / Playwright 多策略）沉淀为可扩展底座。

### 3.2 默认候选平台（默认候选，待确认首批）

> 国内优先；标注 ⚠ 的需特别注意历史技术结论（见 `docs/blive-monitor-context.md` §3）。

| 平台 | 代码 | 直播检测 | 新作检测 | 备注 |
|------|------|----------|----------|------|
| 快手 | `kuaishou` | ✅ 候选 | ✅ 候选 | 服务端 HTML / 签名 API |
| 微信视频号 | `channels` | ✅ 候选 | ✅ 候选 | 私域强、接入成本高 |
| 小红书 | `xhs` | ⚠ **直播已移除** | ✅ 可行 | 见下方风险提示 |
| 淘宝直播 | `taobao_live` | ✅ 候选 | — | 电商场景 |
| YouTube | `youtube` | 可选国际 | 可选国际 | 官方 Data API |
| Twitch | `twitch` | 可选国际 | — | 官方 Helix API |

> ⚠ **小红书风险提示（重要）**：小红书**直播监控已于 2026-07-10 从 `check_status.py` 移除，当前未支持**。根因：直播真实状态不在 SSR HTML / `__INITIAL_STATE__`，而由客户端 JS 经签名 API（`x-s`/`x-t`）填充；数据中心 IP 访问触发风控页。同类项目（如 `aio-dynamic-push`）也明确标直播检测 ❌、仅动态/笔记检测 ✅。若把小红书列入首批，建议**先只做"新作/笔记检测"（走签名 API 或 Playwright 无头），直播检测需重新评估成本**，列为待确认。

### 3.3 平台适配器接口（P0）

统一归一化模型（与前端 JS 逐字节一致的要求延续到后端字段）：

```text
# 归一化房间模型（开播状态）
RoomModel {
  platform    TEXT,   -- kuaishou / channels / xhs / taobao_live / ...
  room_id     TEXT,
  name        TEXT,
  title       TEXT,
  live_status BOOL,   -- True=直播中
  url         TEXT,
  cover       TEXT,
  tags        LIST[TEXT]
}

# 归一化新作模型
PostModel {
  platform     TEXT,
  post_id      TEXT,
  author       TEXT,
  url          TEXT,
  cover        TEXT,
  published_at TS
}
```

适配器契约（后端侧）：

```text
class PlatformAdapter:
    platform: str
    # 开播状态检测 → 返回 RoomModel
    def fetch_room_status(self, room_id: str) -> RoomModel
    # 新作检测 → 返回自 since 以来的 PostModel 列表
    def fetch_new_posts(self, author_or_room: str, since: datetime) -> list[PostModel]
    # 轮询参数（放阶段四 config）
    poll_interval: int   # 秒
    rate_limit:   dict   # 限流/退避配置
```

适配器输出统一交给后端 `check_status` / `check_new_posts` 等价逻辑（阶段四 P4-0.10 落地后）落库与触发通知，**不直接写仓库 JSON**。

### 3.4 配置扩展

各平台凭证/轮询参数放入阶段四 `config`（等价 `BLIVE_CONFIG`）。在现有 `channels` / `routes` / `templates` / `silence` / `summary` 之外新增：

```json
{
  "platforms": {
    "kuaishou":   { "enabled": true,  "credentials": {...}, "poll_interval": 300, "rate_limit": {...} },
    "channels":   { "enabled": false, "credentials": {...}, "poll_interval": 600 },
    "xhs":        { "enabled": true,  "mode": "notes_only", "credentials": {...}, "poll_interval": 900 },
    "taobao_live":{ "enabled": false, "credentials": {...}, "poll_interval": 300 }
  }
}
```

### 3.5 能力分级

- **P0**：开播状态检测 + 新作检测（适配器输出归一化模型，落库 + 触发通知）。
- **P1**：封面/标题归一化（复用 `transcode_covers` 后端化）、限流/退避统一。
- **P2**：平台专属字段扩展（如抖音橱窗、B站分区等）。

### 3.6 需求池

#### P0（必须有，建在地基上）

| 编号 | 需求 | 验收标准 |
|---|---|---|
| **P3-0.1** | 适配器接口定义 | `PlatformAdapter` 契约 + `RoomModel` / `PostModel` 归一化模型落地（§3.3）。 |
| **P3-0.2** | 快手适配器 | 开播状态 + 新作检测，输出归一化模型。 |
| **P3-0.3** | 微信视频号适配器 | 开播状态 + 新作检测。 |
| **P3-0.4** | 小红书适配器（新作优先） | ⚠ 仅做"新作/笔记检测"首批；直播检测待评估（见 §3.2 风险）。 |
| **P3-0.5** | 淘宝直播适配器 | 开播状态检测。 |
| **P3-0.6** | 凭证/轮询配置 | 各平台凭证与轮询参数接入阶段四 `config.platforms`。 |
| **P3-0.7** | 复用检测逻辑后端化 | 适配器输出交给后端 `check_status` / `check_new_posts` 等价逻辑，行为对齐。 |

#### P1（可选）

- **P3-1.1 封面/标题归一化**：复用 `transcode_covers` 后端化，统一封面转存。
- **P3-1.2 统一限流/退避**：所有适配器共享限流与退避策略。
- **P3-1.3 平台健康/降级**：单平台失效不影响其他平台检测。

#### P2（可选）

- **P3-2.1 国际平台**：YouTube / Twitch 适配器（官方 API）。
- **P3-2.2 平台专属字段**：扩展归一化模型承载平台特有信息。

#### 明确不做（本轮边界）

- 不在旧静态架构上写适配器（必须先有阶段四地基）。
- 不做小红书直播检测（除非重新评估通过，见 §3.2）。
- 不改动前端（前端改造属阶段四后续）。

### 3.7 待确认问题（阶段三）

1. **首批平台**：快手 / 视频号 / 小红书(新作) / 淘宝直播 中先做哪几个？
2. **凭证来源**：网页爬取（无头浏览器）/ 官方开放平台 API / 第三方库？各平台策略不同。
3. **检测频率与限流**：各平台轮询间隔、并发上限、退避策略？
4. **小红书范围**：是否接受"新作优先、直播暂缓"？还是要求直播一并攻克？
5. **复用确认**：阶段三适配器是否一律复用阶段四后端化后的 `check_status` / `check_new_posts` 逻辑（而非各自独立落库）？

---

## 4. 合并待确认问题清单（去重）

> 跨两阶段的关键决策点，供用户一次性校准。

**技术栈与部署（阶段四主导）**
1. 后端框架：FastAPI / Flask / 自研 ASGI？
2. 数据库：SQLite 起步 / 直接 Postgres？
3. 部署形态：Docker 镜像 / 单文件可执行 / 反向代理？
4. 鉴权方式：内网无鉴权 / Bearer token / OAuth？
5. 定时检测归属：后端 scheduler 自驱 / 保留 CI 调 API？
6. 是否保留 GitHub 作为兜底（DB 故障回退）？
7. 迁移后是否保留仓库 JSON 只读兼容 / 彻底退役？
8. 封面转存（transcode_covers）是否一并后端化？

**阶段三平台与凭证**
9. 首批平台：快手 / 视频号 / 小红书(新作) / 淘宝直播 中选哪几个？
10. 各平台凭证来源：爬取 / 官方 API / 第三方库？
11. 各平台检测频率与限流（间隔/并发/退避）？
12. 小红书范围：新作优先、直播暂缓？还是直播一并攻克（需重新评估成本）？
13. 适配器是否一律复用阶段四后端化后的统一检测逻辑？

**跨阶段耦合**
14. 交付节奏：确认"阶段四先 → 阶段三后"的解耦顺序，还是坚持并行（并行则需评估适配器返工成本）？

---

*—— 本合并 PRD 覆盖阶段四（后端 + DB 地基）与阶段三（多平台适配器，建在地基上）。不修改代码、不提交 git、不改动其他文件。*
