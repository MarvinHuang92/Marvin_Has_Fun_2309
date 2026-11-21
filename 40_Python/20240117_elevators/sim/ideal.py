"""理想人均交通时间：单人、无其他乘客、无中途停靠的理论下限。

场景：一名乘客随机出现在某一层（1..N），目的地是另一随机层（≠起点的均匀分布），
k 部电梯初始位置各自独立均匀随机。全程只有"来接你"和"送你"两段行程、
两次停靠。

于是

    理想人均时间 = E[ travel(最近电梯到你的距离) ]
                 + E[ travel(起点到终点的距离) ]
                 + 两次停靠的固定开销

固定开销按模型算：接人 = 开门 2 + 上下客 2 + 关门 2 = 6 s；
送达 = 开门 2 + 上下客 2 = 4 s（乘客走出电梯后不再等关门）。
合计 **10 s**，与楼层数无关。
"""

from __future__ import annotations

import random
from itertools import product

from .model import MAX_FLOOR, Timing, make_timing

#: 一次接人 + 一次送人的固定开销（秒）
STOP_OVERHEAD = 10


def _trip_distribution(floors: int) -> dict[int, float]:
    """起点≠终点的均匀分布下，|起点-终点| = m 的概率。"""
    total = floors * (floors - 1)
    return {m: 2 * (floors - m) / total for m in range(1, floors)}


def _nearest_car_distribution(floors: int, cars: int) -> dict[int, float]:
    """k 部电梯随机停放时，"最近一辆到你的距离"的分布（0..floors-1）。"""
    if cars <= 0:
        raise ValueError("至少 1 部电梯")
    # 精确枚举：只要求出 P(最近距离 ≥ d)，再差分。
    dist: dict[int, float] = {d: 0.0 for d in range(floors)}
    for o in range(1, floors + 1):
        # 固定 o 时，单部电梯"距离 ≥ d"的概率（用于求最小值的分布）
        # P(min ≥ d) = (P(|o-p| ≥ d))^k
        for d in range(floors):
            far = sum(1 for p in range(1, floors + 1) if abs(o - p) >= d) / floors
            p_min_ge_d = far ** cars
            # 累加：P(min = d) = P(min ≥ d) - P(min ≥ d+1)
            far_next = sum(1 for p in range(1, floors + 1) if abs(o - p) >= d + 1) / floors
            p_min_ge_next = far_next ** cars
            dist[d] += (p_min_ge_d - p_min_ge_next) / floors
    return dist


def expected(floors: int, cars: int, timing: Timing | None = None,
             include_stops: bool = True) -> dict:
    """解析计算理想值（精确枚举，无采样误差）。"""
    timing = timing or Timing()
    trip = _trip_distribution(floors)
    near = _nearest_car_distribution(floors, cars)

    wait = sum(prob * timing.travel(d) for d, prob in near.items())
    ride = sum(prob * timing.travel(m) for m, prob in trip.items())
    overhead = STOP_OVERHEAD if include_stops else 0

    return {
        "floors": floors,
        "cars": cars,
        "wait": wait,
        "ride": ride,
        "overhead": overhead,
        "total": wait + ride + overhead,
        "mean_pickup_distance": sum(d * p for d, p in near.items()),
        "mean_trip_distance": sum(m * p for m, p in trip.items()),
    }


def simulate(floors: int, cars: int, timing: Timing, trials: int = 5000, seed: int = 1) -> dict:
    """用真正的仿真器做蒙特卡洛校验（单人、无其他乘客）。"""
    from .dispatch import build_dispatcher
    from .model import Elevator, Passenger, World

    rng = random.Random(seed)
    totals = []
    for _ in range(trials):
        origin = rng.randint(1, floors)
        target = rng.randint(1, floors - 1)
        if target >= origin:
            target += 1
        lifts = [Elevator(eid=i + 1, floor=rng.randint(1, floors)) for i in range(cars)]
        world = World(
            [Passenger(0, origin, target)],
            lifts,
            build_dispatcher("look"),
            timing=timing,
            max_floor=floors,
        )
        totals.append(world.run()["avg_total"])
    return {
        "floors": floors,
        "cars": cars,
        "total": sum(totals) / len(totals),
        "trials": trials,
    }


def table(floors_list=(20, 100), cars_list=(1, 2, 4)) -> list[dict]:
    rows = []
    for floors in floors_list:
        timing = make_timing("normal" if floors <= 20 else "skyscraper")
        for cars in cars_list:
            rows.append(expected(floors, cars, timing))
    return rows


def main() -> int:
    print("理想人均交通时间（单人、无其他乘客、无中途停靠）")
    print(f"{'楼层':>4}  {'电梯':>4}  {'期望等车':>8}  {'期望乘梯':>8}  "
          f"{'停靠开销':>8}  {'合计':>8}  {'平均接驾距离':>10}  {'平均行程':>8}")
    for row in table():
        print(f"{row['floors']:>4}  {row['cars']:>4}  {row['wait']:>8.1f}  "
              f"{row['ride']:>8.1f}  {row['overhead']:>8.0f}  {row['total']:>8.1f}  "
              f"{row['mean_pickup_distance']:>10.2f}  {row['mean_trip_distance']:>8.2f}")
    print("\n蒙特卡洛校验（仿真器实跑 5000 次）：")
    for floors, profile in ((20, "normal"), (100, "skyscraper")):
        timing = make_timing(profile)
        for cars in (1, 2, 4):
            sim = simulate(floors, cars, timing, trials=2000, seed=7)
            exact = expected(floors, cars, timing)["total"]
            print(f"  {floors} 层 / {cars} 部：仿真 {sim['total']:.1f}s vs 解析 {exact:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
