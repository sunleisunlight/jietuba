# -*- coding: utf-8 -*-
"""Windows 坐标映射 — Qt 坐标即物理像素（恒等映射）。"""
from __future__ import annotations

from ..base.coordinates import CoordinateMapper


class WindowsCoordinateMapper(CoordinateMapper):
    """Windows：Qt（关闭 highdpi 缩放）与捕获像素 1:1，全部恒等。"""
