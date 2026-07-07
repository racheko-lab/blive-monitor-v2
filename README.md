# 📡 B站/抖音直播监控 + 多渠道推送

一个轻量级的直播状态监控工具，支持 B站 和 抖音 平台，开播 / 新作品时自动通过多渠道（Bark / Server酱 / 企业微信 / PushPlus / Telegram）推送通知。

## ✨ 功能特性

- 🎬 **多平台支持**：同时监控 B站 和 抖音 直播间
- 🔔 **多渠道推送**：开播 / 新作品时通过 Bark / Server酱 / 企业微信 / PushPlus / Telegram 推送通知
- 📊 **直播时长统计**：记录开播时长、上次开播时间
- 📝 **历史日志**：保留最近 200 条状态变更记录
- 🔄 **合并推送**：多个主播同时开播时合并为一条通知
- 📱 **响应式页面**：手机端友好的监控页面
- 🎵 **新作品检测**：支持检测抖音新作品发布（可选）

## 📋 快速开始

### 1. 配置监控房间

编辑 `rooms.json` 文件，添加要监控的主播：

```json
[
  {
    "platform": "bilibili",
    "id": "1874913653",
    "name": "峰哥亡命天涯"
  },
  {
    "platform": "douyin",
    "id": "83134194400",
    "name": "27～"
  }
]
```

**字段说明：**
- `platform`: 平台，`bilibili` 或 `douyin`
- `id`: 直播间 ID
  - B站：直播间号（URL 中的数字，如 `https://live.bilibili.com/1874913653`）
  - 抖音：直播间 web_rid（URL 中的字符串，如 `https://live.douyin.com/83134194400`）
- `name`: 主播名称（用于显示和推送通知）

### 2. 配置推送渠道（可选）

开播 / 新作品通知支持多渠道，通过环境变量 `BLIVE_CONFIG`（JSON）配置：

```bash
# Bark（iPhone，推荐）
export BLIVE_CONFIG='{"push": {"type": "bark", "url": "https://api.day.app/你的KEY", "group": "blive"}}'

# 或 企业微信群机器人（免费无限，推荐）
export BLIVE_CONFIG='{"push": {"type": "wecom", "webhook": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxxx"}}'

# 或 Server酱 / PushPlus / Telegram（详见下方「BLIVE_CONFIG 配置项」）
```

> 也可在监控页「⚙️ 配置 → 🔔 推送渠道」里用页面直接配置：前端会用 libsodium 把配置加密后写入仓库 Secret，密钥不进公开源码。

### 3. 本地运行

```bash
# 检测一次直播状态
./run.sh

# 持续监控（每60秒检测一次）
./run.sh loop

# 检测抖音新作品
./run.sh posts

# 检测全部
./run.sh all
```

## 🚀 部署方案

### 方案一：GitHub Actions + GitHub Pages（推荐）

这是最稳定的部署方式，无需自己的服务器。

1. Fork 本仓库
2. 在仓库 Settings → Secrets and variables → Actions 中添加 Secret：
   - Name: `BLIVE_CONFIG`
   - Value: `{"push": {"type": "bark", "url": "https://api.day.app/你的KEY"}}`（不需要推送可留空 `{}`；也支持 wecom / serverchan / pushplus / telegram）
3. 启用 GitHub Pages：Settings → Pages → Source 选择 `GitHub Actions`
4. 工作流会自动每 5 分钟检测一次，并更新监控页面

**⚠️ 重要提示**：GitHub Actions 的 schedule 触发器不太稳定，可能会延迟或跳过执行。为了保证检测频率，建议配合外部定时服务使用（见下方"外部定时触发"）。

#### 外部定时触发（推荐配置）

使用 [cron-job.org](https://cron-job.org) 作为外部触发器，保证检测频率稳定：

1. 注册并登录 [cron-job.org](https://cron-job.org)
2. 点击 **CREATE CRONJOB** 创建新任务
3. 切换到 **Advanced** 高级模式，填写以下配置：

| 字段 | 值 |
|------|-----|
| **URL** | `https://api.github.com/repos/你的用户名/仓库名/actions/workflows/check.yml/dispatches` |
| **Method** | `POST` |
| **Content-Type** | `application/json` |
| **Headers** | 两行：<br>`Authorization: Bearer <你的GitHub Token>`<br>`Accept: application/vnd.github+json` |
| **Body** | `{"ref":"master"}` |
| **Schedule** | Custom → Minutes: `*/5`，其余全 `*` |
| **Notifications** | 建议打开失败邮件提醒 |

4. 点击 **TEST RUN** 测试，History 中看到 `204` 状态码即为成功
5. 点击 **CREATE** 创建任务

**如何获取 GitHub Token：**
1. 前往 GitHub → Settings → Developer settings → Personal access tokens → Tokens (classic)
2. 点击 Generate new token，勾选 `repo` 权限
3. 复制生成的 token（以 `ghp_` 开头）

> 💡 配置完成后，GitHub Actions 的 schedule 和 cron-job.org 会同时触发，形成双保险，互不冲突。

### 方案二：Netlify（最简单）

1. 打开 [Netlify Drop](https://app.netlify.com/drop)
2. 把整个文件夹拖进去
3. 获得永久链接

注意：Netlify 只提供静态页面托管，定时检测仍需配置 GitHub Actions 或其他方式。

### 方案三：Cloudflare Worker 代理（已弃用）

> ⚠️ **已弃用**：当前前端（`monitor.html`）已改为**直接调用 GitHub Contents API**，不再需要 Cloudflare Worker 代理（`*.workers.dev` 在中国大陆常被屏蔽、导致增删超时）。`cors-proxy-worker.js` 仅作为遗留参考保留，**新部署请使用「方案一」**。

把 `cors-proxy-worker.js` 的内容粘贴到 Cloudflare Workers，用于解决跨域问题。

## 📁 项目结构

```
blive-monitor/
├── check_status.py      # 直播状态检测主脚本
├── check_new_posts.py   # 抖音新作品检测脚本
├── monitor.html         # 监控页面
├── index.html           # 首页重定向
├── worker.js            # Cloudflare Worker 触发器（已弃用/遗留）
├── cors-proxy-worker.js # CORS 代理 Worker（已弃用/遗留）
├── run.sh               # 一键运行脚本
├── rooms.json           # 监控房间配置
├── status.json          # 当前状态（自动生成）
├── state.json           # 状态缓存（自动生成）
├── tracking.json        # 追踪数据（自动生成）
├── history.json         # 历史日志（自动生成）
└── .github/workflows/
    └── check.yml        # GitHub Actions 配置
```

## ⚙️ 配置说明

### 环境变量

| 变量名 | 说明 | 示例 |
|--------|------|------|
| `BLIVE_CONFIG` | JSON 格式推送配置 | `{"push": {"type": "bark", "url": "..."}}` |
| `ENABLE_POST_CHECK` | 是否启用新作品检测 | `true` / `false` |

### BLIVE_CONFIG 配置项

`BLIVE_CONFIG` 为 JSON 字符串，通过 `"push"` 段选择渠道：

```json
{"push": {"type": "bark", "url": "https://api.day.app/你的KEY", "group": "blive"}}
```

| `type` | 渠道 | 关键字段 |
|---|---|---|
| `bark` | Bark（iPhone，无限） | `url`、`group`(可选) |
| `wecom` | 企业微信群机器人（无限） | `webhook` |
| `serverchan` | Server酱（个人微信，5 条/天） | `sendkey` |
| `pushplus` | PushPlus（个人微信） | `token`、`topic`(可选) |
| `telegram` | Telegram（无限） | `token`、`chat` |

旧式 `{"sendkey": "SCTxxx"}` 仍兼容，自动按 `serverchan` 处理。

## 📱 监控页面

部署完成后，访问 `monitor.html` 即可查看监控页面：

- 🟢 直播中 / ⚫ 未开播
- 显示当前直播标题、人气值
- 显示上次开播时间、直播时长
- 历史状态变更日志

## 🔧 技术栈

- **后端**: Python 3（仅使用标准库，无需额外依赖）
- **前端**: 原生 HTML + JavaScript
- **部署**: GitHub Actions(Pages) / Netlify / Cloudflare Pages（纯静态托管；Worker 代理已弃用）
- **推送**: 多渠道（Bark / Server酱 / 企业微信 / PushPlus / Telegram）

## 📝 注意事项

### 已知限制

1. **GitHub Actions schedule 不稳定**：GitHub 的定时触发器可能会延迟或跳过执行，建议配合外部定时服务（如 cron-job.org）使用
2. **抖音直播数据稳定性**：抖音直播状态通过页面 HTML 提取，平台改版可能导致失效
3. **抖音新作品检测**：抖音作品 API 需要签名认证（X-Bogus/msToken + WebID/登录态），无登录态的请求会被风控返回空列表。脚本采用两层策略——**配置 `douyin_cookie`（登录态）后可精确检测并链接到具体作品**；未配置时退化为「作品数推测」（读取 `user/profile/other` 的 `aweme_count`，未登录亦可），作品数增加时才提示，避免误报。账号识别（用户名→`sec_uid`）只认房间主人 `anchor` 结构化字段，并带「中毒防护」校验，杜绝误监控陌生人。详见 `DEPLOYMENT.md` 的「抖音新作品检测与 douyin_cookie」「sec_uid 解析与防污染」两节。
4. **状态持久化**：状态文件每次运行提交到 Git 作为可靠后备（跨 run 不丢），并保持每 5 分钟一次持续保活（防 60 天自动停用 schedule）

### 安全提示

1. **推送密钥保密**：Bark Key / Server酱 SendKey / 企业微信 webhook / PushPlus token / Telegram token 均相当于推送密码，请勿公开或提交到代码仓库
2. **GitHub Token 权限**：创建 Personal Access Token 时只勾选必要的权限（`repo` 即可）
3. **定期轮换密钥**：建议定期更换 SendKey 和 GitHub Token，降低泄露风险

### 使用建议

1. **检测频率**：建议 5 分钟一次，过于频繁可能被平台限流
2. **监控房间数量**：建议控制在 10 个以内，避免单次检测时间过长
3. **异常处理**：如果检测失败，系统会自动重试，无需手动干预

## 🧪 本地开发 / 测试

```bash
pip install -r requirements-dev.txt     # 安装 pytest
python -m pytest -q                      # 回归测试（push_utils / check_status / check_new_posts / common）

# 本地跑一次检测
./run.sh once        # 仅直播状态
./run.sh posts       # 仅抖音新作品（需 ENABLE_POST_CHECK=true）
./run.sh all         # 两者都跑
```

后端 Python 仅依赖标准库；抖音新作品检测另需 `playwright`（见 `requirements.txt`）。

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

## 📄 许可证

MIT License
