/**
 * @file api/worker.js
 * @description Cloudflare Worker 入口：路由 + OPTIONS 预检接线。
 *
 * 仅暴露 /rooms（兼容尾部斜杠 /rooms/）；其余路径返回 404 信封。
 * 所有接口统一返回 {code, data, message}，并携带受限 CORS 头。
 */
import { json } from "./response.js";
import { handleRooms } from "./handlers.js";
import { corsHeaders, preflight } from "./auth.js";

export default {
  /**
   * Worker 请求入口。
   * @param {Request} request - 入站请求。
   * @param {Record<string,string>} env - Worker 绑定环境变量 / Secret。
   * @returns {Promise<Response>} 处理后的响应。
   */
  async fetch(request, env) {
    const cors = corsHeaders(env);

    // 预检优先处理，避免落到业务路由。
    if (request.method === "OPTIONS") {
      return preflight(cors);
    }

    const url = new URL(request.url);
    if (url.pathname === "/rooms" || url.pathname === "/rooms/") {
      return handleRooms(request, env, cors);
    }

    // 未知路径：统一 404 信封。
    return json(404, null, "not found", 404, cors);
  },
};
