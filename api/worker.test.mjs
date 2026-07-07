/**
 * @file api/worker.test.mjs
 * @description 集成测试：Cloudflare Worker 房间管理代理
 *
 * 覆盖用例：鉴权 / 校验 / OPTIONS 预检 / 添加-新增 / 添加-幂等 /
 *          移除-成功 / 移除-不存在 / UTF-8 安全 / 409 重试 / 统一信封。
 *
 * 运行： node /workspace/blive-monitor/api/worker.test.mjs
 *
 * 说明：不使用真实 GitHub PAT。通过覆盖全局 global.fetch 模拟 GitHub
 *       Contents API；env 为构造的测试环境变量。
 */

import { describe, it, beforeEach, afterEach } from "node:test";
import assert from "node:assert";

import worker from "./worker.js";
import { RoomValidator } from "./rooms.js";
import { verifyPass, corsHeaders } from "./auth.js";

// ---------------------------------------------------------------------------
// 测试环境
// ---------------------------------------------------------------------------
const env = {
  GH_REPO: "racheko-lab/blive-monitor",
  BRANCH: "master",
  GH_TOKEN: "test-token",
  PASSPHRASE: "test-pass",
  ALLOWED_ORIGIN: "https://racheko-lab.github.io",
};

// UTF-8 安全 base64（与业务代码 github.js 中算法等价），用于构造与校验 mock 数据。
function b64encode(str) {
  const bytes = new TextEncoder().encode(str);
  let bin = "";
  for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
  return btoa(bin);
}
function b64decode(b64) {
  const bin = atob(b64);
  const bytes = Uint8Array.from(bin, (c) => c.charCodeAt(0));
  return new TextDecoder().decode(bytes);
}

// 构造一个请求对象（Node 22 原生 Request）
function makeRequest(method, body, headers = {}) {
  const h = { ...headers };
  if (method === "POST") h["Content-Type"] = h["Content-Type"] || "application/json";
  const opts = { method, headers: h };
  if (body !== undefined) {
    opts.body = typeof body === "string" ? body : JSON.stringify(body);
  }
  return new Request("https://api.example.com/rooms", opts);
}

// 「一旦被调用即抛错」的 fetch：用于断言鉴权失败时不发起任何 GitHub 调用。
function throwingFetch(msg) {
  return async () => {
    throw new Error(msg);
  };
}

/**
 * 模拟 GitHub Contents API。
 * - GET：文件存在返回 {content, sha}；404 视为无文件（{rooms:[], sha:null}）
 * - PUT：校验 sha（与当前一致则成功并返回新 sha；不一致则 409）；
 *        可注入一次或多次 409 以测试 writeWithRetry 重试；
 *        无文件（sha=null）时视为新建，接受任意 sha。
 * @param {Array} initialRooms 初始房间列表
 * @param {{existing?:boolean, inject409?:number}} [opts]
 */
function makeGithubMock(initialRooms, opts = {}) {
  const hasFile = opts.existing || (initialRooms && initialRooms.length > 0);
  const store = {
    rooms: initialRooms ? initialRooms.slice() : [],
    sha: hasFile ? "v1" : null,
  };
  if (store.sha) store.content = b64encode(JSON.stringify(store.rooms, null, 2));
  let inject409 = opts.inject409 || 0;
  const calls = [];

  const fetchFn = async (url, init = {}) => {
    calls.push({ method: init.method, url, body: init.body });
    if (init.method === "GET") {
      if (store.sha == null) {
        return new Response(JSON.stringify({ message: "Not Found" }), { status: 404 });
      }
      return new Response(JSON.stringify({ content: store.content, sha: store.sha }), { status: 200 });
    }
    if (init.method === "PUT") {
      const body = JSON.parse(init.body);
      if (inject409 > 0) {
        inject409--;
        return new Response(JSON.stringify({ message: "Conflict" }), { status: 409 });
      }
      // 已有文件时必须带正确 sha，否则视为并发冲突
      if (store.sha != null && body.sha !== store.sha) {
        return new Response(JSON.stringify({ message: "Conflict" }), { status: 409 });
      }
      const newSha = "sha-" + Math.random().toString(36).slice(2, 10);
      store.content = body.content;
      store.sha = newSha;
      return new Response(JSON.stringify({ content: { sha: newSha } }), { status: 200 });
    }
    return new Response("method not allowed", { status: 405 });
  };

  return { fetch: fetchFn, calls, store };
}

let originalFetch;
beforeEach(() => {
  originalFetch = global.fetch;
});
afterEach(() => {
  global.fetch = originalFetch;
});

// ---------------------------------------------------------------------------
// 1. 鉴权
// ---------------------------------------------------------------------------
describe("1. 鉴权", () => {
  it("1a GET 缺 x-pass → 401 且未调用 GitHub", async () => {
    global.fetch = throwingFetch("GitHub fetch 不应在 401 时被调用");
    const res = await worker.fetch(makeRequest("GET"), env);
    assert.strictEqual(res.status, 401);
    const body = await res.json();
    assert.strictEqual(body.code, 401);
    assert.strictEqual(body.message, "missing x-pass");
    assert.strictEqual(res.headers.get("Access-Control-Allow-Origin"), env.ALLOWED_ORIGIN);
  });

  it("1b POST 缺 x-pass → 401 且未调用 GitHub", async () => {
    global.fetch = throwingFetch("GitHub fetch 不应在 401 时被调用");
    const res = await worker.fetch(
      makeRequest("POST", { action: "add", platform: "bilibili", id: "1" }),
      env,
    );
    assert.strictEqual(res.status, 401);
    const body = await res.json();
    assert.strictEqual(body.code, 401);
    assert.strictEqual(res.headers.get("Access-Control-Allow-Origin"), env.ALLOWED_ORIGIN);
  });

  it("1c 错误 x-pass → 403 且带 CORS 头", async () => {
    global.fetch = throwingFetch("GitHub fetch 不应在 403 时被调用");
    const res = await worker.fetch(makeRequest("GET", undefined, { "x-pass": "wrong" }), env);
    assert.strictEqual(res.status, 403);
    const body = await res.json();
    assert.strictEqual(body.code, 403);
    assert.strictEqual(body.message, "invalid x-pass");
    assert.strictEqual(res.headers.get("Access-Control-Allow-Origin"), env.ALLOWED_ORIGIN);
  });

  it("1d 正确 x-pass → 通过（GET 200）", async () => {
    const mock = makeGithubMock([{ platform: "bilibili", id: "1", name: "a" }]);
    global.fetch = mock.fetch;
    const res = await worker.fetch(
      makeRequest("GET", undefined, { "x-pass": env.PASSPHRASE }),
      env,
    );
    assert.strictEqual(res.status, 200);
    const body = await res.json();
    assert.strictEqual(body.code, 0);
    assert.ok(Array.isArray(body.data.rooms));
    assert.strictEqual(body.data.sha, "v1");
  });
});

// ---------------------------------------------------------------------------
// 2. 校验
// ---------------------------------------------------------------------------
describe("2. 校验", () => {
  async function expect400(body, message) {
    const mock = makeGithubMock([], { existing: true });
    global.fetch = mock.fetch;
    const res = await worker.fetch(
      makeRequest("POST", body, { "x-pass": env.PASSPHRASE }),
      env,
    );
    assert.strictEqual(res.status, 400, "HTTP 应为 400");
    const b = await res.json();
    assert.strictEqual(b.code, 400, "body.code 应为 400");
    assert.strictEqual(typeof b.message, "string");
    assert.strictEqual(b.data, null);
    if (message) assert.strictEqual(b.message, message);
    return b;
  }

  it("2a body 非 JSON → 400", async () => {
    const mock = makeGithubMock([], { existing: true });
    global.fetch = mock.fetch;
    const res = await worker.fetch(
      makeRequest("POST", "this is not json", { "x-pass": env.PASSPHRASE }),
      env,
    );
    assert.strictEqual(res.status, 400);
    const b = await res.json();
    assert.strictEqual(b.code, 400);
    assert.strictEqual(b.message, "invalid json");
  });

  it("2b action 非法 → 400", async () => {
    await expect400(
      { action: "update", platform: "bilibili", id: "1" },
      "action must be 'add' or 'remove'",
    );
  });

  it("2c platform 非法 → 400", async () => {
    await expect400(
      { action: "add", platform: "youtube", id: "1" },
      "platform must be bilibili|douyin",
    );
  });

  it("2d id 缺失 → 400", async () => {
    await expect400({ action: "add", platform: "bilibili" }, "id required");
  });

  it("2e id 为空串 → 400", async () => {
    await expect400(
      { action: "add", platform: "bilibili", id: "   " },
      "id required",
    );
  });
});

// ---------------------------------------------------------------------------
// 3. OPTIONS 预检
// ---------------------------------------------------------------------------
describe("3. OPTIONS 预检", () => {
  it("OPTIONS /rooms → 204 + CORS 头", async () => {
    global.fetch = throwingFetch("OPTIONS 不应调用 GitHub");
    const res = await worker.fetch(makeRequest("OPTIONS"), env);
    assert.strictEqual(res.status, 204);
    assert.strictEqual(
      res.headers.get("Access-Control-Allow-Origin"),
      "https://racheko-lab.github.io",
    );
    const methods = res.headers.get("Access-Control-Allow-Methods") || "";
    assert.ok(methods.includes("GET"), "应允许 GET");
    assert.ok(methods.includes("POST"), "应允许 POST");
    assert.ok(methods.includes("OPTIONS"), "应允许 OPTIONS");
    const headers = res.headers.get("Access-Control-Allow-Headers") || "";
    assert.ok(headers.includes("Content-Type"), "应允许 Content-Type");
    assert.ok(headers.includes("x-pass"), "应允许 x-pass");
  });
});

// ---------------------------------------------------------------------------
// 4. 添加-新增
// ---------------------------------------------------------------------------
describe("4. 添加-新增", () => {
  it("POST add 新房间 → added:true 且 GitHub PUT 被调用", async () => {
    const mock = makeGithubMock([], { existing: true });
    global.fetch = mock.fetch;
    const res = await worker.fetch(
      makeRequest(
        "POST",
        { action: "add", platform: "bilibili", id: "123", name: "测试" },
        { "x-pass": env.PASSPHRASE },
      ),
      env,
    );
    assert.strictEqual(res.status, 200);
    const body = await res.json();
    assert.strictEqual(body.code, 0);
    assert.strictEqual(body.data.added, true);
    assert.ok(
      body.data.rooms.some((r) => r.platform === "bilibili" && r.id === "123"),
      "响应 rooms 应含新房间",
    );
    assert.ok(mock.calls.some((c) => c.method === "PUT"), "应调用 GitHub PUT");
    const stored = JSON.parse(b64decode(mock.store.content));
    assert.ok(stored.some((r) => r.platform === "bilibili" && r.id === "123"));
  });
});

// ---------------------------------------------------------------------------
// 5. 添加-幂等
// ---------------------------------------------------------------------------
describe("5. 添加-幂等", () => {
  it("再次 add 同 platform|id → duplicate:true 且不重复写入", async () => {
    const mock = makeGithubMock([], { existing: true });
    global.fetch = mock.fetch;
    // 第一次 add（store 为空，应新增）
    const r1 = await worker.fetch(
      makeRequest(
        "POST",
        { action: "add", platform: "bilibili", id: "123", name: "x" },
        { "x-pass": env.PASSPHRASE },
      ),
      env,
    );
    const b1 = await r1.json();
    assert.strictEqual(b1.code, 0);
    assert.strictEqual(b1.data.added, true);
    assert.strictEqual(mock.calls.filter((c) => c.method === "PUT").length, 1);
    // 第二次 add 同 key
    const r2 = await worker.fetch(
      makeRequest(
        "POST",
        { action: "add", platform: "bilibili", id: "123", name: "x" },
        { "x-pass": env.PASSPHRASE },
      ),
      env,
    );
    const b2 = await r2.json();
    assert.strictEqual(b2.code, 0);
    assert.strictEqual(b2.data.duplicate, true, "应为 duplicate:true");
    assert.strictEqual(
      mock.calls.filter((c) => c.method === "PUT").length,
      1,
      "幂等 add 不应再次 PUT",
    );
    const stored = JSON.parse(b64decode(mock.store.content));
    assert.strictEqual(stored.length, 1, "rooms 数量应保持不变");
  });
});

// ---------------------------------------------------------------------------
// 6. 移除-成功
// ---------------------------------------------------------------------------
describe("6. 移除-成功", () => {
  it("POST remove 存在的房间 → removed:true 且 GitHub PUT 被调用", async () => {
    const mock = makeGithubMock([{ platform: "bilibili", id: "123", name: "x" }]);
    global.fetch = mock.fetch;
    const res = await worker.fetch(
      makeRequest(
        "POST",
        { action: "remove", platform: "bilibili", id: "123" },
        { "x-pass": env.PASSPHRASE },
      ),
      env,
    );
    assert.strictEqual(res.status, 200);
    const body = await res.json();
    assert.strictEqual(body.code, 0);
    assert.strictEqual(body.data.removed, true);
    assert.ok(
      !body.data.rooms.some((r) => r.platform === "bilibili" && r.id === "123"),
      "响应 rooms 不应再含该房间",
    );
    assert.ok(mock.calls.some((c) => c.method === "PUT"), "应调用 GitHub PUT");
    const stored = JSON.parse(b64decode(mock.store.content));
    assert.ok(!stored.some((r) => r.platform === "bilibili" && r.id === "123"));
  });
});

// ---------------------------------------------------------------------------
// 7. 移除-不存在
// ---------------------------------------------------------------------------
describe("7. 移除-不存在", () => {
  it("POST remove 不存在的房间 → 404", async () => {
    const mock = makeGithubMock([], { existing: true });
    global.fetch = mock.fetch;
    const res = await worker.fetch(
      makeRequest(
        "POST",
        { action: "remove", platform: "bilibili", id: "999" },
        { "x-pass": env.PASSPHRASE },
      ),
      env,
    );
    assert.strictEqual(res.status, 404);
    const body = await res.json();
    assert.strictEqual(body.code, 404);
    assert.strictEqual(body.message, "room not monitored");
    assert.ok(!mock.calls.some((c) => c.method === "PUT"), "不应调用 PUT");
  });
});

// ---------------------------------------------------------------------------
// 8. UTF-8 安全
// ---------------------------------------------------------------------------
describe("8. UTF-8 安全", () => {
  it("中文 name 经 base64 往返不丢字", async () => {
    const chinese = "峰哥亡命天涯";
    const mock = makeGithubMock([{ platform: "bilibili", id: "777", name: chinese }]);
    global.fetch = mock.fetch;

    // 解码路径：业务代码 b64decodeUtf8 应正确还原中文
    const res = await worker.fetch(
      makeRequest("GET", undefined, { "x-pass": env.PASSPHRASE }),
      env,
    );
    const body = await res.json();
    assert.strictEqual(body.code, 0);
    const room = body.data.rooms.find((r) => r.id === "777");
    assert.ok(room, "应返回该房间");
    assert.strictEqual(room.name, chinese, "GET 解码后中文 name 应完整");

    // 编码路径：业务代码 b64encodeUtf8 后中文 name 应无丢失
    const res2 = await worker.fetch(
      makeRequest(
        "POST",
        { action: "add", platform: "douyin", id: "888", name: "国服第一嗨氏" },
        { "x-pass": env.PASSPHRASE },
      ),
      env,
    );
    const body2 = await res2.json();
    assert.strictEqual(body2.code, 0);
    const stored = JSON.parse(b64decode(mock.store.content));
    const added = stored.find((r) => r.id === "888");
    assert.ok(added, "PUT 后 store 应含新房间");
    assert.strictEqual(added.name, "国服第一嗨氏", "PUT 编码后中文 name 应完整");
    // 原有中文房间在新写入后也应保持完整（验证重编码未损坏）
    const kept = stored.find((r) => r.id === "777");
    assert.ok(kept, "原有房间应保留");
    assert.strictEqual(kept.name, chinese, "重编码后原中文 name 应完整");
  });
});

// ---------------------------------------------------------------------------
// 9. 409 重试
// ---------------------------------------------------------------------------
describe("9. 409 重试", () => {
  it("第一次 PUT 409，第二次成功 → 最终成功且 rooms 已更新", async () => {
    const mock = makeGithubMock([], { existing: true, inject409: 1 });
    global.fetch = mock.fetch;
    const res = await worker.fetch(
      makeRequest(
        "POST",
        { action: "add", platform: "bilibili", id: "555", name: "重试" },
        { "x-pass": env.PASSPHRASE },
      ),
      env,
    );
    assert.strictEqual(res.status, 200, "重试后应成功");
    const body = await res.json();
    assert.strictEqual(body.code, 0);
    assert.strictEqual(body.data.added, true);
    // 重试 ≤2 次：应仅发生 1 次重试，PUT 共 2 次
    const putCalls = mock.calls.filter((c) => c.method === "PUT");
    assert.strictEqual(putCalls.length, 2, "应仅重试 1 次，PUT 共 2 次");
    // 每次重试前应重新 getFile
    const getCalls = mock.calls.filter((c) => c.method === "GET");
    assert.ok(getCalls.length >= 2, "重试前应重新 getFile");
    const stored = JSON.parse(b64decode(mock.store.content));
    assert.ok(stored.some((r) => r.id === "555"), "rooms 应已更新");
  });

  it("连续 3 次 PUT 409 → 重试超限返回 409", async () => {
    const mock = makeGithubMock([], { existing: true, inject409: 3 });
    global.fetch = mock.fetch;
    const res = await worker.fetch(
      makeRequest(
        "POST",
        { action: "add", platform: "bilibili", id: "556", name: "x" },
        { "x-pass": env.PASSPHRASE },
      ),
      env,
    );
    assert.strictEqual(res.status, 409, "超限应返回 409");
    const body = await res.json();
    assert.strictEqual(body.code, 409);
    assert.strictEqual(body.message, "concurrent edit conflict, retry");
  });
});

// ---------------------------------------------------------------------------
// 10. 统一信封
// ---------------------------------------------------------------------------
describe("10. 统一信封", () => {
  it("成功响应 code===0 且含 data/message，Content-Type 为 application/json", async () => {
    const mock = makeGithubMock([{ platform: "bilibili", id: "1", name: "a" }]);
    global.fetch = mock.fetch;

    const res1 = await worker.fetch(
      makeRequest("GET", undefined, { "x-pass": env.PASSPHRASE }),
      env,
    );
    const ct1 = res1.headers.get("content-type") || "";
    assert.ok(ct1.includes("application/json"), "Content-Type 应为 application/json");
    const b1 = await res1.json();
    assert.strictEqual(b1.code, 0);
    assert.ok("data" in b1);
    assert.strictEqual(typeof b1.message, "string");

    const mock2 = makeGithubMock([], { existing: true });
    global.fetch = mock2.fetch;
    const res2 = await worker.fetch(
      makeRequest(
        "POST",
        { action: "add", platform: "douyin", id: "2" },
        { "x-pass": env.PASSPHRASE },
      ),
      env,
    );
    const ct2 = res2.headers.get("content-type") || "";
    assert.ok(ct2.includes("application/json"));
    const b2 = await res2.json();
    assert.strictEqual(b2.code, 0);
    assert.ok("data" in b2 && b2.data !== null);
    assert.strictEqual(typeof b2.message, "string");
  });

  it("错误响应亦为统一信封 {code,data,message}", async () => {
    const mock = makeGithubMock([], { existing: true });
    global.fetch = mock.fetch;
    const res = await worker.fetch(
      makeRequest(
        "POST",
        { action: "add", platform: "bad", id: "1" },
        { "x-pass": env.PASSPHRASE },
      ),
      env,
    );
    const b = await res.json();
    assert.deepStrictEqual(Object.keys(b).sort(), ["code", "data", "message"]);
    assert.strictEqual(b.code, 400);
    assert.strictEqual(b.data, null);
  });
});

// ---------------------------------------------------------------------------
// 11. 单元：RoomValidator / verifyPass（直接调用，补充覆盖）
// ---------------------------------------------------------------------------
describe("11. 单元：RoomValidator / verifyPass", () => {
  it("validateInput 校验各非法 / 合法输入", () => {
    assert.strictEqual(RoomValidator.validateInput({ action: "add" }).ok, false);
    assert.strictEqual(
      RoomValidator.validateInput({ action: "add", platform: "bilibili" }).ok,
      false,
    );
    const ok = RoomValidator.validateInput({
      action: "add",
      platform: "douyin",
      id: 42,
      name: "  ",
    });
    assert.strictEqual(ok.ok, true);
    assert.strictEqual(ok.room.id, "42", "id 应转字符串");
    assert.strictEqual(ok.room.name, "42", "空 name 应回退为 id");
  });

  it("key 去重键为 platform|id", () => {
    assert.strictEqual(RoomValidator.key({ platform: "bilibili", id: "9" }), "bilibili|9");
  });

  it("verifyPass 缺 / 错 / 对", async () => {
    const noPass = new Request("https://x/rooms", { headers: {} });
    assert.strictEqual(verifyPass(noPass, env).status, 401);
    const wrong = new Request("https://x/rooms", { headers: { "x-pass": "nope" } });
    assert.strictEqual(verifyPass(wrong, env).status, 403);
    const okReq = new Request("https://x/rooms", { headers: { "x-pass": env.PASSPHRASE } });
    assert.strictEqual(verifyPass(okReq, env), null);
  });

  it("corsHeaders 含固定源与受限方法/头", () => {
    const c = corsHeaders(env);
    assert.strictEqual(c["Access-Control-Allow-Origin"], env.ALLOWED_ORIGIN);
    assert.ok(c["Access-Control-Allow-Methods"].includes("OPTIONS"));
    assert.ok(c["Access-Control-Allow-Headers"].includes("x-pass"));
  });
});
