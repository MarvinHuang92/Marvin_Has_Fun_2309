"""跑分：1 / 2 / 4 部电梯 × 8 种调度算法 × 多个随机种子。

    python elevators.py --bench
    python -m sim.benchmark --seeds 5

产物：results.csv（每次运行的原始数据）、report.md（表格与结论）、charts/*.png。
"""

from __future__ import annotations

import argparse
import csv
import random
import statistics
import sys
import time
import unicodedata
from pathlib import Path
from typing import Iterable, Sequence

from .dispatch import (
    ALGORITHMS,
    DESTINATION_ONLY,
    HALL_ONLY,
    ORDER,
    SHORT_LABELS,
    build_dispatcher,
)
from .model import CAPACITY, MAX_FLOOR, MIN_FLOOR, Elevator, Passenger, Timing, World, make_timing

BASE_DIR = Path(__file__).resolve().parent.parent

PASSENGERS = 100
CAR_COUNTS = (1, 2, 4)
SEEDS = (1, 2, 3, 4, 5)
#: 动态场景：乘客在 0~180 s（含两端）内均匀到达
DYNAMIC_WINDOW = 180

#: 两种测试场景
SCENARIOS = {
    "lobby": {
        "label": "早高峰（100 人全在 1 楼）",
        "short": "早高峰",
        "desc": "100 人全部在 1 楼等候，目的地 2~20 层随机（20 层楼）",
        "floors": 20, "passengers": 100, "window": 0, "timing": "normal",
        "exclude": set(),
        "csv": "results.csv",
        "report": "report.md",
        "charts": "charts",
    },
    "uniform": {
        "label": "混合交通（起点终点全楼随机）",
        "short": "混合交通",
        "desc": ("100 人随机分布在 1~20 层，目的地是除本层外的随机楼层，"
                 "全部在 t=0 就已在候梯"),
        "floors": 20, "passengers": 100, "window": 0, "timing": "normal",
        "exclude": {"original"},  # 按需求：丢弃"每层必停"的原程序
        "csv": "results_uniform.csv",
        "report": "report_uniform.md",
        "charts": "charts_uniform",
    },
    "dynamic": {
        "label": "动态混合（乘客陆续到达）",
        "short": "动态混合",
        "desc": "100 人分散在 0~180 s 内陆续出现（每秒开始时刷新，含两端），起点/终点全楼随机",
        "floors": 20, "passengers": 100, "window": 180, "timing": "normal",
        "exclude": {"original"},
        "csv": "results_dynamic.csv",
        "report": "report_dynamic.md",
        "charts": "charts_dynamic",
    },
    # ---------------- 摩天楼版（100 层、200 人、4 倍速） ----------------
    "lobby100": {
        "label": "摩天楼早高峰（200 人全在 1 楼）",
        "short": "100 层早高峰",
        "desc": "200 人全部在 1 楼等候，目的地 2~100 层随机（100 层楼、4 倍速）",
        "floors": 100, "passengers": 200, "window": 0, "timing": "skyscraper",
        "exclude": {"original"},
        "csv": "results_lobby100.csv",
        "report": "report_lobby100.md",
        "charts": "charts_lobby100",
    },
    "uniform100": {
        "label": "摩天楼混合交通（起点终点全楼随机）",
        "short": "100 层混合",
        "desc": "200 人随机分布在 1~100 层，目的地是除本层外的随机楼层，全部同时候梯",
        "floors": 100, "passengers": 200, "window": 0, "timing": "skyscraper",
        "exclude": {"original"},
        "csv": "results_uniform100.csv",
        "report": "report_uniform100.md",
        "charts": "charts_uniform100",
    },
    "dynamic100": {
        "label": "摩天楼动态混合（200 人陆续到达）",
        "short": "100 层动态",
        "desc": "200 人分散在 0~360 s 内陆续出现（每秒开始时刷新，含两端），起点/终点全楼随机",
        "floors": 100, "passengers": 200, "window": 360, "timing": "skyscraper",
        "exclude": {"original"},
        "csv": "results_dynamic100.csv",
        "report": "report_dynamic100.md",
        "charts": "charts_dynamic100",
    },
}


INFO_MODELS = {
    "destination": {
        "label": "目的地已知（每层 20 个按钮 / 触摸屏）",
        "short": "",
        "desc": "乘客在进电梯前就选好目的层，系统知道每个人的去向。",
    },
    "hall": {
        "label": "只有上/下按钮",
        "short": "（按钮）",
        "desc": ("电梯外只有上/下两个按钮，系统只知道有人要上楼或下楼、不知道去哪；"
                 "需要目的层的派梯/分组算法无法使用。"),
    },
}


def order_for(scenario: str, info: str = "destination") -> list[str]:
    excluded = set(SCENARIOS[scenario]["exclude"])
    if info == "hall":
        excluded |= set(DESTINATION_ONLY)
    else:
        excluded |= set(HALL_ONLY)
    return [key for key in ORDER if key not in excluded]


def artifacts(scenario: str, info: str = "destination") -> tuple[Path, Path, Path]:
    cfg = SCENARIOS[scenario]
    if info == "destination":
        return BASE_DIR / cfg["csv"], BASE_DIR / cfg["report"], BASE_DIR / cfg["charts"]
    suffix = f"_{info}"
    return (
        BASE_DIR / f"results_{scenario}{suffix}.csv",
        BASE_DIR / f"report_{scenario}{suffix}.md",
        BASE_DIR / f"{cfg['charts']}{suffix}",
    )

#: 表格里的指标：(字段, 显示名, 单位)
METRICS = [
    ("makespan", "完成时间", "s"),
    ("avg_wait", "平均候梯", "s"),
    ("avg_ride", "平均乘梯", "s"),
    ("avg_total", "平均总时", "s"),
    ("p90_total", "P90 总时", "s"),
    ("stops", "停靠次数", "次"),
    ("floors", "运行层数", "层"),
]


# ---------------------------------------------------------------- 构造


def _sample_trip(rng: random.Random, floors: int) -> tuple[int, int]:
    """随机起点 + 不等于起点的随机终点（均匀分布）。"""
    origin = rng.randint(MIN_FLOOR, floors)
    target = rng.randint(MIN_FLOOR, floors - 1)
    if target >= origin:
        target += 1
    return origin, target


def make_world(
    algo_key: str,
    cars: int,
    seed: int,
    passengers: int | None = None,
    timing: Timing | None = None,
    trace: bool = False,
    scenario: str = "lobby",
    info: str = "destination",
) -> World:
    """造一个场景。``scenario`` / ``info`` 见 :data:`SCENARIOS` / :data:`INFO_MODELS`。"""
    cfg = SCENARIOS[scenario]
    floors = cfg["floors"]
    n_people = cfg["passengers"] if passengers is None else passengers
    window = cfg["window"]
    rng = random.Random(seed)

    if scenario.startswith("lobby"):
        trips = [(MIN_FLOOR, rng.randint(MIN_FLOOR + 1, floors), 0) for _ in range(n_people)]
    elif scenario.startswith("uniform"):
        trips = [(*_sample_trip(rng, floors), 0) for _ in range(n_people)]
    elif scenario.startswith("dynamic"):
        trips = [(*_sample_trip(rng, floors), rng.randint(0, window)) for _ in range(n_people)]
    else:
        raise SystemExit(f"未知场景 {scenario!r}，可选：{', '.join(SCENARIOS)}")

    people = [Passenger(pid=i, origin=o, target=t, request_time=at)
              for i, (o, t, at) in enumerate(trips)]
    lifts = [Elevator(eid=i + 1, floor=MIN_FLOOR) for i in range(cars)]
    return World(
        people,
        lifts,
        build_dispatcher(algo_key),
        timing=timing or make_timing(cfg["timing"]),
        trace=trace,
        info_model=info,
        max_floor=floors,
    )


def run_once(
    algo_key: str,
    cars: int,
    seed: int,
    passengers: int | None = None,
    scenario: str = "lobby",
    info: str = "destination",
) -> dict:
    world = make_world(algo_key, cars, seed, passengers, scenario=scenario, info=info)
    stats = world.run()
    stats.update(algo_key=algo_key, seed=seed, cars=cars, scenario=scenario,
                 info=info, done=world.done())
    return stats


def run_matrix(
    car_counts: Sequence[int] = CAR_COUNTS,
    seeds: Sequence[int] = SEEDS,
    passengers: int | None = None,
    verbose: bool = True,
    scenario: str = "lobby",
    info: str = "destination",
) -> list[dict]:
    rows: list[dict] = []
    started = time.time()
    for cars in car_counts:
        for key in order_for(scenario, info):
            for seed in seeds:
                stats = run_once(key, cars, seed, passengers, scenario=scenario, info=info)
                rows.append(stats)
            subset = [r for r in rows if r["cars"] == cars and r["algo_key"] == key]
            if verbose:
                mean_ms = statistics.mean(r["makespan"] for r in subset)
                print(f"  {cars} 部电梯 · {SHORT_LABELS[key]:<6} "
                      f"完成时间均值 {mean_ms:7.1f}s  "
                      f"（{len(subset)} 个种子）")
    if verbose:
        print(f"  共 {len(rows)} 次运行，耗时 {time.time() - started:.2f}s")
    return rows


# ---------------------------------------------------------------- 聚合


def aggregate(rows: Iterable[dict]) -> dict[tuple[int, str], dict]:
    buckets: dict[tuple[int, str], list[dict]] = {}
    for row in rows:
        buckets.setdefault((row["cars"], row["algo_key"]), []).append(row)

    result: dict[tuple[int, str], dict] = {}
    for key, group in buckets.items():
        summary = {"runs": len(group)}
        for metric, _, _ in METRICS:
            values = [r[metric] for r in group]
            summary[metric] = statistics.mean(values)
            summary[metric + "_std"] = statistics.pstdev(values) if len(values) > 1 else 0.0
        result[key] = summary
    return result


# ---------------------------------------------------------------- 文本表格


def text_width(text: str) -> int:
    """中文字符按 2 列算，保证控制台对齐。"""
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in str(text))


def render_table(headers: Sequence[str], rows: Sequence[Sequence], aligns: Sequence[str] | None = None) -> str:
    aligns = list(aligns or ["left"] + ["right"] * (len(headers) - 1))
    widths = [text_width(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], text_width(cell))

    def cell_text(cell, i):
        gap = widths[i] - text_width(cell)
        return cell + " " * gap if aligns[i] == "left" else " " * gap + cell

    lines = ["  ".join(cell_text(h, i) for i, h in enumerate(headers))]
    lines.append("  ".join("-" * w for w in widths))
    for row in rows:
        lines.append("  ".join(cell_text(str(c), i) for i, c in enumerate(row)))
    return "\n".join(lines)


def markdown_table(headers: Sequence[str], rows: Sequence[Sequence], aligns: Sequence[str] | None = None) -> str:
    aligns = list(aligns or ["left"] + ["right"] * (len(headers) - 1))
    head = "| " + " | ".join(headers) + " |"
    rule = "| " + " | ".join(":---" if a == "left" else "---:" for a in aligns) + " |"
    body = "\n".join("| " + " | ".join(str(c) for c in row) + " |" for row in rows)
    return "\n".join([head, rule, body])


# ---------------------------------------------------------------- 控制台输出


def print_summary(summary: dict, car_counts: Sequence[int] = CAR_COUNTS,
                  scenario: str = "lobby", info: str = "destination") -> None:
    order = order_for(scenario, info)
    print(f"\n完成时间（秒，越小越好；{SCENARIOS[scenario]['desc']}）")
    rows = []
    for key in order:
        row = [ALGORITHMS_BY_KEY[key].label]
        for cars in car_counts:
            row.append(f"{summary[(cars, key)]['makespan']:.0f}")
        rows.append(row)
    print(render_table(["算法"] + [f"{c} 部电梯" for c in car_counts], rows))

    print("\n平均总耗时（秒，门到门）")
    rows = []
    for key in order:
        row = [ALGORITHMS_BY_KEY[key].label]
        for cars in car_counts:
            row.append(f"{summary[(cars, key)]['avg_total']:.0f}")
        rows.append(row)
    print(render_table(["算法"] + [f"{c} 部电梯" for c in car_counts], rows))


ALGORITHMS_BY_KEY = {cls.key: cls for cls in ALGORITHMS}


# ---------------------------------------------------------------- 报告


def write_csv(path: Path, rows: Sequence[dict]) -> None:
    fields = ["algo_key", "cars", "seed", "passengers", "makespan", "avg_wait", "avg_ride",
              "avg_total", "p90_total", "max_total", "stops", "floors", "door_seconds",
              "idle_seconds", "done"]
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _best_key(summary: dict, cars: int, order: Sequence[str]) -> str:
    return min(order, key=lambda k: summary[(cars, k)]["makespan"])


def write_report(
    path: Path,
    summary: dict,
    car_counts: Sequence[int],
    seeds: Sequence[int],
    passengers: int,
    charts: dict[str, Path],
    scenario: str = "lobby",
    info: str = "destination",
) -> None:
    order = order_for(scenario, info)
    cfg = SCENARIOS[scenario]
    info_cfg = INFO_MODELS[info]
    lines: list[str] = []
    add = lines.append

    add(f"# 电梯调度算法对比报告 · {cfg['label']} · {info_cfg['label']}")
    add("")
    add(f"> 自动生成于 {time.strftime('%Y-%m-%d %H:%M:%S')}。**{cfg['desc']}**，"
        f"每部电梯容量 {CAPACITY} 人，电梯初始都在 {MIN_FLOOR} 楼。")
    add("")
    add(f"**需求表达方式**：{info_cfg['desc']}")
    add("")
    add("**时间模型**：跨越 1 层 4s，2 层 6s，n≥2 层 4+n s；开关门各 2s；"
        "上下客每人 1s（最少 2s）。电梯只停靠有人的楼层。")
    add("")
    add(f"每个组合跑 {len(seeds)} 个随机种子（{', '.join(map(str, seeds))}），表中为均值。")
    skipped = [k for k in ORDER if k not in order and k not in cfg["exclude"]]
    if cfg["exclude"] or skipped:
        add("")
        names = [ALGORITHMS_BY_KEY[k].label for k in list(cfg["exclude"]) + skipped]
        add("本场景不参与对比：" + "、".join(names) + "。")
    add("")

    # 一、完成时间
    add("## 一、完成时间")
    add("")
    add("把最后一位乘客送到目的层所用的秒数。这是最直观的“电梯够不够用”的指标。")
    add("")
    rows = []
    for key in order:
        best_marks = [summary[(c, key)]["makespan"] for c in car_counts]
        rows.append([ALGORITHMS_BY_KEY[key].label] + [f"{v:.0f}" for v in best_marks])
    add(markdown_table(["算法"] + [f"{c} 部电梯" for c in car_counts], rows))
    add("")
    if "makespan" in charts:
        add(f"![完成时间对比]({charts['makespan'].relative_to(path.parent).as_posix()})")
        add("")

    # 二、平均总耗时
    add("## 二、平均总耗时（门到门）")
    add("")
    add("每位乘客从“开始等待”到“走出电梯”的平均秒数。")
    add("")
    rows = []
    for key in order:
        rows.append([ALGORITHMS_BY_KEY[key].label] +
                    [f"{summary[(c, key)]['avg_total']:.0f}" for c in car_counts])
    add(markdown_table(["算法"] + [f"{c} 部电梯" for c in car_counts], rows))
    add("")
    if "avg_total" in charts:
        add(f"![平均总耗时对比]({charts['avg_total'].relative_to(path.parent).as_posix()})")
        add("")

    # 三、详细指标
    add("## 三、各电梯数量下的完整指标")
    for cars in car_counts:
        add("")
        add(f"### {cars} 部电梯")
        add("")
        headers = ["算法"] + [name for _, name, _ in METRICS]
        rows = []
        best = _best_key(summary, cars, order)
        for key in order:
            values = []
            for metric, _, _ in METRICS:
                value = summary[(cars, key)][metric]
                text = f"{value:.0f}"
                if metric == "makespan" and key == best:
                    text = f"**{text}**"
                values.append(text)
            rows.append([ALGORITHMS_BY_KEY[key].label] + values)
        add(markdown_table(headers, rows))
        add("")
        add(f"最快：**{ALGORITHMS_BY_KEY[best].label}**，"
            f"{summary[(cars, best)]['makespan']:.0f}s。")

    # 四、能耗
    add("")
    add("## 四、停靠次数与运行层数（省电与否）")
    add("")
    add("停靠一次就要开关门 + 上下客，运行层数直接对应耗电。两者都是越小越省。")
    add("")
    rows = []
    for key in order:
        rows.append([ALGORITHMS_BY_KEY[key].label] +
                    [f"{summary[(c, key)]['stops']:.0f}" for c in car_counts] +
                    [f"{summary[(c, key)]['floors']:.0f}" for c in car_counts])
    headers = ["算法"] + [f"{c} 部·停靠" for c in car_counts] + [f"{c} 部·层数" for c in car_counts]
    add(markdown_table(headers, rows))
    add("")
    if "stops" in charts:
        add(f"![停靠次数对比]({charts['stops'].relative_to(path.parent).as_posix()})")
        add("")

    # 五、结论
    add("")
    add("## 五、结论")
    add("")
    for cars in car_counts:
        ranked = sorted(order, key=lambda k: summary[(cars, k)]["makespan"])
        best = ranked[0]
        second = ranked[1] if len(ranked) > 1 else ranked[0]
        best_ms = summary[(cars, best)]["makespan"]
        second_ms = summary[(cars, second)]["makespan"]
        line = f"- **{cars} 部电梯**：最快 {ALGORITHMS_BY_KEY[best].label} {best_ms:.0f}s"
        if second != best:
            line += (f"，其次 {ALGORITHMS_BY_KEY[second].label} {second_ms:.0f}s"
                     f"（慢 {second_ms / best_ms - 1:.0%}）")
        if "original" in order:
            base = summary[(cars, "original")]["makespan"]
            line += f"；原程序 {base:.0f}s，光是跳层 + 正确换向就快 {base / second_ms:.1f} 倍"
        add(line + "。")
    add("")
    add("完整分析见 README.md。")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------- 主流程


def run_benchmark(
    car_counts: Sequence[int] = CAR_COUNTS,
    seeds: Sequence[int] = SEEDS,
    passengers: int | None = None,
    make_charts: bool = True,
    verbose: bool = True,
    scenario: str = "lobby",
    info: str = "destination",
) -> dict:
    rows = run_matrix(car_counts, seeds, passengers, verbose=verbose,
                      scenario=scenario, info=info)
    summary = aggregate(rows)

    csv_path, report_path, chart_dir = artifacts(scenario, info)
    order = order_for(scenario, info)
    write_csv(csv_path, rows)
    if verbose:
        print(f"已写入 {csv_path.name}")

    charts: dict[str, Path] = {}
    if make_charts:
        try:
            from .charts import grouped_bar_chart
        except Exception:  # pragma: no cover - Pillow 缺失时降级
            grouped_bar_chart = None
        if grouped_bar_chart is not None:
            short = SCENARIOS[scenario]["short"] + INFO_MODELS[info]["short"]
            chart_specs = [
                ("makespan", f"完成时间对比 · {short}", "秒", "{:.0f}"),
                ("avg_total", f"平均总耗时对比 · {short}", "秒", "{:.0f}"),
                ("stops", f"总停靠次数对比 · {short}", "次", "{:.0f}"),
            ]
            for metric, title, unit, fmt in chart_specs:
                series = {
                    f"{c} 部电梯": [summary[(c, key)][metric] for key in order]
                    for c in car_counts
                }
                target = chart_dir / f"{metric}.png"
                grouped_bar_chart(
                    target,
                    [SHORT_LABELS[key] for key in order],
                    series,
                    title=title,
                    ylabel=unit,
                    value_format=fmt,
                )
                charts[metric] = target
            if verbose:
                print(f"已生成 {len(charts)} 张图表到 {chart_dir.name}/")

    n_people = SCENARIOS[scenario]["passengers"] if passengers is None else passengers
    write_report(report_path, summary, car_counts, seeds, n_people, charts,
                 scenario, info)
    if verbose:
        print(f"已写入 {report_path.name}")
    return {"rows": rows, "summary": summary, "charts": charts,
            "scenario": scenario, "info": info}


# ---------------------------------------------------------------- 自检


def selftest() -> None:
    """时间模型 + 全部算法 × 两种场景 × 1/2/4 部电梯，必须全部送达且不超载。"""
    timing = Timing()
    assert timing.travel(0) == 0
    assert timing.travel(1) == 4, timing.travel(1)
    assert timing.travel(2) == 6, timing.travel(2)
    assert timing.travel(3) == 7, timing.travel(3)
    assert timing.travel(20) == 24, timing.travel(20)
    assert [timing.transfer(k) for k in (0, 1, 2, 3, 8)] == [2, 2, 2, 3, 8]

    checked = 0
    for scenario in SCENARIOS:
        for info in ("destination", "hall"):
            for cars in (1, 2, 4):
                for key in order_for(scenario, info):
                    world = make_world(key, cars, seed=99, passengers=40,
                                       scenario=scenario, info=info)
                    stats = world.run()
                    assert world.done(), f"{scenario}/{info}/{key}/{cars} 部：仍有乘客没送到"
                    assert all(car.load <= CAPACITY for car in world.cars), "超载"
                    assert all(world.min_floor <= car.floor <= world.max_floor for car in world.cars), "楼层越界"
                    assert stats["makespan"] > 0
                    for p in world.passengers:
                        assert p.board_time is not None and p.alight_time is not None
                        assert p.alight_time >= p.board_time >= p.request_time >= 0
                        assert p.origin != p.target
                        assert p.car_id is not None
                    checked += 1

    # 场景 D（无限客流）的轻量自检：短时长 + 低速率
    from .capacity import make_load_world

    load_world = make_load_world("look", 0.2, seed=1, duration=600)
    load_stats = load_world.run()
    assert load_stats["completed"] > 0, "容量模式没有送出任何人"
    assert not load_stats["failed"], "低速率下不该超载"

    print(f"自检通过：时间模型 + {checked} 个组合"
          f"（{len(SCENARIOS)} 种场景 × {len(INFO_MODELS)} 种需求表达方式 × 算法 × 1/2/4 部电梯）"
          f"全部正常送达。")


# ---------------------------------------------------------------- CLI


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="电梯调度算法跑分")
    parser.add_argument("--seeds", type=int, default=5, help="随机种子个数（默认 5）")
    parser.add_argument("--cars", type=int, nargs="+", default=list(CAR_COUNTS))
    parser.add_argument("--passengers", type=int, default=None, help="覆盖场景默认人数（默认按场景）")
    parser.add_argument("--scenario", choices=list(SCENARIOS) + ["all"], default="lobby",
                        help="测试场景（默认 lobby；all = 六种都跑）")
    parser.add_argument("--info", choices=["destination", "hall", "both"], default="destination",
                        help="需求表达方式：destination=每层 20 按钮/触摸屏；"
                             "hall=只有上/下按钮；both=两种都跑")
    parser.add_argument("--no-charts", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    seeds = tuple(range(1, args.seeds + 1))
    scenarios = list(SCENARIOS) if args.scenario == "all" else [args.scenario]
    infos = list(INFO_MODELS) if args.info == "both" else [args.info]
    for scenario in scenarios:
        for info in infos:
            if len(scenarios) * len(infos) > 1:
                print(f"\n=== {SCENARIOS[scenario]['label']} · {INFO_MODELS[info]['label']} ===")
            result = run_benchmark(
                car_counts=tuple(args.cars),
                seeds=seeds,
                passengers=args.passengers,
                make_charts=not args.no_charts,
                verbose=not args.quiet,
                scenario=scenario,
                info=info,
            )
            print_summary(result["summary"], tuple(args.cars), scenario, info)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
