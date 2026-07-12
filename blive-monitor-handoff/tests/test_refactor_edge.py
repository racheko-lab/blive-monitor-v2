"""日志模块重构 · 独立验证（QA 强化边界用例）。

覆盖 system_design.md 要求的风险点边界与异常：
  - prune_history_orphans：rooms.json 全空（首轮避免清空历史）、全 legacy 保留、
    active_keys 接受 list、跳过非 dict、rid=0(int) 视为 legacy、保留 rid 字段。
  - prune_tracking_orphans：空 active / 空 tracking / active_keys 接受 list。
  - merge_post_rooms_fields：resolved 为空、账号全删、仅 sec_uid 变、仅 name 变、
    resolved 无 sec_uid 仅更新 name、文件损坏不抛异常。
  - init_runtime_logging：轮转真正触发并产生备份、幂等不重复添加 RotatingFileHandler。
  - HISTORY_MAX 单一来源：源码中 check_status/merge_state 不得再各自定义 HISTORY_MAX。
  - check.yml：YAML 合法、CI 两脚本调用未变、Upload artifact 指向 logs/。

设计原则：纯函数测试不依赖具体时间/随机，可重复；不导入 check_status/check_new_posts
（避免其模块级 init_runtime_logging 产生副作用），仅直接测 state_prune / log_utils 与读配置。
"""
import io
import json
import logging
import os
import re

import pytest

import log_utils as lu
import state_prune as sp

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ==================== prune_history_orphans 边界 ====================

def test_pho_rooms_empty_keeps_legacy_drops_rid():
    # active_keys 为空（rooms.json 全删 / 首轮）：legacy（无 rid）保守保留，
    # 带 rid 的孤儿被裁 —— 既避免首轮清空全部历史，又能正确裁剪 rid 孤儿。
    history = [
        {"platform": "bilibili", "name": "Old1"},   # legacy
        {"platform": "douyin", "name": "Old2"},      # legacy
        {"platform": "bilibili", "rid": "1", "name": "X"},  # rid 孤儿 -> 裁
    ]
    out = sp.prune_history_orphans(history, set())
    names = {e["name"] for e in out}
    assert names == {"Old1", "Old2"}   # legacy 全保留
    assert "X" not in names


def test_pho_all_legacy_kept_when_active_empty():
    # 全部为无 rid 存量：即便 active 为空也不误清（首轮安全）。
    history = [{"name": f"H{i}"} for i in range(20)]
    out = sp.prune_history_orphans(history, set())
    assert len(out) == 20


def test_pho_accepts_list_active_keys():
    history = [{"platform": "bilibili", "rid": "1", "name": "A"}]
    out = sp.prune_history_orphans(history, ["bilibili|1"])  # 传 list 也能用
    assert [e["name"] for e in out] == ["A"]


def test_pho_skips_non_dict_entries():
    history = [
        {"platform": "bilibili", "rid": "1", "name": "A"},
        "corrupt",                       # 非 dict -> 跳过（不崩溃）
        123,                             # 非 dict -> 跳过
        {"platform": "douyin", "rid": "9", "name": "B"},
    ]
    out = sp.prune_history_orphans(history, {"bilibili|1", "douyin|9"})
    assert {e["name"] for e in out} == {"A", "B"}


def test_pho_int_zero_rid_treated_as_legacy():
    # rid 为 falsy 值（整数 0 / None / ""）时按 legacy 保守保留，避免误裁。
    history = [
        {"platform": "bilibili", "rid": 0, "name": "Z"},
        {"platform": "douyin", "rid": None, "name": "Y"},
    ]
    out = sp.prune_history_orphans(history, set())
    assert {e["name"] for e in out} == {"Z", "Y"}


def test_pho_preserves_rid_field_on_kept():
    # 保留的条目 rid 字段不被破坏（前端忽略、级联合并透传）。
    history = [{"platform": "bilibili", "rid": "42", "name": "A", "title": "t"}]
    out = sp.prune_history_orphans(history, {"bilibili|42"})
    assert out[0]["rid"] == "42"
    assert out[0]["title"] == "t"


# ==================== prune_tracking_orphans 边界 ====================

def test_pto_empty_active_drops_all():
    tracking = {"douyin_A": {"latest_aweme_id": "1"}}
    assert sp.prune_tracking_orphans(tracking, set()) == {}


def test_pto_empty_tracking_returns_empty():
    assert sp.prune_tracking_orphans({}, {"douyin_A"}) == {}


def test_pto_accepts_list_active_keys():
    tracking = {"douyin_A": {"x": 1}, "douyin_B": {"x": 2}}
    out = sp.prune_tracking_orphans(tracking, ["douyin_A"])
    assert set(out.keys()) == {"douyin_A"}


# ==================== merge_post_rooms_fields 边界 ====================

def test_merge_empty_resolved_no_write(tmp_path):
    cfg = tmp_path / "post_rooms.json"
    cfg.write_text(json.dumps([{"id": "A", "name": "A", "sec_uid": ""}]), encoding="utf-8")
    changed = sp.merge_post_rooms_fields(str(cfg), {})  # resolved 空
    assert changed is False
    # 文件内容不变、无 .tmp 残留
    data = json.loads(cfg.read_text(encoding="utf-8"))
    assert data == [{"id": "A", "name": "A", "sec_uid": ""}]
    assert not list(tmp_path.glob("*.tmp"))


def test_merge_all_rooms_deleted(tmp_path):
    cfg = tmp_path / "post_rooms.json"
    cfg.write_text(json.dumps([]), encoding="utf-8")  # 账号全删
    resolved = {"A": {"id": "A", "name": "A", "sec_uid": "SA"}}
    changed = sp.merge_post_rooms_fields(str(cfg), resolved)
    assert changed is False  # 无操作、不抛异常


def test_merge_secuid_same_name_changed(tmp_path):
    cfg = tmp_path / "post_rooms.json"
    cfg.write_text(json.dumps([{"id": "A", "name": "oldA", "sec_uid": "SA"}]), encoding="utf-8")
    resolved = {"A": {"id": "A", "name": "newA", "sec_uid": "SA"}}  # 仅 name 变
    changed = sp.merge_post_rooms_fields(str(cfg), resolved)
    assert changed is True
    data = json.loads(cfg.read_text(encoding="utf-8"))[0]
    assert data["name"] == "newA"
    assert data["sec_uid"] == "SA"  # sec_uid 未变不写


def test_merge_name_same_secuid_changed(tmp_path):
    cfg = tmp_path / "post_rooms.json"
    cfg.write_text(json.dumps([{"id": "A", "name": "A", "sec_uid": "OLD"}]), encoding="utf-8")
    resolved = {"A": {"id": "A", "name": "A", "sec_uid": "NEW"}}  # 仅 sec_uid 变
    changed = sp.merge_post_rooms_fields(str(cfg), resolved)
    assert changed is True
    data = json.loads(cfg.read_text(encoding="utf-8"))[0]
    assert data["sec_uid"] == "NEW"
    assert data["name"] == "A"  # name 未变不写


def test_merge_resolved_without_secuid_updates_name_only(tmp_path):
    # resolved 本轮回填无 sec_uid（仅拿到 name）：不应清空已有 sec_uid，仅更新 name。
    cfg = tmp_path / "post_rooms.json"
    cfg.write_text(json.dumps([{"id": "A", "name": "oldA", "sec_uid": "SA"}]), encoding="utf-8")
    resolved = {"A": {"id": "A", "name": "newA"}}  # 无 sec_uid 键
    changed = sp.merge_post_rooms_fields(str(cfg), resolved)
    assert changed is True
    data = json.loads(cfg.read_text(encoding="utf-8"))[0]
    assert data["name"] == "newA"
    assert data["sec_uid"] == "SA"  # 未清空


def test_merge_corrupt_file_no_raise(tmp_path):
    cfg = tmp_path / "post_rooms.json"
    cfg.write_text("{这不是合法JSON", encoding="utf-8")  # load 失败应回退默认列表
    changed = sp.merge_post_rooms_fields(str(cfg), {"A": {"id": "A", "sec_uid": "X"}})
    assert changed is False


# ==================== init_runtime_logging 轮转 / 幂等 ====================

def _clear_root_handlers():
    saved = list(logging.root.handlers)
    for h in list(logging.root.handlers):
        logging.root.removeHandler(h)
    return saved


def _restore_root_handlers(saved):
    for h in list(logging.root.handlers):
        logging.root.removeHandler(h)
    for h in saved:
        logging.root.addHandler(h)


def test_runtime_log_rotates_and_creates_backup(tmp_path, monkeypatch):
    # 缩小 maxBytes 以触发真正轮转；验证 RotatingFileHandler 实际产生备份文件。
    monkeypatch.setattr(lu, "_ROTATE_MAX_BYTES", 120)
    monkeypatch.setattr(lu, "_ROTATE_BACKUP_COUNT", 3)
    saved = _clear_root_handlers()
    try:
        lu.init_runtime_logging(level=logging.INFO, log_dir=str(tmp_path / "logs"))
        root = logging.getLogger()
        for i in range(30):  # 每条 ~70B，远超 120B -> 多次轮转
            root.info("payload-%d-" + "x" * 40, i)
        log_dir = tmp_path / "logs"
        backups = sorted(p.name for p in log_dir.glob("runtime.log.*"))
        assert backups, "应当触发轮转并产生备份文件"
        # 备份数量不超过 backupCount(3)
        assert len(backups) <= 3
    finally:
        _restore_root_handlers(saved)


def test_runtime_log_no_duplicate_rotating_handler():
    # 幂等：root 已有 handler 时不重复添加第二个 RotatingFileHandler。
    saved = _clear_root_handlers()
    try:
        logging.root.addHandler(logging.StreamHandler())  # 模拟已有 handler
        before = len(logging.root.handlers)
        before_rfh = sum(1 for h in logging.root.handlers
                         if isinstance(h, logging.handlers.RotatingFileHandler))
        lu.init_runtime_logging()
        after_rfh = sum(1 for h in logging.root.handlers
                        if isinstance(h, logging.handlers.RotatingFileHandler))
        # 不应新增任何 RotatingFileHandler
        assert after_rfh == before_rfh
        assert len(logging.root.handlers) >= before
    finally:
        _restore_root_handlers(saved)


# ==================== HISTORY_MAX 单一来源（静态守卫 D5 不再回归） ====================

def test_no_local_history_max_redefinition():
    # check_status.py / merge_state.py 不得再各自定义 HISTORY_MAX（只能用 from log_utils import）。
    for fname in ("check_status.py", "merge_state.py"):
        path = os.path.join(REPO_ROOT, fname)
        with open(path, encoding="utf-8") as f:
            for ln, line in enumerate(f, 1):
                # 匹配形如 `HISTORY_MAX = 500` 的赋值（排除 import 行）
                if re.search(r"^\s*HISTORY_MAX\s*=\s*", line):
                    raise AssertionError(f"{fname}:{ln} 不应再定义 HISTORY_MAX（应改为 from log_utils import）")
    # 同时确认单一对象身份
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "merge_state_ms", os.path.join(REPO_ROOT, "merge_state.py"))
    ms = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ms)
    assert ms.HISTORY_MAX is lu.HISTORY_MAX


# ==================== check.yml：YAML 合法 + CI 调用未变 + artifact ====================

def test_check_yml_valid_and_ci_calls_intact():
    yml_path = os.path.join(REPO_ROOT, ".github", "workflows", "check.yml")
    import yaml
    with open(yml_path, encoding="utf-8") as f:
        doc = yaml.safe_load(f)  # 不抛异常即 YAML 合法
    assert isinstance(doc, dict) and "jobs" in doc

    runs = []
    for job in doc.get("jobs", {}).values():
        for step in job.get("steps", []):
            if isinstance(step, dict) and step.get("run"):
                runs.append(step["run"])

    joined = "\n".join(runs)
    # 两个脚本调用未变（D 任务要求：CI 两脚本调用不变）
    assert "python3 check_status.py" in joined
    assert "python3 check_new_posts.py" in joined

    # Upload artifact 步骤存在且指向 logs/
    artifact_steps = []
    for job in doc.get("jobs", {}).values():
        for step in job.get("steps", []):
            if (isinstance(step, dict) and isinstance(step.get("uses"), str)
                    and "upload-artifact" in step["uses"]):
                artifact_steps.append(step)
    assert artifact_steps, "缺少 upload-artifact 步骤"
    found_logs = False
    for s in artifact_steps:
        with_block = s.get("with", {})
        path_val = with_block.get("path", "")
        if "logs" in str(path_val):
            found_logs = True
    assert found_logs, "upload-artifact 应指向 logs/ 目录"
