# blive-monitor · 房间管理前端化（Worker 代理）系统设计

> 架构师：高见远（Bob）　|　基于 PRD（许清楚）+ 现有架构约束
> 目标：用户无需接触 Git/JSON，即可在前端增删 B站/抖音 监控房间；用「Worker 代理 + 服务端 PAT + 共享口令 x-pass」消除前端裸奔 PAT 风险；基于文件 sha 保证 rooms.json 写回并发安全。

---

## Part A：系统设计

### 1. 实现方案（Implementation Approach）

**核心难点**
1. 前端（GitHub Pages，纯静态）不能直接持有 PAT，否则 PAT 泄露即全网可用。
2. rooms.json 是监控真相源，且被 `check.yml` 每 5 分钟消费；写入必须并发安全，避免两人同时改互相覆盖。
3. 前端为无构建步骤的原生 JS，改动必须保持「零构建、可被 Pages 直接托管」。

**技术选型（已定，无需新增运行时依赖）**
| 关注点 | 方案 | 理由 |
|---|---|---|
| 服务端代理 | Cloudflare Worker（现代模块语法 `export default { async fetch(request, env){} }`） | 边缘运行、原生 `fetch`、可藏 PAT 于 Secret |
| GitHub 读写 | GitHub Contents API（REST），经 Worker 服务端调用 | 原生 `fetch` 即可，带 `sha` + `409` 重试保证并发安全 |
| 鉴权 | 共享口令 `x-pass` 请求头（明文存于 Worker vars，已知暴露于前端 JS，仅防随手乱改） | PRD 明确，成本极低 |
| 跨域 | Worker 显式回 `Access-Control-Allow-Origin: https://racheko-lab.github.io` + 响应 `OPTIONS` 预检 | 不用 `*`；前端跨域带自定义头必触发预检 |
| 前端 | 修改 `monitor.html`（原生 JS + 暗色主题），新增配置常量 + fetch 封装 + 表单/按钮/toast | 零构建，兼容 Pages |
| 依赖 | **运行时 0 个 npm 包**；仅 `wrangler`（devDependency）用于本地预览/部署 | 优先 Workers 原生能力，不引不必要依赖 |

**架构模式**：经典「BFF（Backend for Frontend）代理」——前端 → Worker（鉴权 + 文件锁 + 响应规整）→ GitHub Contents API。前端与 GitHub 解耦，PAT 永不出服务端。

---

### 2. 文件列表（相对路径）

```
blive-monitor/
├── api/                         # 新增：Cloudflare Worker 源码（wrangler 入口在此）
│   ├── worker.js                # 入口：router + OPTIONS 预检接线（新建）
│   ├── github.js                # GithubContentsClient：getFile / putFile / writeWithRetry（新建）
│   ├── auth.js                  # AuthGuard：verifyPass / corsHeaders / preflight（新建）
│   ├── rooms.js                 # RoomValidator：校验 / 去重键 / id→string（新建）
│   ├── handlers.js              # RoomsHandler：GET / POST 业务处理（新建）
│   └── response.js              # 统一 {code,data,message} 信封 + OPTIONS 响应（新建）
├── wrangler.toml                # 新增：Worker 配置（compatibility_date + vars）
├── .dev.vars.example            # 新增：本地 Secret 模板（GH_TOKEN 等，.dev.vars 自身 gitignore）
├── DEPLOYMENT.md                # 新增：部署步骤 + Secret 校验清单
├── assets/                      # 新增（可选拆分，见 §7 任务说明）：前端伴生脚本
│   ├── rooms-api.js             # 新增：apiGetRooms / apiAddRoom / apiRemoveRoom（fetch 封装）
│   └── rooms-ui.js              # 新增：添加表单 / 移除按钮 / 二次确认 / toast / refresh
└── monitor.html                 # 修改（非新增）：顶部配置区 + 引入脚本 + 渲染钩子
```

> 备注：Worker 全部逻辑放在 `api/`，保持仓库根整洁；`wrangler.toml` 中 `main = "api/worker.js"`。前端逻辑若用户坚持「全部内联进 monitor.html」，可把 `assets/*.js` 合并回去（不影响功能，仅牺牲可测试性）。

---

### 3. 数据结构与接口（API Schema）

**真相源 rooms.json（GitHub 仓库根）**
```jsonc
// GET 解析后的结构
Room[] = [ { "platform": "bilibili" | "douyin", "id": "String", "name": "String" } ]
```

**类图**（详见 `docs/class-diagram.mermaid`）
```mermaid
classDiagram
    class Room {
        +String platform
        +String id
        +String name
    }
    class ApiResponse~T~ {
        +Number code
        +T data
        +String message
    }
    class FileResult {
        +Room[] rooms
        +String sha
    }
    class WriteResult {
        +Room[] rooms
        +Boolean changed
        +String sha
    }
    class GithubContentsClient {
        -Object env
        +getFile(path) Promise~FileResult~
        +putFile(path, rooms, sha) Promise~String~
        +writeWithRetry(path, mutate) Promise~WriteResult~
    }
    class AuthGuard {
        +verifyPass(request, env) Response|null
        +corsHeaders(env) Object
        +preflight(cors) Response
    }
    class RoomValidator {
        +validateInput(body) ValidationResult
        +key(room) String
        +dedupe(rooms) Room[]
    }
    class RoomsHandler {
        +handle(request, env, cors) Promise~Response~
        -handleGet(env, cors) Promise~Response~
        -handlePost(request, env, cors) Promise~Response~
    }
    GithubContentsClient ..> Room : reads / writes
    GithubContentsClient ..> FileResult : returns
    GithubContentsClient ..> WriteResult : returns
    RoomsHandler ..> GithubContentsClient : uses
    RoomsHandler ..> AuthGuard : uses
    RoomsHandler ..> RoomValidator : uses
    RoomsHandler ..> ApiResponse : produces
```

**Worker HTTP 接口契约**

所有请求需带 `x-pass` 头。统一响应体：`{ "code": Number, "data": Any|null, "message": String }`，成功 `code: 0`，HTTP 状态码随错误语义变化（见下矩阵）。

#### 3.1 `GET /rooms`
- 请求头：`x-pass: <PASSPHRASE>`
- 成功 `200`：`{ "code": 0, "data": { "rooms": Room[], "sha": "abc123" }, "message": "ok" }`
- 失败：`401`（缺 x-pass）/ `403`（x-pass 错误）/ `502`（GitHub 错误）/ `504`（超时）/ `500`
- **不发起任何 GitHub 调用即可在鉴权失败时返回。**

#### 3.2 `POST /rooms`
- 请求头：`x-pass: <PASSPHRASE>`；`Content-Type: application/json`
- 请求体（JSON）：
  ```jsonc
  // 添加
  { "action": "add",    "platform": "bilibili"|"douyin", "id": "123", "name": "可选名称" }
  // 移除
  { "action": "remove", "platform": "bilibili"|"douyin", "id": "123" }
  ```
- 校验失败：`400`（见矩阵）
- `action=add`：
  - 重复（同 `platform|id` 已存在）：`200` `{ "code":0, "data":{ "rooms":Room[], "duplicate":true }, "message":"already monitored" }`（**幂等，不报错**）
  - 新增成功：`200` `{ "code":0, "data":{ "rooms":Room[], "added":true }, "message":"added" }`
- `action=remove`：
  - 不存在：`404` `{ "code":404, "data":null, "message":"room not monitored" }`
  - 移除成功：`200` `{ "code":0, "data":{ "rooms":Room[], "removed":true }, "message":"removed" }`
- 并发冲突超限：`409 { "code":409, "message":"concurrent edit conflict, retry" }`
- GitHub 错误：`502`；超时：`504`

**错误码矩阵**
| 场景 | HTTP | body.code | message |
|---|---|---|---|
| x-pass 缺失 | 401 | 401 | missing x-pass |
| x-pass 错误 | 403 | 403 | invalid x-pass |
| body 非 JSON | 400 | 400 | invalid json |
| action 非法 | 400 | 400 | action must be 'add' or 'remove' |
| platform 非法 | 400 | 400 | platform must be bilibili\|douyin |
| id 空/缺 | 400 | 400 | id required |
| 移除不存在 | 404 | 404 | room not monitored |
| 409 重试超限 | 409 | 409 | concurrent edit conflict, retry |
| GitHub 5xx/网络 | 502 | 502 | github upstream error |
| Worker 超时 | 504 | 504 | github timeout |
| 其他异常 | 500 | 500 | internal error |

**关键签名（伪代码）**
```js
// api/github.js
class GithubContentsClient {
  constructor(env) {}
  async getFile(path) -> { rooms: Room[], sha: string|null }   // 404 -> {rooms:[], sha:null}
  async putFile(path, rooms, sha) -> string                    // 抛 ConflictError(409)
  async writeWithRetry(path, mutate) -> { rooms, changed, sha } // mutate(rooms)->{rooms,changed}
}

// api/rooms.js
const RoomValidator = {
  validateInput(body) -> { ok:boolean, room?:Room, error?:string },
  key(room) -> `${platform}|${id}`,
  dedupe(rooms) -> Room[],
};

// api/auth.js
verifyPass(request, env) -> Response|null   // null=通过; 否则 401/403
corsHeaders(env) -> { "Access-Control-Allow-Origin": string, ... }
preflight(cors) -> Response                  // 204

// api/handlers.js
RoomsHandler.handle(request, env, cors) -> Promise<Response>
```

---

### 4. 程序调用流程（时序图）

完整时序见 `docs/sequence-diagram.mermaid`（含 GET / POST-add / POST-remove / 409 重试放大四张图）。以下为关键路径文字版：

**GET /rooms**
1. 前端 `GET /rooms` 带 `x-pass` → Worker。
2. `AuthGuard.verifyPass`：缺/错直接 `401`/`403` 返回，**不调 GitHub**。
3. 通过 → `GithubContentsClient.getFile("rooms.json")` → `GET api.github.com/repos/{GH_REPO}/contents/rooms.json?ref={BRANCH}`（Bearer PAT）。
4. 解码 base64→UTF-8→JSON → 返回 `{rooms, sha}`。

**POST /rooms (add)**
1. 鉴权 → 校验 `validateInput`（非法 `400`）。
2. `writeWithRetry`：`getFile` 取最新 `rooms+sha`；若 `platform|id` 已存在 → `changed:false` → 返回 `duplicate:true`（幂等）。
3. 否则追加，带 `sha` `PUT`；遇 `409` 重新 `getFile` 后重试，最多 2 次；成功返回新 `sha` 与 `added:true`。

**POST /rooms (remove)**
1. 鉴权 → 校验。
2. `writeWithRetry`：`getFile` → 过滤掉 `platform|id`；若数量未变（`changed:false`）→ `404 room not monitored`；否则 `PUT`，成功返回 `removed:true`。

**409 重试放大**：`writeWithRetry` 内含 `while` 循环，`attempt<2` 时遇 `ConflictError` 重新 `getFile` 再 `PUT`；超限抛 `ConflictError` → Handler 返回 `409`。

---

### 5. 待明确事项（Anything UNCLEAR）

| # | 待定项 | 推荐默认值（ architect 建议） |
|---|---|---|
| 1 | CORS 是否收紧到具体路径 | `Allow-Origin` 固定 `https://racheko-lab.github.io`；`Allow-Methods: GET,POST,OPTIONS`；`Allow-Headers: Content-Type,x-pass`。不开放 `*` |
| 2 | `OPTIONS` 预检是否实现 | **实现**（前端跨域带自定义头 `x-pass` 必触发预检），`Worker` 对 `OPTIONS` 直接返回 `204` + CORS 头 |
| 3 | 重复添加语义 | 返回 `200` + `data.duplicate:true`（幂等，不报错），前端 toast「已在该监控列表」 |
| 4 | 移除不存在房间 | 返回 `404`（便于前端感知异常）；但卡片来自已有列表，正常不会触发 |
| 5 | `name` 缺失默认值 | 默认等于 `id`（保证 `check.yml` 展示友好）；用户可在别处编辑（本次无编辑接口） |
| 6 | `PASSPHRASE` 存放 | 作为 `wrangler.toml [vars]`（明文，因其本就暴露于前端 JS，无保密价值）；`GH_TOKEN` 必须用 `wrangler secret put` |
| 7 | Worker 路由 base path | `/rooms`（简洁）；`worker.js` 同时兜底 `/` 返回 404 说明 |
| 8 | 冲突 UX（409 超限） | 前端 toast「并发冲突，请重试」并自动重新 `apiGetRooms()` 刷新 |
| 9 | 读路径归属 | 稳态轮询仍用同域 `rooms.json`（无鉴权、低延迟）；**仅写操作 + 写后即时刷新**走 Worker `GET /rooms`（即时一致）。见 §7 说明 |
| 10 | 审计日志(P2) | 本次仅预留 `writeAudit()` 占位（默认 no-op），不接存储；后续接 KV/日志 |
| 11 | Cloudflare 账户/部署 | 由用户执行；本设计只交付代码 + `wrangler.toml` + `DEPLOYMENT.md` |
| 12 | `GH_REPO`/`BRANCH` | `GH_REPO="racheko-lab/blive-monitor"`，`BRANCH="master"`（仓库默认分支，已确认） |

---

## Part B：任务分解

### 6. 依赖包列表（Required Packages）

```text
# 运行时：无第三方依赖（Worker 原生 fetch / Web Crypto / TextEncoder）
# 开发 / 部署：
- wrangler@^3.0.0   # Cloudflare Worker 本地开发、预览与部署 CLI（devDependency，仅本地/CI 用）
```

> 不引入任何运行时 npm 包。UTF-8/base64 用 `TextEncoder` + `atob/btoa`；超时用 `AbortController`；无加密需求（口令为明文比对）。

---

### 7. 任务列表（按依赖/实现顺序）

> 规则遵循：≤5 任务；每任务 ≥3 文件；T01 为项目基础设施；尽量独立。
> 注：前端为保持「零构建 + 可测试」，拆出 `assets/rooms-api.js`、`assets/rooms-ui.js` 两个 `<script src>` 伴生脚本；若用户要求全部内联，可合并回 `monitor.html`（功能等价）。

- **T01 · 项目基础设施（配置 + 入口 + 文档）** ｜ Priority **P0** ｜ 依赖：无
  - 源文件：`wrangler.toml`、`api/worker.js`、` .dev.vars.example`、`DEPLOYMENT.md`
  - 产出：`wrangler.toml`（compatibility_date + `[vars]`：GH_REPO/BRANCH/PASSPHRASE/ALLOWED_ORIGIN，注释说明 GH_TOKEN 用 secret）、`worker.js` 入口骨架（仅 router + OPTIONS 接线，业务留 TODO 引用 handlers）、`.dev.vars.example`（GH_TOKEN 模板）、`DEPLOYMENT.md`（部署步骤骨架）。

- **T02 · Worker 数据访问与鉴权层** ｜ Priority **P0** ｜ 依赖：无（与 T01 并行；env 变量名采用本设计约定）
  - 源文件：`api/github.js`、`api/auth.js`、`api/rooms.js`
  - 产出：`GithubContentsClient`（getFile/putFile/writeWithRetry、UTF-8 安全 base64、409 重试≤2、8s 超时 AbortController）、`AuthGuard`（verifyPass/corsHeaders/preflight）、`RoomValidator`（validateInput/key/dedupe、id→String）。

- **T03 · Worker 业务路由与响应** ｜ Priority **P0** ｜ 依赖：T01、T02
  - 源文件：`api/handlers.js`、`api/response.js`、`api/worker.js`（修改：注入 handlers 完成接线）
  - 产出：`RoomsHandler`（GET/POST，add/remove 逻辑，401/403/400/404/409/502/504）、`response.js`（统一 `{code,data,message}` 信封 + OPTIONS 响应）、`worker.js` 完成 `/rooms` 路由与错误处理接线。

- **T04 · 前端接入（monitor.html + 伴生脚本）** ｜ Priority **P0/P1** ｜ 依赖：T03（接口契约稳定）
  - 源文件：`monitor.html`（修改：配置区 + 引入脚本 + 渲染钩子）、`assets/rooms-api.js`、`assets/rooms-ui.js`
  - 产出：顶部 `API_BASE`/`API_PASS` 常量（带注释占位）；`apiGetRooms/apiAddRoom/apiRemoveRoom`（fetch 封装 + 超时）；「＋ 添加监控」表单（平台下拉/ID 必填/名称可选 + 添加前校验 + 去重提示）；卡片右上「移除」按钮（hover 变红 + 二次确认）；toast 统一反馈（含失败原因）；写后即时 `apiGetRooms()` 刷新并触发已有同域轮询重排。

- **T05 · 集成联调与部署验证** ｜ Priority **P1** ｜ 依赖：T03、T04
  - 源文件：`api/worker.js`（本地 `wrangler dev` 联调+日志）、`monitor.html`（端到端验证）、`DEPLOYMENT.md`（补充 Secret 校验清单）
  - 产出：本地用 `.dev.vars`（GH_TOKEN）+ 主理人 PAT 跑通 add/remove/refresh/toast；验证 409 重试、CORS 预检、401/403/400/404；`DEPLOYMENT.md` 补全 `wrangler secret put GH_TOKEN` 与发布步骤。

---

### 8. 共享知识（Shared Knowledge / 跨文件约定）

```text
- 房间去重键 = platform + "|" + id（如 "bilibili|123"）；比较前统一 String(id)。
- id 一律转字符串；server 端校验平台 ∈ {bilibili, douyin}。
- 统一响应体 {code, data, message}；成功 code=0，HTTP 200；错误 HTTP 状态随语义（见矩阵）。
- x-pass 缺失 -> 401；错误 -> 403；鉴权失败绝不发起 GitHub 调用。
- POST body 校验失败 -> 400（action/platform/id）。
- rooms.json 是监控真相源；写入必带 sha，遇 409 自动 getFile 后重试，最多 2 次。
- GitHub PAT 为细粒度、仅该仓库 contents:write；存于 Worker Secret（GH_TOKEN），不在前端/仓库出现。
- Worker GitHub 调用超时 8s（AbortController）；上游 5xx 有限重试 1 次。
- CORS 仅允许 https://racheko-lab.github.io；Methods=GET,POST,OPTIONS；Headers=Content-Type,x-pass。
- 写回 rooms.json 会触发 check.yml 自动重建 Pages + 开始/停止监控（最终一致）。
- UTF-8 安全 base64（中文 name）：用 TextEncoder + Uint8Array -> btoa(stringFromCharCode)。
- 稳态房间列表读：同域 rooms.json（无鉴权）；写 + 写后即时刷新：Worker GET /rooms。
- 本次范围仅 rooms.json；post_rooms.json 预留不动。
```

---

### 9. 任务依赖图（Task Dependency Graph）

```mermaid
graph TD
    T01["T01 项目基础设施<br/>(wrangler.toml, api/worker.js, .dev.vars.example, DEPLOYMENT.md)"]
    T02["T02 Worker 数据访问与鉴权层<br/>(api/github.js, api/auth.js, api/rooms.js)"]
    T03["T03 Worker 业务路由与响应<br/>(api/handlers.js, api/response.js, api/worker.js)"]
    T04["T04 前端接入<br/>(monitor.html, assets/rooms-api.js, assets/rooms-ui.js)"]
    T05["T05 集成联调与部署验证<br/>(api/worker.js, monitor.html, DEPLOYMENT.md)"]

    T01 --> T03
    T02 --> T03
    T03 --> T04
    T03 --> T05
    T04 --> T05
```

> 说明：T01 与 T02 无依赖、可并行启动；T03 收口 Worker 全部逻辑；T04 等接口契约稳定后开工；T05 依赖 Worker 与前端双双就绪。

---

## 附录：关键实现片段（签名级，非完整代码）

**wrangler.toml**
```toml
name = "blive-monitor-api"
main = "api/worker.js"
compatibility_date = "2024-09-23"
# account_id = "用户 Cloudflare 账户 ID（部署前填）"

[vars]
GH_REPO = "racheko-lab/blive-monitor"
BRANCH = "master"
PASSPHRASE = "change-me-shared-passphrase"
ALLOWED_ORIGIN = "https://racheko-lab.github.io"
# GH_TOKEN 用 secret：wrangler secret put GH_TOKEN （勿写此文件）
```

**api/worker.js（入口骨架）**
```js
import { handleRooms } from "./handlers.js";
import { corsHeaders, preflight } from "./auth.js";

export default {
  async fetch(request, env) {
    const cors = corsHeaders(env);
    if (request.method === "OPTIONS") return preflight(cors);
    const url = new URL(request.url);
    if (url.pathname === "/rooms" || url.pathname === "/rooms/") {
      return handleRooms(request, env, cors);
    }
    return new Response(JSON.stringify({ code: 404, data: null, message: "not found" }),
      { status: 404, headers: { "Content-Type": "application/json", ...cors } });
  }
};
```

**api/github.js（写回 + 409 重试核心）**
```js
export class GithubContentsClient {
  constructor(env) { this.env = env; }
  async getFile(path) { /* GET contents; 404->{rooms:[],sha:null}; base64->utf8->json */ }
  async putFile(path, rooms, sha) { /* PUT contents; 409->throw ConflictError */ }
  async writeWithRetry(path, mutate) {
    let attempt = 0;
    while (true) {
      const { rooms, sha } = await this.getFile(path);
      const res = mutate(rooms);                 // {rooms, changed}
      if (!res.changed) return { rooms: res.rooms, changed: false, sha };
      try { const newSha = await this.putFile(path, res.rooms, sha);
            return { rooms: res.rooms, changed: true, sha: newSha }; }
      catch (e) {
        if (e.name === "Conflict" && attempt < 2) { attempt++; continue; }
        throw e;
      }
    }
  }
}
```

**api/auth.js（鉴权 + CORS）**
```js
export function verifyPass(request, env) {
  const pass = request.headers.get("x-pass");
  if (!pass) return json(401, null, "missing x-pass");
  if (pass !== env.PASSPHRASE) return json(403, null, "invalid x-pass");
  return null; // 通过
}
export function corsHeaders(env) {
  return {
    "Access-Control-Allow-Origin": env.ALLOWED_ORIGIN,
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, x-pass",
    "Access-Control-Max-Age": "86400",
    "Vary": "Origin",
  };
}
export function preflight(cors) {
  return new Response(null, { status: 204, headers: cors });
}
```

**前端 monitor.html（新增配置区 + 脚本挂载，示意）**
```html
<!-- 顶部配置区：用户部署后改这两行 -->
<script>
  const API_BASE = "https://blive-monitor-api.<你的子域>.workers.dev"; // ← 改为你的 Worker URL
  const API_PASS = "change-me-shared-passphrase";                     // ← 与 wrangler PASSPHRASE 一致
</script>
<script src="assets/rooms-api.js"></script>
<script src="assets/rooms-ui.js"></script>
```
`assets/rooms-api.js` 暴露 `apiGetRooms() / apiAddRoom({platform,id,name}) / apiRemoveRoom({platform,id})`，统一带 `x-pass` 头、8s 超时、解析 `{code,data,message}`。
`assets/rooms-ui.js` 负责渲染「＋ 添加监控」表单、给卡片注入「移除」按钮 + 二次确认弹窗、toast、写后调用 `apiGetRooms()` 刷新并触发既有同域 `rooms.json` 轮询重排。
```
