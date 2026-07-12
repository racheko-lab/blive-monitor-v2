#!/usr/bin/env python3
"""
级联清理模块（孤儿记录 / 字段合并）。

纯函数 + common.save_json_file 原子写，不引入额外状态。
所有「孤儿识别」必须基于「重读磁盘当前内容」构造的 active_keys，
绝不使用启动内存副本，以避免与前端增删竞态（防止复活已删账号）。

识别键约定（与 docs/system_design.md §8 一致）：
  - history 孤儿：``f"{platform}|{rid}"``（来自当前磁盘 rooms.json）
  - post_tracking 孤儿：``f"douyin_{rid}"``（来自当前磁盘 post_rooms.json）
"""

import common


def prune_history_orphans(history, active_keys):
    """级联清理 history.json 孤儿：仅保留 ``f"{platform}|{rid}" ∈ active_keys`` 的条目。

    Args:
        history: history.json 内容（list[dict]）。
        active_keys: 活钥集合，元素形如 ``"platform|rid"``（来自当前磁盘 rooms.json）。

    Returns:
        清理后的 history 列表（新对象，不改写入参）。

    Note:
        对无 rid 的存量（历史）条目（本次重构前写入，结构无 rid），因无法用 rid 精确归因，
        一律保留，避免首轮部署即清空全部历史；后续新写入的条目带 rid，可被正确裁剪。
    """
    if not isinstance(history, list):
        return []
    if not isinstance(active_keys, set):
        active_keys = set(active_keys)

    result = []
    for entry in history:
        if not isinstance(entry, dict):
            continue
        rid = entry.get("rid")
        if rid:  # 新结构：按 platform|rid 精确匹配
            key = f"{entry.get('platform', '')}|{rid}"
            if key in active_keys:
                result.append(entry)
        else:  # 存量无 rid：保守保留（无法可靠归因）
            result.append(entry)
    return result


def prune_tracking_orphans(tracking, active_keys):
    """级联清理 post_tracking.json 孤儿：删除 ``key ∉ active_keys`` 的账号状态。

    Args:
        tracking: post_tracking.json 内容（dict，key 形如 ``"douyin_{rid}"``）。
        active_keys: 活钥集合，元素形如 ``"douyin_{rid}"``（来自当前磁盘 post_rooms.json）。

    Returns:
        清理后的 tracking 字典（新对象）。
    """
    if not isinstance(tracking, dict):
        return {}
    if not isinstance(active_keys, set):
        active_keys = set(active_keys)
    return {k: v for k, v in tracking.items() if k in active_keys}


def merge_post_rooms_fields(config_file, resolved):
    """重读磁盘 post_rooms.json，仅对仍存在的账号「原地」更新 sec_uid/name。

    用本轮解析到的值（resolved）回填磁盘文件中「仍存在的」账号字段：
      - 绝不把内存副本里多出来的账号写回（即不复活前端已删除的账号）；
      - 仅当有字段实际变化时回写，避免无意义提交。

    Args:
        config_file: post_rooms.json 路径。
        resolved: ``{rid: entry}`` 本轮解析/写回过的账号（entry 含最新 sec_uid/name）。

    Returns:
        是否发生了字段变更（bool）。仅在变更时原子写回磁盘。
    """
    current_rooms = common.load_json_file(config_file, []) or []
    if not isinstance(current_rooms, list):
        current_rooms = []
    if not isinstance(resolved, dict):
        resolved = {}

    changed = False
    for entry in current_rooms:
        if not isinstance(entry, dict):
            continue
        rid = str(entry.get("id", ""))
        if not rid:
            continue
        r = resolved.get(rid)
        if not r:
            continue
        new_sec = r.get("sec_uid")
        new_name = r.get("name")
        if new_sec and entry.get("sec_uid") != new_sec:
            entry["sec_uid"] = new_sec
            changed = True
        if new_name and entry.get("name") != new_name:
            entry["name"] = new_name
            changed = True

    if changed:
        common.save_json_file(config_file, current_rooms)
    return changed
