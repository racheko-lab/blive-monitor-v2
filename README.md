# 📡 B站/抖音直播监控 + 微信推送

一个轻量级的直播状态监控工具，支持 B站 和 抖音 平台，开播时自动通过微信推送通知。

## ✨ 功能特性

- 🎬 **多平台支持**：同时监控 B站 和 抖音 直播间
- 🔔 **微信推送**：开播时通过 Server酱 推送微信通知
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

### 2. 配置微信推送（可选）

1. 前往 [Server酱](https://sct.ftqq.com/) 注册并获取 SendKey
2. 设置环境变量：

```bash
export BLIVE_CONFIG='{"sendkey": "SCTxxxxxxxxxxxxxx"}'
```

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
   - Value: `{"sendkey": "SCTxxxxxxxxxxxxxx"}`（不需要推送可留空 `{}`）
3. 启用 GitHub Pages：Settings → Pages → Source 选择 `GitHub Actions`
4. 工作流会自动每 5 分钟检测一次，并更新监控页面

### 方案二：Netlify（最简单）

1. 打开 [Netlify Drop](https://app.netlify.com/drop)
2. 把整个文件夹拖进去
3. 获得永久链接

注意：Netlify 只提供静态页面托管，定时检测仍需配置 GitHub Actions 或其他方式。

### 方案三：Cloudflare Worker 代理

把 `cors-proxy-worker.js` 的内容粘贴到 Cloudflare Workers，用于解决跨域问题。

## 📁 项目结构

```
blive-monitor/
├── check_status.py      # 直播状态检测主脚本
├── check_new_posts.py   # 抖音新作品检测脚本
├── monitor.html         # 监控页面
├── index.html           # 首页重定向
├── worker.js            # Cloudflare Worker 触发器
├── cors-proxy-worker.js # CORS 代理 Worker
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
| `BLIVE_CONFIG` | JSON 格式配置 | `{"sendkey": "SCTxxx"}` |
| `ENABLE_POST_CHECK` | 是否启用新作品检测 | `true` / `false` |

### BLIVE_CONFIG 配置项

```json
{
  "sendkey": "SCTxxxxxxxxxxxxxx"  // Server酱 SendKey，用于微信推送
}
```

## 📱 监控页面

部署完成后，访问 `monitor.html` 即可查看监控页面：

- 🟢 直播中 / ⚫ 未开播
- 显示当前直播标题、人气值
- 显示上次开播时间、直播时长
- 历史状态变更日志

## 🔧 技术栈

- **后端**: Python 3（仅使用标准库，无需额外依赖）
- **前端**: 原生 HTML + JavaScript
- **部署**: GitHub Actions / Netlify / Cloudflare Workers
- **推送**: Server酱（微信推送）

## 📝 注意事项

1. **抖音数据稳定性**：抖音直播状态通过页面 HTML 提取，平台改版可能导致失效
2. **检测频率**：GitHub Actions 免费版建议不低于 5 分钟一次
3. **API 限制**：频繁请求可能被平台限流，请合理设置检测间隔
4. **状态持久化**：GitHub Actions 使用 Cache 保存状态，可能偶尔丢失

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

## 📄 许可证

MIT License
