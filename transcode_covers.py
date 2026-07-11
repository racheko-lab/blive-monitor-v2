"""D1 封面转存：将抖音新作封面从外部 CDN 转存到仓库内 ``assets/covers/``，
改写 ``post_tracking[id].latest_cover`` 为仓库 raw URL，规避抖音防盗链破图。

设计要点（与阶段二 2a 架构设计一致）：
- **零新增依赖**：仅使用标准库 ``urllib.request``（检测脚本用 Playwright 抓封面源 URL，
  本模块只负责下载，不引入 requests）。
- **差异提交**：仅当「封面缺失」或「latest_aweme_id 相对 manifest 变更」时才下载；
  manifest（``<covers_dir>/.manifest.json``，结构 ``{id:{aweme_id, sha256}}``）用于判定，
  避免每次 CI 重写同一封面导致仓库膨胀。
- **下载失败不阻塞**：``download_cover`` 失败返回 ``False``，保留原 CDN URL，下轮重试。

前端 ``monitor.html`` 已渲染 ``tt.latest_cover``（line ~2129 + ``onerror`` 兜底），
本模块只改写该字段为仓库内 raw URL，前端零改动。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import urllib.request
from typing import Any, Dict, Optional


def _raw_url(owner: str, repo: str, branch: str, covers_dir: str, key: str) -> str:
    """构造仓库内封面的 raw.githubusercontent.com URL。"""
    covers_dir = covers_dir.strip("/")
    return f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{covers_dir}/{key}.jpg"


def download_cover(url: str, dest: str, timeout: int = 15) -> bool:
    """用标准库 urllib 下载封面到 dest。

    失败返回 ``False``（不阻塞，下轮重试）。成功返回 ``True``。
    """
    req = urllib.request.Request(
        url, headers={"User-Agent": "blive-monitor-cover-transcoder"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec B310 (CI 内部固定来源)
            data = resp.read()
        if not data:
            return False
        parent = os.path.dirname(dest)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(dest, "wb") as f:
            f.write(data)
        return True
    except Exception:
        # 下载失败（网络/防盗链/超时等）：返回 False，不抛异常，下轮重试。
        return False


def rewrite_latest_cover(t: Dict[str, Any], raw_url: str) -> None:
    """将 post_tracking 条目 t 的 latest_cover 改写为仓库内 raw URL。"""
    t["latest_cover"] = raw_url


def _sha256(path: str) -> Optional[str]:
    """计算文件 sha256（用于 manifest），失败返回 None。"""
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


def transcode_all(
    tracking: Dict[str, dict],
    manifest: Dict[str, dict],
    owner: str,
    repo: str,
    branch: str,
    covers_dir: str = "assets/covers",
) -> Dict[str, Any]:
    """遍历 post_tracking，对 latest_cover 存在且（封面缺失或 aweme_id 变更）的账号，
    下载封面到 ``covers_dir/<key>.jpg``，改写 ``latest_cover`` 为 raw URL。

    :param tracking: post_tracking.json 内容（dict by key，如 ``douyin_601914453``）
    :param manifest: 既有 ``.manifest.json``（``{id:{aweme_id, sha256}}``），可为空
    :param owner/repo/branch: 仓库坐标（如 racheko-lab / blive-monitor / master）
    :param covers_dir: 仓库内封面目录（相对仓库根，默认 ``assets/covers``）
    :return: ``{tracking, manifest, changed, downloaded, total}``
    """
    manifest = dict(manifest or {})
    changed = 0
    downloaded = 0
    total = 0
    abs_covers = covers_dir  # 相对 CI checkout 工作目录（仓库根）

    for key, t in tracking.items():
        if not isinstance(t, dict):
            continue
        src = t.get("latest_cover")
        if not src or not isinstance(src, str):
            # 无封面源（如 count 退化模式 / 尚未抓到作品）→ 跳过
            continue
        total += 1
        aweme_id = t.get("latest_aweme_id")
        cover_path = os.path.join(abs_covers, f"{key}.jpg")
        prev = manifest.get(key, {})
        # 差异判定：封面文件缺失，或最新 aweme_id 相对 manifest 变更
        need = (not os.path.exists(cover_path)) or (prev.get("aweme_id") != aweme_id)
        if need:
            if download_cover(src, cover_path):
                rewrite_latest_cover(t, _raw_url(owner, repo, branch, covers_dir, key))
                manifest[key] = {"aweme_id": aweme_id, "sha256": _sha256(cover_path)}
                changed += 1
                downloaded += 1
            else:
                # 下载失败：保留原 CDN URL，下轮重试；不写入 manifest
                continue
        else:
            # 封面已存在且未变更：防御性确保 latest_cover 指向仓库 raw URL
            # （防止 check_new_posts.py 每轮回填 CDN URL 导致前端破图）
            raw = _raw_url(owner, repo, branch, covers_dir, key)
            if not str(t.get("latest_cover", "")).startswith(raw):
                rewrite_latest_cover(t, raw)
                changed += 1
    return {
        "tracking": tracking,
        "manifest": manifest,
        "changed": changed,
        "downloaded": downloaded,
        "total": total,
    }


def main(argv: Optional[list] = None) -> int:
    """CLI：读取 post_tracking.json + manifest，转存封面，写回变更。"""
    parser = argparse.ArgumentParser(
        description="Transcode douyin new-post covers into repo assets/covers"
    )
    parser.add_argument("--owner", default="racheko-lab")
    parser.add_argument("--repo", default="blive-monitor")
    parser.add_argument("--branch", default="master")
    parser.add_argument("--covers-dir", default="assets/covers")
    parser.add_argument("--tracking", default="post_tracking.json")
    parser.add_argument("--manifest", default=None,
                        help="manifest 路径（默认 <covers-dir>/.manifest.json）")
    args = parser.parse_args(argv)

    manifest_path = args.manifest or os.path.join(args.covers_dir, ".manifest.json")

    try:
        with open(args.tracking, "r", encoding="utf-8") as f:
            tracking = json.load(f)
    except FileNotFoundError:
        tracking = {}

    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
    except FileNotFoundError:
        manifest = {}

    res = transcode_all(
        tracking, manifest, args.owner, args.repo, args.branch, args.covers_dir
    )

    if res["changed"]:
        with open(args.tracking, "w", encoding="utf-8") as f:
            json.dump(res["tracking"], f, ensure_ascii=False, indent=2)
        os.makedirs(args.covers_dir, exist_ok=True)
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(res["manifest"], f, ensure_ascii=False, indent=2)

    print(
        f"[transcode_covers] total={res['total']} "
        f"changed={res['changed']} downloaded={res['downloaded']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
