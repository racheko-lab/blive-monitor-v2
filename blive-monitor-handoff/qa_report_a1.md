# QA 验证报告 — A1 定时摘要自动投递

- **验证人**：严过关（Edward，QA 工程师）
- **项目**：`racheko-lab/blive-monitor`（`/tmp/repo_verify`）
- **方式**：真实代码黑盒（直接 `import` 真实 `auto_summary.py`/`common.py`/`push_utils.py` + 真实 `check.yml` 静态分析 + `monitor.html` 抽取 JS 实跑 `node` 对照）。**不依赖工程师自测**，独立构造场景。
- **验证轮次**：第 1 轮（发现 1 个源码 Bug，按规则上报，不自行修改源码）。

---

## 1. 环境

| 项 | 值 |
|---|---|
| Python | 3.11.1 |
| pyyaml | 6.0.3（`yaml.safe_load` 可用）|
| node | v22.13.1（`node` 实跑 JS 对照可用）|
| 工作区 | `/tmp/repo_verify`，分支 `master`（领先 origin/master 1 commit，改动未提交）|
| 改动文件 | `auto_summary.py`（新增）、`common.py`（diff）、`.github/workflows/check.yml`（diff）、`tests/test_auto_summary.py`（新增）、`docs/a1_*.md/mermaid`（新增）|

---

## 2. pytest 基线

```
cd /tmp/repo_verify && python3 -m pytest -q  ->  430 passed in 1.73s
```

✅ **430 passed** 确认（414 既有 + 16 A1 新增）。记录数字：**430**。

---

## 3. 逐项结果表

| # | 验证项 | 方法 | 结果 |
|---|---|---|---|
| 1 | pytest 基线 | `pytest -q` | ✅ 430 passed |
| 2 | persist 6 处 `summary_state.json` | `grep -n` + `grep -c` | ✅ 行号 106/112/118/130/134/138，计数 **6** |
| 3 | persist 坑逻辑推理 | 分析 CI 流程 + `merge_state.py` 行为 | ✅ 6 处足以防 `lastSent` 丢失（见 §4）|
| 4 | 新 step 顺序 | `yaml.safe_load` 取 step 名索引 | ✅ Transcode(7) < Auto-deliver(8) < Persist(9) |
| 5 | Auto-deliver step 属性 | YAML 解析 | ✅ `continue-on-error: true`、`run: python3 auto_summary.py`、注入 `BLIVE_CONFIG` |
| 6 | YAML 合法性 | `yaml.safe_load` | ✅ 解析无错 |
| 7 | `parse_beijing` 时区无关（Python） | 在 5 个 TZ（UTC/上海/纽约/Kiritimati/GMT+12）跑同进程 | ✅ 全部稳定一致 |
| 8 | `parse_beijing` 跨语言逐值相等 | 抽取 `monitor.html` `parseBeijing` 在 5 个 TZ 用 `node` 实跑，与 Python 对照 | ✅ 全部 `py*1000 == js`；空/非法 → 两侧均 `None` |
| 9 | 正则逐字符一致 | 抽取 Python/JS 正则字面量比较 | ✅ 完全一致 |
| 10 | 北京午夜 `-8h` 不变量 | `2026-07-11 00:00:00` → `1783699200`（=2026-07-10 16:00 UTC）| ✅ |
| 11 | `should_deliver` 五态 | 直接 `import auto_summary` 独立造例 | ✅ disabled/too_early/already_sent/cooldown/deliver 全部符合预期 |
| 12 | `main()` 成功路径 | `monkeypatch` 隔离（chdir tmp_path，假 `dispatch_push` 返回 ok）| ⚠️ **见 §5 源码 Bug**：`lastSent` 写出 OK，但 `lastFailedAt/lastFailedSince` 未被清除 |
| 13 | `main()` 失败路径 | 假 `dispatch_push` 返回 `ok=False` | ✅ 写 `lastFailedAt/lastFailedSince`，`lastSent` 不被覆盖（sentinel 原值保留）|
| 14 | `main()` 无 push no-op | `BLIVE_CONFIG` 无 push 段 | ✅ 不调用推送、不写 `lastSent`、不写冷却 |
| 15 | `compute_since`/`compute_summary` 与 JS 对照（bonus） | 抽取 `computeSince`/`computeSummary`/`pad2` 用 `node` 实跑 | ✅ daily/weekly 计数/去重/rangeText 逐字段相等 |
| 16 | 契约：`monitor.html` 未被改 | `git diff --stat monitor.html` | ✅ 为空（A1 未碰前端）|
| 17 | 契约：`monitor.html` 摘要符号齐全 | grep 12 个符号 | ✅ 全部 FOUND（summaryEnabled/summaryFreq/summarySendTime/computeSummary/computeSince/buildSummaryConfig/summaryCard/copySummary/requestPushSummary/maybeShowSummary/renderSummary/parseBeijing）|
| 18 | 契约：`common.py` 仅新增 | `git diff common.py` | ✅ 仅 `+import calendar/re` + `parse_beijing` 函数，既有符号未改 |
| 19 | 契约：无新第三方依赖 | 检查 `auto_summary.py` import | ✅ 仅 stdlib + `common` + `push_utils` |
| 20 | 契约：`ghp_` 完整令牌单串 | `grep -rn ghp_` | ⚠️ 见 §6：仅在 `monitor.html`（HEAD 既有、A1 未改）发现**分串拼接**的 `ghp_…`，A1 自身文件 0 命中 |

---

## 4. persist 坑独立复核结论（最高优先级）

### 4.1 结构断言
`summary_state.json` 在 `check.yml` 中共出现 **6 处**（已 `grep -c` 计数 = 6，并列出行号）：
- **主流程**：TMPD 暂存循环 copy（106）、TMPD 恢复循环 restore（112）、`git add -f`（118）
- **重试流程**：TMPD 暂存循环 copy（130）、TMPD 恢复循环 restore（134）、`git add -f`（138）

新 step「Auto-deliver summary」位于第 8 位，介于「Transcode covers」(7) 与「Persist state & keepalive」(9) 之间 ✅。YAML 经 `yaml.safe_load` 解析无错 ✅。

### 4.2 逻辑推理验证
Persist step 实际流程：
```
git fetch origin master
→ python3 merge_state.py origin/master        # 仅合并 history/status 等已知文件，不涉及 summary_state.json
→ TMPD=$(mktemp -d)
→ for f in ... summary_state.json : cp $f $TMPD/   # (106) 先把 auto_summary 刚写好的文件拷进 TMPD
→ git reset --hard origin/master              # (110) 工作区被回滚到远端旧版（无本 run 的 lastSent）
→ for f in ... summary_state.json : cp $TMPD/$f .  # (112) 用 TMPD 里的副本覆盖回工作区
→ git add -f ... summary_state.json ...       # (118) 强制纳入
→ commit & push
```
关键点：`auto_summary.py` 在「Auto-deliver summary」step 写出 `lastSent`，该 step 早于「Persist state」。Persist 在 `reset --hard` **之前**把 `summary_state.json` 拷进 TMPD（106），在 `reset --hard` **之后**又从 TMPD 拷回（112）。因此 `reset --hard` 虽然会冲掉工作区里 auto_summary 写的版本，但随即被 TMPD 副本覆盖还原——**`lastSent` 不会丢失**。

若 `summary_state.json` 只在 `git add -f`（118）出现、**不在** TMPD restore 循环（112）：`reset --hard` 后工作区是远端旧版（无 lastSent），`git add -f` 只会把这份陈旧版纳入 → 下一轮误判「本周期未投」而重投。当前实现 112 处已包含 `summary_state.json`，该缺陷被规避。

此外 `merge_state.py` 完全不引用 `summary_state.json`（grep 0 命中），即该文件完全依赖 TMPD 拷贝机制保全——这与 6 处断言一致，逻辑自洽。

### 4.3 结论
✅ **当前 6 处足以防止 `lastSent` 丢失**：`summary_state.json` 同时出现在「TMPD 暂存 copy（106）」与「TMPD 恢复 restore（112）」是防丢失的必要条件，二者均已具备（主+重试各一份）。

---

## 5. 源码 Bug（上报工程师修复）

### Bug-A1-1：`main()` 成功路径未能清除失败冷却字段 `lastFailedAt`/`lastFailedSince`

- **现象**：当 `summary_state.json` 已存在上一轮失败遗留的 `lastFailedAt`/`lastFailedSince` 时，即使本轮投递**成功**，这两个字段仍残留在落盘文件中。
- **复现**（最小黑盒，隔离 tmp_path）：
  ```
  种子 summary_state.json = {"lastFailedAt":111,"lastFailedSince":222,"lastSent":0}
  → 运行 main()（dispatch_push 返回 ok=True）
  → 落盘 summary_state.json = {"lastFailedAt":111,"lastFailedSince":222,"lastSent":1783761488,"enabled":true,"freq":"daily","sendTime":"00:00"}
  断言 lastFailedAt cleared? False（应为 True）
  断言 lastFailedSince cleared? False（应为 True）
  ```
- **根因**：`main()` 成功分支执行 `new_state.pop("lastFailedAt", None)` / `.pop("lastFailedSince", None)`，再调用 `save_summary_state()`。但 `save_summary_state()` 实现为
  ```python
  old = load_summary_state(path)          # 重新读磁盘（仍含 lastFailedAt/Sinced）
  merged = dict(old); merged.update(data) # 旧值被合回
  save_json_file(path, merged)
  ```
  磁盘上的 `old` 仍含失败的冷却字段，`merged.update(new_state)` 不会删除它们 → 内存里的 `pop` 被「磁盘合并」打败。设计契约明确要求「成功 → 清除失败冷却字段」（`auto_summary.py` 注释亦写「成功：回写 lastSent，并清除失败冷却字段」），当前实现未达成。
- **影响评估**：核心是**违反显式设计契约 + 持久化状态残留陈旧冷却时间戳**。功能上因 `should_deliver` 先判 `already_sent`（早于 `cooldown`）且 `lastFailedSince` 按周期判定，故「每周期投递一次」的主流程不受破坏；但状态文件长期残留无效冷却字段属于正确性/整洁性缺陷，应在修复后消除。
- **建议修复**（供工程师参考，QA 不改动源码）：`save_summary_state()` 需支持「显式删除字段」，或在 `main()` 成功分支直接以「全量期望状态」覆盖写（如 `save_json_file(STATE_FILENAME, new_state)` 并保留前端字段），使 `pop` 真正生效。
- **路由**：源码 Bug → 转工程师（Alex）修复。本 QA 不修改 `auto_summary.py`。

> 注：工程师自测 `tests/test_auto_summary.py::test_integration_deliver_writes_state` 仅用「不含失败字段」的初始 state 种子，故未覆盖此场景；本独立验证以「含失败字段」种子才暴露该缺陷——印证独立黑盒的价值。

---

## 6. 契约扫描与遗留观察

- **前端未被改**：`git diff monitor.html` 为空；12 个摘要相关符号全部存在。✅
- **common.py 仅增不改**：`git diff` 仅 `+import calendar`/`+import re` 与 `parse_beijing` 函数，既有符号（`bjnow`/`load_json_file`/`save_json_file` 等）签名与实现均未改动。✅
- **无新第三方依赖**：`auto_summary.py` 仅 import stdlib + `common` + `push_utils`。✅
- **`ghp_` 令牌**：`grep -rn ghp_` 仅在 `monitor.html:2399` 命中，且为**分串拼接** `("ghp_"+ "v4XmZ6xQ32" + "Pq5TII4sOca" + "BH500JCL44" + "dHicP")`。经 `git show HEAD:monitor.html` 确认该令牌**在 A1 之前已存在于 HEAD 提交**（`ee5ff64`），`git diff monitor.html` 为空 → **非 A1 引入，属历史既有**，不在 A1 回归范围内。A1 自身新增文件（`auto_summary.py`/`check.yml`/`common.py` diff/`tests`）**0 命中** `ghp_`。建议（超出 A1 范围）：仓库应轮换/移除该内置默认 Token。

## 7. 额外健壮性观察（非阻塞，非 A1 范围）

- **`parse_beijing` 对越界但格式合法输入抛 `ValueError`**：例如 `"2026-13-40 99:99:99"`（正则 `^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}$` 接受，因 `\d{2}` 不校验取值范围）。Python `calendar.timegm` 抛 `ValueError`，而 JS `parseBeijing` 静默回滚得到一个（错误但非 null 的）值。在 CI 中若 `history.json` 混入此类时间，`compute_summary` 会抛异常被 `main()` 顶层 `except` 吞掉 → 本轮静默 no-op（不投递也不写状态）。任务定义的测试串仅含「合法分隔符/空串/非法格式」，故不在验收内；但建议对 `parse_beijing` 包 `try/except` 返回 `None` 以对齐「loadfail」语义、避免静默 no-op。

---

## 8. 最终判定

### 🔴 源码Bug（1 个确认源码缺陷）

- **pytest**：✅ 430 passed
- **persist 坑**：✅ 6 处齐备、逻辑推理证明足以防 `lastSent` 丢失
- **parse_beijing 时区无关 + 跨语言一致**：✅ 全部通过（5 TZ）
- **should_deliver 五态**：✅ 全部通过
- **main() 失败/无 push 路径**：✅ 通过
- **compute_since/summary 与 JS 对照**：✅ 通过
- **契约保全**：✅ 前端未改、common 仅增、无新依赖、`ghp_` 非 A1 回归
- **⚠️ main() 成功路径**：❌ **Bug-A1-1** —— 未清除 `lastFailedAt`/`lastFailedSince`（设计契约违背，根因 `save_summary_state` 磁盘合并覆盖内存 `pop`）。

**结论**：A1 主体逻辑（时区无关解析、五态门控、跨语言对齐、persist 防丢失、失败/无 push 处理）均通过真实黑盒验证；但存在 1 个源码缺陷（成功路径冷却字段清除失效），需工程师修复后复测。建议工程师修复 Bug-A1-1 后，由 QA 做第 2 轮回归（仅需重跑 `main()` 成功路径 + 全量 `pytest`）。

**遗留问题清单**
1. 【源码 Bug·待修】Bug-A1-1：`main()` 成功路径未清除 `lastFailedAt`/`lastFailedSince`（详见 §5）。
2. 【健壮性建议·非阻塞】`parse_beijing` 对越界格式合法串应 `try/except → None`（详见 §7）。
3. 【历史遗留·非 A1】`monitor.html` 分串拼接的 `DEFAULT_GH_TOKEN` 应轮换/移除（不在 A1 范围）。
