# -*- coding: utf-8 -*-
"""备注默认尺寸必须跟屏幕分辨率成正比（Retina 2x 上放大一倍）。"""


class _Manager:
    def get_setting(self, _tool, key, default=None):
        return {"font_size": 14, "font_family": ""}.get(key, default)


class _View:
    def __init__(self, scale):
        self._scale = scale

    def display_scale(self):
        return self._scale


class _Scene:
    def __init__(self, scale):
        self._scale = scale

    def views(self):
        return [_View(self._scale)]


class _Ctx:
    def __init__(self, scale):
        self.scene = _Scene(scale)


def test_font_size_scales_with_dpr(qapp):
    from tools.note import NoteTool

    assert NoteTool._load_font(_Manager(), 1.0).pointSize() == 14
    assert NoteTool._load_font(_Manager(), 2.0).pointSize() == 28


def test_capture_dpr_from_display_scale(qapp):
    from tools.note import NoteTool

    assert NoteTool._capture_dpr(_Ctx(1.0)) == 1.0
    assert NoteTool._capture_dpr(_Ctx(0.5)) == 2.0
    # 异常情况退回 1.0，绝不让备注消失
    assert NoteTool._capture_dpr(_Ctx(0.0)) == 1.0
