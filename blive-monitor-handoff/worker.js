/**
 * 直播监控 - Cloudflare Worker 定时触发器
 * 每10分钟触发一次 GitHub Action
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
