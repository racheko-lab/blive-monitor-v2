# QA 报告 · A2 / A4 CI 侧打通（多通道路由 + 模板渲染）

**验证人**：严过关（QA Engineer，独立黑盒）
**项目**：`racheko-lab/blive-monitor`（`/tmp/repo_verify`）
**日期**：2026-07-11
**验证方式**：真实 `import` 源码（`push_utils.py` / `common.py` / `check_status.py` / `check_new_posts.py` / `auto_summary.py`）+ 真实 `monitor.html` JS 实跑 node 对照；**不依赖工程师自测**，未修改任何被测源码。

---

## 1. 环境与基线

| 项 | 值 |
|---|---|
| Python | 3.11.1 |
| Node | v22.13.1（用于 JS↔Python 跨语言对照） |
| `pytest` 基线 | **456 passed**（2.59s） |
| git 改动文件 | `auto_summary.py` / `check_new_posts.py` / `check_status.py` / `push_utils.py` |
| `monitor.html` / `common.py` | **零改动**（git diff 为空，已核） |

> 注：456 passed 含既有向后兼容锁（`test_phase2_a2_routes.py`、`test_phase2_a4_templates.py`、`test_check_status_legacy_parity` 等）与工程师新增 `tests/test_a2a4_ci.py`，全绿。本次独立验证脚本 `qa_verify_a2a4.py` 置于仓库根（不匹配 `test_*.py`），**不进入 pytest 收集**，故基线数字未被污染。

---

## 2. 验证方法

1. **pytest 基线**：`python3 -m pytest -q` → 记录 **456 passed**。
2. **向后兼容黑盒**：`monkeypatch push_utils.dispatch_push`（与 `check_new_posts.dispatch_push`）记录每次 `(pcfg, title, desp)`；用仅含旧 `push` 的 `BLIVE_CONFIG` 跑 `check_status` Step3 真实分组逻辑（逐字节复刻生产循环，下游 `format_push_title`/`render_body`/`dispatch_event` 均为真实函数），断言收到的 `(title, desp)` 与改造前 `format_push_title`/`format_push_desp` 拼接结果**逐字节一致**（单房间 + 多房间聚合）。
3. **多通道路由 + 分组**：构造 `channels + routes`，断言路由命中与同通道合并为单条消息。
4. **tag 路由**：标量匹配语义与 JS `resolveChannel` 逐字节一致。
5. **模板渲染（A4）**：断言 `desp` 含 `render_template` 结果，占位符替换与缺字段保留。
6. **JS↔Python 跨语言**：从 `monitor.html` **抽取** `resolveChannel`/`renderTemplate` 实跑 node，与 `common.resolve_channel`/`common.render_template` 在相同 ctx/模板下逐例对照。
7. **no-config 守卫**：`{}` / 通道无 `type` 时 `dispatch_event` 返回 `ok=False` 且 `dispatch_push` **未被调用**。
8. **契约保全**：grep 前端契约标记、`git diff` 空校验、`ghp_` 完整令牌单串 0 命中、第三方依赖扫描。

---

## 3. 逐项结果表

| # | 验证项 | 结果 | 关键证据 |
|---|---|---|---|
| 1 | pytest 基线 456 passed | ✅ PASS | `456 passed in 2.59s` |
| 2a | legacy 单房间 `(title,desp)` 逐字节一致 | ✅ PASS | `title_match=True; desp_match=True; calls=1` |
| 2b | legacy 多房间聚合 `(title,desp)` 逐字节一致 | ✅ PASS | `calls=1`（聚合为单条，`title/desp` 与 `format_push_desp` 拼接一致） |
| 2c | legacy `dispatch_event` 退化为单次 `dispatch_push(legacy_push_cfg)` | ✅ PASS | `calls=1; res.ok=True` |
| 3 | 多通道路由 + 分组 | ✅ PASS | `calls=2`；bilibili×2→wecom 合一条（`🔴 2位主播开播：峰哥、阿强`），douyin×1→bark（`🔴 小美开播了！`） |
| 4 | tag 路由（vip→bark / other→wecom / []→wecom默认） | ✅ PASS | bark=`VIP主播`；wecom=`普通主播、无名主播`（空 tags 落默认） |
| 5a | A4 模板渲染（含房间名/title/{platform}替换） | ✅ PASS | `desp='峰哥 开播：今晚联动 @ bilibili'` |
| 5b | 缺字段保留占位符 | ✅ PASS | `desp='峰哥 开播：今晚联动{area}'` |
| 6 | JS↔Python 跨语言对照 | ✅ PASS | `resolveChannel`/`renderTemplate` 4+5 例逐例完全一致（见下） |
| 7a | `dispatch_event({})` → `ok=False` 且 0 次 `dispatch_push` | ✅ PASS | `ok=False; calls=0; err=config: empty push_cfg` |
| 7b | 通道无 `type` → 守卫不调 `dispatch_push` | ✅ PASS | `ok=False; calls=0` |
| 7c | `check_status` 无配置 → 0 次推送（no-op） | ✅ PASS | `calls=0` |
| 7d | `check_new_posts` 无配置 → `ok=False` 不调 `dispatch_push` | ✅ PASS | `ok=False; calls=0` |
| 7e | `auto_summary({event:summary})` 无配置 → `ok=False` 不调 `dispatch_push` | ✅ PASS | `ok=False; calls=0`（源码 line 259-261 亦为 `sys.exit(0)` 优雅退出） |
| 8a | `monitor.html` 前端契约标记全 FOUND | ✅ PASS | `summaryEnabled`/`buildPushConfigV2`/`resolveChannel`/`renderTemplate`/`tplLiveOn`/`tplNewPost` 均在 |
| 8b | `git diff monitor.html` 为空 | ✅ PASS | 无输出 |
| 8c | `git diff common.py` 为空 | ✅ PASS | 无输出 |
| 8d | `ghp_` 完整令牌单串 0 命中（无 PAT 泄漏） | ✅ PASS | 6 个真实源码文件 grep 完整令牌 = **0 hits** |
| 8e | 无新第三方依赖 | ✅ PASS | 4 文件仅 `stdlib` + 既有本地模块（`common`/`push_utils`/`notify_dedup` 等）；无新增第三方 |

**独立验证脚本结果**：`python3 qa_verify_a2a4.py` → **18/18 项全部 PASS**。

### 6）JS↔Python 对照明细（逐例一致）
- `resolveChannel`：
  - ctx(bilibili,game,live_on) → `c_bark` ✓
  - ctx(bilibili,new_post) → `c_wecom` ✓
  - ctx(douyin,new_post) 默认 → `c_default` ✓
  - legacy `push` 退化 → `type:serverchan` ✓
- `renderTemplate`：
  - `🔴 {name} 开播了：{title}` + `{name:峰哥,title:今晚联动}` → `🔴 峰哥 开播了：今晚联动` ✓
  - 全占位符 `{name}|{title}|{platform}|{time}|{url}` → 全替换 ✓
  - 缺 `title` → 保留 `{title}` ✓；`title:""` → 保留 `{title}` ✓
  - `tpl=None` → `""` ✓

---

## 4. 向后兼容结论（最高优先级，A2/A4 硬约束）

**已锁死。** 仅含旧 `push`（无 `routes`/`channels`/`templates`）配置下：

1. **公式逐字节一致**：单房间与多房间聚合两种场景下，`dispatch_push` 收到的 `(title, desp)` 与改造前 `format_push_title`/`format_push_desp` 拼接结果**完全相等**（含 `检测时间` 时间戳——已冻结 `bjnow` 以排除抖动）。
2. **调用次数一致**：legacy 下 `dispatch_event` 退化为单次 `dispatch_push(legacy_push_cfg, ...)`；多房间聚合为**单条**消息（与改造前 `Step3` 聚合行为一致），调用次数与改造前相同。
3. **未配置优雅跳过**：legacy 无 `push` 时等价旧 `elif newly_live:` 静默分支，`dispatch_push` 0 次调用、`no_sendkey` 标记，不刷伪失败 `error` 日志。

---

## 5. 契约扫描

| 契约 | 结果 |
|---|---|
| `monitor.html` 摘要/推送相关前端逻辑（`summaryEnabled`/`buildPushConfigV2`/`resolveChannel`/`renderTemplate`/`tplLiveOn`/`tplNewPost`） | 全部 FOUND 且**未被改动**（git diff 空） |
| `common.py` 仅含既有 `resolve_channel`/`render_template`/`parse_beijing` | **未被改动**（git diff 空） |
| `grep ghp_` 完整令牌单串 | **0 命中**（无 PAT 泄漏回归；分片字面量 `monitor.html:2399` 为既有零改动，非完整串） |
| 新第三方依赖 | 无（`push_utils`/`check_status`/`auto_summary` 仅 `stdlib`+本地模块；`check_new_posts` 的 `playwright` 为抖音抓取既有懒加载依赖，**非 A2/A4 引入**） |

---

## 6. 最终判定

> ## ✅ PASS（源码无 Bug，测试代码自修复 1 处）

- **pytest 数字**：**456 passed**（2 次独立运行一致）。
- **向后兼容**：**已锁死**（单/多房间逐字节一致 + 调用次数一致 + 未配置优雅跳过）。
- **8 大类 / 18 子项独立黑盒验证全部 PASS**，含 JS↔Python 跨语言逐例对照。

### 智能路由说明
- 源码 Bug：未发现。
- 测试代码 Bug（自检修复）：第 1 轮 PAT 令牌 grep 因本验证脚本自身含有该字面量而**误命中自身文件**（1 次假阳性），属测试代码自引用缺陷；已修正为仅扫描 6 个真实源码文件，复测 0 命中 → 全部 PASS。此修复符合「测试代码有 Bug → 自行修复」规则，未触及任何被测源码。

---

## 7. 遗留问题 / 观察项（非阻塞，建议后续优化）

1. **`check_new_posts.py` 存在本地重复的 `dispatch_event`**（lines 629-661），逻辑与 `push_utils.dispatch_event` 完全等价，但为代码复制。本次已用真实函数验证其行为正确（`ok=False` 守卫、`0` 次 `dispatch_push` 均符合预期），**不影响正确性**，仅建议后续收敛为统一引用以消除漂移风险。
2. `dispatch_event` 内部会**重新 `resolve_channel`**（消费 `group_ctx`），与 Step3 分组时的解析理论上一致；若后续引入「同通道但不同 tag 路由」场景，需确保分组维度与重解析维度对齐（当前测试覆盖的 tag 路由场景已验证一致）。
3. `qa_verify_a2a4.py`（独立黑盒验证脚本）与 `qa_report_a2a4.md` 为本次 QA 产出，未提交、不进入 `git` 源码基线。
