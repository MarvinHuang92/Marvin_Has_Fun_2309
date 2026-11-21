"""电梯调度仿真 —— 入口脚本。

用法::

    python elevators.py                        # 默认：2 部电梯 + LOOK，跑一遍看结果
    python elevators.py --algo dd_group --cars 4 --seed 3
    python elevators.py --algo look --cars 2 --trace    # 打印逐秒事件流
    python elevators.py --list                 # 看有哪些调度算法
    python elevators.py --check                # 自检：时间模型 + 全部算法都能跑通
    python elevators.py --bench                # 跑分：1/2/4 部电梯 × 8 种算法

场景是固定的：20 层楼，100 人全在 1 楼，目的地 2~20 层随机，每梯 8 人。
时间模型见 sim/model.py：1 层 4s / 2 层 6s / n≥2 层 n+4s，开关门各 2s，
上下客每人 1s（最少 2s）。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# 允许从任意目录 `python 40_Python/20240117_elevators/elevators.py`
sys.path.insert(0, str(Path(__file__).resolve().parent))

from sim.benchmark import (  # noqa: E402
    INFO_MODELS,
    PASSENGERS,
    SCENARIOS,
    make_world,
    print_summary,
    run_benchmark,
    selftest,
)
from sim.dispatch import ALGORITHMS, ORDER  # noqa: E402
from sim.model import CAPACITY, MIN_FLOOR  # noqa: E402


def human(seconds: float) -> str:
    seconds = int(round(seconds))
    if seconds < 60:
        return f"{seconds} 秒"
    return f"{seconds // 60} 分 {seconds % 60:02d} 秒"


def list_algorithms() -> None:
    print("可用的调度算法：\n")
    for cls in ALGORITHMS:
        print(f"  {cls.key:<10} {cls.label}")
        print(f"  {'':<10} {cls.desc}\n")


def demo(algo: str, cars: int, seed: int, passengers: int, trace: bool, verbose: bool,
         scenario: str = "lobby") -> None:
    world = make_world(algo, cars, seed, passengers, trace=trace, scenario=scenario)
    dispatcher = world.dispatcher

    print(f"场景：{SCENARIOS[scenario]['desc']}")
    print(f"配置：{cars} 部电梯（初始都在 {MIN_FLOOR} 楼），每部容量 {CAPACITY} 人，"
          f"调度算法 = {dispatcher.label}")
    print(f"随机种子 {seed}\n")

    stats = world.run(verbose=verbose)

    if trace:
        print("\n".join(world.events))

    print("=" * 66)
    print(f"完成时间（最后一位乘客走出电梯）：{human(stats['makespan'])}（{stats['makespan']:.0f}s）")
    print(f"平均候梯 {human(stats['avg_wait'])} ｜ 平均乘梯 {human(stats['avg_ride'])} "
          f"｜ 平均总耗时 {human(stats['avg_total'])}")
    print(f"P90 总耗时 {human(stats['p90_total'])} ｜ 最慢的乘客 {human(stats['max_total'])}")
    print(f"停靠 {stats['stops']:.0f} 次 ｜ 运行 {stats['floors']:.0f} 层 ｜ "
          f"开关门+上下客合计 {human(stats['door_seconds'])}")

    print("-" * 66)
    for car in world.cars:
        delivered = sum(1 for p in world.passengers if p.car_id == car.eid)
        print(f"{car.name}：运送 {delivered:>3} 人 ｜ 停靠 {car.stops:>3} 次 ｜ "
              f"运行 {car.floors_travelled:>4} 层 ｜ 空等 {car.idle_seconds:>4}s")
    print("=" * 66)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="电梯调度仿真：100 人、20 层楼，用不同算法比较谁更快。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--algo", default="look", choices=ORDER, help="调度算法（默认 look）")
    parser.add_argument("--cars", type=int, default=2, help="电梯数量（默认 2）")
    parser.add_argument("--seed", type=int, default=1, help="随机种子（默认 1）")
    parser.add_argument("--passengers", type=int, default=None, help="乘客数量（默认按场景：100 或 200）")
    parser.add_argument("--scenario", choices=list(SCENARIOS) + ["all"], default="lobby",
                        help="lobby/uniform/dynamic=20 层版；lobby100/uniform100/dynamic100=100 层版；all=全跑")
    parser.add_argument("--info", choices=["destination", "hall", "both"], default="destination",
                        help="destination=每层 20 按钮/触摸屏；hall=只有上/下按钮；both=跑分时两种都跑")
    parser.add_argument("--trace", action="store_true", help="打印逐秒事件流")
    parser.add_argument("--quiet", action="store_true", help="不打印进度")
    parser.add_argument("--list", action="store_true", help="列出所有调度算法")
    parser.add_argument("--check", action="store_true", help="自检")
    parser.add_argument("--bench", action="store_true", help="跑全量对比并生成报告")
    parser.add_argument("--ladder", action="store_true",
                        help="场景 4：容量阶梯（4 部电梯、7200s、单层候梯 >40 判超载）")
    parser.add_argument("--duration", type=int, default=7200, help="容量阶梯的运行时长（默认 7200s）")
    parser.add_argument("--ideal", action="store_true",
                        help="打印理想人均交通时间的理论下限（单人、无其他乘客）")
    parser.add_argument("--ladder100", action="store_true",
                        help="场景 H：摩天楼容量阶梯（100 层、4 倍速、14400s、0.33~0.125 人/秒）")
    parser.add_argument("--seeds", type=int, default=5, help="跑分时的随机种子个数（默认 5）")
    args = parser.parse_args(argv)

    if args.list:
        list_algorithms()
        return 0
    if args.check:
        selftest()
        return 0
    if args.ideal:
        from sim.ideal import main as ideal_main
        return ideal_main()

    if args.ladder100:
        from sim.capacity import print_capacity100, run_capacity100_benchmark

        infos = ["destination", "hall"] if args.info == "both" else [args.info]
        for info in infos:
            if len(infos) > 1:
                print(f"\n=== 摩天楼容量阶梯 · {INFO_MODELS[info]['label']} ===")
            result = run_capacity100_benchmark(
                seeds=tuple(range(1, args.seeds + 1)),
                info=info,
                verbose=not args.quiet,
            )
            print_capacity100(result["summary"], result["rates"])
        return 0

    if args.ladder:
        from sim.capacity import print_capacity, run_capacity_benchmark

        info = "destination" if args.info == "both" else args.info
        result = run_capacity_benchmark(
            seeds=tuple(range(1, args.seeds + 1)),
            duration=args.duration,
            info=info,
            verbose=not args.quiet,
        )
        print_capacity(result["main"], result["fine"], result["main_rates"], result["fine_rates"])
        return 0

    if args.bench:
        scenarios = list(SCENARIOS) if args.scenario == "all" else [args.scenario]
        infos = list(INFO_MODELS) if args.info == "both" else [args.info]
        for scenario in scenarios:
            for info in infos:
                if len(scenarios) * len(infos) > 1:
                    print(f"\n=== {SCENARIOS[scenario]['label']} · {INFO_MODELS[info]['label']} ===")
                result = run_benchmark(
                    seeds=tuple(range(1, args.seeds + 1)),
                    passengers=args.passengers,
                    verbose=not args.quiet,
                    scenario=scenario,
                    info=info,
                )
                print_summary(result["summary"], scenario=scenario, info=info)
        return 0

    demo(args.algo, args.cars, args.seed, args.passengers, args.trace, not args.quiet,
         scenario=args.scenario)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
