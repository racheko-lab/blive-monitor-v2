#!/usr/bin/env python3
"""
状态文件合并工具（CI 持久化步骤使用）

解决的问题
----------
CI 的 Persist 步骤原本用 `git pull --rebase` 拉取远端最新后再提交本地状态。
但当远端和本地都修改了同一批状态文件（state.json / tracking.json /
post_tracking.json / notify_dedup.json 等）时，rebase 会因冲突而失败；
abort 后本地提交基于旧 base，push 非快进被拒，状态丢失。
下一轮 checkout 到旧状态，会把已推送过的「新作品」/「开播」当成首次检测
重新推送 —— 这正是重复推送的根因。

解决思路
----------
不再依赖 Git 的文本级 rebase 合并状态文件（JSON 语义 Git 不懂），
而是在 Python 层面做语义合并：

  1. git fetch origin <branch>（不 merge、不 rebase）
  2. 本脚本读取本地 + 远端两份状态文件，按字段语义合并
  3. 合并后的文件覆盖本地，git add + commit + push

合并规则
----------
  notify_dedup.json : 取并集（local ∪ remote），同一 key 保留更早的 ts
                      —— 绝不丢失任何去重记录，是防重复推送的核心
  post_tracking.json: 每个账号取基线更新的那份（aweme_id 数值更大，或
                      create_time 更新）；sec_uid/nickname 取非空值
  post_rooms.json   : 取并集（按 id 去重），sec_uid 取非空值
  state.json        : 取本地（本 run 刚写入，最新）
  tracking.json     : 取本地（本 run 刚写入，最新）
  history.json      : 取并集（按 time+name 去重，保留最近 N 条）

用法
----------
  python3 merge_state.py origin/master
  python3 merge_state.py origin/master --repo /path/to/repo
"""

import argparse
import json
import os
import subprocess
import sys
from typing import Any, Dict, Optional, Tuple

# 合并时保留的历史日志上限
HISTORY_MAX = 500


def git_show(repo: str, ref: str, filename: str) -> Optional[str]:
    """读取远端某个 ref 的文件内容，失败返回 None。"""
    try:
        result = subprocess.run(
            ["git", "-C", repo, "show", f"{ref}:{filename}"],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode == 0:
            return result.stdout
        return None
    except Exception:
        return None


def load_json(text: Optional[str]) -> Dict[str, Any]:
    """安全解析 JSON，空/异常返回 {}。"""
    if not text:
        return {}
    try:
        return json.loads(text)
    except Exception:
        return {}


def load_local_json(filepath: str) -> Dict[str, Any]:
    """读取本地 JSON 文件，不存在返回 {}。"""
    if not os.path.exists(filepath):
        return {}
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def merge_notify_dedup(local: Dict, remote: Dict) -> Dict:
    """合并去重账本：取并集，同一 key 保留更早的 ts。

    绝不丢失任何去重记录 —— 这是防止重复推送的核心防线。
    """
    merged = {}
    for key in set(local.keys()) | set(remote.keys()):
        l_ts = _get_ts(local.get(key))
        r_ts = _get_ts(remote.get(key))
        # 保留更早的时间戳（首次推送时间）
        ts = min(l_ts, r_ts) if (l_ts and r_ts) else (l_ts or r_ts)
        merged[key] = {"ts": ts}
    return merged


def _get_ts(entry) -> float:
    """从账本条目提取时间戳，异常返回 0。"""
    if not entry or not isinstance(entry, dict):
        return 0.0
    try:
        return float(entry.get("ts", 0))
    except (ValueError, TypeError):
        return 0.0


def _aweme_sort_value(aweme_id: str) -> int:
    """把 aweme_id 转为可比较的数值。非数字（如 count:63）取数字部分。"""
    if not aweme_id:
        return 0
    s = aweme_id.removeprefix("count:")
    try:
        return int(s)
    except ValueError:
        return 0


def merge_post_tracking(local: Dict, remote: Dict) -> Dict:
    """合并作品追踪状态：每个账号取基线更新的那份。

    判断「更新」：aweme_id 数值更大（抖音 id 单调递增）。
    sec_uid / nickname 取非空值（优先 local）。
    """
    merged = {}
    for key in set(local.keys()) | set(remote.keys()):
        l = local.get(key, {})
        r = remote.get(key, {})
        if not l and r:
            merged[key] = r
            continue
        if l and not r:
            merged[key] = l
            continue

        # 两方都有：取基线更新的
        l_aid = l.get("latest_aweme_id", "")
        r_aid = r.get("latest_aweme_id", "")
        l_val = _aweme_sort_value(l_aid)
        r_val = _aweme_sort_value(r_aid)

        if r_val > l_val:
            base = dict(r)
            # 但保留 local 的 sec_uid / nickname（如果非空）
            for field in ("sec_uid", "nickname"):
                if l.get(field):
                    base[field] = l[field]
        else:
            base = dict(l)
            for field in ("sec_uid", "nickname"):
                if r.get(field) and not base.get(field):
                    base[field] = r[field]
        merged[key] = base
    return merged


def merge_post_rooms(local: list, remote: list) -> list:
    """合并作品监控列表：取并集（按 id 去重），sec_uid 取非空值。"""
    if not isinstance(local, list):
        local = []
    if not isinstance(remote, list):
        remote = []
    by_id = {}
    # 先放 remote，再 local 覆盖（local 优先，因为本 run 可能新增了 sec_uid）
    for entry in remote:
        rid = entry.get("id", "")
        if rid:
            by_id[rid] = entry
    for entry in local:
        rid = entry.get("id", "")
        if not rid:
            continue
        if rid in by_id:
            # 合并：sec_uid 取非空
            merged = dict(by_id[rid])
            for field in ("sec_uid", "name"):
                if entry.get(field):
                    merged[field] = entry[field]
            by_id[rid] = merged
        else:
            by_id[rid] = entry
    return list(by_id.values())


def merge_history(local: list, remote: list) -> list:
    """合并历史日志：取并集（按 time+name+platform 去重），保留最近 N 条。"""
    if not isinstance(local, list):
        local = []
    if not isinstance(remote, list):
        remote = []
    seen = set()
    merged = []
    # 先放 remote（旧数据），再 local（新数据覆盖）
    for entry in remote + local:
        if not isinstance(entry, dict):
            continue
        key = (entry.get("time", ""), entry.get("name", ""), entry.get("platform", ""))
        if key in seen:
            continue
        seen.add(key)
        merged.append(entry)
    # 保留最近 N 条
    if len(merged) > HISTORY_MAX:
        merged = merged[-HISTORY_MAX:]
    return merged


def save_json(filepath: str, data: Any) -> None:
    """原子写 JSON 文件。"""
    tmp = f"{filepath}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, filepath)


def main() -> int:
    parser = argparse.ArgumentParser(description="合并本地与远端状态文件")
    parser.add_argument("ref", help="远端 ref（如 origin/master）")
    parser.add_argument("--repo", default=".", help="仓库路径（默认当前目录）")
    args = parser.parse_args()

    repo = os.path.abspath(args.repo)
    ref = args.ref

    # 定义需要合并的文件及其合并策略
    # (filename, merge_func, is_list)
    mergers = [
        ("notify_dedup.json", merge_notify_dedup, False),
        ("post_tracking.json", merge_post_tracking, False),
        ("post_rooms.json", merge_post_rooms, True),
        ("history.json", merge_history, True),
    ]

    changed = False
    for filename, merge_fn, is_list in mergers:
        filepath = os.path.join(repo, filename)
        local_data = load_local_json(filepath)
        if is_list:
            local_data = local_data if isinstance(local_data, list) else []
        remote_text = git_show(repo, ref, filename)

        # 如果远端没有该文件，跳过（本地版本即为最终版本）
        if remote_text is None:
            print(f"  {filename}: 远端无此文件，保留本地版本")
            continue

        if is_list:
            try:
                remote_data = json.loads(remote_text) if remote_text else []
                if not isinstance(remote_data, list):
                    remote_data = []
            except Exception:
                remote_data = []
        else:
            remote_data = load_json(remote_text)

        merged = merge_fn(local_data, remote_data)

        # 检查是否有变化
        local_str = json.dumps(local_data, ensure_ascii=False, sort_keys=True)
        merged_str = json.dumps(merged, ensure_ascii=False, sort_keys=True)
        if local_str != merged_str:
            save_json(filepath, merged)
            l_count = len(local_data) if isinstance(local_data, (dict, list)) else 0
            r_count = len(remote_data) if isinstance(remote_data, (dict, list)) else 0
            m_count = len(merged) if isinstance(merged, (dict, list)) else 0
            print(f"  {filename}: 合并完成 local={l_count} remote={r_count} → merged={m_count}")
            changed = True
        else:
            print(f"  {filename}: 无变化")

    # state.json 和 tracking.json：取本地（本 run 刚写入，是最新的）
    for filename in ("state.json", "tracking.json"):
        filepath = os.path.join(repo, filename)
        if os.path.exists(filepath):
            print(f"  {filename}: 保留本地版本（本 run 最新）")

    if changed:
        print("状态文件合并完成，有变更需要提交")
    else:
        print("状态文件合并完成，无变更")
    return 0


if __name__ == "__main__":
    sys.exit(main())
