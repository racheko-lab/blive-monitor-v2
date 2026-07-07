/**
 * @file api/response.js
 * @description 统一响应信封构造工具：所有 Worker 接口均返回 {code, data, message} 结构。
 *
 * 约定：
 *  - 成功 code = 0，HTTP 状态 200；
 *  - 错误 HTTP 状态随语义变化（见系统设计的错误码矩阵），body 中 code 与 HTTP 状态保持一致。
 */

/**
 * 构造统一 JSON 响应。
 * @param {number} code - 业务状态码，成功约定为 0。
 * @param {*} [data=null] - 业务数据载荷，可为任意类型或 null。
 * @param {string} [message="ok"] - 提示信息。
 * @param {number} [status] - HTTP 状态码；缺省时成功(0)取 200，其余取 code。
 * @param {Record<string,string>} [cors={}] - 附加响应头（通常为 CORS 头）。
 * @returns {Response} 携带 JSON 的响应对象。
 */
export function json(
    code,
    data = null,
    message = "ok",
    status = (code === 0 ? 200 : code),
    cors = {},
) {
  const body = JSON.stringify({ code: code, data: data, message: message });
  return new Response(body, {
    status: status,
    headers: { "Content-Type": "application/json", ...cors },
  });
}

/**
 * 构造 OPTIONS 预检响应（无正文，204）。
 * @param {Record<string,string>} cors - 由 corsHeaders 生成的 CORS 头集合。
 * @returns {Response} 204 预检响应。
 */
export function preflight(cors) {
  return new Response(null, { status: 204, headers: cors });
}
