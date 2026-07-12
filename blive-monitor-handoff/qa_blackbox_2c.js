/**
 * qa_blackbox_2c.js — 真实代码黑盒验证（2c 波次）
 *
 * 方法：直接从 monitor.html 抽取内联 <script> 源码，用 Node `vm` 在最小 DOM 桩中运行，
 *       然后直接调用真实函数并断言。绝不依赖工程师自测镜像。
 *
 * 运行：TZ=Asia/Shanghai node qa_blackbox_2c.js
 */
'use strict';

const fs = require('fs');
const vm = require('vm');
const path = require('path');

const ROOT = '/tmp/repo_verify';
const HTML = fs.readFileSync(path.join(ROOT, 'monitor.html'), 'utf8');

/* ---------------- 抽取内联 <script>（排除带 src 的外链） ---------------- */
function extractInlineScripts(html) {
  const blocks = [];
  const re = /<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/gi;
  let m;
  while ((m = re.exec(html)) !== null) blocks.push(m[1]);
  return blocks;
}
const inlineCode = extractInlineScripts(HTML).join('\n;\n');

/* ---------------- 最小 DOM 桩 ---------------- */
function makeClassList() {
  const set = new Set();
  return {
    add: (c) => set.add(c),
    remove: (c) => set.delete(c),
    contains: (c) => set.has(c),
    toggle: (c, on) => {
      if (on === undefined) { if (set.has(c)) set.delete(c); else set.add(c); }
      else { if (on) set.add(c); else set.delete(c); }
      return set.has(c);
    },
    _set: set,
  };
}
class FakeEl {
  constructor(id) {
    this.id = id || '';
    this.tagName = (id || 'div').toUpperCase();
    this.style = {};
    this._html = '';
    this.textContent = '';
    this.value = '';
    this.href = '';
    this.download = '';
    this.dataset = {};
    this.classList = makeClassList();
    this.children = [];
    this._attrs = {};
  }
  get innerHTML() { return this._html; }
  set innerHTML(v) { this._html = String(v); }
  appendChild(c) { this.children.push(c); return c; }
  removeChild(c) { const i = this.children.indexOf(c); if (i >= 0) this.children.splice(i, 1); return c; }
  addEventListener() {}
  removeEventListener() {}
  setAttribute(k, v) { this._attrs[k] = v; }
  getAttribute(k) { return this._attrs[k] != null ? this._attrs[k] : null; }
  querySelectorAll() { return []; }
  querySelector() { return null; }
  click() {}
  getBoundingClientRect() { return { width: 0, height: 0, top: 0, left: 0 }; }
  focus() {}
  blur() {}
}

const elements = {};
// 'apiStatus' 返回 null，让顶层 checkApi() 立即优雅返回，避免触碰 AbortController/fetch
const documentStub = {
  getElementById(id) {
    if (id === 'apiStatus') return null;
    if (!elements[id]) elements[id] = new FakeEl(id);
    return elements[id];
  },
  createElement(tag) { return new FakeEl('_' + tag); },
  querySelectorAll() { return []; },
  querySelector() { return null; },
  addEventListener() {},
  removeEventListener() {},
  body: new FakeEl('body'),
};

const windowStub = { addEventListener() {}, removeEventListener() {} };

const store = {};
const localStorageStub = {
  getItem: (k) => (k in store ? store[k] : null),
  setItem: (k, v) => { store[k] = String(v); },
  removeItem: (k) => { delete store[k]; },
};

let capturedCsv = null;
function BlobStub(parts) { capturedCsv = (parts && parts.join('')) || ''; this.parts = parts; }
const URLStub = { createObjectURL: () => 'blob:fake', revokeObjectURL() {} };
class AbortControllerStub { constructor() { this.signal = {}; } abort() {} }
function fetchStub() { return Promise.reject(new Error('network: stub')); }

const sandbox = {
  document: documentStub,
  window: windowStub,
  localStorage: localStorageStub,
  Blob: BlobStub,
  URL: URLStub,
  AbortController: AbortControllerStub,
  fetch: fetchStub,
  console: console,
  Math: Math,
  Date: Date,
  JSON: JSON,
  Object: Object,
  Array: Array,
  String: String,
  Number: Number,
  RegExp: RegExp,
  Promise: Promise,
  isNaN: isNaN,
  parseInt: parseInt,
  parseFloat: parseFloat,
  setTimeout: (fn, ms) => setTimeout(fn, 0),
  clearTimeout: (id) => clearTimeout(id),
  setInterval: (fn, ms) => setInterval(fn, 0),
  clearInterval: (id) => clearInterval(id),
};

/* ---------------- 运行真实内联 JS ---------------- */
let topLevelError = null;
const ctx = vm.createContext(sandbox);
try {
  vm.runInContext(inlineCode, ctx, { filename: 'monitor_inline.js' });
} catch (e) {
  topLevelError = e;
}

/* ---------------- 极简断言框架 ---------------- */
let pass = 0, fail = 0;
const failures = [];
function assert(cond, msg, detail) {
  if (cond) { pass++; console.log('  ✓ ' + msg); }
  else { fail++; failures.push({ msg, detail }); console.log('  ✗ ' + msg + (detail ? '  >> ' + detail : '')); }
}

/* ---------------- CSV 解析（尊重引号/逗号/换行） ---------------- */
function parseCSV(text) {
  const rows = []; let row = []; let field = ''; let i = 0; let inQ = false;
  while (i < text.length) {
    const c = text[i];
    if (inQ) {
      if (c === '"') {
        if (text[i + 1] === '"') { field += '"'; i += 2; continue; }
        inQ = false; i++; continue;
      }
      field += c; i++; continue;
    } else {
      if (c === '"') { inQ = true; i++; continue; }
      if (c === ',') { row.push(field); field = ''; i++; continue; }
      if (c === '\r') { i++; continue; }
      if (c === '\n') { row.push(field); rows.push(row); row = []; field = ''; i++; continue; }
      field += c; i++; continue;
    }
  }
  if (field.length > 0 || row.length > 0) { row.push(field); rows.push(row); }
  return rows;
}

/* =====================================================================
 * 0. 顶层加载 & computeStatsJS 回归（2c 未破坏，line 2731）
 * ===================================================================== */
console.log('\n[0] 顶层加载 / computeStatsJS 回归');
assert(!topLevelError, '内联脚本在 vm 中无顶层异常', topLevelError && (topLevelError.stack || topLevelError.message));
assert(typeof ctx.computeLiveDuration === 'function', 'computeLiveDuration 已定义');
assert(typeof ctx.computeLiveDurationAll === 'function', 'computeLiveDurationAll 已定义');
assert(typeof ctx.applyTrendRange === 'function', 'applyTrendRange 已定义');
assert(typeof ctx.enhancedMerge === 'function', 'enhancedMerge 已定义');
assert(typeof ctx.isRetryableError === 'function', 'isRetryableError 已定义');
assert(typeof ctx.roomKeyOf === 'function', 'roomKeyOf 已定义');
assert(typeof ctx.csvField === 'function', 'csvField 已定义');
assert(typeof ctx.exportReport === 'function', 'exportReport 已定义');
assert(typeof ctx.openRoomDetail === 'function', 'openRoomDetail 已定义');
assert(typeof ctx.closeRoomDetail === 'function', 'closeRoomDetail 已定义');
assert(typeof ctx.ghWriteWithRetry === 'function', 'ghWriteWithRetry 已定义');
assert(typeof ctx.computeStatsJS === 'function', 'computeStatsJS 已定义');

// computeStatsJS 回归：签名 (histData, days, now)，分桶正确
{
  const s = ctx.computeStatsJS([], 7);
  assert(Array.isArray(s.days) && s.days.length === 7, 'computeStatsJS([],7).days 长度=7');
  assert(Array.isArray(s.live_on) && s.live_on.length === 7, 'computeStatsJS live_on 桶数=7');
  assert(s.totals.live_on === 0 && s.totals.new_post === 0, 'computeStatsJS 空数据 totals=0');

  const hist = [
    { type: 'live_on', time: '2024-06-01 10:00:00' },
    { type: 'new_post', time: '2024-06-02 09:00:00' },
  ];
  const now = new Date(2024, 5, 8, 12, 0, 0); // 2024-06-08
  const s2 = ctx.computeStatsJS(hist, 7, now);
  // days: 06-02 ~ 06-08；live_on 应在 06-01? 06-01 不在 7 天窗口(06-02~06-08) -> 不计；new_post 06-02 计
  assert(s2.totals.new_post === 1, 'computeStatsJS new_post 命中=1');
  assert(s2.totals.live_on === 0, 'computeStatsJS live_on 窗口外不计=0');
}

/* =====================================================================
 * 1. C1 开播时长 computeLiveDuration
 * ===================================================================== */
console.log('\n[1] C1 computeLiveDuration');
const nowBJ = new Date(2024, 5, 1, 12, 0, 0); // 2024-06-01 12:00:00 北京

// ① 配对完整累计正确
{
  const hist = [
    { type: 'live_on', platform: 'bilibili', rid: '1', time: '2024-06-01 10:00:00' },
    { type: 'live_off', platform: 'bilibili', rid: '1', time: '2024-06-01 11:30:00' },
  ];
  const r = ctx.computeLiveDuration(hist, 'bilibili|1', { now: nowBJ });
  assert(r.totalSec === 5400, '①配对累计 totalSec=5400 (1.5h)', 'got ' + r.totalSec);
  assert(r.completedSec === 5400, '① completedSec=5400');
  assert(r.ongoing === false, '① 非进行中');
  assert(r.last30Sec === 5400, '① 近30天计入=5400');
}

// ② 进行中（仅 live_on）不计入累计，返回进行中标记
{
  const hist = [
    { type: 'live_on', platform: 'bilibili', rid: '1', time: '2024-06-01 10:00:00' },
  ];
  const r = ctx.computeLiveDuration(hist, 'bilibili|1', { now: nowBJ });
  assert(r.ongoing === true, '② 返回进行中标记 ongoing=true');
  // 设计规范：进行中（无对应 live_off）不计入累计（仅标"进行中"）
  // 代码当前把进行中时长计入了 totalSec，与规范冲突 -> 记录实际值并标记
  if (r.totalSec === 0) {
    assert(true, '② 进行中时长不计入累计 totalSec=0');
  } else {
    assert(false, '② 进行中时长【不应】计入累计 totalSec（规范要求=0）', '代码实际 totalSec=' + r.totalSec + ' (把进行中时长计入了累计)');
  }
}

// ③ 近 30 天窗口外不计入 last30Sec（累计仍含）
{
  const hist = [
    { type: 'live_on', platform: 'bilibili', rid: '1', time: '2024-04-22 10:00:00' }, // 40 天前，窗口外
    { type: 'live_off', platform: 'bilibili', rid: '1', time: '2024-04-22 12:00:00' },
    { type: 'live_on', platform: 'bilibili', rid: '1', time: '2024-05-27 10:00:00' }, // 5 天前，窗口内
    { type: 'live_off', platform: 'bilibili', rid: '1', time: '2024-05-27 11:00:00' },
  ];
  const r = ctx.computeLiveDuration(hist, 'bilibili|1', { now: nowBJ });
  assert(r.totalSec === 10800, '③ 累计含窗口外(全部) totalSec=10800 (3h)', 'got ' + r.totalSec);
  assert(r.last30Sec === 3600, '③ 近30天仅窗口内 last30Sec=3600', 'got ' + r.last30Sec);
}

// computeLiveDurationAll 聚合
{
  const hist = [
    { type: 'live_on', platform: 'bilibili', rid: '1', time: '2024-06-01 10:00:00' },
    { type: 'live_off', platform: 'bilibili', rid: '1', time: '2024-06-01 11:00:00' },
    { type: 'live_on', platform: 'douyin', rid: '2', time: '2024-06-01 10:00:00' },
    { type: 'live_off', platform: 'douyin', rid: '2', time: '2024-06-01 10:30:00' },
  ];
  const all = ctx.computeLiveDurationAll(hist);
  assert(all.totalSec === 5400, 'computeLiveDurationAll 跨房间累计=5400', 'got ' + all.totalSec);
  assert(all.completedCount === 2, 'computeLiveDurationAll 完成场次=2');
}

/* =====================================================================
 * 2. C2 applyTrendRange
 * ===================================================================== */
console.log('\n[2] C2 applyTrendRange');
{
  const orig = ctx.computeStatsJS;
  const statCalls = [];
  ctx.computeStatsJS = function (hd, days, now) { statCalls.push(days); return orig(hd, days, now); };

  // 3 个不同日期的事件 -> daysCovered=3
  ctx.hist = [
    { type: 'live_on', platform: 'bilibili', rid: '1', time: '2024-06-01 10:00:00' },
    { type: 'live_off', platform: 'bilibili', rid: '1', time: '2024-06-01 11:00:00' },
    { type: 'live_on', platform: 'bilibili', rid: '1', time: '2024-06-02 10:00:00' },
    { type: 'live_off', platform: 'bilibili', rid: '1', time: '2024-06-02 11:00:00' },
    { type: 'live_on', platform: 'bilibili', rid: '1', time: '2024-06-03 10:00:00' },
    { type: 'live_off', platform: 'bilibili', rid: '1', time: '2024-06-03 11:00:00' },
  ];
  ctx.stat = null; ctx.rooms = []; ctx.postRooms = [];

  let dashErr = null;
  try { ctx.applyTrendRange(7); } catch (e) { dashErr = e; }
  assert(!dashErr, 'applyTrendRange(7) 不抛异常', dashErr && dashErr.message);
  assert(ctx.trendDays === 7, 'applyTrendRange(7) -> trendDays=7', 'got ' + ctx.trendDays);

  try { ctx.applyTrendRange(30); } catch (e) { dashErr = e; }
  assert(ctx.trendDays === 30, 'applyTrendRange(30) -> trendDays=30');

  try { ctx.applyTrendRange(90); } catch (e) { dashErr = e; }
  assert(ctx.trendDays === 90, 'applyTrendRange(90) -> trendDays=90');

  try { ctx.applyTrendRange(45); } catch (e) { dashErr = e; }
  assert(ctx.trendDays === 7, 'applyTrendRange(45 非法) -> 默认 7');

  assert(statCalls.indexOf(7) >= 0, 'computeStatsJS 被以 days=7 调用');
  assert(statCalls.indexOf(30) >= 0, 'computeStatsJS 被以 days=30 调用');
  assert(statCalls.indexOf(90) >= 0, 'computeStatsJS 被以 days=90 调用');

  // 数据不足提示：trendDays=90，daysCovered=3 < 90
  try { ctx.applyTrendRange(90); } catch (e) { dashErr = e; }
  const dtHtml = (elements['dashTrend'] && elements['dashTrend']._html) || '';
  assert(/数据不足/.test(dtHtml), 'daysCovered<trendDays 时显示"数据不足"提示', JSON.stringify(dtHtml.slice(0, 80)));
  assert(/90/.test(dtHtml), '提示中包含所选天数 90');

  ctx.computeStatsJS = orig; // 还原
}

/* =====================================================================
 * 3. C3 openRoomDetail / closeRoomDetail + show() views 5-key
 * ===================================================================== */
console.log('\n[3] C3 openRoomDetail / closeRoomDetail');
{
  ctx.rooms = [{ platform: 'bilibili', id: '1', name: '测试房间', tags: ['t1'], enabled: true }];
  ctx.postRooms = []; ctx.hist = []; ctx.stat = null;

  ctx.openRoomDetail('bilibili|1');
  assert((elements['roomDetail'] && elements['roomDetail'].style.display) === 'block', 'openRoomDetail 后 roomDetail 可见(display=block)');
  assert(ctx.window.__roomDetailKey === 'bilibili|1', 'openRoomDetail 写入 window.__roomDetailKey');
  const bodyHtml = (elements['roomDetailBody'] && elements['roomDetailBody']._html) || '';
  assert(bodyHtml.length > 0, 'renderRoomDetail 已渲染弹层内容');

  ctx.closeRoomDetail();
  assert((elements['roomDetail'] && elements['roomDetail'].style.display) === 'none', 'closeRoomDetail 后 roomDetail 复位(display=none)');
}

// show() 的 views 仍是 5-key 字典（grep 源码验证，line 2415）
{
  const m = HTML.match(/var views=\{([^}]*)\}/);
  assert(!!m, '源码中存在 var views={...}');
  if (m) {
    const pairs = (m[1].match(/'(\w+)'\s*:\s*'[^']*'/g) || []);
    const keys = pairs.map((p) => p.match(/'(\w+)'/)[1]);
    const expected = ['live', 'posts', 'log', 'config', 'dashboard'];
    assert(pairs.length === 5, 'show() views 恰好 5 个 key', 'got ' + JSON.stringify(keys));
    assert(expected.every((k) => keys.indexOf(k) >= 0), 'show() views 含 live/posts/log/config/dashboard', JSON.stringify(keys));
  }
}

/* =====================================================================
 * 4. D2 enhancedMerge / roomKeyOf / isRetryableError
 * ===================================================================== */
console.log('\n[4] D2 enhancedMerge / roomKeyOf / isRetryableError');
{
  assert(ctx.roomKeyOf({ platform: 'bilibili', rid: '123' }) === 'bilibili|123', 'roomKeyOf(rid)');
  assert(ctx.roomKeyOf({ platform: 'douyin', id: '456' }) === 'douyin|456', 'roomKeyOf(id)');
  assert(ctx.roomKeyOf({ account: '789' }) === '|789', 'roomKeyOf(account 无 platform)');

  const local = [{ platform: 'bilibili', id: '1', name: 'A', tags: ['x'], enabled: true, sec_uid: '', extra: 'L' }];
  const remote = [{ platform: 'bilibili', id: '1', name: 'A_REMOTE', tags: ['y'], enabled: false, sec_uid: 'REMOTE', extra: 'R' }];
  const merged = ctx.enhancedMerge(local, remote).rooms[0];
  assert(JSON.stringify(merged.tags) === JSON.stringify(['x']), '本地 tags 优先');
  assert(merged.enabled === true, '本地 enabled 优先');
  assert(merged.sec_uid === 'REMOTE', '远端 sec_uid 优先（本地空）');
  assert(merged.name === 'A_REMOTE', '双方都有时 远端 name 优先');
  assert(merged.extra === 'R', '其余字段 远端优先');

  // 单边存在 -> 保留该方
  const m2 = ctx.enhancedMerge([{ id: '1', name: 'L' }], [{ id: '2', name: 'R' }]).rooms;
  assert(m2.length === 2, 'enhancedMerge 并集两房间', 'got ' + m2.length);
  assert(m2.some((r) => r.id === '1' && r.name === 'L'), '仅本地房间保留');
  assert(m2.some((r) => r.id === '2' && r.name === 'R'), '仅远端房间保留');

  // isRetryableError
  assert(ctx.isRetryableError({ conflict: true }) === true, 'isRetryableError 409/conflict=true');
  assert(ctx.isRetryableError(new Error('HTTP 500 Internal')) === true, 'isRetryableError 5xx=true');
  assert(ctx.isRetryableError(new Error('failed to fetch')) === true, 'isRetryableError 网络=true');
  assert(ctx.isRetryableError(new Error('HTTP 400 Bad Request')) === false, 'isRetryableError 4xx(非409)=false');
  assert(ctx.isRetryableError(new Error('HTTP 404 Not Found')) === false, 'isRetryableError 明文404消息=false(注: ghPutFile 实际会把404包成 conflict)');
  assert(ctx.isRetryableError(null) === false, 'isRetryableError null=false');
}

/* =====================================================================
 * 5. C4 csvField / exportReport
 * ===================================================================== */
console.log('\n[5] C4 csvField / exportReport');
{
  assert(ctx.csvField('hello') === 'hello', 'csvField 普通文本');
  assert(ctx.csvField('a,b') === '"a,b"', 'csvField 含逗号加引号');
  assert(ctx.csvField('he said "hi"') === '"he said ""hi"""', 'csvField 含引号翻倍');
  assert(ctx.csvField('line1\nline2') === '"line1\nline2"', 'csvField 含换行加引号');
  assert(ctx.csvField(null) === '', 'csvField null->空');
  assert(ctx.csvField(undefined) === '', 'csvField undefined->空');

  capturedCsv = null;
  ctx.rooms = [{ platform: 'bilibili', id: '1', name: 'Room, One', tags: ['t1', 't2'], enabled: true }];
  ctx.postRooms = [{ id: '99', name: 'Post Room', tags: ['p'], enabled: false }];
  ctx.hist = [
    { type: 'live_on', platform: 'bilibili', rid: '1', time: '2024-06-01 10:00:00' },
    { type: 'live_off', platform: 'bilibili', rid: '1', time: '2024-06-01 11:00:00' },
    { type: 'new_post', platform: 'bilibili', rid: '1', time: '2024-06-02 09:00:00' },
  ];
  ctx.stat = { rooms: [{ platform: 'bilibili', id: '1', status: 'live' }] };
  ctx.exportReport('csv');
  assert(capturedCsv && capturedCsv.length > 0, 'exportReport 产出 CSV', capturedCsv ? '' : 'capturedCsv 为空');

  if (capturedCsv) {
    const content = capturedCsv.replace(/^﻿/, '');
    const rows = parseCSV(content);
    assert(rows.length === 3, 'CSV 行数=3 (表头 + rooms1 + postRooms1)', 'got ' + rows.length);
    assert(rows[0].length === 13, 'CSV 表头 13 列', 'got ' + rows[0].length);
    let all13 = true;
    rows.forEach((r) => { if (r.length !== 13) all13 = false; });
    assert(all13, 'CSV 每行均 13 字段');
    // 含逗号字段被引号包裹后可正确解析为单一字段
    const nameField = rows[1][0];
    assert(nameField === 'Room, One', '含逗号名称被正确转义解析', JSON.stringify(nameField));
  }
}

/* =====================================================================
 * 6. ghWriteWithRetry 重试 + 合并不破签名
 * ===================================================================== */
console.log('\n[6] ghWriteWithRetry 重试/合并');
(async () => {
  const baseRooms = [{ platform: 'bilibili', id: '1', name: 'A', tags: ['x'], enabled: true, sec_uid: 'S1' }];
  let putCalls = [];
  let mutateCalls = 0;

  // 桩：ghGetFile 返回远端 base；ghPutFile 首次 409，之后成功
  ctx.ghGetFile = (p) => Promise.resolve({ rooms: JSON.parse(JSON.stringify(baseRooms)), sha: 'sha-base' });
  ctx.ghPutFile = (p, payload, sha) => {
    putCalls.push(payload);
    if (putCalls.length === 1) return Promise.reject({ conflict: true }); // 409
    return Promise.resolve('sha-new');
  };

  const mutate = (rooms) => {
    mutateCalls++;
    return { rooms: rooms.concat([{ platform: 'bilibili', id: '2', name: 'B' }]), changed: true };
  };

  let result, ghErr = null;
  try {
    result = await ctx.ghWriteWithRetry('rooms.json', mutate);
  } catch (e) { ghErr = e; }

  assert(!ghErr, 'ghWriteWithRetry 最终成功（无未捕获异常）', ghErr && (ghErr.message || JSON.stringify(ghErr)));
  assert(mutateCalls >= 1, 'mutate 被调用', 'mutateCalls=' + mutateCalls);
  assert(putCalls.length === 2, '首次 409 失败后重试一次(共2次写回)', 'putCalls=' + putCalls.length);

  if (putCalls.length >= 2 && result) {
    const localRes = baseRooms.concat([{ platform: 'bilibili', id: '2', name: 'B' }]);
    const expected = ctx.enhancedMerge(localRes, baseRooms).rooms;
    assert(JSON.stringify(putCalls[putCalls.length - 1]) === JSON.stringify(expected),
      '最终落库内容 = enhancedMerge(本地意图, 远端)', 'got=' + JSON.stringify(putCalls[putCalls.length - 1]));
    assert(result.changed === true, '返回 changed=true');
    assert(result.sha === 'sha-new', '返回新 sha');
    assert(typeof ctx.ghWriteWithRetry === 'function' &&
      ctx.ghWriteWithRetry.toString().indexOf('function ghWriteWithRetry(path, mutate)') >= 0,
      'ghWriteWithRetry 源码签名未变 (path, mutate)');
  }

  /* ---------------- 汇总 ---------------- */
  console.log('\n==================== QA 黑盒汇总 ====================');
  console.log('PASS: ' + pass + '   FAIL: ' + fail);
  if (failures.length) {
    console.log('\n失败项:');
    failures.forEach((f, i) => console.log('  ' + (i + 1) + '. ' + f.msg + (f.detail ? '  >> ' + f.detail : '')));
  }
  process.exit(fail === 0 ? 0 : 1);
})();
