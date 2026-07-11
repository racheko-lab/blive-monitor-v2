"""阶段二 2b · A4 推送模板：前端 schema + UI + Python 参考实现。

grep 契约：
  - monitor.html 必须含 tplLiveOn / tplNewPost（模板编辑 textarea id）/
    renderTemplate / buildTemplateConfig（函数名）。
  - 占位符集合：{name}{title}{platform}{time}{url}（不扩 {duration}）。

Python 参考实现镜像 common.render_template（缺字段保留原占位符不崩）。
"""
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HTML = os.path.join(ROOT, "monitor.html")

import common


# ---------------------------------------------------------------------------
# grep 契约
# ---------------------------------------------------------------------------
def test_html_template_contract():
    src = open(HTML, encoding="utf-8").read()
    for token in ["tplLiveOn", "tplNewPost", "renderTemplate", "buildTemplateConfig"]:
        assert token in src, f"monitor.html 缺少 A4 契约标记: {token}"


def test_html_template_placeholders():
    """前端模板变量提示含 {name}{title}{platform}{time}{url}。"""
    src = open(HTML, encoding="utf-8").read()
    for ph in ["{name}", "{title}", "{platform}", "{time}", "{url}"]:
        assert ph in src, f"模板占位符缺失: {ph}"


def test_html_template_not_expands_duration():
    """本波不扩 {duration}（主理人拍板 #4）。"""
    src = open(HTML, encoding="utf-8").read()
    assert "{duration}" not in src, "本波不应出现 {duration} 占位符"


# ---------------------------------------------------------------------------
# Python 参考实现（镜像 common.render_template）
# ---------------------------------------------------------------------------
def test_render_template_basic():
    tpl = "🔴 {name} 开播了：{title}"
    out = common.render_template(tpl, {"name": "峰哥", "title": "今晚联动"})
    assert out == "🔴 峰哥 开播了：今晚联动", out


def test_render_template_all_placeholders():
    tpl = "{name}|{title}|{platform}|{time}|{url}"
    ctx = {
        "name": "A", "title": "T", "platform": "B站",
        "time": "2026-07-11 20:00", "url": "https://x",
    }
    assert common.render_template(tpl, ctx) == "A|T|B站|2026-07-11 20:00|https://x"


def test_render_template_missing_field_keeps_placeholder():
    """缺字段保留原占位符不崩。"""
    tpl = "{name} 开播：{title}"
    out = common.render_template(tpl, {"name": "峰哥"})  # 缺 title
    assert out == "峰哥 开播：{title}", out
    # 空字符串视为缺省，保留占位符
    out2 = common.render_template(tpl, {"name": "峰哥", "title": ""})
    assert out2 == "峰哥 开播：{title}", out2


def test_render_template_none_tpl():
    assert common.render_template(None, {"name": "x"}) == ""


def test_render_template_int_value():
    tpl = "时长 {duration} 分"
    # {duration} 不在占位符集合，但 ctx 若含则替换；缺省保留
    assert common.render_template(tpl, {}) == "时长 {duration} 分"
    assert common.render_template(tpl, {"duration": 30}) == "时长 30 分"
