/**
 * B站/抖音直播监控 - Cloudflare Worker (轻量版)
 * 只负责定时触发 GitHub Action，检测逻辑仍在 check_status.py 中
 * 
 * Cron Triggers: */10 * * * *  (每10分钟)
 * 环境变量: GH_TOKEN (GitHub token)
 */
const GH_OWNER = "racheko-lab";
const GH_REPO = "blive-monitor";

export default {
  async scheduled(event, env, ctx) {
    await fetch(
      `https://api.github.com/repos/${GH_OWNER}/${GH_REPO}/actions/workflows/check.yml/dispatches`,
      {
        method: "POST",
        headers: {
          Authorization: `Bearer ${env.GH_TOKEN}`,
          Accept: "application/vnd.github+json",
        },
        body: JSON.stringify({ ref: "master" }),
      }
    );
  },

  async fetch(request, env) {
    const resp = await fetch(
      `https://api.github.com/repos/${GH_OWNER}/${GH_REPO}/actions/workflows/check.yml/dispatches`,
      {
        method: "POST",
        headers: {
          Authorization: `Bearer ${env.GH_TOKEN}`,
          Accept: "application/vnd.github+json",
        },
        body: JSON.stringify({ ref: "master" }),
      }
    );
    return new Response(
      `Triggered: ${resp.status}`, 
      { headers: { "Content-Type": "text/plain" } }
    );
  },
};
