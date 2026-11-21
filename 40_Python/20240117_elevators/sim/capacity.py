"""容量阶梯（场景 4）：无限客流下的"人均交通时间"与"能扛住多少人/秒"。

评估口径和前面三个场景不同：

* 不看"多久运完"（客流无限，永远运不完），而看**人均交通时间**
  ——从按下按钮到走出电梯的平均秒数；
* 到 7200 s 冻结，**没送到的乘客直接剔除**，只统计已完成的；
* 难度用"每秒到达人数 n"控制；
* **任一层候梯超过 40 人即判超载**，本次模拟作废；
* 5 个种子里失败 ≥3 次，就认为该算法扛不住这个 n。

实测发现：4 部电梯的运力大约在 **0.4 人/秒**（≈1400 人/小时）附近，
所以 n=1（3600 人/小时）已经超出 2 倍多。于是报告跑两档阶梯：

* ``RATES_MAIN``：题目给的 1/2/4/8/16 人/秒 —— 全部超载，只能比"谁撑得久"；
* ``RATES_FINE``：0.5 ~ 0.125 人/秒（每 2~8 秒 1 人）—— 真正的容量分界线在这里。
"""

from __future__ import annotations

import csv
import random
import statistics
import time
from pathlib import Path
from typing import Iterable, Sequence

from .benchmark import BASE_DIR, INFO_MODELS, markdown_table, render_table
from .dispatch import ALGORITHMS, DESTINATION_ONLY, HALL_ONLY, ORDER, SHORT_LABELS, build_dispatcher
from .model import MIN_FLOOR, Elevator, Passenger, SimulationError, SkyscraperTiming, Timing, World

#: 场景 4 的固定参数
FLOORS = 20            # 容量阶梯仍然用 20 层楼
CARS = 4
DURATION = 7200        # 秒
FAIL_LIMIT = 40        # 任一层候梯超过这个数就判超载
SEEDS = (1, 2, 3, 4, 5)

#: 题目给的阶梯：每秒 n 人（全部超出 4 部电梯的运力）
RATES_MAIN = (1, 2, 4, 8, 16)
#: 细分阶梯：人/秒（0.5 = 每 2 秒 1 人）
RATES_FINE = (0.5, 0.4, 0.33, 0.25, 0.2, 0.125)

ALGORITHMS_BY_KEY = {cls.key: cls for cls in ALGORITHMS}


class LoadSpawner:
    """按给定速率生成乘客：``rate`` 人/秒，可以是小数（0.25 = 每 4 秒 1 人）。"""

    def __init__(self, rate: float, rng: random.Random, floors: int = 20) -> None:
        self.rate = float(rate)
        self.rng = rng
        self.floors = floors
        self.next_pid = 0
        self._acc = 0.0

    def __call__(self, now: int) -> list[Passenger]:
        self._acc += self.rate
        count = int(self._acc + 1e-9)
        self._acc -= count
        batch = []
        for _ in range(count):
            origin = self.rng.randint(MIN_FLOOR, self.floors)
            target = self.rng.randint(MIN_FLOOR, self.floors - 1)
            if target >= origin:
                target += 1
            batch.append(Passenger(self.next_pid, origin, target, request_time=now))
            self.next_pid += 1
        return batch


def make_load_world(
    algo_key: str,
    rate: float,
    seed: int,
    duration: int = DURATION,
    fail_limit: int = FAIL_LIMIT,
    cars: int = CARS,
    info: str = "destination",
    timing: Timing | None = None,
    floors: int = FLOORS,
) -> World:
    """造一个"无限客流"的世界：电梯停在随机楼层，每秒平均来 ``rate`` 人。"""
    # 种子只取决于 (seed, rate)：保证同一组客流在不同楼层/场景下可复现
    rng = random.Random(seed * 100_003 + int(round(rate * 1000)))
    lifts = [Elevator(eid=i + 1, floor=rng.randint(MIN_FLOOR, floors)) for i in range(cars)]
    spawner = LoadSpawner(rate, rng, floors)
    return World(
        [],
        lifts,
        build_dispatcher(algo_key),
        timing=timing or Timing(),
        duration=duration,
        spawner=spawner,
        fail_waiting_limit=fail_limit,
        info_model=info,
        max_floor=floors,
    )


def run_once(algo_key: str, rate: float, seed: int, **kwargs) -> dict:
    world = make_load_world(algo_key, rate, seed, **kwargs)
    try:
        stats = world.run()
    except SimulationError as exc:  # 防御：极端参数下不至于整批崩掉
        stats = {
            "avg_total": float("nan"),
            "avg_wait": float("nan"),
            "avg_ride": float("nan"),
            "p90_total": float("nan"),
            "completed": world.delivered,
            "completion_rate": 0.0,
            "passengers": len(world.passengers),
            "failed": True,
            "fail_time": world.now,
            "max_floor_waiting": world.peak_waiting,
            "error": str(exc),
        }
    stats.update(algo_key=algo_key, rate=rate, seed=seed)
    return stats


def run_ladder(
    rates: Sequence[float],
    seeds: Sequence[int] = SEEDS,
    algorithms: Sequence[str] | None = None,
    duration: int = DURATION,
    fail_limit: int = FAIL_LIMIT,
    info: str = "destination",
    verbose: bool = True,
    tag: str = "",
    floors: int = FLOORS,
    timing: Timing | None = None,
) -> list[dict]:
    keys = list(algorithms or [k for k in ORDER if k != "original"])
    rows: list[dict] = []
    started = time.time()
    for key in keys:
        for rate in rates:
            for seed in seeds:
                rows.append(run_once(key, rate, seed, duration=duration,
                                     fail_limit=fail_limit, info=info,
                                     floors=floors, timing=timing))
        if verbose:
            subset = [r for r in rows if r["algo_key"] == key]
            fails = sum(1 for r in subset if r.get("failed"))
            print(f"  {tag}{SHORT_LABELS[key]:<6} 完成（{fails}/{len(subset)} 次超载）")
    if verbose:
        print(f"  {tag}共 {len(rows)} 次运行，耗时 {time.time() - started:.1f}s")
    return rows


def summarize(rows: Iterable[dict], rates: Sequence[float]) -> dict:
    buckets: dict[tuple[str, float], list[dict]] = {}
    for row in rows:
        buckets.setdefault((row["algo_key"], row["rate"]), []).append(row)

    result = {}
    for key, group in buckets.items():
        ok = [r for r in group if not r.get("failed")]
        result[key] = {
            "runs": len(group),
            "fails": len(group) - len(ok),
            "avg_total": statistics.mean(r["avg_total"] for r in ok) if ok else float("nan"),
            "avg_wait": statistics.mean(r["avg_wait"] for r in ok) if ok else float("nan"),
            "completion": statistics.mean(r["completion_rate"] for r in ok) if ok else 0.0,
            "completed": statistics.mean(r["completed"] for r in ok) if ok else 0.0,
            "fail_time": (statistics.mean(r["fail_time"] for r in group if r.get("failed"))
                          if any(r.get("failed") for r in group) else float("nan")),
            "peak_waiting": max((r.get("max_floor_waiting", 0) for r in group), default=0),
        }
    return result


def capacity_of(summary: dict, key: str, rates: Sequence[float]) -> float:
    """该算法能扛住的最大速率（失败次数 ≤2 视为通过）。"""
    passing = [r for r in rates
               if summary.get((key, r)) and summary[(key, r)]["fails"] <= 2]
    return max(passing) if passing else 0.0


def quality_capacity(summary: dict, key: str, rates: Sequence[float],
                     threshold: float = 0.90) -> float:
    """"体面运力"：还要求完成率 ≥ threshold。

    楼越高，"单层积压 >40" 越难触发（需求摊在 100 层上），
    所以额外用完成率兜底，避免把"只送走七成人"的算法算作通过。
    """
    passing = [r for r in rates
               if summary.get((key, r))
               and summary[(key, r)]["fails"] <= 2
               and summary[(key, r)]["completion"] >= threshold]
    return max(passing) if passing else 0.0


def _fmt_rate(rate: float) -> str:
    return f"{rate:g}"


# ---------------------------------------------------------------- 控制台


def print_capacity(main_summary: dict, fine_summary: dict,
                   main_rates: Sequence[float], fine_rates: Sequence[float]) -> None:
    keys = [k for k in ORDER if (k, main_rates[0]) in main_summary]

    print("\n【主阶梯】n 人/秒 —— 全部超载，比“谁撑得久”（坚持到超载的秒数）")
    rows = []
    for key in keys:
        cells = [f"{main_summary[(key, r)]['fail_time']:.0f}s" for r in main_rates]
        rows.append([ALGORITHMS_BY_KEY[key].label] + cells)
    print(render_table(["算法"] + [f"{_fmt_rate(r)}人/秒" for r in main_rates], rows))

    print("\n【细分阶梯】人/秒 —— 人均交通时间（秒，未超载的种子均值）")
    rows = []
    for key in keys:
        cells = []
        for r in fine_rates:
            item = fine_summary[(key, r)]
            cells.append(f"失败{item['fails']}/5" if item["fails"] >= 3 else f"{item['avg_total']:.0f}")
        rows.append([ALGORITHMS_BY_KEY[key].label] + cells)
    print(render_table(["算法"] + [f"{_fmt_rate(r)}" for r in fine_rates], rows))

    print("\n【容量上限】4 部电梯，失败 ≤2/5 的最大到达速率")
    rows = []
    for key in keys:
        rate = capacity_of(fine_summary, key, fine_rates)
        rows.append([ALGORITHMS_BY_KEY[key].label,
                     f"{rate:g} 人/秒", f"{rate * 3600:.0f} 人/小时"])
    print(render_table(["算法", "速率", "折算"], rows))


# ---------------------------------------------------------------- 报告


def write_capacity_report(
    path: Path,
    main_summary: dict,
    fine_summary: dict,
    main_rates: Sequence[float],
    fine_rates: Sequence[float],
    seeds: Sequence[int],
    duration: int,
    fail_limit: int,
    info: str,
    charts: dict[str, Path],
) -> None:
    keys = [k for k in ORDER if (k, main_rates[0]) in main_summary]
    lines: list[str] = []
    add = lines.append

    add("# 容量阶梯 · 4 部电梯 · " + INFO_MODELS[info]["label"])
    add("")
    add(f"> 自动生成于 {time.strftime('%Y-%m-%d %H:%M:%S')}。"
        f"每秒平均刷出 n 名乘客（起点/终点全楼随机），电梯初始停在随机楼层，"
        f"连续运行 **{duration} s** 后冻结；只统计已经到达的乘客，"
        f"指标是**人均交通时间**（按下按钮 → 走出电梯）。")
    add("")
    add(f"**超载判定**：任一层候梯超过 {fail_limit} 人 → 该次模拟失败；"
        f"每个 n 跑 {len(seeds)} 个种子，失败 **≥3 次** 判定该算法扛不住这个 n。")
    add("")

    add("## 一、按题目阶梯：n = 1 / 2 / 4 / 8 / 16 人每秒")
    add("")
    add("结果很直接：**所有算法在 n=1 就超载了**。4 部电梯的运力约 0.4 人/秒"
        "（≈1400 人/小时），而 n=1 相当于 3600 人/小时，是运力的 2.5 倍。"
        "所以这一档只能比“谁撑得久”——表里是平均坚持到超载的秒数。")
    add("")
    rows = []
    for key in keys:
        rows.append([ALGORITHMS_BY_KEY[key].label] +
                    [f"{main_summary[(key, r)]['fail_time']:.0f}" for r in main_rates])
    add(markdown_table(["算法"] + [f"n={_fmt_rate(r)}" for r in main_rates], rows,
                       aligns=["left"] + ["---:"] * len(main_rates)))
    add("")

    add("## 二、细分阶梯：0.5 ~ 0.125 人/秒（每 2~8 秒 1 人）")
    add("")
    add("真正的容量分界线在这里。表格是**人均交通时间**（秒，越小越好），"
        "`失败 k` 表示 5 个种子里有 k 次超载。")
    add("")
    rows = []
    for key in keys:
        cells = []
        for r in fine_rates:
            item = fine_summary[(key, r)]
            cells.append(f"失败 {item['fails']}/5" if item["fails"] >= 3
                         else f"{item['avg_total']:.0f}" + (f" *{item['fails']}" if item["fails"] else ""))
        rows.append([ALGORITHMS_BY_KEY[key].label] + cells)
    add(markdown_table(["算法"] + [f"{_fmt_rate(r)} 人/秒" for r in fine_rates], rows))
    add("")
    if "avg_total" in charts:
        add(f"![人均交通时间]({charts['avg_total'].relative_to(path.parent).as_posix()})")
        add("")

    add("## 三、完成率")
    add("")
    add(f"{duration} s 内送到的比例。冻结时**没送到的人被剔除**，"
        "所以完成率越低，人均交通时间越“挑过”——要和这张表一起看。")
    add("")
    rows = []
    for key in keys:
        cells = []
        for r in fine_rates:
            item = fine_summary[(key, r)]
            cells.append("—" if item["fails"] >= 3 else f"{item['completion'] * 100:.0f}%")
        rows.append([ALGORITHMS_BY_KEY[key].label] + cells)
    add(markdown_table(["算法"] + [f"{_fmt_rate(r)}" for r in fine_rates], rows))
    add("")

    add("## 四、容量上限")
    add("")
    add("规则：5 个种子里失败不超过 2 次。")
    add("")
    rows = []
    for key in keys:
        rate = capacity_of(fine_summary, key, fine_rates)
        rows.append([ALGORITHMS_BY_KEY[key].label,
                     f"{rate:g} 人/秒" if rate else "低于 0.125",
                     f"{rate * 3600:.0f} 人/小时" if rate else "—"])
    add(markdown_table(["算法", "最大可持续到达速率", "折算"], rows))
    add("")
    if "capacity" in charts:
        add(f"![容量上限]({charts['capacity'].relative_to(path.parent).as_posix()})")
        add("")

    add("## 五、结论")
    add("")
    top = max(capacity_of(fine_summary, k, fine_rates) for k in keys)
    winners = [ALGORITHMS_BY_KEY[k].label for k in keys
               if capacity_of(fine_summary, k, fine_rates) == top]
    light = min(keys, key=lambda k: fine_summary[(k, fine_rates[-1])]["avg_total"])
    add(f"* 容量最高的（{top:g} 人/秒 ≈ {top * 3600:.0f} 人/小时）：**"
        + "、".join(winners) + "**。")
    add(f"* 最低负载（{fine_rates[-1]:g} 人/秒）下人均交通时间最短的是 "
        f"**{ALGORITHMS_BY_KEY[light].label}**"
        f"（{fine_summary[(light, fine_rates[-1])]['avg_total']:.0f} s）。")
    add("* 人均交通时间随负载上升而变长：低负载时大家都差不多，"
        "接近容量上限时才拉开差距。")
    add("")
    add("完整分析见 README.md。")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_capacity_csv(path: Path, rows: Sequence[dict]) -> None:
    fields = ["algo_key", "rate", "seed", "passengers", "completed", "completion_rate",
              "avg_total", "avg_wait", "avg_ride", "p90_total", "max_floor_waiting",
              "failed", "fail_time"]
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore", restval="")
        writer.writeheader()
        writer.writerows(rows)


# ---------------------------------------------------------------- 主流程


def run_capacity_benchmark(
    main_rates: Sequence[float] = RATES_MAIN,
    fine_rates: Sequence[float] = RATES_FINE,
    seeds: Sequence[int] = SEEDS,
    duration: int = DURATION,
    fail_limit: int = FAIL_LIMIT,
    info: str = "destination",
    cars: int = CARS,
    make_charts: bool = True,
    verbose: bool = True,
) -> dict:
    keys = [k for k in ORDER if k != "original"]
    if info == "hall":
        keys = [k for k in keys if k not in DESTINATION_ONLY]
    else:
        keys = [k for k in keys if k not in HALL_ONLY]

    kwargs = dict(duration=duration, fail_limit=fail_limit, info=info)
    main_rows = run_ladder(main_rates, seeds, keys, verbose=verbose, tag="主阶梯·", **kwargs)
    fine_rows = run_ladder(fine_rates, seeds, keys, verbose=verbose, tag="细分·", **kwargs)
    rows = main_rows + fine_rows

    main_summary = summarize(main_rows, main_rates)
    fine_summary = summarize(fine_rows, fine_rates)

    suffix = "" if info == "destination" else f"_{info}"
    csv_path = BASE_DIR / f"results_capacity{suffix}.csv"
    report_path = BASE_DIR / f"report_capacity{suffix}.md"
    chart_dir = BASE_DIR / f"charts_capacity{suffix}"
    write_capacity_csv(csv_path, rows)

    charts: dict[str, Path] = {}
    if make_charts:
        try:
            from .charts import grouped_bar_chart
        except Exception:  # pragma: no cover
            grouped_bar_chart = None
        if grouped_bar_chart is not None:
            palette = ["#c6dbef", "#9ecae1", "#6baed6", "#4292c6", "#08519c", "#08306b"]
            grouped_bar_chart(
                chart_dir / "avg_total.png",
                [SHORT_LABELS[k] for k in keys],
                {f"{1 / r:g} 秒/人":
                 [fine_summary[(k, r)]["avg_total"] if fine_summary[(k, r)]["fails"] < 3 else 0
                  for k in keys]
                 for r in fine_rates},
                title="人均交通时间 · 4 部电梯",
                ylabel="秒",
                palette=palette,
                skip_zero=True,
            )
            charts["avg_total"] = chart_dir / "avg_total.png"
            grouped_bar_chart(
                chart_dir / "capacity.png",
                [SHORT_LABELS[k] for k in keys],
                {"容量上限（人/小时）": [capacity_of(fine_summary, k, fine_rates) * 3600 for k in keys]},
                title="容量上限 · 4 部电梯（失败 ≤2/5）",
                ylabel="人/小时",
                palette=["#4292c6"],
            )
            charts["capacity"] = chart_dir / "capacity.png"
            if verbose:
                print(f"已生成图表到 {chart_dir.name}/")

    write_capacity_report(report_path, main_summary, fine_summary, main_rates, fine_rates,
                          seeds, duration, fail_limit, info, charts)
    if verbose:
        print(f"已写入 {report_path.name} / {csv_path.name}")
    return {"main": main_summary, "fine": fine_summary, "rows": rows,
            "charts": charts, "main_rates": main_rates, "fine_rates": fine_rates}


# ================================================================ 场景 H（摩天楼版）
#: 100 层、4 倍速、14400 s，四档低速率（0.33 实际取 1/3）
RATES_H = (1 / 3, 0.25, 0.2, 0.125)
DURATION_H = 14400
FLOORS_H = 100


def _rate_label(rate: float) -> str:
    if abs(rate - 1 / 3) < 1e-9:
        return "1/3"
    return f"{rate:g}"


def write_capacity100_report(
    path: Path,
    summary: dict,
    rates: Sequence[float],
    seeds: Sequence[int],
    duration: int,
    fail_limit: int,
    info: str,
    charts: dict[str, Path],
) -> None:
    keys = [k for k in ORDER if (k, rates[0]) in summary]
    lines: list[str] = []
    add = lines.append

    add("# 容量阶梯 · 摩天楼（100 层、4 倍速、4 部电梯） · " + INFO_MODELS[info]["label"])
    add("")
    add(f"> 自动生成于 {time.strftime('%Y-%m-%d %H:%M:%S')}。"
        f"每秒平均刷出 n 名乘客（起点/终点全楼随机），4 部电梯初始停在随机楼层，"
        f"连续运行 **{duration} s** 后冻结；只统计已经到达的乘客，"
        f"指标是**人均交通时间**（按下按钮 → 走出电梯）。")
    add("")
    add(f"**超载判定**：任一层候梯超过 {fail_limit} 人 → 该次模拟失败；"
        f"每个 n 跑 {len(seeds)} 个种子，失败 **≥3 次** 判定该算法扛不住这个 n。")
    add("")

    add("## 一、人均交通时间")
    add("")
    add("单位秒，越小越好。`失败 k` 表示 5 个种子里有 k 次单层积压超过 40 人。")
    add("")
    rows = []
    for key in keys:
        cells = []
        for r in rates:
            item = summary[(key, r)]
            cells.append(f"失败 {item['fails']}/5" if item["fails"] >= 3
                         else f"{item['avg_total']:.0f}" + (f" *{item['fails']}" if item["fails"] else ""))
        rows.append([ALGORITHMS_BY_KEY[key].label] + cells)
    add(markdown_table(["算法"] + [f"{_rate_label(r)} 人/秒" for r in rates], rows))
    add("")
    if "avg_total" in charts:
        add(f"![人均交通时间]({charts['avg_total'].relative_to(path.parent).as_posix()})")
        add("")

    add("## 二、完成率")
    add("")
    add(f"{duration} s 内送到的比例。冻结时没送到的人被剔除，所以要和人均时间一起看。")
    add("")
    rows = []
    for key in keys:
        cells = []
        for r in rates:
            item = summary[(key, r)]
            cells.append("—" if item["fails"] >= 3 else f"{item['completion'] * 100:.0f}%")
        rows.append([ALGORITHMS_BY_KEY[key].label] + cells)
    add(markdown_table(["算法"] + [f"{_rate_label(r)}" for r in rates], rows))
    add("")

    add("## 三、容量上限")
    add("")
    add("规则：5 个种子里失败不超过 2 次。")
    add("")
    rows = []
    for key in keys:
        rate = capacity_of(summary, key, rates)
        good = quality_capacity(summary, key, rates)
        rows.append([ALGORITHMS_BY_KEY[key].label,
                     f"{_rate_label(rate)} 人/秒" if rate else "低于 0.125",
                     f"{rate * 3600:.0f} 人/小时" if rate else "—",
                     f"{_rate_label(good)} 人/秒" if good else "低于 0.125"])
    add(markdown_table(["算法", "超载线（失败 ≤2/5）", "折算", "体面运力（完成率 ≥90%）"], rows))
    add("")
    add("> **为什么要两列**：100 层楼里需求摊得很开，"
        "「某层积压 40 人」很难触发——1/3 人/秒时 LOOK 只送走 73%，"
        "却一次都没判超载。")
    add("")
    if "capacity" in charts:
        add(f"![容量上限]({charts['capacity'].relative_to(path.parent).as_posix()})")
        add("")

    add("## 四、结论")
    add("")
    top = max(quality_capacity(summary, k, rates) for k in keys)
    winners = [ALGORITHMS_BY_KEY[k].label for k in keys
               if quality_capacity(summary, k, rates) == top]
    light = min(keys, key=lambda k: summary[(k, rates[-1])]["avg_total"])
    add(f"* 体面运力最高（完成率 ≥90%，{_rate_label(top)} 人/秒 ≈ {top * 3600:.0f} 人/小时）：**"
        + "、".join(winners) + "**。")
    add("* 超载线（失败 ≤2/5）几乎都是 1/3 人/秒（只有目的层分区/分组是 0.25），"
        "说明这个判据在 100 层楼里偏宽松，真正的差别要看完成率和人均时间。")
    add(f"* 最低负载（{_rate_label(rates[-1])} 人/秒）下人均交通时间最短的是 "
        f"**{ALGORITHMS_BY_KEY[light].label}**"
        f"（{summary[(light, rates[-1])]['avg_total']:.0f} s）。")
    add("* 人均交通时间随负载上升而变长；100 层、4 倍速下，单程时间被放大，"
        "但排名与 20 层版一致（见 README 第 10 节）。")
    add("")
    add("完整分析见 README.md。")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_capacity100_benchmark(
    rates: Sequence[float] = RATES_H,
    seeds: Sequence[int] = SEEDS,
    duration: int = DURATION_H,
    fail_limit: int = FAIL_LIMIT,
    info: str = "destination",
    cars: int = CARS,
    make_charts: bool = True,
    verbose: bool = True,
) -> dict:
    keys = [k for k in ORDER if k != "original"]
    if info == "hall":
        keys = [k for k in keys if k not in DESTINATION_ONLY]
    else:
        keys = [k for k in keys if k not in HALL_ONLY]

    rows = run_ladder(rates, seeds, keys, duration=duration, fail_limit=fail_limit,
                      info=info, verbose=verbose, floors=FLOORS_H,
                      timing=SkyscraperTiming())
    summary = summarize(rows, rates)

    suffix = "" if info == "destination" else f"_{info}"
    csv_path = BASE_DIR / f"results_capacity100{suffix}.csv"
    report_path = BASE_DIR / f"report_capacity100{suffix}.md"
    chart_dir = BASE_DIR / f"charts_capacity100{suffix}"
    write_capacity_csv(csv_path, rows)

    charts: dict[str, Path] = {}
    if make_charts:
        try:
            from .charts import grouped_bar_chart
        except Exception:  # pragma: no cover
            grouped_bar_chart = None
        if grouped_bar_chart is not None:
            palette = ["#c6dbef", "#9ecae1", "#6baed6", "#4292c6", "#08519c", "#08306b"]
            grouped_bar_chart(
                chart_dir / "avg_total.png",
                [SHORT_LABELS[k] for k in keys],
                {f"{_rate_label(r)} 人/秒": [summary[(k, r)]["avg_total"]
                                             if summary[(k, r)]["fails"] < 3 else 0
                                             for k in keys] for r in rates},
                title="人均交通时间 · 100 层 / 4 部电梯",
                ylabel="秒",
                palette=palette,
                skip_zero=True,
            )
            charts["avg_total"] = chart_dir / "avg_total.png"
            grouped_bar_chart(
                chart_dir / "capacity.png",
                [SHORT_LABELS[k] for k in keys],
                {"容量上限（人/小时）": [capacity_of(summary, k, rates) * 3600 for k in keys]},
                title="容量上限 · 100 层 / 4 部电梯",
                ylabel="人/小时",
                palette=["#4292c6"],
            )
            charts["capacity"] = chart_dir / "capacity.png"
            if verbose:
                print(f"已生成图表到 {chart_dir.name}/")

    write_capacity100_report(report_path, summary, rates, seeds, duration,
                             fail_limit, info, charts)
    if verbose:
        print(f"已写入 {report_path.name} / {csv_path.name}")
    return {"summary": summary, "rows": rows, "rates": rates, "charts": charts}


def print_capacity100(summary: dict, rates: Sequence[float]) -> None:
    keys = [k for k in ORDER if (k, rates[0]) in summary]
    print("\n【人均交通时间】100 层 / 4 倍速 / 4 部电梯（秒，越小越好）")
    rows = []
    for key in keys:
        cells = []
        for r in rates:
            item = summary[(key, r)]
            cells.append(f"失败{item['fails']}/5" if item["fails"] >= 3
                         else f"{item['avg_total']:.0f}")
        rows.append([ALGORITHMS_BY_KEY[key].label] + cells)
    print(render_table(["算法"] + [f"{_rate_label(r)} 人/秒" for r in rates], rows))

    print("\n【容量上限】超载线（失败 ≤2/5）与体面运力（完成率 ≥90% 且失败 ≤2/5）")
    rows = []
    for key in keys:
        rate = capacity_of(summary, key, rates)
        good = quality_capacity(summary, key, rates)
        rows.append([ALGORITHMS_BY_KEY[key].label,
                     f"{_rate_label(rate)} 人/秒" if rate else "低于 0.125",
                     f"{_rate_label(good)} 人/秒" if good else "低于 0.125"])
    print(render_table(["算法", "超载线", "体面运力"], rows))
