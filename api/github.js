/**
 * @file api/github.js
 * @description GitHub Contents API 客户端：封装 GET/PUT 与基于 sha 的 409 并发重试。
 *
 * 关键保证：
 *  - UTF-8 安全的 base64 编解码（中文 name 不丢失）；
 *  - 写回必带 sha；遇 409 自动重新 getFile 后重试，最多 2 次；
 *  - GitHub 调用统一 8s AbortController 超时（超时抛 TimeoutError，网络/5xx 抛 UpstreamError）。
 */

/** 并发写冲突错误，对应 HTTP 409。 */
export class ConflictError extends Error {
  constructor(message) {
    super(message);
    this.name = "Conflict";
  }
}

/** GitHub 上游错误（网络异常 / 5xx / 非预期 4xx），对应 HTTP 502。 */
export class UpstreamError extends Error {
  constructor(message) {
    super(message);
    this.name = "Upstream";
  }
}

/** Worker 调用 GitHub 超时错误，对应 HTTP 504。 */
export class TimeoutError extends Error {
  constructor(message) {
    super(message);
    this.name = "Timeout";
  }
}

/** GitHub 调用超时阈值（毫秒）。 */
const TIMEOUT_MS = 8000;

/** GitHub Contents API 基础地址。 */
const API_BASE = "https://api.github.com";

/**
 * UTF-8 安全的 base64 编码（中文 name 不丢失）。
 * @param {string} str - 待编码字符串。
 * @returns {string} base64 文本。
 */
function b64encodeUtf8(str) {
  const bytes = new TextEncoder().encode(str);
  let bin = "";
  const CHUNK = 0x8000;
  for (let i = 0; i < bytes.length; i += CHUNK) {
    bin += String.fromCharCode.apply(null, bytes.subarray(i, i + CHUNK));
  }
  return btoa(bin);
}

/**
 * UTF-8 安全的 base64 解码。
 * @param {string} b64 - base64 文本。
 * @returns {string} 解码后的 UTF-8 字符串。
 */
function b64decodeUtf8(b64) {
  const bin = atob(b64);
  const bytes = Uint8Array.from(bin, (c) => c.charCodeAt(0));
  return new TextDecoder().decode(bytes);
}

/** 带超时的 fetch 封装，统一抛出 TimeoutError / UpstreamError。 */
async function fetchWithTimeout(url, options) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), TIMEOUT_MS);
  let resp;
  try {
    resp = await fetch(url, Object.assign({}, options, { signal: ctrl.signal }));
  } catch (err) {
    clearTimeout(timer);
    if (err && err.name === "AbortError") {
      throw new TimeoutError("github timeout");
    }
    throw new UpstreamError("github upstream error: " + (err && err.message ? err.message : "network"));
  }
  clearTimeout(timer);
  return resp;
}

/**
 * GitHub Contents API 客户端。
 */
export class GithubContentsClient {
  /**
   * @param {{GH_REPO:string, BRANCH:string, GH_TOKEN:string}} env - Worker 环境变量。
   */
  constructor(env) {
    this.env = env;
  }

  /**
   * 读取仓库内指定路径文件，解析为房间数组。
   * @param {string} path - 仓库内相对路径（如 rooms.json）。
   * @returns {Promise<{rooms: Array<object>, sha: string|null}>}
   *   404 时返回 {rooms: [], sha: null}；其余解码 base64 → UTF-8 → JSON。
   */
  async getFile(path) {
    const url = API_BASE + "/repos/" + this.env.GH_REPO +
      "/contents/" + path + "?ref=" + this.env.BRANCH;
    const resp = await fetchWithTimeout(url, {
      method: "GET",
      headers: this._authHeaders(),
    });
    if (resp.status === 404) {
      return { rooms: [], sha: null };
    }
    if (resp.status >= 500) {
      throw new UpstreamError("github upstream error");
    }
    if (!resp.ok) {
      throw new UpstreamError("github upstream error (" + resp.status + ")");
    }
    const data = await resp.json();
    const content = data.content ? data.content.replace(/\s/g, "") : "";
    const rooms = content ? JSON.parse(b64decodeUtf8(content)) : [];
    return { rooms: rooms, sha: data.sha || null };
  }

  /**
   * 写回房间数组到指定路径。
   * @param {string} path - 仓库内相对路径。
   * @param {Array<object>} rooms - 待写入的房间数组。
   * @param {string|null} sha - 当前文件 sha（新建文件传 null）。
   * @returns {Promise<string|null>} 写入后的新 sha。
   * @throws {ConflictError} 并发冲突（409）时抛出。
   * @throws {UpstreamError} GitHub 5xx / 网络异常时抛出。
   */
  async putFile(path, rooms, sha) {
    const url = API_BASE + "/repos/" + this.env.GH_REPO + "/contents/" + path;
    const body = {
      message: "chore(rooms): update monitored rooms via blive-monitor-api",
      content: b64encodeUtf8(JSON.stringify(rooms, null, 2)),
      branch: this.env.BRANCH,
    };
    // 仅当已有文件（sha 存在）时附带 sha，新建文件须省略。
    if (sha) {
      body.sha = sha;
    }
    const resp = await fetchWithTimeout(url, {
      method: "PUT",
      headers: Object.assign({ "Content-Type": "application/json" }, this._authHeaders()),
      body: JSON.stringify(body),
    });
    if (resp.status === 409 || resp.status === 404) {
      // 404 亦视为文件被他人删除导致的冲突，统一按并发冲突重试。
      throw new ConflictError("concurrent edit conflict");
    }
    if (resp.status >= 500) {
      throw new UpstreamError("github upstream error");
    }
    if (!resp.ok) {
      throw new UpstreamError("github upstream error (" + resp.status + ")");
    }
    const data = await resp.json();
    return (data && data.content && data.content.sha) || null;
  }

  /**
   * 基于 sha 的「读-改-写」重试封装，保证并发安全。
   * @param {string} path - 仓库内相对路径。
   * @param {(rooms: Array<object>) => {rooms: Array<object>, changed: boolean, [key:string]: *}} mutate
   *   纯函数：接收最新房间数组，返回修改后的数组与 changed 标记（可附带额外元信息，如 duplicate/removed）。
   * @returns {Promise<{rooms: Array<object>, changed: boolean, sha: string|null, [key:string]: *}>}
   *   若 mutate 判定未变化（changed=false）直接返回，不发起写；否则 PUT，遇 ConflictError 且重试次数 <2 时重读重试。
   * @throws {ConflictError} 重试 2 次仍冲突时抛出（对应 HTTP 409）。
   * @throws {UpstreamError|TimeoutError} GitHub 上游/超时错误向上抛出。
   */
  async writeWithRetry(path, mutate) {
    let attempt = 0;
    while (true) {
      const file = await this.getFile(path);
      const res = mutate(file.rooms);
      if (!res.changed) {
        // 未变化：直接返回（含 mutate 可能携带的元信息，如 duplicate/notFound）。
        return Object.assign({}, res, { sha: file.sha });
      }
      try {
        const newSha = await this.putFile(path, res.rooms, file.sha);
        return Object.assign({}, res, { changed: true, sha: newSha });
      } catch (e) {
        if (e instanceof ConflictError && attempt < 2) {
          attempt++;
          continue; // 重新 getFile 后重试
        }
        throw e;
      }
    }
  }

  /**
   * 构造带 Bearer PAT 的 GitHub 请求头。
   * @returns {Record<string,string>} 请求头对象。
   * @private
   */
  _authHeaders() {
    return {
      "Authorization": "Bearer " + this.env.GH_TOKEN,
      "Accept": "application/vnd.github+json",
      "User-Agent": "blive-monitor-worker",
      "X-GitHub-Api-Version": "2022-11-28",
    };
  }
}

/**
 * 审计日志占位（P2）：本次不接存储，默认 no-op。
 * @param {string} action - 操作类型（add / remove）。
 * @param {object} room - 房间对象。
 */
export function writeAudit(action, room) {
  // TODO(P2): 接入 KV / 日志服务记录写操作审计
  void action;
  void room;
}
