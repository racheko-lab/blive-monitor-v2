# 给其他工具的提示词（复制即用）

> 本文件随整合包一起放入仓库 `blive-monitor-handoff/`，供你直接复制给其它 AI 工具 / 协作者。
> 前置：对方应能访问 GitHub 仓库 `racheko-lab/blive-monitor`（已含本目录），或你先把本目录发给它。

---

## 0. 背景卡（粘贴到任意对话开头，建立上下文）

```
你将要处理的项目是 GitHub 上的 racheko-lab/blive-monitor：一个 B站/抖音 直播+新作监控工具。
后端是 Python（GitHub Actions CI 每5分钟检测，结果写仓库 JSON），前端是单文件 SPA monitor.html（直连 GitHub Contents API 渲染），开播/新作时多渠道推送。

当前痛点：雇主判定前端"整体布局混乱"。已知背景与雷区见仓库内 blive-monitor-handoff/PROJECT_SUMMARY.md（必读），
其中 §3 是"需求/雇主侧不合理"，§4 是"UI 侧不合理"，§5.2 是改动前必读的"雷区清单"（被测试 grep 保护的元素 id / 函数名 / CSS 别名，动了测试就崩）。

注意：本仓库前端曾硬编码一个全权限默认 GitHub Token，已在 blive-monitor-handoff/ 副本中脱敏。真实工程应轮换并吊销该 Token。
```

---

## 1. 提示词 A —— 先诊断 + 出方案（不动代码）

```
你是资深前端工程师。请阅读 GitHub 仓库 racheko-lab/blive-monitor，重点看：
1) blive-monitor-handoff/PROJECT_SUMMARY.md（背景与雷区）
2) 根目录 monitor.html（单文件 SPA，约 4959 行 / 319 个 div）

雇主判定该前端"整体布局混乱"。请只做分析与方案，不要改代码：
1. 诊断布局混乱的根因（重点关注：桌面端被锁 max-width:430px、真实数据密度——直播11房/新作12条/日志101条、单文件巨石、配置视图100+ div 堆砌、无路由无 URL 状态等）。
2. 给出重构方案，明确区分两类：
   a) 在不破坏现有测试契约（见 §5.2 雷区）前提下能做的最小改动；
   b) 必须松绑契约（允许改测试/改结构/拆文件/引构建工具）才能做的"真正重构"。
3. 给出可量化的"UI 验收标准"建议（桌面/移动各自什么样算"不乱"）。
输出：根因清单 + 分层方案 + 验收标准。代码 0 改动。
```

---

## 2. 提示词 B —— 真正重构（授权松绑契约，推荐给"能大改"的工具）

```
你是前端重构负责人。仓库 racheko-lab/blive-monitor 的 monitor.html 是一个约 4959 行单文件 SPA，前端直连 GitHub API。
雇主要求重构 UI/布局（当前被判"整体乱"）。先读 blive-monitor-handoff/PROJECT_SUMMARY.md 了解背景与雷区（§5.2）。

本次授权你：
- 可以修改/补充测试（tests/ 下，约 511 例，含大量 grep 源码字符串的契约测试）；
- 可以调整各 render* 函数输出的 HTML 结构；
- 可以引入构建工具或拆分文件（如 Vite + React / 或至少拆成多文件 + 模板）；
- 目标是做出"桌面宽屏 + 移动端都清晰"的监控面板，信息密度合理、有视觉呼吸。

硬性底线（不可越界）：
- 功能逻辑不动：检测 / 推送 / 数据层（push_utils.py、check_status.py、check_new_posts.py、common.py、backend/ 等）零改动；
- 不引入需要服务端密钥的架构（保持"前端直连 GitHub"的可部署性，除非你明确论证替代方案）；
- 不得把任何 GitHub Token 写进前端源码（此前有硬编码默认 Token 的安全债，应彻底移除）。

交付：实施计划 + 执行 + 跑 `python -m pytest tests/ -q` 确认通过（或说明为何需调整某条测试及其合理性）。
```

---

## 3. 提示词 C —— 聚焦"桌面响应式 + 降噪"（保守，保契约）

```
你是前端工程师。请重构 racheko-lab/blive-monitor 的 monitor.html 布局，解决三个具体问题：
1) 桌面端（≥1100px）不再是 430px 窄条漂浮在空白里，改为宽屏多列（直播房间卡2列、新作卡3列、日志2列、仪表盘图表并排）；
2) 日志视图约 101 条做虚拟滚动或分页，避免单次渲染过长；
3) 配置视图（约100+ div）做分组折叠，降低纵向堆砌。

约束（重要）：
- 只能改 <style> CSS + 各 render* 函数生成的 HTML 模板字符串；
- 保留所有被测试 grep 的元素 id 与 JS 函数名/签名（详见 blive-monitor-handoff/PROJECT_SUMMARY.md §5.2 雷区清单）；
- 保留 :root 遗留 CSS 变量别名（--green/--live/--bili/--bg/--radius 等）与 Phase-1 类（.health.*/.pf.ok/.toast*/.view/.ld-*/.chip/.lchip/.blm-room-link）；
- 不得改动任何 JS 函数逻辑。

完成后跑 `python -m pytest tests/ -q` 确认 0 回归。若某条契约与"真正重构"冲突，停下来说明，不要硬改。
```

---

## 4. 提示词 D —— 安全整改专用（如果要先排雷）

```
你是安全工程师。仓库 racheko-lab/blive-monitor 的 monitor.html 曾硬编码一个全权限默认 GitHub Token（DEFAULT_GH_TOKEN，repo+workflow 权限），
这是暴露在公开源码里的严重凭据。请：
1) 确认当前仓库与 blive-monitor-handoff/ 副本中该 Token 是否已脱敏（grep 完整令牌字面量应为 0 命中）；
2) 给出整改清单：前端不再内置任何凭据；Token 改为用户自填并存 localStorage；
   说明原默认 Token 应如何在 GitHub 侧轮换/吊销；
3) 检查其它可能泄露密钥的位置（推送配置、worker.js、cors-proxy 等），列出风险与修复建议。
输出：风险清单 + 修复步骤，不改业务代码。
```

---

## 5. 使用建议

- 想"先看清楚再决定" → 用 **提示词 A**。
- 想把 UI 真正重做一遍 → 用 **提示词 B**（给工具最大权限）。
- 想快速见效果、怕破坏现有测试 → 用 **提示词 C**。
- 想先把安全雷排掉 → 用 **提示词 D**。
- 把 **背景卡（§0）** 贴进任意对话开头，再跟 A/B/C/D 之一即可。
