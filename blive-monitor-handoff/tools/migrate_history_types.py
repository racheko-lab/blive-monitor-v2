#!/usr/bin/env python3
"""存量 history.json 按 status 推导补 type（幂等，可重跑）。

- 仅对缺 ``type`` 的条目补写 ``type``（由 ``log_utils.type_from_status`` 推导）与
  ``level``（由 type 推导）；已存在 ``type`` 的条目不覆盖；
- 默认就地写回 history.json（原子写，复用 ``common.save_json_file``）；
  ``--dry-run`` 仅预览、不改变文件；
- 可重复运行，结果稳定（幂等）。

用法:
    python3 tools/migrate_history_types.py [history.json 路径] [--dry-run]
"""
import os
import sys

# 工具脚本位于 tools/ 子目录，需把仓库根目录加入 sys.path 才能 import common / log_utils
# （既支持 `python3 tools/migrate_history_types.py` 直接运行，也支持测试通过 importlib 加载）
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import common
import log_utils as lu


def backfill_type(entry: dict) -> dict:
    """给单条历史补 ``type``/``level``（缺省按 status 推导）；已存在不覆盖。原地修改并返回。"""
    if not isinstance(entry, dict):
        return entry
    if "type" not in entry:
        entry["type"] = lu.type_from_status(entry.get("status"))
    if "level" not in entry:
        entry["level"] = lu.level_from_type(entry["type"])
    return entry


def run(history_path: str, dry_run: bool = False) -> int:
    """对 history.json 做幂等迁移；返回补写条数。"""
    history = lu.load_history(history_path)
    changed = 0
    for e in history:
        if "type" not in e:
            backfill_type(e)
            changed += 1
    if changed and not dry_run:
        common.save_json_file(history_path, history)
        print(f"[migrate] 已写回 {changed} 条 type/level → {history_path}")
    elif changed and dry_run:
        print(f"[migrate][dry-run] 将补写 {changed} 条 type/level（未写盘）")
    else:
        print(f"[migrate] 无缺失 type，无需迁移：{history_path}")
    return changed


def main() -> int:
    args = sys.argv[1:]
    dry_run = "--dry-run" in args
    # 默认路径：本脚本位于 tools/ 下，history.json 在仓库根目录
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    history_path = os.path.join(repo_root, "history.json")
    for a in args:
        if a != "--dry-run" and not a.startswith("-"):
            history_path = a
            break
    run(history_path, dry_run=dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
