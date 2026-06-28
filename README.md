# B站/抖音直播监控 + 微信推送

手机打开 `monitor.html` 即可使用。

配合 Cloudflare Worker 代理实现永久稳定运行。

## 部署到 Netlify（最简单）

1. 打开 https://app.netlify.com/drop
2. 把整个文件夹拖进去
3. 获得永久链接

## 部署到 GitHub Pages

```bash
git init && git add . && git commit -m "init"
git remote add origin https://github.com/你的用户名/blive-monitor.git
git push -u origin main
# Settings → Pages → Source: main → Save
```

## 部署 Cloudflare Worker 代理

把 `cors-proxy-worker.js` 的内容粘贴到 Cloudflare Workers 即可。
