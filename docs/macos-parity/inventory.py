"""Read-only baseline entry extractor. Prints JSON; never overwrites acceptance records.

Usage: .venv/bin/python docs/macos-parity/inventory.py <verified commit>
Static extraction is a review aid, not evidence that UI or behavior passed.
"""
import ast
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True)


def owner(path, text):
    value = (path + " " + text).lower()
    if any(word in value for word in ("gif", "stitch", "scroll_cooldown", "long_screenshot")):
        return 4
    if any(word in value for word in ("clipboard", "pin", "translation", "translate", "ocr", "scan_code", "hotkey", "smart_selection")):
        return 3
    if any(word in value for word in ("welcome", "tray", "preload", "show_main_window", "permission")):
        return 1
    if any(word in value for word in ("update", "account", "migration")):
        return 5
    if any(word in value for word in ("tool", "canvas", "capture", "selection", "screenshot", "annotation")):
        return 2
    return 3


def entries(ref):
    result = {}

    def add(path, line, kind, label, behavior):
        identity = hashlib.sha256(f"{path}:{kind}:{label}".encode()).hexdigest()[:12]
        result.setdefault(identity, dict(id=f"WIN-{identity}", source=f"{path}:{line}",
            path=path, kind=kind, label=label, baseline=behavior,
            task=owner(path, label)))

    files = git("ls-tree", "-r", "--name-only", ref, "main").splitlines()
    for path in files:
        if not path.endswith(".py") or "/tests/" in path:
            continue
        if not any(part in path for part in ("/ui/", "/settings/", "/pin/", "/gif/", "/stitch/", "/tools/", "/translation/")):
            continue
        source = git("show", f"{ref}:{path}").lstrip("\ufeff")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = getattr(node.func, "attr", getattr(node.func, "id", ""))
                if name in {"QAction", "QPushButton", "PushButton", "PrimaryPushButton", "addAction",
                            "_add_button", "_add_tool_button", "setToolTip"}:
                    strings = [item.value for arg in node.args for item in ast.walk(arg)
                               if isinstance(item, ast.Constant) and isinstance(item.value, str)]
                    strings = [s for s in strings if s.strip() and not s.startswith(("svg/", "background:"))]
                    if strings:
                        add(path, node.lineno, "入口", strings[0], " / ".join(strings))
                if name == "connect" and isinstance(node.func, ast.Attribute):
                    signal = ast.unparse(node.func.value)
                    if any(s in signal for s in ("clicked", "triggered", "Requested", "requested")):
                        add(path, node.lineno, "操作绑定", signal, ast.unparse(node.args[0]) if node.args else "")
            if isinstance(node, ast.Assign):
                names = [getattr(target, "id", "") for target in node.targets]
                if any(name in {"DEFAULT_SETTINGS", "APP_DEFAULT_SETTINGS"} for name in names) and isinstance(node.value, ast.Dict):
                    for key, value in zip(node.value.keys, node.value.values):
                        if not isinstance(key, ast.Constant):
                            continue
                        if isinstance(value, ast.Dict):
                            for subkey, subvalue in zip(value.keys, value.values):
                                if isinstance(subkey, ast.Constant):
                                    add(path, subkey.lineno, "工具设置", f"{key.value}.{subkey.value}", ast.unparse(subvalue))
                        else:
                            add(path, key.lineno, "应用设置", str(key.value), ast.unparse(value))
                if any(name in {"ANNOTATION_TOOL_SHORTCUTS", "EXTRA_TOOL_SHORTCUTS"} for name in names):
                    for item in ast.literal_eval(node.value):
                        add(path, node.lineno, "工具快捷键", item[2], f"{item[0]} = {item[3]!r}")
    return sorted(result.values(), key=lambda item: (item["task"], item["source"], item["id"]))


if __name__ == "__main__":
    print(json.dumps(entries(sys.argv[1]), ensure_ascii=False, indent=2))
