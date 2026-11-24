# -*- coding: utf-8 -*-
"""命令行版性能报告（不打开 tkinter，适合脚本/CI 对比调参前后的数据）。

跑法::

    python scripts/benchmark_report.py            # 打印到控制台
    python scripts/benchmark_report.py --save     # 另存到 data/benchmark_*.txt
"""
import argparse
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from minirace.benchmark import run_all  # noqa: E402
from minirace.config import load_config  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="Mini Race 2 性能报告")
    parser.add_argument("--save", action="store_true",
                        help="把报告保存到 data/benchmark_YYYYmmdd_HHMMSS.txt")
    args = parser.parse_args()

    start = time.time()
    report = run_all(load_config(PROJECT_DIR))
    print(report.as_text())
    print("（测试耗时 %.2f s）" % (time.time() - start))

    if args.save:
        folder = os.path.join(PROJECT_DIR, "data")
        if not os.path.isdir(folder):
            os.makedirs(folder)
        path = os.path.join(folder, "benchmark_%s.txt" % time.strftime("%Y%m%d_%H%M%S"))
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(report.as_text())
        print("报告已保存：%s" % path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
