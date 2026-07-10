# P0-2 通知可靠性 PRD（简单 PRD）

> 产品经理：许清楚（Alice）｜ 版本：v1.0（阶段 1 / P0-2）
> 关联：`docs/product_analysis.md` §3.2、§4.1 P0-2；P0-1（统一日志/健康条）已交付，本 PRD 复用其能力。
> 范围：纯后端可靠性；不动前端。

---

## 0. 项目信息

- **Language**：中文
- **Programming Language**：后端 Python 3（纯脚本，不引入新依赖；前端不改）
- **Project Name**：`p0_notify_reliability`
- **原始需求复述**：直播/新作品监控的推送在瞬时失败（超时 / 连接错误 / 5xx / 429）与通道失效（Token / Webhook 失效）时直接丢通知，且失败对调用方与用户不可见。本轮为 P0-2，聚焦纯后端可靠性：给 `dispatch_push` 加带退避的重试、明确失败分类、让发送失败成为可见的 error 级统一日志事件，且重试不得破坏去重账本。

---

## 1. 产品目标

1. **通知必达**：瞬时网络/服务端错误不再直接丢通知，自动重试吸收抖动。
2. **失败可见**：推送通道挂了 / 配置失效时，用户与监控能感知（error 级事件入统一日志，供 P0-1 健康条与日志筛选）。
3. **去重不被破坏**：重试只发生在 `record()` 之前；同一事件无论重试几次都不产生重复发送标记。

---

## 2. 用户故事

- 作为**监控用户**，我希望开播时即便推送通道短暂抖动也能收到通知，以免错过开播。
- 作为**监控用户**，我希望推送通道失效（Token / Webhook 坏掉）时能被告知，而不是静默错过所有通知。
- 作为**维护者（P0-1 健康条）**，我希望推送失败作为 error 事件进入统一日志，以便健康度与错误统计反映通知健康。
- 作为**开发者**，我希望重试逻辑不破坏现有去重账本，避免「重试反而造成重复推送」。

---

## 3. 需求池

### P0（必须有，纯后端，聚焦可靠性）

| 编号 | 需求 | 验收标准 |
|---|---|---|
| **P0-2.1** | `dispatch_push` 增加带退避的重试 | 对瞬时失败重试 N 次（默认 3 次），指数退避（默认 2s/4s/8s）；仅最终所有重试失败才返回「失败」。 |
| **P0-2.2** | 失败分类（哪些重试 / 哪些放弃） | 超时 / 连接错误 / 5xx / 429 → 重试；4xx 鉴权(401/403) / 400 / 404 → 不重试直接失败。分类逻辑与具体渠道解耦。 |
| **P0-2.3** | 发送失败的可见性 | 调用方在日志 `push` 字段区分 `"pushed_fail"` / `"pushed_ok"` / `"queued"` / `"deduped"`；并把「通知发送失败」作为 **error 级**事件写入统一日志（复用 `log_utils.append_history`，type 用 `"error"` 或新增 `"notify_fail"`，含 attempts / last_error / detail），供 P0-1 健康条与日志筛选使用。 |
| **P0-2.4** | 去重账本不被重试破坏 | `record()` 仍只在「最终成功」后由调用方调用一次；重试完全发生在 `record()` 之前，绝不重复 `record()`。 |

### P1（可选，本轮不默认做，写进 PRD）

- **P1-1 备用通道**：主通道最终失败后自动用第二个渠道兜底（需配置支持多通道；与 P2-4 渠道降级相关）。

### P2（可选，本轮不默认做）

- **P2-1 CI 自身失败自通知**：脚本崩溃时通知用户（需 workflow 层配合，超出纯后端范围）。
- **P2-2 per-账号 / 按平台分组路由**：不同账号走不同通道。

### 明确不做（本轮边界）

- 不改前端（P0-2 纯后端）。
- 不引入多通道并行 / 自动降级（归入 P1 / P2）。
- 不新增第三方依赖（仅标准库 `time` / `urllib`，退避用 `time.sleep`）。

---

## 4. 关键设计取舍

### 4.1 重试策略

- 默认 **3 次（含首次）**，指数退避 **2s / 4s / 8s**，全部在 `dispatch_push` 内同步完成（CI 单 run 容忍约 14s 额外耗时，远低于 5 分钟周期）。
- 次数与退避以常量集中配置（`MAX_ATTEMPTS=3`、`BACKOFF=(2,4,8)`），便于后续调参。

### 4.2 失败分类（哪些重试 / 哪些直接放弃）

需要在「拿到 HTTP 状态码」这一层做分类。当前 `send_via_*` 把一切异常 `except → return False`，状态码被吞，导致 `dispatch_push` 无法区分 4xx 与 5xx。

**推荐方案**：引入 `SendResult(ok: bool, permanent: bool, error: str)`；`send_via_*` 改为返回该结构（**渠道对外行为 / URL / 荷载语义不变，仅返回形状变化**）：

- 成功 → `ok=True`
- 4xx 鉴权 / 400 / 404 → `ok=False, permanent=True`（不重试）
- 超时（`socket.timeout` / `urllib.error.URLError` 超时）、连接错误、5xx、429 → `ok=False, permanent=False`（重试）

`dispatch_push_detailed` 跑重试循环：仅当 `not ok and not permanent` 时退避后重试；`permanent` 失败立即返回。

**保守替代方案（零改动 `send_via_*`）**：保持 `send_via_*` 返回 bool，新增一个并行「带分类的发送」内部函数供重试循环使用，分类在 `dispatch_push` 内通过捕获 `urllib.error.HTTPError` 的 `.code` 实现。代价是 URL / 荷载构建逻辑需在两处维护，不推荐。

### 4.3 与去重的协作（关键不变量）

- 现有调用方语义：`check_status.py` L733-736、L829-836 的 `if ok: dedup_record(...)`。
- 重试后，`dispatch_push_detailed` 返回 `PushResult(ok, attempts, last_error)`；调用方**仅在 `ok=True` 时** `dedup_record(...)`。
- 因为重试完全发生在 `dispatch_push` 内部、在调用方拿到最终结果之前，调用方只会对「最终成功」做一次 `record()`；`record()` 不会被重试多次调用 → 去重账本安全。
- 失败（含重试耗尽）时**不** `record()` → 下一轮 CI（5 分钟后）会重新尝试推送（受 `live:` 2h 冷却吸收，不会刷屏）。这正好满足「失败不标记去重、可补推」。

### 4.4 返回结构怎么设计不破坏现有调用方

- 新增 `PushResult` dataclass：`ok: bool, attempts: int, last_error: str`。
- 新增 `dispatch_push_detailed(push_cfg, title, desp) -> PushResult`：承载重试 + 分类 + 明细。
- **保留** `dispatch_push(push_cfg, title, desp) -> bool` 作为向后兼容薄包装：`return dispatch_push_detailed(...).ok`。任何外部调用方继续可用；本轮把 `check_status.py` / `check_new_posts.py` 两个调用方升级为 `dispatch_push_detailed` 以取 attempts / last_error 写日志。
- `send_via_*` 返回 `SendResult` 仅被 `dispatch_push` 内部消费（无其他直接调用方）；但其返回形状变化会触及 `tests/test_push_utils.py` 中 `send_via_*` 的 `is True/is False` 断言，需在测试更新中一并修正（见 §6）。
- 前端完全不感知（P0-2 纯后端）；`status.json` / `history.json` 的 `push` 字段字符串值（`"pushed_fail"` 等）保持兼容。

---

## 5. UI / 日志影响（失败如何进统一日志）

- 复用 `log_utils.append_history(path, new_entries, max_n)`（**注意：代码中没有 `append_event` 这个函数**，统一日志写入接口即 `append_history`；PRD 按真实 API 命名，待确认项一并列出）。
- 调用方在 `dispatch_push_detailed` 返回 `ok=False` 时，构造一条统一日志事件并 `append_history`：

  ```json
  {
    "time": "2026-07-...",
    "type": "notify_fail" | "error",   // 命名见待确认
    "level": "error",
    "detail": "渠道=wecom attempts=3 last_error=<最后一次错误>",
    "account": "<rid>",                // 供按账号视图/健康聚合
    "name": "<display_name>",
    "platform": "<platform>",
    "push": "pushed_fail"
  }
  ```

- 该事件进入 `history.json`，被 P0-1 健康条的错误桶与日志「类型 / 账号」筛选直接可用；同时 `logger.error("通知推送失败: ...")` 落 `runtime.log`（替代当前的 `logger.info` 失败提示）。
- 事件计数受 `ERROR_THROTTLE_MINUTES`（默认 30min / rid+type）节流，避免瞬时大量失败刷屏。
- 若采用新增 `"notify_fail"` type，需同步把该字符串加入 `log_utils.EVENT_TYPES` frozenset（单一真相源），且前端 JS 必须镜像同一字符串（否则新类型在前端被忽略）——此项属跨端改动，须一并评估。

---

## 6. 测试要求（新增 / 更新，均在 `tests/` 下）

- **重试成功**：mock `urlopen` 前两次抛 `URLError`、第三次成功 → 断言最终 `ok=True` 且 `attempts=3`。
- **不重试**：mock 返回 4xx（permanent）→ 断言 `attempts=1` 且 `ok=False`。
- **退避序列**：用 `monkeypatch` 替换 `time.sleep` 验证退避 2 / 4 / 8 被按序调用。
- **去重安全**：验证「重试成功」场景下 `dedup_record` 仅被调用一次（由调用方测试覆盖）。
- **兼容契约**：保留 `dispatch_push(...)` 返回 bool 的旧契约测试。
- **更新既有断言**：`tests/test_push_utils.py` 中 `send_via_*` 的 `is True / is False` 断言需适配 `SendResult` 返回形状（若采用推荐方案 §4.2）。

---

## 7. 待确认问题

1. **重试次数与退避取值**：默认 3 次 / 2s·4s·8s 是否合适？还是 2 次 / 1s·2s？需权衡 CI 单 run 耗时与抖动吸收率。
2. **失败事件 type 命名**：复用现有 `"error"`（零跨端改动，健康条错误桶直接命中）还是新增 `"notify_fail"`（语义更清晰，但需改 `EVENT_TYPES` + 前端 JS 镜像）？
3. **是否本轮引入备用通道（P1-1）/ 渠道降级（P2-4）**：当前 PRD 仅做单通道重试，多通道兜底留待后续。
4. **`send_via_*` 返回形状是否接受改为 `SendResult`**（推荐，需更新少量现有单测），还是采用保守的「不改 `send_via_*`、重试分类另起炉灶」方案？
5. **失败明细是否要进 `status.json`**（`push_res` 摘要）供前端展示，还是仅入 `history.json` + `runtime.log`？（前端本轮不改，建议仅入日志。）

---

*—— 本 PRD 仅覆盖 P0-2 通知可靠性，改动文件预计 `push_utils.py` + `check_status.py` + `check_new_posts.py` + 测试，均 <10 文件。不修改代码、不提交 git。*
