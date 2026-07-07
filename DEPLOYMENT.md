# 部署指南 · blive-monitor-api（Cloudflare Worker 代理）

本 Worker 作为 BFF 代理：前端（GitHub Pages 静态站）经它读写仓库 `rooms.json`，
服务端持有 GitHub 细粒度 PAT（Secret），前端仅持共享口令 `x-pass`。

---

## 一、前置条件

- 已安装 [Node.js](https://nodejs.org/)（≥ 18）
- 拥有 Cloudflare 账户，并取得 `account_id`
- 一个 **细粒度 Personal Access Token（PAT）**，仅授予 `racheko-lab/blive-monitor` 仓库的 `Contents: Read and write` 权限

---

## 二、本地安装

```bash
# 安装 wrangler（开发依赖，仅本地 / CI 使用）
npm install -D wrangler

# 校验版本
npx wrangler --version
```

---

## 三、配置 account_id

编辑 `wrangler.toml`，取消注释并填入你的 Cloudflare `account_id`：

```toml
account_id = "你的 Cloudflare 账户 ID"
```

> `account_id` 可在 Cloudflare 控制台「右侧账户信息」或 `wrangler whoami` 后获取。

---

## 四、注入 GitHub PAT（Secret，勿入库）

`GH_TOKEN` **必须** 作为 Secret 注入，绝不能写进 `wrangler.toml` 或提交到仓库：

```bash
wrangler secret put GH_TOKEN
# 按提示粘贴细粒度 PAT
```

---

## 五、本地联调

1. 复制本地环境变量模板并填入真实值：

   ```bash
   cp .dev.vars.example .dev.vars
   # 编辑 .dev.vars：填入 GH_TOKEN / PASSPHRASE
   ```

2. 启动本地 Worker：

   ```bash
   npx wrangler dev
   # 默认监听 http://localhost:8787
   ```

3. 联调验证（建议配合真实 PAT）：

   ```bash
   # 读取（需带 x-pass）
   curl -H "x-pass: change-me-shared-passphrase" http://localhost:8787/rooms

   # 添加
   curl -X POST -H "x-pass: change-me-shared-passphrase" -H "Content-Type: application/json" \
     -d '{"action":"add","platform":"bilibili","id":"123","name":"测试主播"}' \
     http://localhost:8787/rooms

   # 移除
   curl -X POST -H "x-pass: change-me-shared-passphrase" -H "Content-Type: application/json" \
     -d '{"action":"remove","platform":"bilibili","id":"123"}' \
     http://localhost:8787/rooms
   ```

---

## 六、部署到 Cloudflare

```bash
npx wrangler deploy
```

部署成功后，控制台会输出 Worker URL，形如：

```
https://blive-monitor-api.<你的子域>.workers.dev
```

记下该 URL，供前端 `monitor.html` 顶部 `API_BASE` 使用。

---

## 七、前端接入（必做）

部署后，编辑仓库根 `monitor.html`，在其 `<script>` 顶部配置区改为：

```js
// 改为你的 Worker URL
var API_BASE = "https://blive-monitor-api.<你的子域>.workers.dev";
// 与 wrangler.toml 中 [vars].PASSPHRASE 一致
var API_PASS = "change-me-shared-passphrase";
```

- `API_BASE` 为空时，前端自动隐藏「添加 / 移除」控件，保持原有只读监控能力；
- `API_PASS` 必须与 `wrangler.toml` 的 `PASSPHRASE` **完全一致**，否则返回 403。

修改后提交，GitHub Pages 会自动重新构建发布。

---

## 八、Secret 校验清单（发布前核对）

| 检查项 | 说明 | 正确示例 |
|---|---|---|
| `GH_TOKEN` | 作为 **Secret** 注入（`wrangler secret put GH_TOKEN`），不出现在 `wrangler.toml` / 仓库 | 已执行 secret put |
| `GH_TOKEN` 权限 | 仅 `racheko-lab/blive-monitor` 的 `Contents: Read and write` | 细粒度、单仓库 |
| `PASSPHRASE` | 与前端 `monitor.html` 的 `API_PASS` 完全一致 | `change-me-shared-passphrase` |
| `ALLOWED_ORIGIN` | 等于 GitHub Pages 站点地址 | `https://racheko-lab.github.io` |
| `BRANCH` | 等于仓库默认分支 | `master` |
| `GH_REPO` | 等于仓库坐标 | `racheko-lab/blive-monitor` |

---

## 九、错误码速查

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
