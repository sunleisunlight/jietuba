#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""应用版本号唯一读取工具。

项目版本唯一源是 ``main/main_app.py`` 中的 ``APP_VERSION``（见 AGENTS.md）。
本模块用 ``ast`` 静态解析该赋值，**不 import main_app.py**——直接导入会连带
引入 PySide6、平台 backend 等模块，产生副作用，且在没有图形环境时会失败。

用法::

    from version_utils import read_app_version
    read_app_version()          # -> "2.4.0"

CLI（打包脚本用）::

    python scripts/version_utils.py
    # 输出: 2.4.0
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MAIN_APP = REPO_ROOT / "main" / "main_app.py"
APP_VERSION_NAME = "APP_VERSION"

# 正式软件版本统一三段式 MAJOR.MINOR.PATCH（AGENTS.md 版本规则）
_SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


def read_app_version(path: Path | str | None = None) -> str:
    """返回 ``main/main_app.py`` 中 ``APP_VERSION`` 的字符串值。

    Args:
        path: 可选，覆盖默认的 ``main/main_app.py`` 路径（测试用）。

    Raises:
        FileNotFoundError: 目标文件不存在。
        ValueError: 文件中找不到 ``APP_VERSION`` 或它不是合法的三段式版本字符串。
    """
    target = Path(path) if path is not None else MAIN_APP
    if not target.is_file():
        raise FileNotFoundError(f"版本唯一源文件不存在: {target}")

    source = target.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(target))

    for node in tree.body:
        # 只认模块级 `APP_VERSION = "<str>"`；子作用域里的同名变量不算
        if not isinstance(node, ast.Assign):
            continue
        if not any(
            isinstance(t, ast.Name) and t.id == APP_VERSION_NAME
            for t in node.targets
        ):
            continue
        value = node.value
        if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
            raise ValueError(
                f"{target} 中的 {APP_VERSION_NAME} 必须是字符串字面量"
            )
        version = value.value.strip()
        if not _SEMVER.match(version):
            raise ValueError(
                f"{target} 中的 {APP_VERSION_NAME}={version!r} 不是 MAJOR.MINOR.PATCH "
                "三段式版本号"
            )
        return version

    raise ValueError(f"{target} 中未找到 {APP_VERSION_NAME} 赋值")


def main() -> None:
    print(read_app_version())


if __name__ == "__main__":
    main()