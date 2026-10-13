#!/usr/bin/env python3
"""清理「僵尸 run」：卡在 waiting/queued 状态、长期占着 concurrency 组坑位的 workflow run。

## 为什么需要它（2026-10-07 事故）

``check.yml`` 的 concurrency 组是 ``live-check-v2`` + ``cancel-in-progress: false``。
GitHub 的规则是**同组只允许 1 个 pending，新来的挤掉旧的**。于是只要有一个 run 卡住
不结束，之后每 5 分钟一次的触发全部变成 ``pending → 被下一个挤掉 → cancelled``，
**永远轮不到执行**，监控静默停更。

实测：run ``37438236822`` 卡在 ``waiting`` 状态 12 小时 22 分钟，导致
``status.json`` 从 2026-10-06 16:45 起停更，且**没有任何告警**。

关键认知：``timeout-minutes: 30`` 对它**无效** —— job 处于 ``waiting``（还没分配到
runner）时超时计时器根本没启动，所以它能无限期堵下去。同理 ``in_progress`` 的 run
由 GitHub 自己的 timeout 兜底，本脚本**不去动它**，避免误杀慢但正常的抓取。

## 做法

独立 concurrency 组（``blive-reaper``）的轻量 job，每 15 分钟跑一次：
把目标 workflow 中 ``status ∈ {waiting, queued}`` 且已持续超过 ``STUCK_MINUTES``
（默认 20 分钟，一轮正常抓取 4~5 分钟，留足余量）的 run 取消掉。

依赖 CI 注入的 ``GITHUB_TOKEN``，权限 ``actions: write`` 即可，无需额外密钥。
任何网络/权限失败都只告警、不 fail（看门狗自己不该把仓库搞红）。
"""
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Optional

# 目标 workflow（文件名或 id）
TARGET_WORKFLOW = os.environ.get("REAP_TARGET_WORKFLOW", "check.yml")
# 判定为「卡死」的持续时间（分钟）
STUCK_MINUTES = int(os.environ.get("REAP_STUCK_MINUTES", "20"))
# 只处理这些状态：in_progress 交给 GitHub 自己的 timeout-minutes，不误杀
STUCK_STATUSES = {"waiting", "queued"}
# 单次最多取消多少个（防御：批量异常时不要一次打爆 API）
MAX_CANCEL = int(os.environ.get("REAP_MAX_CANCEL", "5"))
# 拉取多少条 run 用于判断
PER_PAGE = int(os.environ.get("REAP_PER_PAGE", "30"))

TIMEOUT = 20


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_ts(s) -> Optional[datetime]:
    """解析 GitHub 的 ISO8601（…Z）。非字符串 / 格式错误返回 None（脏数据兼容）。"""
    if not isinstance(s, str):
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def api(method: str, path: str, token: str, body=None):
    """调用 api.github.com，返回 (status_code, parsed_json_or_None)。"""
    url = f"https://api.github.com{path}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "blive-monitor-reaper",
    }
    data = json.dumps(body).encode() if body is not None else None
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            raw = resp.read()
            return resp.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        return e.code, None
    except Exception as e:  # noqa: BLE001
        print(f"[reaper] 请求失败 {method} {path}: {e}")
        return 0, None


def find_stuck(runs: list, now: datetime, stuck_minutes: int = STUCK_MINUTES) -> list:
    """筛出卡死的 run：状态属于 STUCK_STATUSES 且已持续超过阈值。

    Args:
        runs: GitHub runs 列表（元素含 id/status/created_at）
        now: 当前 UTC 时间（可注入，便于测试）
        stuck_minutes: 阈值（分钟）
    Returns:
        卡死的 run 列表
    """
    out = []
    for r in runs or []:
        if r.get("status") not in STUCK_STATUSES:
            continue
        created = _parse_ts(r.get("created_at"))
        if created is None:
            continue
        age_min = (now - created).total_seconds() / 60.0
        if age_min >= stuck_minutes:
            out.append(r)
    return out


def main() -> int:
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY") or "racheko-lab/blive-monitor"
    if not token:
        print("[reaper] 无 GITHUB_TOKEN，跳过")
        return 0

    status, payload = api(
        "GET",
        f"/repos/{repo}/actions/workflows/{TARGET_WORKFLOW}/runs"
        f"?per_page={PER_PAGE}",
        token,
    )
    if status != 200 or not isinstance(payload, dict):
        print(f"[reaper] 拉取 runs 失败（HTTP {status}），跳过")
        return 0

    runs = payload.get("workflow_runs", [])
    stuck = find_stuck(runs, _now())
    if not stuck:
        print(f"[reaper] 无卡死 run（检查了 {len(runs)} 条）")
        return 0

    print(f"[reaper] 发现 {len(stuck)} 个卡死 run（>{STUCK_MINUTES} 分钟）：")
    cancelled = 0
    for r in stuck[:MAX_CANCEL]:
        rid = r.get("id")
        created = _parse_ts(r.get("created_at"))
        age = ((_now() - created).total_seconds() / 60.0) if created else -1.0
        print(f"  - {rid}  status={r.get('status')}  age={age:.0f}min")
        code, _ = api("POST", f"/repos/{repo}/actions/runs/{rid}/cancel", token, {})
        if code in (202, 204):
            cancelled += 1
            print(f"    → 已取消（HTTP {code}）")
        else:
            print(f"    → 取消失败（HTTP {code}）")
    print(f"[reaper] 完成：取消 {cancelled}/{len(stuck)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
