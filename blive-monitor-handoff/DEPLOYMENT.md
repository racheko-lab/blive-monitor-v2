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

## 二（续）、抖音新作品检测与 `douyin_cookie`

`check_new_posts.py` 负责抖音新作品检测，由 CI 的 `ENABLE_POST_CHECK=true` 开关启用。
它采用**三层策略 + 优雅降级**，越靠前越精确：

| 优先级 | 模式 | 是否需要 Cookie | 数据来源 | 推送内容 |
|---|---|---|---|---|
| 0（首选） | **移动端精确** | ❌ 不需要 | 用移动端 UA 打开 `m.douyin.com/share/user/{sec_uid}`，其加载的**老接口** `m.douyin.com/web/api/v2/aweme/post/` **无 Cookie 即返回真实作品列表**（含 aweme_id / 描述 / 视频或图文链接） | 「🆕 X 发布了新作品」并链接到**具体作品** |
| 1 | 桌面端精确 | ✅ 需要 `douyin_cookie` | 拦截浏览器自身签名的 `aweme/v1/web/aweme/post/` 接口，返回真实作品列表（含发布时间 / 描述） | 「🆕 X 发布了新作品」并链接到**具体作品** |
| 2（兜底） | 推测模式 | ❌ 不需要 | 读取 `user/profile/other` 的 `aweme_count`（**未登录也可达**） | 「🔔 X 可能发布了新作品」并链接到**用户主页**，提示自行确认 |

> **为什么移动端老接口能「无 Cookie 精确检测」？**
> 抖音移动端分享页 `m.douyin.com/share/user/{sec_uid}` 会加载老版 Web API
> `web/api/v2/aweme/post/`，该接口**不强制 X-Bogus / a_bogus 签名与登录态**，
> 未登录即返回该账号真实作品列表（按 aweme_id 倒序、最新在前）。所有账号通用，
> 因此**无需任何 Cookie 即可精确检测新作品**——这是当前最稳的首选路径。
> 注意：该接口不返回 `create_time`，排序退化为按 `aweme_id` 数值（抖音作品 id 单调递增），
> 脚本的 `_post_is_newer` 已支持该降级。
>
> 桌面端 `aweme/v1/web/aweme/post/` 仍强制签名 + 登录态（无 Cookie 被风控返回空），
> 仅作为「已配 `douyin_cookie` 时的补充精确源」；无 Cookie 时自动退化为「作品数推测」，
> 至少不会漏得毫无动静。无论走哪条路径，都会额外捕获 `user/profile/other` 的 `unique_id`
> 供「中毒防护」校验 sec_uid 是否真对应本账号。

### 如何获取并配置 `douyin_cookie`

1. 用**已登录抖音**的桌面浏览器打开目标用户主页 `https://www.douyin.com/user/{sec_uid}`。
2. 打开 DevTools → Network，刷新页面，点任意一个 `douyin.com` 请求，
   复制 **Request Headers** 里的 `Cookie` 整串（含 `sessionid`、`sid_tt`、`ttwid`、`passport_csrf_token` 等关键字段）。
3. 二选一配置（CI 里建议用 Secret，避免明文入源码）：
   - **环境变量 `DOUYIN_COOKIE`**（推荐）：值填整串 Cookie；
   - 或写入 `BLIVE_CONFIG`：`{"push": {...}, "douyin_cookie": "<整串 Cookie>"}`。
4. 重新触发 CI 即生效；配置成功后日志会打印「已注入抖音登录 Cookie（N 条）」。

> ⚠️ **安全提醒**：Cookie 等同账号会话。仅用于自用监控，切勿泄露；若怀疑泄露，
> 到抖音 App「设置 → 账号与安全 → 登录设备管理」踢出对应设备（或重新登录使旧 Cookie 失效）。

### sec_uid 解析与防污染（账号识别的核心）

抖音的作品接口、主页接口都以 **`sec_uid`**（而非用户名）作为账号主键。脚本需要先把
`post_rooms.json` 里的 `id`（直播房号 / 用户名）换算成 `sec_uid`，才能正确打开主页、
拿到该账号自己的作品数与作品列表。这一步若算错，就会「监控了陌生人」——表现为某些账号
**永远抓不准 / 抓到别人的新作品**。

**解析顺序（越往下越不可靠，不确定时直接跳过账号，绝不瞎猜）：**

1. `id` 本身已是 `sec_uid`（以 `MS4w` 开头）→ 直接采用；
2. `post_rooms.json` 该账号已直存 `sec_uid` 字段 → 直接采用（**推荐**，见下方「前端最佳实践」）；
3. 打开直播页 `live.douyin.com/{id}`，**只从房间主人 `anchor` 结构化字段**提取 `sec_uid`
   （开播 / 离线均可，且 `anchor` 始终排在推荐流之前，是房主本人）；
4. 都拿不到（如页面未渲染、且未配 Cookie）→ 本次**跳过该账号**，避免监控陌生人。

**为什么不再用「整页第一个 MS4w」或「`/user/` 链接循环」？**
旧实现会从整页 HTML 用正则抓「第一个 `MS4w…`」，或在 DOM 里循环 `a[href*="/user/"]` 链接。
问题在于：**离线页 / 推荐流里充斥大量其他主播的 `MS4w`**，且推荐流的 `/user/` 链接可能排在房主
之前——这会让脚本误取**陌生人**的 `sec_uid`，导致该账号基线全错、把别人的新作品推给你。
现仅认房间主人的 `anchor` 字段，从根上杜绝该问题。

**实战坑：RENDER_DATA 转义形态。** 直播页 HTML 里，`anchor` 字段可能以两种形态出现：
- (A) 正常 JSON：`"anchor":{"id_str":"…","sec_uid":"MS4w…"}`；
- (B) RENDER_DATA 转义形态（引号被转义、花括号不转义）：
  `\"anchor\":{\"id_str\":\"…\",\"sec_uid\":\"MS4w…\"}`。
  注意整页里**唯一的未转义 `"anchor"`** 往往是 `<script … "anchor" nonce="">` 这种 **HTML 属性**
  （不是 JSON 对象），绝不能误匹配；真正的房主 JSON 在转义形态 (B) 里。`extract_host_sec_uid`
  已同时支持两种形态，且**只锚定 `anchor`/`roomInfo`/`owner`/`or`/`anchorInfo` 字段**，绝不对整页
  取「第一个 MS4w」。`81197422897`（昵称「整天白日梦」）正是 (B) 形态的真实案例。

**中毒防护（运行时兜底）**：即使解析逻辑回归，脚本每次抓取主页后都会用 `user/profile/other`
返回的 `unique_id` 校验「这个 `sec_uid` 是不是本账号」。若发现指向了别的账号（被推荐流污染），
本次**跳过、不推送**，并**清除已缓存的错误 `sec_uid`**，待账号下次开播或你配置 `DOUYIN_COOKIE`
后自动重新解析。基线不会被污染数据覆盖。

**前端最佳实践（彻底摆脱开播依赖）**：新前端在「添加监控」时，可用浏览器打开
`@{用户名}` 或直播页，读取房间主人 `sec_uid` 后**直接写入 `post_rooms.json` 的 `sec_uid` 字段**：

```json
[ { "id": "zhuizhuguang61", "name": "傻坏蛋于东来", "sec_uid": "MS4wLjABAAAA..." } ]
```

这样 CI 端完全无需解析、不受开播状态影响，识别 100% 可靠。

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
