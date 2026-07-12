# 打包说明（PACKAGE NOTES）

- **打包日期**：见本目录文件时间戳（约 2026-07-12）。
- **来源**：`racheko-lab/blive-monitor` 仓库工作树（不含 `.git` 历史）。
- **目的**：整合整个项目 + 总结，交由其他工具 / 协作者接手尝试（尤其 UI 重构）。

## 已剔除（安全 / 噪音）
| 项 | 原因 |
|----|------|
| `.git/` | 避免令牌随提交历史泄露；且历史对"试 UI"无用 |
| `__pycache__/` `.pytest_cache/` | Python 缓存噪音 |
| `qa_verify_a2a4.py` | **含完整明文 PAT**（grep 测试用），绝不外发 |
| `node_modules/` | 无 |
| `.keepalive` `.refresh` | CI 保活占位文件 |

## 已脱敏
- `monitor.html` 第 2453 行：原内置默认 `DEFAULT_GH_TOKEN`（全权限 PAT，分串拼接硬编码）已置空并加注释说明。
  - ⚠️ 真实工程中应**轮换并吊销该 Token**、前端不再内置任何凭据。
- `README.md` / `docs/product_analysis.md` / 几份 QA 报告仍**提及 `ghp_` 前缀**（讨论性质，非令牌），未改动。

## 校验
- 全包 `grep` 完整令牌字面量 = **0 命中** ✅
- 测试基数：约 **511** 例（53 个测试文件）；前端契约测试见 `tests/test_*_clickable.py` 等。

## 使用建议
1. 先用 `PROJECT_SUMMARY.md` 了解"为什么乱、改不动在哪"。
2. 动 UI 前必读 §5.2 雷区清单（受测试 grep 保护的 id / 函数 / CSS 别名）。
3. 如需本地起前端看效果：起任意静态服务器指向本目录（如 `python3 -m http.server`），开 `monitor.html`；数据走相对路径 JSON（本包已带 `*.json` 运行时状态）。
