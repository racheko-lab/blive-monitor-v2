// ============================================================
//  B站/抖音直播监控 - CORS 代理
//  部署到 Cloudflare Workers (免费 100,000 次/天)
// ============================================================
//  部署步骤:
//    1. 打开 https://dash.cloudflare.com/ → 注册/登录
//    2. 左侧菜单 → Workers & Pages → 创建应用程序 → 创建 Worker
//    3. 给 Worker 起个名字 (比如 live-proxy)
//    4. 把下面全部代码粘贴进去 → 点击"部署"
//    5. 得到地址: https://live-proxy.你的用户名.workers.dev/
//    6. 把这个地址填到监控页面的「自定义代理」里
// ============================================================

export default {
  async fetch(request) {
    // 从 URL 参数中获取目标地址
    const url = new URL(request.url);
    const target = url.searchParams.get('url');
    
    if (!target) {
      return new Response('Missing "url" parameter', { 
        status: 400,
        headers: { 'Access-Control-Allow-Origin': '*' }
      });
    }

    // 验证目标 URL (只允许 B站和抖音的 API)
    const allowedHosts = [
      'api.live.bilibili.com',
      'live.douyin.com',
    ];
    try {
      const targetUrl = new URL(target);
      if (!allowedHosts.some(h => targetUrl.hostname.includes(h))) {
        return new Response('Blocked host: ' + targetUrl.hostname, {
          status: 403,
          headers: { 'Access-Control-Allow-Origin': '*' }
        });
      }
    } catch(e) {
      return new Response('Invalid URL', {
        status: 400,
        headers: { 'Access-Control-Allow-Origin': '*' }
      });
    }

    // 转发请求
    const response = await fetch(target, {
      headers: {
        'User-Agent': 'Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36',
        'Referer': 'https://live.bilibili.com/',
        'Accept': 'application/json, text/html',
      }
    });

    // 添加 CORS 头，返回给浏览器
    const newHeaders = new Headers(response.headers);
    newHeaders.set('Access-Control-Allow-Origin', '*');
    newHeaders.set('Access-Control-Allow-Methods', 'GET, OPTIONS');
    
    return new Response(response.body, {
      status: response.status,
      statusText: response.statusText,
      headers: newHeaders
    });
  }
};
