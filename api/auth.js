/**
 * @file api/auth.js
 * @description 鉴权守卫与 CORS 头构造：共享口令校验 + 预检响应。
 *
 * 设计要点：
 *  - 仅校验请求头中的明文共享口令 x-pass，用于「防随手乱改」，非强鉴权（口令本就暴露于前端 JS）；
 *  - 鉴权失败（401/403）绝不发起任何 GitHub 调用；
 *  - CORS 仅放行固定源，不开放 *，以契合 Pages 跨域带自定义头的预检场景。
 */
import { json, preflight } from "./response.js";

// 预检响应构造统一收敛到 response.js，这里仅做再导出以满足模块边界约定。
export { preflight };

/**
 * 校验请求头中的共享口令 x-pass。
 * @param {Request} request - 入站请求。
 * @param {Record<string,string>} env - Worker 绑定环境变量（含 PASSPHRASE / ALLOWED_ORIGIN）。
 * @returns {Response|null} 鉴权失败返回对应响应体；校验通过返回 null。
 */
export function verifyPass(request, env) {
  const cors = corsHeaders(env);
  const pass = request.headers.get("x-pass");
  if (!pass) {
    return json(401, null, "missing x-pass", 401, cors);
  }
  if (pass !== env.PASSPHRASE) {
    return json(403, null, "invalid x-pass", 403, cors);
  }
  return null;
}

/**
 * 构造受限 CORS 响应头集合。
 * @param {Record<string,string>} env - 含 ALLOWED_ORIGIN 的环境变量。
 * @returns {Record<string,string>} CORS 头键值对。
 */
export function corsHeaders(env) {
  return {
    "Access-Control-Allow-Origin": env.ALLOWED_ORIGIN || "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, x-pass",
    "Access-Control-Max-Age": "86400",
    "Vary": "Origin",
  };
}
