# P0-5 平台定位落地 · 轻量设计稿（架构师：高见远）

> 本文档对应 PRD：`docs/p0_platform_position_prd.md`（P0-1 前端固化 / P0-2 清理死代码 / P0-3 一致性守护）。
> 范围：纯静态前端展示 + CI 配置清理 + 一致性回归测试。**零运行时逻辑、零监控/推送逻辑改动、不提交 git、不改业务代码。**

---

## 1. 实现方案（一句话）

在 `monitor.html` 配置页顶部新增 `id="supportedPlatforms"` 纯展示区块（B站/抖音「已支持」、小红书「已放弃，不计划支持」），从 `.github/workflows/check.yml` 直接删除 `Check xhs rooms` 死步骤及其两处 `steps.xhslist` 引用，并新增 `tests/test_platform_position.py` 以文件系统读取（open + 正则/JSON）锁死上述三处事实、防止回潮。

---

## 2. 文件列表（< 10 文件，轻量）

| 文件 | 改动类型 | 说明 | 对应需求 |
|---|---|---|---|
| `monitor.html` | 修改 | ① `#view-config` 顶部新增 `id="supportedPlatforms"` 卡片（HTML）；② 追加约 2 行 `.pf.ok` / `.pf.bad` 状态徽标 CSS（复用 `--green`/`--live` 变量） | P0-1 |
| `.github/workflows/check.yml` | 修改 | 删除 `Check xhs rooms` 步骤整段（id: xhslist，含其前置注释）；两处 `if` 改为仅 `steps.postlist.outputs.enabled == 'true'` | P0-2 |
| `tests/test_platform_position.py` | 新增 | 4~5 个断言：前端含区块、rooms.json 无 xhs、check.yml 无 xhs 死步骤、全仓（产品文档）无幽灵声明、check_status.py 无 xhs 实现分支（重申） | P0-3 |

> 不改动：`check_status.py`、`check_new_posts.py`、`push_utils.py`、`rooms.json`（已干净）、`README.md`（已对齐）、`docs/*.md`（仅被测试扫描、不修改）。

---

## 3. 数据结构 / 接口（签名伪代码 + HTML 片段）

### 3.1 支持平台区块 HTML（插入 `#view-config` 顶部，作为第一个 `.room`）

插入位置：紧跟 `<div class="panel-head"><h2>⚙️ 配置</h2></div>`（monitor.html 第 259 行）之后、GitHub Token 卡片（第 261 行）之前。

```html
<!-- P0-1 平台定位固化：纯展示，不参与任何检测/推送逻辑 -->
<div class="room" id="supportedPlatforms" style="margin-bottom:12px">
  <div style="font-size:14px;font-weight:800;margin-bottom:6px">📡 支持平台</div>
  <div style="font-size:12px;color:var(--text2);line-height:1.6;margin-bottom:10px">
    本项目当前支持以下平台的直播监控。平台定位已正式确定，无隐藏能力。
  </div>
  <div style="display:flex;flex-direction:column;gap:6px">
    <div style="display:flex;align-items:center;gap:8px;font-size:13px">
      <span class="pf bili">🟢 B站</span>
      <span style="color:var(--text2)">直播开播</span>
      <span class="pf ok" style="margin-left:auto">✅ 已支持</span>
    </div>
    <div style="display:flex;align-items:center;gap:8px;font-size:13px">
      <span class="pf dy">🟢 抖音</span>
      <span style="color:var(--text2)">直播开播 + 新作品</span>
      <span class="pf ok" style="margin-left:auto">✅ 已支持</span>
    </div>
    <div style="display:flex;align-items:center;gap:8px;font-size:13px">
      <span class="pf bad">🔴 小红书</span>
      <span style="color:var(--text2)">直播（曾尝试，已移除）</span>
      <span class="pf bad" style="margin-left:auto">❌ 已放弃，不计划支持</span>
    </div>
  </div>
  <div style="font-size:11px;color:var(--text3);line-height:1.55;margin-top:10px">
    小红书直播监控已于 2026-07-10 从代码中移除：开播短链每次都变、数据中心 IP 触发风控，维护成本高且误判/漏推难根除。当前专注 B站 / 抖音。
  </div>
</div>
```

文案约定（终态词、无歧义）：
- B站/抖音：`✅ 已支持`
- 小红书：`❌ 已放弃，不计划支持`（附一句根因：短链易变 / IP 风控 / 维护成本高）
- 禁用「计划支持 / 即将上线 / 开发中 / 敬请期待」等过渡词。

### 3.2 新增 CSS（追加到 monitor.html 现有 `.pf` 规则附近，第 54 行后）

```css
/* P0-1 支持平台区块状态徽标：复用既有 --green / --live 变量，风格与 .s-live/.s-replay 一致 */
.pf.ok{background:rgba(46,213,115,.15);color:var(--green)}
.pf.bad{background:rgba(255,71,87,.15);color:var(--live)}
```

> 平台名徽标直接复用既有 `.pf.bili` / `.pf.dy`，无需新增。整段不引入任何 JS、不绑定事件。

### 3.3 `check.yml` 改动（删除死代码 + 修正 `if`）

| 改动点 | 现状（行号参考） | 目标 |
|---|---|---|
| 前置注释（L39-40） | `# 判断 rooms.json 是否含需无头浏览器的平台房间……保留 xhs 判断以便未来恢复小红书检测时自动触发 chromium 安装` | **整段删除**（该注释描述的是 xhs 步骤，删除后不再适用，且含 xhs 幽灵引用） |
| `Check xhs rooms` 步骤（L41-45, id: xhslist） | `- name: Check xhs rooms` … `id: xhslist` … `run: n=$(… platform=='xhs' …)` | **整段删除** |
| `Cache Playwright browsers` 的 `if`（L57） | `if: ${{ steps.xhslist.outputs.enabled == 'true' \|\| steps.postlist.outputs.enabled == 'true' }}` | `if: ${{ steps.postlist.outputs.enabled == 'true' }}` |
| `Install Playwright` 的 `if`（L65） | `if: ${{ steps.xhslist.outputs.enabled == 'true' \|\| steps.postlist.outputs.enabled == 'true' }}` | `if: ${{ steps.postlist.outputs.enabled == 'true' }}` |

> 全仓仅 `check.yml` 含 `xhslist` / `Check xhs rooms`（已 grep 确认），删改后该 workflow 不再有 `steps.xhslist` 引用，语法安全。`Install Playwright` / `Cache Playwright browsers` 现在仅由抖音作品监控开关 `postlist` 控制，与 PRD 一致。

### 3.4 一致性测试签名伪代码（新增 `tests/test_platform_position.py`）

```python
"""P0-5 平台定位一致性守护：前端固化 + 死代码清理 + 无幽灵声明。"""
import os, re, json
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def _read(p): return open(os.path.join(REPO_ROOT, p), encoding="utf-8").read()

def test_frontend_has_supported_platforms_block():
    html = _read("monitor.html")
    assert 'id="supportedPlatforms"' in html
    assert "已支持" in html and "已放弃，不计划支持" in html

def test_rooms_no_xhs():
    data = json.loads(_read("rooms.json"))
    assert not any(r.get("platform") == "xhs" for r in data)

def test_workflow_no_xhs_dead_step():
    wf = _read(".github/workflows/check.yml")
    assert "Check xhs rooms" not in wf
    assert "xhslist" not in wf

def test_no_ghost_claims():
    # 仅扫描产品/贡献者可见文档；排除合法引用的分析文档与本期过程文档
    targets = ["README.md",
               "docs/blive-monitor-context.md",
               "docs/live-monitor-detection-landscape.md"]
    ghost = ("15 passed","15 单测","补了行业空白","已端到端验证",
             "test_check_xhs","补空白","最关键的技术突破","已实现小红书")
    for t in targets:
        doc = _read(t)
        for g in ghost:
            assert g not in doc, f"{t} 含幽灵声明: {g}"

def test_check_status_no_xhs_branch():
    # 重申：check_status.py 无小红书实现函数，提及均带「已移除/未支持」标注
    src = _read("check_status.py")
    for fn in ("fetch_xiaohongshu","parse_xiaohongshu","query_xiaohongshu",
               "fetch_xhs","parse_xhs","_extract_xhs_state"):
        assert fn not in src, f"check_status.py 仍存在小红书实现: {fn}"
```

> 风格对齐既有 `tests/test_phase0_hardening.py`（`REPO_ROOT` + `_read` + `open` 文件系统读取，不执行 JS、不启动浏览器）。

---

## 4. 程序调用流程（无运行时逻辑，编号改动步骤）

```
[配置页渲染（纯静态）]
  1. 浏览器加载 monitor.html → CSS 定义 .pf.ok/.pf.bad
  2. #view-config 顶部直接渲染 #supportedPlatforms 卡片（HTML 静态内容，无 JS 绑定）

[CI 构建期（GitHub Actions）]
  3. check.yml 不再有 Check xhs rooms 步骤
  4. Cache/Install Playwright 的 if 仅依赖 steps.postlist.outputs.enabled

[回归测试（pytest，本地/CI test job）]
  5. test_frontend_has_supported_platforms_block → 读 monitor.html，断言区块 + 标记
  6. test_rooms_no_xhs → 读 rooms.json，断言无 platform=='xhs'
  7. test_workflow_no_xhs_dead_step → 读 check.yml，断言无 Check xhs rooms / xhslist
  8. test_no_ghost_claims → 读产品文档，断言无幽灵声明 token
  9. test_check_status_no_xhs_branch → 读 check_status.py，断言无 xhs 实现函数
```

---

## 5. 任务列表（有序、含依赖）

| 任务 | 名称 | 源文件 | 依赖 | 优先级 |
|---|---|---|---|---|
| **T1** | 前端固化支持平台区块 | `monitor.html`（新增 `id="supportedPlatforms"` 卡片 HTML + `.pf.ok`/`.pf.bad` CSS，插入配置页顶部） | 无 | P0 |
| **T2** | 清理 workflow 小红书死代码 | `.github/workflows/check.yml`（删 `Check xhs rooms` 步骤整段 + 前置注释；L57/L65 的 `if` 改为仅 `steps.postlist.outputs.enabled == 'true'`） | 无 | P0 |
| **T3** | 新增平台定位一致性测试 | `tests/test_platform_position.py`（5 个断言，见 §3.4） | T1、T2 | P0 |

> T1 与 T2 互相独立、可并行；T3 断言 T1/T2 的落地结果，故依赖二者。本期仅 P0（P1-1 adapter 扩展点、P2-1 小红书重做均回退）。

---

## 6. 依赖包

**无。** 纯静态 HTML/CSS 改动 + YAML 配置清理 + 标准库（`os`/`re`/`json`）+ pytest（已在 `requirements-dev.txt`，沿用既有 test job）。

---

## 7. 共享知识（跨文件约定）

- **区块文案口径**：终态词「已支持 / 已放弃，不计划支持」，禁用任何过渡词；小红书行附一句根因（短链易变 / 数据中心 IP 风控 / 维护成本高）。
- **状态徽标样式复用**：`.pf.ok`（绿，用 `--green`）/ `.pf.bad`（红，用 `--live`）与既有 `.s-live`/`.s-replay` 同色系；平台名徽标复用 `.pf.bili`/`.pf.dy`。新增 CSS 仅 2 行。
- **测试一律用文件系统读取**：`open(..., encoding="utf-8")` + 字符串包含 / `re` / `json.loads`，**不执行 JS、不启动浏览器、不发网络请求**，与 `test_phase0_hardening.py` 一致。
- **幽灵声明扫描范围（重要）**：仅扫描对外/对贡献者可见的**产品文档** —— `README.md` + `docs/blive-monitor-context.md` + `docs/live-monitor-detection-landscape.md`；**排除** `docs/product_analysis.md`（合法引用，正文以「实际这些全部不存在于当前代码」否定虚假声明）以及本期**过程文档**（`docs/p0_platform_position_prd.md`、本设计稿）—— 后者需引用这些 token 来定义「应避免什么」，若纳入自查会自我误报。
- **rooms.json 契约**：`platform` 取值仅为 `bilibili` / `douyin`，不得出现 `xhs`（已由 T3 锁死）。

---

## 8. 待明确事项（PRD 开放问题 → 设计收敛）

| # | PRD 开放问题 | 设计处理 | 状态 |
|---|---|---|---|
| 1 | 区块位置：配置页顶部 / 直播 banner / 两者 | 默认：配置页顶部第一个 `.room`（`id="supportedPlatforms"`），改动最小、不与直播过滤 chip 混淆 | ✅ 设计已按默认处理 |
| 2 | workflow 直接删 vs 预留注释段 | 默认：直接移除 `Check xhs rooms` 整段（主理人倾向），不留误导源 | ✅ 设计已按默认处理 |
| 3 | 本轮回退 P1-1 adapter 扩展点？ | 默认：回退，本期仅做 P0（当前仅 2 平台，抽象 ROI 低） | ✅ 设计已按默认处理 |
| 4 | 小红书文案是否附根因 | 默认：附一句根因（短链易变 / IP 风控 / 维护成本高），若嫌长可精简 | ✅ 设计已按默认处理 |
| 5 | 幽灵声明扫描范围（核对中补充发现） | 默认：限定为 3 份产品文档，排除分析文档 + 过程文档自身（见 §7），避免自查误报 | ⚠️ 设计已按默认处理，建议用户拍板确认范围口径 |

> 以上 1-4 均按 PRD 主推/主理人倾向默认落定；第 5 点为我在核对现有测试范围时补充收敛的设计决策，建议主理人确认是否认可「仅扫产品文档、排除过程文档自身」的口径（否则测试会因本 PRD/设计稿引用幽灵 token 而自我失败）。

---

## 9. 风险与阻塞

- **零运行时风险**：纯静态展示 + YAML 配置清理，不涉及监控/推送/健康条逻辑；前端体积增量可忽略。
- **CI 语法安全**：删除 `xhslist` 步骤后已确认全仓无其他 `steps.xhslist` 引用，两处 `if` 改为仅依赖 `postlist`，YAML 合法。
- **硬阻塞**：**无。** 所有改动所需上下文已核对完备，可直接指导工程师落地。唯一需主理人拍板的是 §8 第 5 点（幽灵扫描范围口径），属非阻塞的口径确认。
