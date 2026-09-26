"""标注图元的 JSON 序列化 / 反序列化。

职责边界：这里只负责"一个 QGraphicsItem ↔ 一份可 JSON 化的 dict"。不碰
SQLite、不碰文件、不碰撤销栈。所有取值都走图元已有的公开接口（pen() /
rect() / outline_state() / export_state() ...），所以以后再改图元内部实现，
只要接口不变，老历史仍然能恢复。

刻意不做的事：
- 不 pickle QGraphicsItem / QObject / Scene；
- 不把最终合成图当历史（那样矩形、箭头、备注就焊死在像素上了）；
- 不把备注的子图元（目标框、箭头）单独当成一条标注。

容错策略（见 AGENTS 约定的 history 部分）：
- 未知类型：写 warning + 跳过这一条，其余照常恢复；
- 缺失的可选字段：用合理默认值；
- 单个 annotation 恢复失败：不影响整张历史打开。
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainterPath, QPen, QTransform

from core.logger import log_debug, log_warning, T


# ── 类型标识（写进 JSON，必须稳定）────────────────────────────
TYPE_STROKE = "stroke"
TYPE_RECT = "rect"
TYPE_ELLIPSE = "ellipse"
TYPE_ARROW = "arrow"
TYPE_TEXT = "text"
TYPE_NOTE = "note"
TYPE_NUMBER = "number"
TYPE_MOSAIC = "mosaic"
TYPE_SPOTLIGHT = "spotlight"


# ── 基础值的转换 ───────────────────────────────────────────────

def _color_to_list(color: Optional[QColor]):
    if not isinstance(color, QColor) or not color.isValid():
        return None
    return [int(color.red()), int(color.green()), int(color.blue()), int(color.alpha())]


def _list_to_color(value, default: QColor = None) -> QColor:
    if isinstance(value, (list, tuple)) and len(value) >= 3:
        try:
            alpha = int(value[3]) if len(value) > 3 else 255
            return QColor(int(value[0]), int(value[1]), int(value[2]), alpha)
        except (TypeError, ValueError):
            pass
    return QColor(default) if isinstance(default, QColor) else QColor(0, 0, 0, 255)


def _point_to_list(point: QPointF):
    try:
        return [float(point.x()), float(point.y())]
    except Exception:
        return [0.0, 0.0]


def _list_to_point(value, default=None) -> QPointF:
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        try:
            return QPointF(float(value[0]), float(value[1]))
        except (TypeError, ValueError):
            pass
    return QPointF(default) if isinstance(default, QPointF) else QPointF(0.0, 0.0)


def _rect_to_list(rect: QRectF):
    try:
        return [float(rect.x()), float(rect.y()),
                float(rect.width()), float(rect.height())]
    except Exception:
        return [0.0, 0.0, 0.0, 0.0]


def _list_to_rect(value, default=None) -> QRectF:
    if isinstance(value, (list, tuple)) and len(value) >= 4:
        try:
            return QRectF(float(value[0]), float(value[1]),
                          float(value[2]), float(value[3]))
        except (TypeError, ValueError):
            pass
    return QRectF(default) if isinstance(default, QRectF) else QRectF()


def _font_to_dict(font: QFont) -> dict:
    try:
        point_size = float(font.pointSizeF())
        if point_size <= 0:
            point_size = float(font.pixelSize() or 12)
    except Exception:
        point_size = 12.0
    return {
        "family": str(font.family()),
        "point_size": point_size,
        "bold": bool(font.bold()),
        "italic": bool(font.italic()),
        "underline": bool(font.underline()),
        "strikeout": bool(font.strikeOut()),
    }


def _dict_to_font(data) -> QFont:
    data = data if isinstance(data, dict) else {}
    font = QFont(str(data.get("family") or "").strip() or "Arial")
    try:
        font.setPointSizeF(max(1.0, float(data.get("point_size", 12.0))))
    except (TypeError, ValueError):
        font.setPointSizeF(12.0)
    font.setBold(bool(data.get("bold", False)))
    font.setItalic(bool(data.get("italic", False)))
    font.setUnderline(bool(data.get("underline", False)))
    font.setStrikeOut(bool(data.get("strikeout", False)))
    return font


# 画笔样式/端帽/连接以枚举名落盘：名字比数值稳定，Qt 改枚举编号也不会串味。
_PEN_STYLE_NAMES = ("SolidLine", "DashLine", "DotLine", "DashDotLine",
                    "DashDotDotLine", "CustomDashLine")
_PEN_CAP_NAMES = ("FlatCap", "SquareCap", "RoundCap")
_PEN_JOIN_NAMES = ("MiterJoin", "BevelJoin", "RoundJoin", "SvgMiterJoin")

_DEFAULT_PEN_STYLE = "SolidLine"
_DEFAULT_PEN_CAP = "RoundCap"
_DEFAULT_PEN_JOIN = "RoundJoin"

_BRUSH_STYLE_NAMES = ("NoBrush", "SolidPattern")


def _pen_to_dict(pen: QPen) -> dict:
    data = {
        "color": _color_to_list(pen.color()),
        "width": float(pen.widthF()),
        "style": pen.style().name if hasattr(pen.style(), "name") else _DEFAULT_PEN_STYLE,
        "cap": pen.capStyle().name if hasattr(pen.capStyle(), "name") else _DEFAULT_PEN_CAP,
        "join": pen.joinStyle().name if hasattr(pen.joinStyle(), "name") else _DEFAULT_PEN_JOIN,
    }
    if data["style"] == "CustomDashLine":
        try:
            data["dash"] = [float(v) for v in pen.dashPattern()]
        except Exception:
            data["dash"] = []
    return data


def _dict_to_pen(data, fallback_color: QColor = None, fallback_width: float = 1.0) -> QPen:
    data = data if isinstance(data, dict) else {}
    pen = QPen()
    pen.setColor(_list_to_color(data.get("color"),
                                fallback_color or QColor(0, 0, 0, 255)))
    try:
        pen.setWidthF(max(0.1, float(data.get("width", fallback_width))))
    except (TypeError, ValueError):
        pen.setWidthF(max(0.1, float(fallback_width)))

    style_name = str(data.get("style") or _DEFAULT_PEN_STYLE)
    if style_name not in _PEN_STYLE_NAMES:
        style_name = _DEFAULT_PEN_STYLE
    pen.setStyle(getattr(Qt.PenStyle, style_name, Qt.PenStyle.SolidLine))

    cap_name = str(data.get("cap") or _DEFAULT_PEN_CAP)
    pen.setCapStyle(getattr(Qt.PenCapStyle,
                            cap_name if cap_name in _PEN_CAP_NAMES else _DEFAULT_PEN_CAP,
                            Qt.PenCapStyle.RoundCap))

    join_name = str(data.get("join") or _DEFAULT_PEN_JOIN)
    pen.setJoinStyle(getattr(Qt.PenJoinStyle,
                             join_name if join_name in _PEN_JOIN_NAMES else _DEFAULT_PEN_JOIN,
                             Qt.PenJoinStyle.RoundJoin))

    if style_name == "CustomDashLine":
        dash = data.get("dash")
        if isinstance(dash, (list, tuple)) and len(dash) >= 2:
            try:
                pen.setDashPattern([float(v) for v in dash])
            except Exception:
                pen.setStyle(Qt.PenStyle.SolidLine)
        else:
            pen.setStyle(Qt.PenStyle.SolidLine)
    return pen


def _element_type_value(element) -> int:
    """QPainterPath 元素类型取整数。

    PySide6 里 element.type 是真正的 Python 枚举（不是 int 子类），直接 int()
    会抛 TypeError，所以先取 .value。
    """
    kind = getattr(element, "type", 0)
    value = getattr(kind, "value", None)
    if isinstance(value, int):
        return int(value)
    try:
        return int(kind)
    except (TypeError, ValueError):
        return 0


def _path_to_list(path: QPainterPath) -> list:
    """QPainterPath → [[元素类型, x, y], ...]

    直接按 elementAt 逐个落盘，曲线数据点也原样带着——重建时按同样的顺序
    回放，形状逐点一致，不需要理解路径语义。
    """
    elements = []
    try:
        count = path.elementCount()
    except Exception:
        return elements
    for index in range(count):
        element = path.elementAt(index)
        elements.append([
            _element_type_value(element),
            float(element.x),
            float(element.y),
        ])
    return elements


def _list_to_path(elements) -> QPainterPath:
    path = QPainterPath()
    if not isinstance(elements, (list, tuple)):
        return path

    # MoveTo=0, LineTo=1, CurveTo=2, CurveToData=3
    index = 0
    total = len(elements)
    while index < total:
        entry = elements[index]
        if not isinstance(entry, (list, tuple)) or len(entry) < 3:
            index += 1
            continue
        try:
            kind = int(entry[0])
            x = float(entry[1])
            y = float(entry[2])
        except (TypeError, ValueError):
            index += 1
            continue

        if kind == 0:
            path.moveTo(x, y)
        elif kind == 1:
            path.lineTo(x, y)
        elif kind == 2 and index + 2 < total:
            try:
                c1x = float(elements[index + 1][1]); c1y = float(elements[index + 1][2])
                c2x = float(elements[index + 2][1]); c2y = float(elements[index + 2][2])
            except (TypeError, ValueError, IndexError):
                index += 1
                continue
            path.cubicTo(x, y, c1x, c1y, c2x, c2y)
            index += 2
        index += 1
    return path


class AnnotationCodec:
    """QGraphicsItem ↔ dict。实例无状态，可按需 new。"""

    # ==================================================================
    # 序列化
    # ==================================================================

    def serialize(self, item) -> Optional[dict]:
        """把一个顶级标注图元序列化成 JSON 友好的 dict；不支持的类型返回 None。"""
        try:
            data = self._serialize_specific(item)
        except Exception as e:
            log_warning(T("序列化标注失败 ({item_type}): {error}",
                          item_type=type(item).__name__, error=str(e)), "History")
            return None
        if data is None:
            log_warning(T("不支持的标注类型，跳过: {item_type}",
                          item_type=type(item).__name__), "History")
            return None
        self._write_common(item, data)
        return data

    def serialize_all(self, items) -> list:
        """序列化一组顶级标注（顺序即传入顺序，恢复后绘制顺序一致）。"""
        result = []
        for item in items or []:
            data = self.serialize(item)
            if data:
                result.append(data)
        return result

    def _write_common(self, item, data: dict):
        """所有图元共有的位置/层级/变换。"""
        try:
            data["pos"] = _point_to_list(item.pos())
        except Exception:
            pass
        try:
            data["z"] = float(item.zValue())
        except Exception:
            pass
        try:
            data["opacity"] = float(item.opacity())
        except Exception:
            pass
        try:
            rotation = float(item.rotation())
            if rotation:
                data["rotation"] = rotation
                data["transform_origin"] = _point_to_list(item.transformOriginPoint())
        except Exception:
            pass
        try:
            transform = QTransform(item.transform())
            if not transform.isIdentity():
                data["transform"] = [float(transform.m11()), float(transform.m12()),
                                     float(transform.m21()), float(transform.m22()),
                                     float(transform.dx()), float(transform.dy())]
        except Exception:
            pass

    def _serialize_specific(self, item) -> Optional[dict]:
        from canvas.items import (
            ArrowItem, EllipseItem, MosaicItem, NoteItem, NumberItem,
            RectItem, SpotlightItem, StrokeItem, TextItem,
        )

        # 顺序有讲究：SpotlightItem 是 RectItem 的子类、NoteItem 是 TextItem 的
        # 子类，子类判定必须排在父类前面。
        if isinstance(item, StrokeItem):
            return self._serialize_stroke(item)
        if isinstance(item, MosaicItem):
            return self._serialize_mosaic(item)
        if isinstance(item, SpotlightItem):
            return self._serialize_spotlight(item)
        if isinstance(item, RectItem):
            return self._serialize_rect(item)
        if isinstance(item, EllipseItem):
            return self._serialize_ellipse(item)
        if isinstance(item, ArrowItem):
            return self._serialize_arrow(item)
        if isinstance(item, NoteItem):
            return self._serialize_note(item)
        if isinstance(item, TextItem):
            return self._serialize_text(item)
        if isinstance(item, NumberItem):
            return self._serialize_number(item)
        return None

    def _serialize_stroke(self, item) -> dict:
        return {
            "type": TYPE_STROKE,
            "path": _path_to_list(item.path()),
            "pen": _pen_to_dict(item.pen()),
            "highlighter": bool(getattr(item, "is_highlighter", False)),
        }

    def _serialize_rect(self, item) -> dict:
        data = {
            "type": TYPE_RECT,
            "rect": _rect_to_list(item.rect()),
            "pen": _pen_to_dict(item.pen()),
            "corner_radius": float(item.get_corner_radius())
            if hasattr(item, "get_corner_radius") else 0.0,
        }
        brush_color = _color_to_list(item.brush().color())
        if item.brush().style() != Qt.BrushStyle.NoBrush and brush_color is not None:
            data["brush"] = brush_color
        if getattr(item, "is_highlighter", False):
            data["highlighter_rect"] = True
        return data

    def _serialize_ellipse(self, item) -> dict:
        return {
            "type": TYPE_ELLIPSE,
            "rect": _rect_to_list(item.rect()),
            "pen": _pen_to_dict(item.pen()),
        }

    def _serialize_arrow(self, item) -> dict:
        return {
            "type": TYPE_ARROW,
            "start": _point_to_list(item.start_pos),
            "end": _point_to_list(item.end_pos),
            "control": _point_to_list(item.control_pos),
            "control_modified": bool(getattr(item, "_control_modified", False)),
            "arrow_style": str(getattr(item, "_arrow_style", "single")),
            "color": _color_to_list(getattr(item, "color", None)),
            "base_width": float(getattr(item, "base_width", 2.0)),
        }

    def _serialize_text(self, item) -> dict:
        enabled, color, width = item.outline_state()
        shadow_enabled, shadow_color = item.shadow_state()
        return {
            "type": TYPE_TEXT,
            "text": item.toPlainText(),
            "font": _font_to_dict(item.font()),
            "color": _color_to_list(item.defaultTextColor()),
            "paragraph_width": item.paragraph_width(),
            "outline": [bool(enabled), _color_to_list(color), float(width)],
            "shadow": [bool(shadow_enabled), _color_to_list(shadow_color)],
            "background": [bool(getattr(item, "has_background", False)),
                           _color_to_list(getattr(item, "background_color", None))],
        }

    def _serialize_note(self, item) -> dict:
        """复合备注只落一条：目标框和箭头是它的子图元，走 export_state 一起带走。"""
        state = item.export_state()
        return {
            "type": TYPE_NOTE,
            "text": state["text"],
            "font": _font_to_dict(state["font"]),
            "color": _color_to_list(state["color"]),
            "direction": state["direction"],
            "arrow_at": state["arrow_at"],
            "layout_mode": state["layout_mode"],
            "gap": float(state["gap"]),
            "target_rect_local": _rect_to_list(state["target_rect_local"]),
            "paragraph_width": state["paragraph_width"],
            "stroke_width": float(state["stroke_width"]),
            "arrow_style": state["arrow_style"],
            "arrow_start_local": _point_to_list(state["arrow_start_local"]),
            "arrow_end_local": _point_to_list(state["arrow_end_local"]),
            "outline": [bool(state["outline"][0]),
                        _color_to_list(state["outline"][1]),
                        float(state["outline"][2])],
            "shadow": [bool(state["shadow"][0]), _color_to_list(state["shadow"][1])],
            "background": [bool(state["background"][0]),
                           _color_to_list(state["background"][1])],
        }

    def _serialize_number(self, item) -> dict:
        return {
            "type": TYPE_NUMBER,
            "number": int(getattr(item, "number", 1)),
            "number_order": getattr(item, "number_order", None),
            "radius": float(getattr(item, "radius", 16.0)),
            "color": _color_to_list(getattr(item, "color", None)),
            "style": str(getattr(item, "style", "")),
        }

    def _serialize_mosaic(self, item) -> dict:
        """马赛克只存几何与参数，不存像素。

        它画的"颜料"是从背景按 block_size 缩出来的小图，恢复时由同一个背景、
        同一个 block_size、同一个背景锚点重新算出来必然一致——把那张小图编进
        JSON 既大又没有意义。
        """
        return {
            "type": TYPE_MOSAIC,
            "path": _path_to_list(item.path()),
            "brush_width": float(item.brush_width()),
            "block_size": int(item.block_size()),
            "background_rect": _rect_to_list(item.background_rect()),
            "fill_mode": bool(item.fill_mode()),
            "smooth": bool(item.smooth()),
        }

    def _serialize_spotlight(self, item) -> dict:
        """幕布不是标注：这里只存孔，孔恢复进场景后幕布会自己长出来。"""
        return {
            "type": TYPE_SPOTLIGHT,
            "rect": _rect_to_list(item.rect()),
            "corner_radius": float(item.get_corner_radius())
            if hasattr(item, "get_corner_radius") else 0.0,
        }

    # ==================================================================
    # 反序列化
    # ==================================================================

    def restore_all(self, scene, annotations: list) -> int:
        """把一组 annotation 恢复到场景里，返回成功条数。

        单条失败只写 warning 并继续——一张历史里有几十条标注，不能因为其中一条
        是旧版本写下的未知结构就整张打不开。
        """
        restored = 0
        for data in annotations or []:
            if not isinstance(data, dict):
                continue
            try:
                item = self.deserialize(scene, data)
            except Exception as e:
                log_warning(T("恢复标注失败 ({item_type}): {error}",
                              item_type=data.get("type"), error=str(e)), "History")
                continue
            if item is None:
                continue
            try:
                scene.addItem(item)
                restored += 1
            except Exception as e:
                log_warning(T("标注加入场景失败: {error}", error=str(e)), "History")
        log_debug(T("历史标注恢复: {restored}/{total}",
                    restored=restored, total=len(annotations or [])), "History")
        return restored

    def deserialize(self, scene, data: dict):
        """dict → QGraphicsItem；不认识的类型返回 None。"""
        kind = str(data.get("type") or "")
        builder = {
            TYPE_STROKE: self._deserialize_stroke,
            TYPE_RECT: self._deserialize_rect,
            TYPE_ELLIPSE: self._deserialize_ellipse,
            TYPE_ARROW: self._deserialize_arrow,
            TYPE_TEXT: self._deserialize_text,
            TYPE_NOTE: self._deserialize_note,
            TYPE_NUMBER: self._deserialize_number,
            TYPE_MOSAIC: self._deserialize_mosaic,
            TYPE_SPOTLIGHT: self._deserialize_spotlight,
        }.get(kind)
        if builder is None:
            log_warning(T("未知的标注类型，跳过: {kind}", kind=kind or "(空)"), "History")
            return None

        item = builder(scene, data)
        if item is None:
            return None
        self._apply_common(item, data)
        return item

    def _apply_common(self, item, data: dict):
        try:
            item.setPos(_list_to_point(data.get("pos")))
        except Exception:
            pass
        try:
            item.setZValue(float(data.get("z", item.zValue())))
        except Exception:
            pass
        try:
            item.setOpacity(float(data.get("opacity", 1.0)))
        except Exception:
            pass
        rotation = data.get("rotation")
        if isinstance(rotation, (int, float)) and rotation:
            try:
                item.setTransformOriginPoint(
                    _list_to_point(data.get("transform_origin"))
                )
                item.setRotation(float(rotation))
            except Exception:
                pass
        transform = data.get("transform")
        if isinstance(transform, (list, tuple)) and len(transform) >= 6:
            try:
                item.setTransform(QTransform(
                    float(transform[0]), float(transform[1]),
                    float(transform[2]), float(transform[3]),
                    float(transform[4]), float(transform[5]),
                ))
            except Exception:
                pass
        if hasattr(item, "update"):
            item.update()

    def _deserialize_stroke(self, scene, data: dict):
        from canvas.items import StrokeItem
        path = _list_to_path(data.get("path"))
        pen = _dict_to_pen(data.get("pen"))
        return StrokeItem(path, pen, bool(data.get("highlighter", False)))

    def _deserialize_rect(self, scene, data: dict):
        from canvas.items import RectItem
        from PySide6.QtGui import QBrush
        rect = _list_to_rect(data.get("rect"))
        pen = _dict_to_pen(data.get("pen"))
        item = RectItem(rect, pen, float(data.get("corner_radius", 0.0) or 0.0))
        brush_color = data.get("brush")
        if brush_color is not None:
            item.setBrush(QBrush(_list_to_color(brush_color)))
        if data.get("highlighter_rect"):
            item.is_highlighter = True
            item.is_highlighter_rect = True
        return item

    def _deserialize_ellipse(self, scene, data: dict):
        from canvas.items import EllipseItem
        return EllipseItem(_list_to_rect(data.get("rect")),
                           _dict_to_pen(data.get("pen")))

    def _deserialize_arrow(self, scene, data: dict):
        from canvas.items import ArrowItem
        color = _list_to_color(data.get("color"), QColor(0, 0, 0, 255))
        try:
            width = max(1.0, float(data.get("base_width", 2.0)))
        except (TypeError, ValueError):
            width = 2.0
        pen = QPen(color, width)
        item = ArrowItem(_list_to_point(data.get("start")),
                         _list_to_point(data.get("end")),
                         pen,
                         str(data.get("arrow_style") or ArrowItem.STYLE_SINGLE))
        if data.get("control_modified"):
            item.set_control_point(_list_to_point(data.get("control")))
        return item

    def _deserialize_text(self, scene, data: dict):
        from canvas.items import TextItem
        item = TextItem(
            str(data.get("text") or ""),
            _list_to_point(data.get("pos")),
            _dict_to_font(data.get("font")),
            _list_to_color(data.get("color"), QColor(255, 0, 0, 255)),
        )
        self._apply_text_decoration(item, data)
        return item

    @staticmethod
    def _apply_text_decoration(item, data: dict):
        """描边/阴影/背景/排版宽度：文字与备注共用的装饰字段。"""
        paragraph_width = data.get("paragraph_width")
        if paragraph_width is not None:
            try:
                item.set_paragraph_width(float(paragraph_width))
            except (TypeError, ValueError):
                pass

        outline = data.get("outline")
        if isinstance(outline, (list, tuple)) and len(outline) >= 3:
            try:
                item.set_outline(bool(outline[0]),
                                 _list_to_color(outline[1], QColor(255, 255, 255)),
                                 float(outline[2]))
            except Exception:
                pass

        shadow = data.get("shadow")
        if isinstance(shadow, (list, tuple)) and len(shadow) >= 2:
            try:
                item.set_shadow(bool(shadow[0]),
                                _list_to_color(shadow[1], QColor(0, 0, 0, 102)))
            except Exception:
                pass

        background = data.get("background")
        if isinstance(background, (list, tuple)) and len(background) >= 2:
            color = _list_to_color(background[1], QColor(255, 255, 255, 255))
            try:
                item.set_background(enabled=bool(background[0]),
                                    color=color,
                                    opacity=color.alpha())
            except Exception:
                pass

    def _deserialize_note(self, scene, data: dict):
        from canvas.items import NoteItem
        from canvas.items.arrow_item import ArrowItem as _ArrowItem

        state = {
            "text": str(data.get("text") or ""),
            "font": _dict_to_font(data.get("font")),
            "color": _list_to_color(data.get("color"), QColor(255, 0, 0, 255)),
            "direction": data.get("direction"),
            "arrow_at": data.get("arrow_at"),
            "layout_mode": data.get("layout_mode"),
            "gap": data.get("gap", 0.0) or 0.0,
            "target_rect_local": _list_to_rect(data.get("target_rect_local")),
            "paragraph_width": data.get("paragraph_width"),
            "stroke_width": float(data.get("stroke_width", 3.0) or 3.0),
            "arrow_style": str(data.get("arrow_style") or _ArrowItem.STYLE_SINGLE),
            "arrow_start_local": _list_to_point(data.get("arrow_start_local")),
            "arrow_end_local": _list_to_point(data.get("arrow_end_local")),
            "outline": [],
            "shadow": [],
            "background": [False, QColor(255, 255, 255, 255)],
        }
        # 备注的装饰字段结构与文字一致，复用同一段还原逻辑
        item = NoteItem.from_export_state(state, pos=_list_to_point(data.get("pos")))
        self._apply_text_decoration(item, data)
        return item

    def _deserialize_number(self, scene, data: dict):
        from canvas.items import NumberItem
        item = NumberItem(
            int(data.get("number", 1) or 1),
            QPointF(0.0, 0.0),
            float(data.get("radius", 16.0) or 16.0),
            _list_to_color(data.get("color"), QColor(255, 0, 0, 255)),
            data.get("style"),
        )
        order = data.get("number_order")
        if isinstance(order, int) and order >= 0:
            item.number_order = order
        return item

    def _deserialize_mosaic(self, scene, data: dict):
        """马赛克的"颜料"从当前场景背景重新算：同一张 source + 同一 block_size
        + 同一背景锚点，算出来的小图与保存时逐像素相同。"""
        from canvas.items import MosaicItem
        from PySide6.QtGui import QImage

        block_size = int(data.get("block_size", 8) or 8)
        background = getattr(scene, "background", None)
        reduced = QImage()
        if background is not None and hasattr(background, "reduced_image"):
            try:
                reduced = background.reduced_image(block_size)
            except Exception as e:
                log_warning(T("重建马赛克底图失败: {error}", error=str(e)), "History")
        if reduced.isNull():
            log_warning(T("背景不可用，马赛克被跳过"), "History")
            return None

        return MosaicItem(
            _list_to_path(data.get("path")),
            float(data.get("brush_width", 20.0) or 20.0),
            block_size,
            reduced,
            _list_to_rect(data.get("background_rect")),
            fill_mode=bool(data.get("fill_mode", False)),
            smooth=bool(data.get("smooth", False)),
        )

    def _deserialize_spotlight(self, scene, data: dict):
        from canvas.items import SpotlightItem
        return SpotlightItem(
            _list_to_rect(data.get("rect")),
            float(data.get("corner_radius", 0.0) or 0.0),
        )