# -*- coding: utf-8 -*-
"""Mini Race 2 入口。

正常启动::

    python scripts/main.py

或双击 01_Run.bat（自动找带 pygame 的 Python，用 pythonw 启动）。

调试 / 自动化用::

    python scripts/main.py --smoke                 # 1.5 秒后自动退出
    python scripts/main.py --smoke --record        # 同时把遥测写到 data/run_*.csv
    python scripts/main.py --capture data/shot.png # 存一帧截图后退出
    python scripts/main.py --diagnose              # 诊断模式：逐步写 data/diag_*.csv
                                                   # + 异常事件标记，退出时输出摘要（F9 可开关）
"""
import argparse
import logging
import sys
import traceback
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = PROJECT_DIR / "scripts"
LOG_DIR = PROJECT_DIR / "logs"
LOG_FILE = LOG_DIR / "run.log"

# 让 `from minirace import ...` 生效（不依赖当前工作目录）
sys.path.insert(0, str(SCRIPTS_DIR))


def setup_logging():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    for handler in list(logging.root.handlers):
        logging.root.removeHandler(handler)
    handler = logging.FileHandler(str(LOG_FILE), mode="w", encoding="utf-8")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[handler],
    )
    logging.getLogger(__name__).info("程序启动，项目目录：%s", PROJECT_DIR)


def main():
    parser = argparse.ArgumentParser(description="Mini Race 2 - 车辆模拟器")
    parser.add_argument("--smoke", action="store_true",
                        help="启动 1.5 秒后自动退出（冒烟测试）")
    parser.add_argument("--record", action="store_true",
                        help="把每一步物理观测写到 data/run_*.csv")
    parser.add_argument("--capture", metavar="PATH",
                        help="运行约 1 秒后保存一帧截图，然后退出")
    parser.add_argument("--diagnose", action="store_true",
                        help="启动即进入诊断模式（逐步写 data/diag_*.csv + 异常事件摘要）；"
                             "游戏里按 F9 可随时开/关")
    args = parser.parse_args()

    setup_logging()
    log = logging.getLogger(__name__)
    try:
        from minirace.app import App
        from minirace.config import load_config

        config = load_config(PROJECT_DIR)
        app = App(PROJECT_DIR, config, record=args.record, capture=args.capture,
                  diagnose=args.diagnose)
        try:
            return app.run(smoke=args.smoke)
        finally:
            app.close()
    except Exception:
        log.exception("启动失败")
        sys.stderr.write("Mini Race 2 启动失败，详情见：%s\n" % LOG_FILE)
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
