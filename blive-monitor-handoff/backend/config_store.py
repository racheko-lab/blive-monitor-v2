"""ConfigStore：BLIVE_CONFIG 与 summary/silence 状态的读写（封装 config 表）。

设计 §7.1 / §3.2：
  - BLIVE_CONFIG 整段存 ConfigKV(key='blive_config', value=<完整 dict>)，语义 100% 兼容
    （channels/routes/templates/silence/summary 字段不变）；dispatch_event(cfg_all, …)
    直接传该 dict，推送逻辑零改动。
  - summary_state.json / silence_state.json 分别存 SummaryState(key='summary') /
    SilenceState(key='silence')。

约定：所有写操作持 ``db.WRITER_LOCK``。
"""

from contextlib import contextmanager
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from . import db, config
from .models import ConfigKV, SilenceState, SummaryState

CONFIG_KEY = "blive_config"
SUMMARY_KEY = "summary"
SILENCE_KEY = "silence"

# /config 的合法顶层段（用于 PUT 校验，保持语义兼容）。
CONFIG_SECTIONS = ("channels", "routes", "templates", "silence", "summary", "push", "platforms")


def _now() -> datetime:
    return datetime.utcnow()


class ConfigStore:
    """配置读写封装。"""

    @contextmanager
    def _session_scope(self):
        s: Session = db.SessionLocal()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    # ==================== BLIVE_CONFIG ====================
    def get_config(self) -> Dict[str, Any]:
        """读 BLIVE_CONFIG；缺失返回含空段的默认 dict（保证 /config 永远可用）。"""
        with self._session_scope() as s:
            row = s.get(ConfigKV, CONFIG_KEY)
            if row and isinstance(row.value, dict):
                return row.value
        return {
            "channels": [],
            "routes": [],
            "templates": {},
            "silence": {"enabled": False, "start": "23:00", "end": "08:00"},
            "summary": {"enabled": False, "freq": "daily", "sendTime": "09:00"},
            "push": {},
            "platforms": {},
        }

    def put_config(self, cfg: Dict[str, Any]) -> str:
        """写入 BLIVE_CONFIG（覆盖式）。返回 updated_at 字符串。"""
        if not isinstance(cfg, dict):
            raise ValueError("BLIVE_CONFIG 必须是 dict")
        # 轻量校验：仅允许已知段（多写未知段不致命，但告警以便发现误用）。
        unknown = [k for k in cfg.keys() if k not in CONFIG_SECTIONS]
        if unknown:
            import logging

            logging.getLogger(__name__).warning("BLIVE_CONFIG 含未知段（已忽略校验）: %s", unknown)
        with db.WRITER_LOCK:
            with self._session_scope() as s:
                row = s.get(ConfigKV, CONFIG_KEY)
                if row is None:
                    row = ConfigKV(key=CONFIG_KEY, value=cfg)
                    s.add(row)
                else:
                    row.value = cfg
                row.updated_at = _now()
                s.flush()
                return row.updated_at.strftime("%Y-%m-%d %H:%M:%S")

    def get_push_cfg(self) -> Dict[str, Any]:
        """兼容 legacy 单通道：返回 BLIVE_CONFIG['push']（可能为空 dict）。"""
        return self.get_config().get("push") or {}

    def get_platform_cfg(self, platform: str) -> Dict[str, Any]:
        """取某平台的多平台适配器配置（BLIVE_CONFIG['platforms'][platform]）。

        阶段三 T04：AdapterRegistry.from_config 据此构建/跳过各平台适配器。
        缺省返回空 dict（等价于「未配置/未启用」）。
        """
        return self.get_config().get("platforms", {}).get(platform, {}) or {}

    # ==================== summary / silence 状态 ====================
    def _upsert_kv_state(self, model, key: str, value: Dict[str, Any]) -> Dict[str, Any]:
        with db.WRITER_LOCK:
            with self._session_scope() as s:
                row = s.get(model, key)
                if row is None:
                    row = model(key=key, value=value)
                    s.add(row)
                else:
                    # 合并保留既有字段，避免覆盖前端/调度写入的 lastSent 等。
                    base = dict(row.value or {})
                    base.update(value)
                    row.value = base
                row.updated_at = _now()
                return dict(row.value or {})

    def _get_kv_state(self, model, key: str, default: Dict[str, Any]) -> Dict[str, Any]:
        with self._session_scope() as s:
            row = s.get(model, key)
            if row and isinstance(row.value, dict):
                return dict(row.value)
            return dict(default)

    # summary
    def get_summary_state(self) -> Dict[str, Any]:
        return self._get_kv_state(
            SummaryState, SUMMARY_KEY,
            {"enabled": False, "freq": "daily", "sendTime": "09:00", "lastSent": 0},
        )

    def put_summary_state(self, value: Dict[str, Any], remove: Optional[list] = None) -> Dict[str, Any]:
        # 合并写入后支持显式删除字段（如失败冷却字段）。
        result = self._upsert_kv_state(SummaryState, SUMMARY_KEY, value)
        if remove:
            changed = False
            with db.WRITER_LOCK:
                with self._session_scope() as s:
                    row = s.get(SummaryState, SUMMARY_KEY)
                    if row and isinstance(row.value, dict):
                        for k in remove:
                            if k in row.value:
                                del row.value[k]
                                changed = True
            if changed:
                return self.get_summary_state()
        return result

    # silence
    def get_silence_state(self) -> Dict[str, Any]:
        return self._get_kv_state(
            SilenceState, SILENCE_KEY,
            {"enabled": False, "start": "23:00", "end": "08:00"},
        )

    def put_silence_state(self, value: Dict[str, Any]) -> Dict[str, Any]:
        return self._upsert_kv_state(SilenceState, SILENCE_KEY, value)
