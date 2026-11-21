"""电梯调度仿真的核心模型：时间、乘客、电梯、世界。

时间模型（单位：秒，全部是整数，仿真逐秒推进）
------------------------------------------------
    全速通过一层            1 s
    起步 → 停稳的固定代价     4 s（含第一层位移，所以 1→2 一共 4 s）
    跨越 n 层               n=1: 4 s，n=2: 6 s，n=3: 7 s，n>=2: 4+n s
    开门 / 关门             各 2 s
    上下客                  每人 1 s，最少 2 s

与给定的三个观测点（1→2 用 4 s、1→3 用 6 s、1→4 用 7 s）完全一致；
20 层直达是 24 s。若想换一套"体感"，只改 Timing 里的几个数字即可。

建模约定
--------
* 电梯只在"有人要上或有人要下"的楼层开门（原程序是每层都开），
  这是本轮改造的核心：跳层。
* 一辆空车（车厢里没人）可以接任意方向的乘客，并按第一位上车乘客
  的方向确定行驶方向；车厢里有乘客时，只接同方向的候梯者——
  这就是现实里的"顺向截梯"，避免把上行乘客塞进下行电梯。
* 时间步长 = 1 秒。所有动作都落在整数秒上，事件时刻是精确的。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# ---------------------------------------------------------------- 常量

MIN_FLOOR = 1
MAX_FLOOR = 100          # 摩天楼场景用它做默认上限；普通场景按 20 层传参
CAPACITY = 8

# 电梯动作阶段
IDLE = "idle"
MOVING = "moving"
OPENING = "opening"
BOARDING = "boarding"
CLOSING = "closing"


class SimulationError(RuntimeError):
    """仿真跑不出结果（死锁、超时等）。"""


# ---------------------------------------------------------------- 时间模型


class Timing:
    """秒级时间模型。所有参数都能改，改完整个仿真立刻生效。"""

    def __init__(
        self,
        start_stop: int = 4,      # 起步→停稳固定代价（含第一层位移）
        floor_time: int = 1,      # 全速通过一层
        door_open: int = 2,
        door_close: int = 2,
        per_passenger: int = 1,
        min_transfer: int = 2,
    ) -> None:
        self.start_stop = start_stop
        self.floor_time = floor_time
        self.door_open = door_open
        self.door_close = door_close
        self.per_passenger = per_passenger
        self.min_transfer = min_transfer

    def travel(self, floors: int) -> int:
        """从静止到静止、跨越 ``floors`` 层所需秒数。"""
        if floors <= 0:
            return 0
        if floors == 1:
            return self.start_stop
        return self.start_stop + floors * self.floor_time

    def transfer(self, people: int) -> int:
        """上下客耗时：每人 1 秒，最少 2 秒。"""
        return max(self.min_transfer, people * self.per_passenger)

    def stop_cost(self, people: int) -> int:
        """一次停靠的总耗时：开门 + 上下客 + 关门。"""
        return self.door_open + self.transfer(people) + self.door_close


class SkyscraperTiming(Timing):
    """100 层摩天楼：最高速度是原来的 4 倍，但按 1 秒颗粒取整。

    分段（中间不停站）::

        1 层      4 s
        2~3 层    6 s
        4~7 层    7 s
        8~11 层   8 s
        12~15 层  9 s
        ...       每 4 层 +1 s，100 层直达 31 s
    """

    def travel(self, floors: int) -> int:
        if floors <= 0:
            return 0
        if floors == 1:
            return 4
        if floors <= 3:
            return 6
        return 7 + (floors - 4) // 4


#: 按名字取时间模型
def make_timing(profile: str = "normal") -> Timing:
    if profile == "skyscraper":
        return SkyscraperTiming()
    return Timing()


# ---------------------------------------------------------------- 乘客


@dataclass(eq=False)
class Passenger:
    """一名乘客。只用编号，不再用人名。"""

    pid: int
    origin: int
    target: int
    request_time: int = 0
    board_time: Optional[int] = None
    alight_time: Optional[int] = None
    car_id: Optional[int] = None
    assigned_car: Optional[int] = None

    @property
    def direction(self) -> int:
        """+1 向上，-1 向下。"""
        return 1 if self.target > self.origin else -1

    @property
    def is_waiting(self) -> bool:
        return self.board_time is None

    @property
    def is_riding(self) -> bool:
        return self.board_time is not None and self.alight_time is None

    @property
    def is_done(self) -> bool:
        return self.alight_time is not None

    @property
    def wait(self) -> int:
        return 0 if self.board_time is None else self.board_time - self.request_time

    @property
    def ride(self) -> int:
        if self.board_time is None or self.alight_time is None:
            return 0
        return self.alight_time - self.board_time

    @property
    def total(self) -> int:
        if self.alight_time is None:
            return 0
        return self.alight_time - self.request_time

    def __str__(self) -> str:  # 便于调试
        return f"#{self.pid}({self.origin}→{self.target})"


# ---------------------------------------------------------------- 电梯


class Elevator:
    """一辆电梯：一个很小的状态机。

    每个"秒"调用一次 :meth:`update`：

    * IDLE     —— 问调度器下一站去哪；没活就待命
    * MOVING   —— 倒计时走完若干层
    * OPENING  —— 门开 2 s
    * BOARDING —— 上下客（每人 1 s，最少 2 s）
    * CLOSING  —— 门关 2 s
    """

    def __init__(self, eid: int, floor: int = MIN_FLOOR, capacity: int = CAPACITY,
                 min_floor: int = MIN_FLOOR, max_floor: int = MAX_FLOOR) -> None:
        self.eid = eid
        self.floor = floor
        self.capacity = capacity
        self.min_floor = min_floor
        self.max_floor = max_floor
        self.timing: Optional[Timing] = None
        self.riders: list[Passenger] = []
        self.direction = 0                 # +1 上 / -1 下 / 0 待命
        self.phase = IDLE
        self.due = 0                       # 当前动作的完成时刻
        self.dest = floor
        # 统计
        self.stops = 0
        self.floors_travelled = 0
        self.door_seconds = 0
        self.idle_seconds = 0
        self.boards = 0
        self.alights = 0
        #: 上一次"空停"的楼层（没人上下）。用于避免反复空开门。
        self.blank_stop_floor: Optional[int] = None

    # ---------------------------------------------------------- 基本属性

    @property
    def name(self) -> str:
        return f"{self.eid}号梯"

    @property
    def load(self) -> int:
        return len(self.riders)

    @property
    def is_empty(self) -> bool:
        return not self.riders

    def direction_arrow(self) -> str:
        return {1: "↑", -1: "↓", 0: "·"}[self.direction]

    # ---------------------------------------------------------- 主循环

    def update(self, now: int, world: "World") -> None:
        """推进一秒。"""
        for _ in range(32):  # 防御：状态机不允许在同一秒里无限自转
            if self.phase == IDLE:
                stop = world.dispatcher.next_stop(self, world, now)
                if stop is None:
                    self.idle_seconds += 1
                    return
                self._begin(stop, now, world)
                continue
            if now < self.due:
                return
            self._finish(self.due, world)
        raise SimulationError(f"{self.name} 状态机在同一秒内没有收敛")

    # ---------------------------------------------------------- 阶段切换

    def _begin(self, stop: int, now: int, world: "World") -> None:
        timing = self.timing
        assert timing is not None
        if stop == self.floor:
            # 就在本层上客
            self.dest = stop
            self.stops += 1
            self.phase = OPENING
            self.due = now + timing.door_open
            self.direction = self.direction or world.planned_direction(self, stop)
            world.log(f"{self.name} 在{stop}F 开门")
            return

        distance = abs(stop - self.floor)
        self.direction = 1 if stop > self.floor else -1
        self.dest = stop
        self.blank_stop_floor = None
        self.floors_travelled += distance
        self.phase = MOVING
        self.due = now + timing.travel(distance)
        world.log(f"{self.name} {self.floor}F→{stop}F 发车，{distance}层约{self.due - now}s")

    def _finish(self, now: int, world: "World") -> None:
        timing = self.timing
        assert timing is not None

        if self.phase == MOVING:
            self.floor = self.dest
            self.stops += 1
            self.phase = OPENING
            self.due = now + timing.door_open
            world.log(f"{self.name} 到达{self.floor}F")
            return

        if self.phase == OPENING:
            self._doors_open(now, world)
            return

        if self.phase == BOARDING:
            self.phase = CLOSING
            self.due = now + timing.door_close
            return

        if self.phase == CLOSING:
            self.phase = IDLE
            self.due = now
            world.log(f"{self.name} 在{self.floor}F 关门，{self.load}人")
            return

        raise SimulationError(f"未知阶段 {self.phase}")

    # ---------------------------------------------------------- 上下客

    def _doors_open(self, now: int, world: "World") -> None:
        timing = self.timing
        assert timing is not None

        alighting = [p for p in self.riders if p.target == self.floor]
        for p in alighting:
            self.riders.remove(p)

        boarding: list[Passenger] = []
        for p in world.waiting_at(self.floor):
            if len(self.riders) + len(boarding) >= self.capacity:
                break
            if not world.dispatcher.accepts(self, p):
                continue
            if not world.dispatcher.may_board(self, p):
                continue
            boarding.append(p)

        seconds = timing.transfer(len(alighting) + len(boarding))
        end = now + seconds

        for p in alighting:
            p.alight_time = end
            p.car_id = self.eid
            self.alights += 1
            world.dispatcher.note_alight(self, p)
        for p in boarding:
            p.board_time = end
            p.car_id = self.eid
            self.riders.append(p)
            self.boards += 1
            world.note_boarded(p)
            world.dispatcher.note_board(self, p)

        if boarding and self.load == len(boarding):
            # 刚才还是空车：以第一位乘客的方向为准
            self.direction = boarding[0].direction

        self.door_seconds += timing.door_open + seconds + timing.door_close
        if alighting or boarding:
            world.note_progress(now)
            world.log(
                f"{self.name} {self.floor}F 上{len(boarding)}人 / 下{len(alighting)}人，"
                f"车内{self.load}人（{seconds}s）"
            )
        else:
            self.blank_stop_floor = self.floor
            world.log(f"{self.name} {self.floor}F 空停（{seconds}s）")

        self.phase = BOARDING
        self.due = end

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Elevator {self.eid} @{self.floor}F {self.direction_arrow()} {self.load}人>"


# ---------------------------------------------------------------- 世界


class World:
    """一次仿真运行：100 名乘客、若干电梯、一个调度器。"""

    def __init__(
        self,
        passengers: list[Passenger],
        cars: list[Elevator],
        dispatcher,
        timing: Optional[Timing] = None,
        max_time: int = 20000,
        stall_timeout: int = 1800,
        trace: bool = False,
        info_model: str = "destination",
        duration: Optional[int] = None,
        spawner=None,
        fail_waiting_limit: Optional[int] = None,
        max_floor: int = MAX_FLOOR,
        min_floor: int = MIN_FLOOR,
    ) -> None:
        self.passengers = passengers
        self.cars = cars
        self.dispatcher = dispatcher
        self.timing = timing or Timing()
        self.max_time = max_time
        self.stall_timeout = stall_timeout
        self.trace = trace
        #: "destination" = 乘客在进电梯前就表达了目的层（20 按钮 / 触摸屏）
        #: "hall"        = 只能表达"上楼/下楼"（电梯外只有两个按钮）
        self.info_model = info_model
        #: 固定运行时长（秒）。设了就不再等"全部送完"，到点冻结。
        self.max_floor = max_floor
        self.min_floor = min_floor
        self.duration = duration
        #: 每秒生成新乘客的函数 ``(now) -> list[Passenger]``。
        self.spawner = spawner
        #: 任一层候梯人数超过这个值就判定超载（场景 4 用）。
        self.fail_waiting_limit = fail_waiting_limit
        self.failed = False
        self.fail_time: Optional[int] = None
        self.fail_floor: Optional[int] = None
        self.peak_waiting = 0
        self.now = 0
        self.finish_time: Optional[int] = None
        self.last_progress = 0
        self.events: list[str] = []

        # 候梯索引：按楼层 + 全量，避免每次调度都扫描所有乘客
        self._waiting_all: list[Passenger] = []
        self._waiting_by_floor: dict[int, list[Passenger]] = {}
        # 未到场的乘客按到达时刻分桶
        self._arrivals: dict[int, list[Passenger]] = {}
        for p in passengers:
            self._arrivals.setdefault(p.request_time, []).append(p)

        for car in cars:
            car.timing = self.timing
            car.min_floor = min_floor
            car.max_floor = max_floor
            car.floor = max(min_floor, min(max_floor, car.floor))
        # 调度器在 run() 里、第一秒的乘客进场之后再初始化，
        # 这样它看到的"初始客流"和真实世界一致（而不是空的）。
        self._attached = False

    # ---------------------------------------------------------- 查询

    def waiting(self) -> list[Passenger]:
        """此刻真正在候梯的人（还没到场的乘客不在索引里）。"""
        return self._waiting_all

    def waiting_at(self, floor: int) -> list[Passenger]:
        return self._waiting_by_floor.get(floor, ())

    def parked_waiting(self) -> int:
        """任一层楼候梯人数的最大值。"""
        return max((len(v) for v in self._waiting_by_floor.values()), default=0)

    def _activate(self, p: Passenger) -> None:
        self._waiting_all.append(p)
        self._waiting_by_floor.setdefault(p.origin, []).append(p)

    def note_boarded(self, p: Passenger) -> None:
        """乘客上车后从候梯索引里摘掉。"""
        try:
            self._waiting_all.remove(p)
        except ValueError:
            pass
        bucket = self._waiting_by_floor.get(p.origin)
        if bucket is not None:
            try:
                bucket.remove(p)
            except ValueError:
                pass

    def unfinished(self) -> list[Passenger]:
        return [p for p in self.passengers if not p.is_done]

    def done(self) -> bool:
        return all(p.is_done for p in self.passengers)

    def has_demand(self) -> bool:
        return bool(self.waiting()) or any(c.riders for c in self.cars)

    @property
    def delivered(self) -> int:
        return sum(1 for p in self.passengers if p.is_done)

    def planned_direction(self, car: Elevator, stop: int) -> int:
        """本层停靠（没有位移）时，该往哪个方向接人。"""
        if stop > car.floor:
            return 1
        if stop < car.floor:
            return -1
        for p in self.waiting_at(car.floor):
            if self.dispatcher.accepts(car, p):
                return p.direction
        return car.direction or 1

    # ---------------------------------------------------------- 日志

    def log(self, message: str) -> None:
        if self.trace:
            self.events.append(f"[t={self.now:>4}] {message}")

    def note_progress(self, now: int) -> None:
        self.last_progress = now

    # ---------------------------------------------------------- 主循环

    def run(self, verbose: bool = False) -> dict:
        if verbose:
            self._print_header()
        # 有 duration 就跑到点冻结；否则跑到全部送完
        end_time = self.duration if self.duration is not None else self.max_time

        while self.now < end_time:
            # ① 本秒开始时，已到场的乘客进入候梯池（乘客先按按钮，电梯再动作）
            for p in self._arrivals.pop(self.now, ()):
                self._activate(p)
            if self.spawner is not None:
                for p in self.spawner(self.now):
                    self.passengers.append(p)
                    self._activate(p)

            if not self._attached:
                self.dispatcher.attach(self)
                self._attached = True

            # ② 超载判定：任一层候梯人数超过阈值
            if self.fail_waiting_limit is not None:
                peak = self.parked_waiting()
                if peak > self.peak_waiting:
                    self.peak_waiting = peak
                if peak > self.fail_waiting_limit:
                    self.failed = True
                    self.fail_time = self.now
                    self.fail_floor = max(
                        self._waiting_by_floor,
                        key=lambda f: len(self._waiting_by_floor[f]),
                    )
                    break

            # ③ 没有时长限制时，全员送达即结束
            if self.duration is None and self.done():
                break

            # ④ 电梯动作
            for car in self.cars:
                car.update(self.now, self)

            if verbose and self.now and self.now % 30 == 0:
                self._print_progress()

            self.now += 1

            # ⑤ 死锁检测只对"必须全部送完"的场景有意义
            if self.duration is None:
                if (self.delivered < len(self.passengers)
                        and self.now - self.last_progress > self.stall_timeout):
                    raise SimulationError(
                        f"疑似死锁：{self.stall_timeout}s 内没有任何乘客送达"
                        f"（完成 {self.delivered}/{len(self.passengers)}）"
                    )

        if self.duration is None and not self.done() and not self.failed:
            raise SimulationError(
                f"仿真超过 {self.max_time}s 仍未完成（完成 {self.delivered}/{len(self.passengers)}）"
            )
        self.finish_time = self.now
        return self.stats()

    def _print_header(self) -> None:
        print(f"仿真开始：{len(self.passengers)} 名乘客，{len(self.cars)} 部电梯，"
              f"调度算法 = {self.dispatcher.label}")
        print(f"时间模型：1 层 4s / 2 层 6s / n>=2 层 n+4s；开门关门各 2s；"
              f"上下客每人 1s（最少 2s）")

    def _print_progress(self) -> None:
        riding = sum(c.load for c in self.cars)
        print(
            f"[t={self.now:>4}s] 送达 {self.delivered:>3}/{len(self.passengers)}"
            f"，在梯 {riding}，候梯 {len(self.waiting())}"
            + "｜" + "  ".join(
                f"{c.name}@{c.floor}F{c.direction_arrow()}({c.load})" for c in self.cars
            )
        )

    # ---------------------------------------------------------- 统计

    def stats(self) -> dict:
        done = [p for p in self.passengers if p.is_done]
        totals = sorted(p.total for p in done)
        waits = [p.wait for p in done]
        rides = [p.ride for p in done]

        def mean(values):
            return sum(values) / len(values) if values else float("nan")

        def percentile(values, q):
            if not values:
                return float("nan")
            k = int(round((len(values) - 1) * q))
            return values[k]

        total_spawned = len(self.passengers)
        return {
            "passengers": total_spawned,
            "completed": len(done),
            "completion_rate": len(done) / total_spawned if total_spawned else 1.0,
            "cars": len(self.cars),
            "algorithm": self.dispatcher.key,
            "makespan": max(totals) if totals else 0,
            "avg_wait": mean(waits),
            "avg_ride": mean(rides),
            "avg_total": mean(totals),
            "p90_total": percentile(totals, 0.90),
            "max_total": max(totals) if totals else float("nan"),
            "stops": sum(c.stops for c in self.cars),
            "floors": sum(c.floors_travelled for c in self.cars),
            "door_seconds": sum(c.door_seconds for c in self.cars),
            "idle_seconds": sum(c.idle_seconds for c in self.cars),
            "max_floor_waiting": self.peak_waiting,
            "failed": self.failed,
            "fail_time": self.fail_time if self.fail_time is not None else float("nan"),
        }
