# 部署指南 · blive-monitor 前端增删监控

> **当前方案（2026-07 起）：前端直连 GitHub API，无需后端 / 域名。**
> 旧版「Cloudflare Worker 代理」（`api/` 目录）因 `*.workers.dev` 在中国大陆常被屏蔽、导致添加/删减超时，
> 已弃用并从仓库移除。下方「附录 A」保留旧 Worker 部署说明，仅供回溯。

前端（`monitor.html`）直接调用 `api.github.com` 的 Contents API 读写 `rooms.json`：
GET → 改 → 带 `sha` PUT（遇 409 重试）。GitHub PAT 由用户在页面「⚙️ 设置 Token」中填写，
**仅存于本机浏览器 `localStorage`，不进入仓库源码**。

---

## 一、用户侧配置（只需一次）

1. 打开监控页 `https://racheko-lab.github.io/blive-monitor/monitor.html`。
2. 点「⚙️ 设置 Token」，填入一个**细粒度 Personal Access Token**：
   - 创建地址：GitHub → Settings → Developer settings → **Fine-grained tokens** → Generate new token
   - 授权仓库：`racheko-lab/blive-monitor`
   - 权限：Repository permissions → **Contents: Read and write**
   - 有效期按需设置（建议 90 天或 365 天）
3. 保存后，顶部横幅显示「✅ GitHub API 可连接」。此后「＋ 添加监控」与卡片「✕」即可直连 GitHub 生效。

> 安全提示：该 Token 仅写入你本机浏览器，不会上传。建议用细粒度 Token 并仅授权本仓库，
> 不要用含 `repo` 全量权限的普通 PAT。旧的全量 PAT（曾在对话中贴出）应到
> GitHub → Settings → Developer settings 中**撤销/轮换**。

---

## 二、推送渠道配置（BLIVE_CONFIG Secret）

开播与「新作品」通知通过 **GitHub Actions Secret `BLIVE_CONFIG`** 配置，支持多通道：

| 渠道 | `type` | 关键字段 | 备注 |
|---|---|---|---|
| Bark（iPhone） | `bark` | `url`、`group`(可选) | 无限、免费；`url` 形如 `https://api.day.app/你的KEY` |
| Server酱 / 方糖 | `serverchan` | `sendkey` | 个人微信，免费 **5 条/天** |
| 企业微信群机器人 | `wecom` | `webhook` | 无限、免费，推荐 |
| PushPlus | `pushplus` | `token`、`topic`(可选) | 个人微信，免费额度较高 |
| Telegram | `telegram` | `token`、`chat` | 无限，需 BotFather 申请 token |

`BLIVE_CONFIG` 是 JSON 字符串，写法示例：

```json
{"push": {"type": "bark", "url": "https://api.day.app/你的KEY", "group": "blive"}}
```

旧式 `{"sendkey": "SCTxxxx"}` 仍兼容，会自动按 `serverchan` 处理。

**在页面上配置（推荐）**：打开「⚙️ 配置」页 → 「🔔 推送渠道」→ 选择渠道、填写对应字段 →
「保存推送配置」。前端会用 libsodium 把配置**加密**后写入仓库 Secret（`BLIVE_CONFIG`），
密钥不会出现在公开源码里；若自动写入失败，会给出 JSON 供你手动粘贴到
GitHub → Settings → Secrets → Actions → `BLIVE_CONFIG`。

**手动配置**：GitHub → Settings → Secrets → Actions → New repository secret，
Name 填 `BLIVE_CONFIG`，Secret 填上面的 JSON 字符串。

> 注意：`check_status.py`（B站/抖音开播）与 `check_new_posts.py`（抖音新作品）共用同一份
> `BLIVE_CONFIG`，改一处即可同时生效。

---

## 三、前置条件（开发 / 重新部署前端）

- 已安装 [Node.js](https://nodejs.org/)（≥ 18）
- 一个 **细粒度 PAT**，仅授予 `racheko-lab/blive-monitor` 的 `Contents: Read and write`

---

## 四、本地安装

```bash
npm install -D wrangler   # 仅在需要回溯旧 Worker 时才需要
```

---

## 五、附录 A：旧版 Cloudflare Worker 代理（已弃用）

`GH_TOKEN` **必须** 作为 Secret 注入，绝不能写进 `wrangler.toml` 或提交到仓库：

```bash
wrangler secret put GH_TOKEN
# 按提示粘贴细粒度 PAT
```

---

## 六、本地联调

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

## 七、部署到 Cloudflare

```bash
npx wrangler deploy
```

部署成功后，控制台会输出 Worker URL，形如：

```
https://blive-monitor-api.<你的子域>.workers.dev
```

记下该 URL，供前端 `monitor.html` 顶部 `API_BASE` 使用。

---

## 八、前端接入（必做）

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

## 九、Secret 校验清单（发布前核对）

| 检查项 | 说明 | 正确示例 |
|---|---|---|
| `GH_TOKEN` | 作为 **Secret** 注入（`wrangler secret put GH_TOKEN`），不出现在 `wrangler.toml` / 仓库 | 已执行 secret put |
| `GH_TOKEN` 权限 | 仅 `racheko-lab/blive-monitor` 的 `Contents: Read and write` | 细粒度、单仓库 |
| `PASSPHRASE` | 与前端 `monitor.html` 的 `API_PASS` 完全一致 | `change-me-shared-passphrase` |
| `ALLOWED_ORIGIN` | 等于 GitHub Pages 站点地址 | `https://racheko-lab.github.io` |
| `BRANCH` | 等于仓库默认分支 | `master` |
| `GH_REPO` | 等于仓库坐标 | `racheko-lab/blive-monitor` |

---

## 十、错误码速查

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
