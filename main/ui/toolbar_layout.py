"""
截图工具栏的按钮排布：按钮的顺序，以及每个按钮始终显示、收进「…」还是始终隐藏

排布只决定按钮摆在哪、看不看得见，不碰按钮背后的逻辑：收起或隐藏的按钮照样连着
信号，快捷键走 select_tool 和信号、不经过按钮本身，所以隐藏按钮不会让功能失效。

钉图工具栏不读这份配置，排布固定（见 PinToolbar.LAYOUT）。
"""

import json

SHOW = "show"   # 始终显示在工具栏上
MORE = "more"   # 收进「…」弹层
HIDE = "hide"   # 始终隐藏
MODES = (SHOW, MORE, HIDE)

# 可配置按钮的全集，也是默认顺序。
# 默认按"先数字、后英文、再无快捷键"排：1~9 数字快捷键的按钮排最前（含收进「…」的
# 文字识别/截图翻译，它们的 8/9 仍排在数字队列里），接着是单字母快捷键的按钮，再是
# 组合键/固定键，没有快捷键的按钮垫底；「确定」是固定收尾按钮，始终在最右。
DEFAULT_ORDER = (
    # 数字 1~9
    "note", "rect", "arrow", "text", "number", "pin", "mosaic",
    "text_recognize", "screenshot_translate",
    # 单字母快捷键
    "pen", "highlighter", "ellipse", "eraser",
    # 组合键 / 固定键
    "undo", "redo", "cancel",
    # 无快捷键
    "long_screenshot", "save", "scan_code", "gif", "spotlight",
    # 固定收尾
    "confirm",
)

# 默认收进「…」的按钮，其余默认始终显示。后加的低频、无快捷键功能放这里，
# 免得把工具栏默认宽度越撑越宽；数字 8/9 的识别/翻译给足存在感，拿出来始终显示。
DEFAULT_MORE = frozenset({"scan_code", "spotlight"})

# 确定按钮固定显示、不可调整，也不出现在工具栏调整界面中：截图必须始终有办法收尾。
# 其余按钮都是普通编辑操作，用户可以自由排序、收进「…」或隐藏。
LOCKED = frozenset({"confirm"})

SETTING_KEY = "screenshot_toolbar_layout"


def _default_mode(key):
    return MORE if key in DEFAULT_MORE else SHOW


def default_layout():
    """[(按钮, 显示方式)]，默认顺序、默认显示方式"""
    return [(key, _default_mode(key)) for key in DEFAULT_ORDER]


def normalize_layout(entries):
    """把任意来源的排布整理成合法、完整的排布；读配置、存配置、对话框回填都只走这里。

    - 未知按钮、重复按钮、格式不对的条目丢掉；不认识的显示方式按这个按钮的默认显示方式
    - 锁定的按钮一律始终显示
    - 缺的按钮（比如升级后新加的）按默认显示方式，插回默认顺序里它前一个按钮的后面。按
      默认顺序逐个补，补到第 i 个时前面的都已在列表里，前一个按钮一定找得到。不直接堆到
      末尾，是因为那样新按钮会出现在「确定」右边
    """
    if not isinstance(entries, (list, tuple)):
        entries = ()

    result = []
    seen = set()
    for entry in entries:
        try:
            key, mode = entry
        except (TypeError, ValueError):
            continue
        if key not in DEFAULT_ORDER or key in seen:
            continue
        seen.add(key)
        if key in LOCKED:
            mode = SHOW
        elif mode not in MODES:
            mode = _default_mode(key)
        result.append((key, mode))

    for index, key in enumerate(DEFAULT_ORDER):
        if key in seen:
            continue
        keys = [k for k, _mode in result]
        position = keys.index(DEFAULT_ORDER[index - 1]) + 1 if index else 0
        result.insert(position, (key, _default_mode(key)))
        seen.add(key)
    return result


def load_layout():
    """读用户配置；没配过或配置损坏时就是默认排布"""
    from settings import get_tool_settings_manager

    raw = get_tool_settings_manager().get_app_setting(SETTING_KEY)
    try:
        stored = json.loads(raw) if raw else None
    except ValueError:
        stored = None
    return normalize_layout(stored)


def save_layout(entries):
    """归一化后写入配置，返回实际保存的排布"""
    from settings import get_tool_settings_manager

    layout = normalize_layout(entries)
    get_tool_settings_manager().set_app_setting(SETTING_KEY, json.dumps(layout))
    return layout
