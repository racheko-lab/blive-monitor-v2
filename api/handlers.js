/**
 * @file api/handlers.js
 * @description /rooms 业务路由处理：GET 读取、POST 增删，统一错误码与 CORS 响应。
 */
import { json } from "./response.js";
import { verifyPass, preflight } from "./auth.js";
import { RoomValidator } from "./rooms.js";
import {
  GithubContentsClient,
  ConflictError,
  UpstreamError,
  TimeoutError,
  writeAudit,
} from "./github.js";

/**
 * 处理 /rooms 请求（GET / POST / OPTIONS）。
 * @param {Request} request - 入站请求。
 * @param {Record<string,string>} env - Worker 绑定环境变量。
 * @param {Record<string,string>} cors - 已构造的 CORS 头。
 * @returns {Promise<Response>} 统一 {code, data, message} 响应。
 */
export async function handleRooms(request, env, cors) {
  // 预检直接放行，无需鉴权。
  if (request.method === "OPTIONS") {
    return preflight(cors);
  }

  // 鉴权：失败立即返回，绝不发起 GitHub 调用。
  const authErr = verifyPass(request, env);
  if (authErr) {
    return authErr;
  }

  const client = new GithubContentsClient(env);

  if (request.method === "GET") {
    try {
      const file = await client.getFile("rooms.json");
      return json(0, { rooms: file.rooms, sha: file.sha }, "ok", 200, cors);
    } catch (err) {
      return mapUpstreamError(err, cors);
    }
  }

  if (request.method === "POST") {
    let body;
    try {
      body = await request.json();
    } catch (e) {
      return json(400, null, "invalid json", 400, cors);
    }
    const v = RoomValidator.validateInput(body);
    if (!v.ok) {
      return json(400, null, v.error, 400, cors);
    }
    const room = v.room;
    const key = RoomValidator.key(room);

    try {
      if (body.action === "add") {
        const res = await client.writeWithRetry("rooms.json", (rooms) => {
          const exists = rooms.some((r) => RoomValidator.key(r) === key);
          if (exists) {
            // 幂等：已存在则不写，标记 duplicate。
            return { rooms: rooms, changed: false, duplicate: true };
          }
          return { rooms: rooms.concat([room]), changed: true, added: true };
        });
        writeAudit("add", room);
        if (res.duplicate) {
          return json(0, { rooms: res.rooms, duplicate: true }, "already monitored", 200, cors);
        }
        return json(0, { rooms: res.rooms, added: true }, "added", 200, cors);
      } else {
        const res = await client.writeWithRetry("rooms.json", (rooms) => {
          const next = rooms.filter((r) => RoomValidator.key(r) !== key);
          if (next.length === rooms.length) {
            // 数量未变：房间本就不在监控列表。
            return { rooms: rooms, changed: false, notFound: true };
          }
          return { rooms: next, changed: true, removed: true };
        });
        if (res.notFound) {
          return json(404, null, "room not monitored", 404, cors);
        }
        writeAudit("remove", room);
        return json(0, { rooms: res.rooms, removed: true }, "removed", 200, cors);
      }
    } catch (err) {
      if (err instanceof ConflictError) {
        return json(409, null, "concurrent edit conflict, retry", 409, cors);
      }
      return mapUpstreamError(err, cors);
    }
  }

  // 其余方法不被允许。
  return json(405, null, "method not allowed", 405, cors);
}

/**
 * 将 GitHub 上游异常映射为对应的 HTTP 错误响应。
 * @param {Error} err - 捕获到的异常。
 * @param {Record<string,string>} cors - CORS 头。
 * @returns {Response} 502 / 504 / 500 响应。
 */
function mapUpstreamError(err, cors) {
  if (err instanceof TimeoutError) {
    return json(504, null, "github timeout", 504, cors);
  }
  if (err instanceof UpstreamError) {
    return json(502, null, "github upstream error", 502, cors);
  }
  return json(500, null, "internal error", 500, cors);
}
