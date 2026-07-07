/**
 * @file api/rooms.js
 * @description 房间输入校验与去重工具（RoomValidator）。
 *
 * 共享约定：
 *  - 去重键 = platform + "|" + id（比较前统一 String(id)）；
 *  - id 一律转字符串；name 缺省等于 id；
 *  - 服务端仅接受 platform ∈ {bilibili, douyin}。
 */

/** 允许的直播平台枚举。 */
export const PLATFORMS = ["bilibili", "douyin"];

/**
 * 房间校验 / 去重工具对象。
 * @type {{
 *   validateInput: (body: object) => {ok: boolean, room?: {platform: string, id: string, name: string}, error?: string},
 *   key: (room: {platform: string, id: *}) => string,
 *   dedupe: (rooms: Array<{platform: string, id: *}>) => Array<object>
 * }}
 */
export const RoomValidator = {
  /**
   * 校验 POST body 是否合法。
   * @param {{action?:string, platform?:string, id?:*, name?:string}} body - 请求体。
   * @returns {{ok:boolean, room?:{platform:string,id:string,name:string}, error?:string}}
   *   ok 为 true 时携带规范化后的 room；否则携带人类可读 error（对应错误码矩阵的 message）。
   */
  validateInput(body) {
    if (!body || typeof body !== "object") {
      return { ok: false, error: "invalid json" };
    }
    const action = body.action;
    if (action !== "add" && action !== "remove") {
      return { ok: false, error: "action must be 'add' or 'remove'" };
    }
    const platform = body.platform;
    if (PLATFORMS.indexOf(platform) === -1) {
      return { ok: false, error: "platform must be bilibili|douyin" };
    }
    const rawId = body.id;
    if (rawId === undefined || rawId === null || String(rawId).trim() === "") {
      return { ok: false, error: "id required" };
    }
    const id = String(rawId);
    const rawName = body.name;
    const name = (rawName != null && String(rawName).trim() !== "")
      ? String(rawName).trim()
      : id;
    return { ok: true, room: { platform: platform, id: id, name: name } };
  },

  /**
   * 生成房间去重键。
   * @param {{platform:string, id:*}} room - 房间对象。
   * @returns {string} 形如 "bilibili|123" 的去重键。
   */
  key(room) {
    return room.platform + "|" + String(room.id);
  },

  /**
   * 按去重键对房间数组去重，保留首次出现者。
   * @param {Array<{platform:string, id:*}>} rooms - 原始房间数组。
   * @returns {Array<object>} 去重后的房间数组。
   */
  dedupe(rooms) {
    const seen = new Set();
    const out = [];
    const list = rooms || [];
    for (let i = 0; i < list.length; i++) {
      const k = RoomValidator.key(list[i]);
      if (!seen.has(k)) {
        seen.add(k);
        out.push(list[i]);
      }
    }
    return out;
  },
};
