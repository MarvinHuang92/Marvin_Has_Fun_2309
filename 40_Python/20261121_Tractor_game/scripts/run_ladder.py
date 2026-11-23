# -*- coding: utf-8 -*-
"""跑 AI 强度阶梯：rule / heuristic / adv 两两对战。

跑法：python scripts/run_ladder.py [局数]
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = HERE


def run(a, b, deals, extra=None):
    cmd = [sys.executable, "-u", "-m", "tractor.eval_harness",
           "--a", a, "--b", b, "--deals", str(deals),
           "--adv-samples", "4"]
    if extra:
        cmd += extra
    out = subprocess.run(cmd, cwd=SCRIPTS, capture_output=True, text=True,
                         encoding="utf-8", errors="replace")
    line = ""
    for ln in (out.stdout or "").splitlines():
        if "A 队平均" in ln:
            line = ln.strip()
    print("%-10s vs %-10s  %s" % (a, b, line), flush=True)
    return line


def main():
    deals = int(sys.argv[1]) if len(sys.argv) > 1 else 600
    print("=" * 70)
    print("AI 强度阶梯（每对 %d 局；负数 = B 更强）" % deals)
    print("=" * 70)
    run("rule", "heuristic", deals)
    run("rule", "adv", deals, ["--adv-model", "models/adv_mix3.json"])
    run("heuristic", "adv", deals, ["--adv-model", "models/adv_mix3.json"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
