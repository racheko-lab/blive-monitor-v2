"""阶段三 T05：适配器基座 / 归一化模型 / 注册表（docs/phase3_design.md §3,§5.2）。"""

import pytest

from backend.adapters import (
    AdapterError,
    AdapterGated,
    AdapterRegistry,
    AdapterSkip,
    PlatformAdapter,
    PostModel,
    RoomModel,
)


def test_room_model_defaults():
    m = RoomModel(platform="x", room_id="1")
    assert m.platform == "x" and m.room_id == "1"
    assert m.live_status is False
    assert m.tags == [] and m.extra == {}


def test_post_model_defaults():
    p = PostModel(platform="x", post_id="9")
    assert p.platform == "x" and p.post_id == "9"
    assert p.published_at == "" and p.extra == {}


def test_platform_adapter_is_abstract():
    # 含未实现的抽象方法，不能直接实例化
    with pytest.raises(TypeError):
        PlatformAdapter()


def test_adapter_skip_and_gated_hierarchy():
    assert issubclass(AdapterSkip, AdapterError)
    assert issubclass(AdapterGated, AdapterError)
    e = AdapterSkip("no_sec_uid", detail="缺 sec_uid")
    assert e.reason == "no_sec_uid" and e.detail == "缺 sec_uid"


def test_registry_register_get_list():
    reg = AdapterRegistry()

    class A(PlatformAdapter):
        platform = "a"

        def fetch_room_status(self, room_id):
            raise NotImplementedError

        def fetch_new_posts(self, *a, **k):
            raise NotImplementedError

    inst = A()
    reg.register(inst)
    assert reg.get("a") is inst
    assert "a" in reg.list_platforms()
    assert reg.get("missing") is None


def test_registry_from_config_builtins():
    reg = AdapterRegistry.from_config({})
    assert set(reg.list_platforms()) == {"bilibili", "douyin"}


def test_registry_from_config_enabled_platforms():
    cfg = {
        "platforms": {
            "kuaishou": {"enabled": True, "credentials": {}},
            "xhs": {"enabled": True, "credentials": {}},
        }
    }
    reg = AdapterRegistry.from_config(cfg)
    assert "kuaishou" in reg.list_platforms()
    assert "xhs" in reg.list_platforms()
    # 未启用 / 未知平台不应注册
    assert "channels" not in reg.list_platforms()
    assert "taobao_live" not in reg.list_platforms()


def test_registry_from_config_disabled_skipped():
    cfg = {"platforms": {"kuaishou": {"enabled": False}}}
    reg = AdapterRegistry.from_config(cfg)
    assert "kuaishou" not in reg.list_platforms()


def test_registry_from_config_unknown_platform_skipped():
    cfg = {"platforms": {"not_a_platform": {"enabled": True}}}
    # 不应抛异常，仅告警跳过
    reg = AdapterRegistry.from_config(cfg)
    assert "not_a_platform" not in reg.list_platforms()
