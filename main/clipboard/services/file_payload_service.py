# -*- coding: utf-8 -*-

"""文件条目 payload 工具。

负责 file 类型内容在表单层和存储层之间的转换，包括路径规范化、
JSON payload 构建，以及兼容旧格式内容时的首个文件路径提取。
"""

import json
import os
import re
from typing import Optional

#: Windows 盘符路径（如 C:\Users\... 或 C:/Users/...）
_WIN_DRIVE_RE = re.compile(r"^[A-Za-z]:[\\/]")


def normalize_file_path(path: str) -> str:
    """规范化文件路径（跨平台一致）。

    Windows 盘符/反斜杠路径在 POSIX 上会被 os.path.normpath 当成普通字符
    （双反斜杠不折叠、正反斜杠不统一），导致剪贴板数据库跨平台读到不同的
    字符串；此类路径统一用 ntpath 按 Windows 语义归一化，其余用本平台语义。
    """
    s = path.strip()
    if "\\" in s or _WIN_DRIVE_RE.match(s):
        import ntpath
        return ntpath.normpath(s)
    return os.path.normpath(s)


def build_file_payload(path: str) -> str:
    """构建 file 类型条目的 JSON payload。"""
    return json.dumps({"files": [normalize_file_path(path)]}, ensure_ascii=False)


def extract_first_file_path_from_content(content: Optional[str]) -> str:
    """从 file 类型内容中提取首个路径，兼容旧格式原始路径文本。"""
    raw_content = (content or "").strip()
    if not raw_content:
        return ""

    try:
        data = json.loads(raw_content)
    except Exception:
        return os.path.normpath(raw_content)

    if not isinstance(data, dict):
        return ""

    files = data.get("files", [])
    if not files:
        return ""
    return normalize_file_path(files[0])
