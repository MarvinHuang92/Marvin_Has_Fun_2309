# -*- coding: utf-8 -*-
"""检查 dependencies.txt 里列的库，缺了就自动用 pip 安装。"""

import importlib
import importlib.util
import subprocess
import sys
from pathlib import Path

TOOL_ROOT = Path(__file__).resolve().parent.parent
DEPENDENCIES_FILE = TOOL_ROOT / "dependencies.txt"
MIRROR = "https://pypi.tuna.tsinghua.edu.cn/simple"

SEPARATORS = ("==", ">=", "<=", "~=", "!=", ">", "<", "[", ";", " ")


def read_requirements():
    if not DEPENDENCIES_FILE.exists():
        return []
    requirements = []
    for line in DEPENDENCIES_FILE.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            requirements.append(line)
    return requirements


def module_name(requirement):
    name = requirement
    for separator in SEPARATORS:
        name = name.split(separator, 1)[0]
    return name.strip().replace("-", "_")


def is_installed(requirement):
    importlib.invalidate_caches()
    try:
        return importlib.util.find_spec(module_name(requirement)) is not None
    except (ImportError, AttributeError, ValueError):
        return False


def install(extra_args):
    command = [sys.executable, "-m", "pip", "install",
               "--disable-pip-version-check", "-r", str(DEPENDENCIES_FILE)]
    command.extend(extra_args)
    print("  执行：%s" % " ".join(command))
    return subprocess.call(command) == 0


def main():
    requirements = read_requirements()
    missing = [item for item in requirements if not is_installed(item)]
    if not missing:
        return 0

    print("缺少依赖：%s" % ", ".join(missing))
    print("正在自动安装 ...")
    if install([]):
        print("依赖安装完成。")
        return 0

    print()
    print("默认源安装失败，改用国内镜像重试 ...")
    if install(["-i", MIRROR]):
        print("依赖安装完成。")
        return 0

    print()
    print("[出错] 依赖没能自动装好。请手动执行：")
    print("  \"%s\" -m pip install -r \"%s\"" % (sys.executable, DEPENDENCIES_FILE))
    return 1


if __name__ == "__main__":
    sys.exit(main())
