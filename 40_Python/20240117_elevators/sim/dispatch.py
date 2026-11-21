"""调度算法集合。

每个算法只回答一个问题：**这辆车下一站停哪一层**（``next_stop``）。
另外两个钩子用来表达"派梯"和"只载自己片区的人"：

* ``accepts(car, p)``    —— 这名候梯乘客能不能上这辆车（默认都可以）
* ``setup(world)``       —— 初始化时做派梯/分区

共 7 种，从最笨到最聪明：

====================  ==================================================
original              原程序逻辑：不管有没有人，每层都开关门
fcfs                  先来先服务：严格按请求先后接送
sstf                  最近优先：每次去离自己最近的那个请求
scan                  扫描算法：保持方向走到底再回头
look                  顺向截梯：前方没有请求就立刻换向
zoning                目的层分区：固定楼层区间分给各车
dd_eta                目的层派梯：按"预计送达时刻"把乘客派给最快那辆
====================  ==================================================
"""

from __future__ import annotations

from typing import Optional

from .model import MAX_FLOOR, MIN_FLOOR, Elevator, Passenger, World


# ---------------------------------------------------------------- 公共工具


def alighting_at(car: Elevator, floor: int) -> int:
    """到这一层会下去几个人。"""
    return sum(1 for p in car.riders if p.target == floor)


def free_space_at(car: Elevator, floor: int) -> int:
    """到达该层、下完人之后还剩几个空位。"""
    return car.capacity - len(car.riders) + alighting_at(car, floor)


def can_pickup(car: Elevator, world: World, floor: int, direction: Optional[int] = None) -> bool:
    """这辆车在这一层有没有可能接到人。"""
    if free_space_at(car, floor) <= 0:
        return False
    if car.blank_stop_floor == floor:  # 刚在这里白停过，别再来一次
        return False
    strict = world.dispatcher.direction_strict and direction is not None and car.riders
    blind = world.dispatcher.blind_pickup
    for p in world.waiting_at(floor):
        if not blind and not world.dispatcher.accepts(car, p):
            continue
        if strict and p.direction != direction:
            continue
        return True
    return False


def demand_floors(car: Elevator, world: World, direction: Optional[int]) -> set[int]:
    """值得停靠的楼层：车上乘客的目的层 + 能上客的候梯层。

    ``direction`` 只在车厢非空、且该策略要求同向时才用来过滤。
    """
    floors = {p.target for p in car.riders}
    strict = world.dispatcher.direction_strict and bool(car.riders) and direction is not None
    blind = world.dispatcher.blind_pickup
    for p in world.waiting():
        if p.origin == car.blank_stop_floor:
            continue
        if not blind and not world.dispatcher.accepts(car, p):
            continue
        if strict and p.direction != direction:
            continue
        if free_space_at(car, p.origin) <= 0:
            continue
        floors.add(p.origin)
    return floors


def split_by_direction(floors: set[int], floor: int, direction: int):
    """把候选楼层拆成"前方 / 后方"，各自按距离由近到远排序。"""
    ahead = sorted((f for f in floors if (f - floor) * direction > 0), key=lambda f: abs(f - floor))
    behind = sorted((f for f in floors if (f - floor) * direction < 0), key=lambda f: abs(f - floor))
    return ahead, behind


# ---------------------------------------------------------------- 基类


class Dispatcher:
    """调度器基类。"""

    key = "base"
    label = "基础"
    desc = ""

    #: 是否要求"同方向上客"（顺向截梯）。
    #: LOOK / SCAN / 分区 / 派梯都是 True；FCFS / SSTF 不看方向，置 False。
    direction_strict: bool = True

    #: 是否"看不见"候梯乘客的目的地（只有上/下按钮时）。
    #: 置 True 的车会在所有呼叫楼层停靠，再由乘客自己挑选上哪辆车。
    blind_pickup: bool = False

    #: 这个策略需要乘客在进电梯前表达目的层吗？
    requires_destination: bool = False

    def __init__(self) -> None:
        self.world: Optional[World] = None

    # ---------------------------------------------------------- 生命周期

    def attach(self, world: World) -> None:
        self.world = world
        self.setup(world)

    def setup(self, world: World) -> None:  # 默认什么都不做
        pass

    # ---------------------------------------------------------- 策略钩子

    def next_stop(self, car: Elevator, world: World, now: int) -> Optional[int]:
        raise NotImplementedError

    def accepts(self, car: Elevator, p: Passenger) -> bool:
        return True

    def may_board(self, car: Elevator, p: Passenger) -> bool:
        """这名乘客此刻能不能进这辆车（方向规则在这里）。"""
        if not self.direction_strict:
            return True
        if car.is_empty or car.direction == 0:
            return True
        return p.direction == car.direction

    def note_board(self, car: Elevator, p: Passenger) -> None:
        pass

    def note_alight(self, car: Elevator, p: Passenger) -> None:
        pass

    # ---------------------------------------------------------- 工具

    @staticmethod
    def terminal_reverse(car: Elevator) -> None:
        """到顶/到底必换向，和真实电梯一致。"""
        if car.floor <= car.min_floor and car.direction < 0:
            car.direction = 1
        elif car.floor >= car.max_floor and car.direction > 0:
            car.direction = -1


# ---------------------------------------------------------------- 0. 原程序


class OriginalSweep(Dispatcher):
    """原程序逻辑：从 1 楼扫到 20 楼再扫回来，每层都开门。"""

    key = "original"
    label = "原程序（每层必停）"
    desc = "忠实复刻原来的扫楼逻辑：不管有没有人，每层都开关门一次，最慢。"

    def next_stop(self, car: Elevator, world: World, now: int) -> Optional[int]:
        if not world.has_demand():
            return None
        self.terminal_reverse(car)
        if car.direction == 0:
            car.direction = 1
        nxt = car.floor + car.direction
        if nxt < car.min_floor or nxt > car.max_floor:  # 理论上到不了，防御一下
            car.direction = -car.direction
            nxt = car.floor + car.direction
        return nxt


# ---------------------------------------------------------------- 1. FCFS


class Fcfs(Dispatcher):
    """先来先服务：谁先按的键先送谁。

    完全按请求队列走：先到最早请求所在层，把那儿的人全部接上，
    再按上车顺序一个一个送。它不看方向，所以 ``direction_strict = False``。
    """

    key = "fcfs"
    label = "FCFS（先来先服务）"
    desc = "严格按请求先后服务，目标楼层随机时来回折返，单梯时代价很大。"
    direction_strict = False

    def next_stop(self, car: Elevator, world: World, now: int) -> Optional[int]:
        if not world.has_demand():
            return None
        self.terminal_reverse(car)
        items = []  # (时间, 类型, 乘客号, 楼层, 方向)

        for p in world.waiting():
            if not self.accepts(car, p):
                continue
            if free_space_at(car, p.origin) <= 0:
                continue
            items.append((p.request_time, 0, p.pid, p.origin, p.direction))
        for p in car.riders:
            items.append((p.board_time if p.board_time is not None else 0, 1, p.pid, p.target, 0))

        if not items:
            return None
        items.sort()
        when, kind, pid, floor, want = items[0]
        return floor


class Sstf(Dispatcher):
    """最近优先：每次跑向离自己最近的那个请求（磁盘磁头调度那套）。

    同样不看方向：谁近就先去哪儿，到站把人接上再说。
    """

    key = "sstf"
    label = "SSTF（最近优先）"
    desc = "每次服务最近的请求，不管方向，容易在楼层之间来回横跳。"
    direction_strict = False

    def next_stop(self, car: Elevator, world: World, now: int) -> Optional[int]:
        if not world.has_demand():
            return None
        self.terminal_reverse(car)
        direction = car.direction if car.riders else None
        if can_pickup(car, world, car.floor, direction):
            return car.floor
        floors = demand_floors(car, world, direction)
        if not floors:
            return None
        d = car.direction or 1
        return min(floors, key=lambda f: (abs(f - car.floor), -d * (f - car.floor)))


# ---------------------------------------------------------------- 3. SCAN


class Scan(Dispatcher):
    """扫描算法：像磁盘 SCAN 一样走到底再回头。"""

    key = "scan"
    label = "SCAN（扫描）"
    desc = "保持方向走到底，前方没请求也空驶到端点再回头；跳层，但会空跑。"

    def next_stop(self, car: Elevator, world: World, now: int) -> Optional[int]:
        if not world.has_demand():
            return None
        self.terminal_reverse(car)
        direction = car.direction or 1
        floor = car.floor

        if can_pickup(car, world, floor, direction if car.riders else None):
            return floor

        floors = demand_floors(car, world, direction if car.riders else None)
        ahead, behind = split_by_direction(floors, floor, direction)
        if ahead:
            return ahead[0]

        edge = car.max_floor if direction > 0 else car.min_floor
        if floor != edge:
            return edge  # 空驶到端点

        car.direction = -direction
        ahead, _ = split_by_direction(floors, floor, car.direction)
        return ahead[0] if ahead else None


# ---------------------------------------------------------------- 4. LOOK


class Look(Dispatcher):
    """顺向截梯（LOOK）：前方没请求就立刻换向，不空驶到端点。"""

    key = "look"
    label = "LOOK（顺向截梯）"
    desc = "沿当前方向服务，前方没有请求立即换向——原程序想实现、但写错了的策略。"

    def next_stop(self, car: Elevator, world: World, now: int) -> Optional[int]:
        if not world.has_demand():
            return None
        self.terminal_reverse(car)
        direction = car.direction or 1
        floor = car.floor

        if can_pickup(car, world, floor, direction if car.riders else None):
            return floor

        floors = demand_floors(car, world, direction if car.riders else None)
        ahead, behind = split_by_direction(floors, floor, direction)
        if ahead:
            return ahead[0]
        if behind:
            car.direction = -direction
            return behind[0]
        return None


# ---------------------------------------------------------------- 5. 分区


class Zoning(Dispatcher):
    """目的层分区：每辆车负责一段楼层，只载"目的地在自己区里"的乘客。

    大堂（1 楼）是公共层：不管哪个区的人，都要能下楼回大堂，所以
    ``target == 1`` 对所有车开放，避免"某层没人负责"的死锁。
    """

    key = "zoning"
    label = "目的层分区"
    desc = "把 2~20 层切成 n 段，每辆车只把乘客送到自己区内；1 楼对所有车开放。"

    def __init__(self) -> None:
        super().__init__()
        self.zones: dict[int, tuple[int, int]] = {}

    def setup(self, world: World) -> None:
        n = max(1, len(world.cars))
        lo, hi = world.min_floor + 1, world.max_floor
        total = hi - lo + 1
        for i, car in enumerate(world.cars):
            start = lo + total * i // n
            end = lo + total * (i + 1) // n - 1
            self.zones[car.eid] = (start, end)
        # 只有上/下按钮时，车不知道候梯者要去哪：它只能见呼叫就停，
        # 让乘客自己挑该上哪辆车（"白停"的代价由此产生）。
        self.blind_pickup = world.info_model == "hall"

    def _in_zone(self, car: Elevator, floor: int) -> bool:
        start, end = self.zones.get(car.eid, (car.min_floor, car.max_floor))
        return start <= floor <= end

    def accepts(self, car: Elevator, p: Passenger) -> bool:
        # 按目的地分区：谁负责那个楼层，谁就负责把乘客送上去/下去。
        # 1 楼（大堂）是公共目的地，所有车都能送。
        return p.target == MIN_FLOOR or self._in_zone(car, p.target)

    # 路线规划沿用 LOOK
    next_stop = Look.next_stop


class CallZoning(Zoning):
    """呼叫分区：每辆车负责一段楼层的**呼叫**（而不是目的地）。

    这是「电梯外只有上下按钮」时唯一真正可行的分区方式：
    系统虽然不知道乘客要去哪，但知道呼叫发生在哪一层，于是把楼层划给各车，
    每辆车只响应自己那几层的呼叫，乘客上车后再按目的层送。
    """

    key = "zoning_call"
    label = "呼叫分区（按楼层）"
    desc = "只有上下按钮时的分区：每辆车只响应自己那几层的呼叫，送到哪都行。"

    def setup(self, world: World) -> None:
        super().setup(world)
        self.blind_pickup = False  # 呼叫是按楼层派过来的，不需要白停

    def accepts(self, car: Elevator, p: Passenger) -> bool:
        return p.origin == MIN_FLOOR or self._in_zone(car, p.origin)


# ---------------------------------------------------------------- 6. 目的层派梯


class DestinationDispatch(Dispatcher):
    """目的层派梯：楼宇级分配 + 单车 LOOK 执行。

    每位乘客只归属于一辆车，车厢里的人按 LOOK 顺序送达。
    这是"静态均分"版本：100 人 / 4 辆车 = 每车 25 人，跑 4 趟。
    """

    key = "dd_eta"
    label = "目的层派梯（ETA 均分）"
    desc = "按各车现有工作量把乘客均分下去，车按 LOOK 执行；末段会产生载不满的尾程。"

    #: 一位在梯乘客大致值多少秒（含一次停靠和层间运行）
    RIDER_COST = 9
    #: 一位还没接上的预约乘客大致值多少秒
    WAITING_COST = 5

    requires_destination = True

    def __init__(self) -> None:
        super().__init__()
        self.assigned: dict[int, int] = {}  # pid -> eid

    def setup(self, world: World) -> None:
        if world.info_model != "destination":
            raise SystemExit(f"{self.label} 需要乘客进电梯前就表达目的层，"
                             f"只有上/下按钮时无法使用。")
        for p in world.waiting():
            self.assigned[p.pid] = self._best_car(world, p).eid

    def _best_car(self, world: World, p: Passenger) -> Elevator:
        best: Optional[Elevator] = None
        best_score = float("inf")
        for car in world.cars:
            pending = sum(1 for q in world.waiting() if self.assigned.get(q.pid) == car.eid)
            score = (
                world.timing.travel(abs(car.floor - p.origin))
                + self.RIDER_COST * car.load
                + self.WAITING_COST * pending
            )
            if score < best_score:
                best, best_score = car, score
        assert best is not None
        return best

    def accepts(self, car: Elevator, p: Passenger) -> bool:
        target = self.assigned.get(p.pid)
        if target is None:  # 后到的乘客，现场派
            target = self._best_car(self.world, p).eid
            self.assigned[p.pid] = target
        return target == car.eid

    next_stop = Look.next_stop


# ---------------------------------------------------------------- 7. 目的层分组


class DestinationGrouping(Dispatcher):
    """目的层分组：把目的地相近的人凑成一车，一趟只停 2~4 层。

    早高峰（所有人都在大堂）最有效的一招：既然乘客还没上车，就先把他们
    按目的层排序、每 8 人一批分给各车。每趟只服务相邻的两三层。

    动态场景下批次是**现凑的**：每次装车时从还没被别的车认领的候梯者里，
    挑一批目的地最集中的（不超过 8 人）。客流一稀，批次就凑不满，优势随之消失。
    """

    key = "dd_group"
    label = "目的层分组"
    desc = "按目的层把候梯者凑成 8 人一批分给各车，一趟只停相邻几层，早高峰最强。"

    requires_destination = True

    def __init__(self) -> None:
        super().__init__()
        self.owner: dict[int, int] = {}                  # pid -> eid
        self._current: dict[int, set[int]] = {}          # eid -> 当前要上的那一批

    def setup(self, world: World) -> None:
        if world.info_model != "destination":
            raise SystemExit(f"{self.label} 需要乘客进电梯前就表达目的层，"
                             f"只有上/下按钮时无法使用。")
        self.owner = {}
        self._current = {car.eid: set() for car in world.cars}

    def _refresh(self, car: Elevator, world: World) -> None:
        """当前批次接完了，就从"还没主的候梯者"里再凑一批。"""
        current = self._current.setdefault(car.eid, set())
        waiting_ids = {p.pid for p in world.waiting()}
        if current & waiting_ids:
            return  # 这批还没接完

        free = [p for p in world.waiting() if self.owner.get(p.pid) in (None, car.eid)]
        if not free:
            self._current[car.eid] = set()
            return

        seed = min(free, key=lambda p: (p.target, p.pid))
        group = sorted(free, key=lambda p: (abs(p.target - seed.target), p.pid))[:car.capacity]
        self._current[car.eid] = {p.pid for p in group}
        for p in group:
            self.owner[p.pid] = car.eid

    def accepts(self, car: Elevator, p: Passenger) -> bool:
        return p.pid in self._current.get(car.eid, ())

    def next_stop(self, car: Elevator, world: World, now: int) -> Optional[int]:
        self._refresh(car, world)
        return Look.next_stop(self, car, world, now)


# ---------------------------------------------------------------- 注册表

ALGORITHMS = [
    OriginalSweep,
    Fcfs,
    Sstf,
    Scan,
    Look,
    Zoning,
    CallZoning,
    DestinationDispatch,
    DestinationGrouping,
]

ALGO_BY_KEY = {cls.key: cls for cls in ALGORITHMS}

#: 图表/表格里的短名
SHORT_LABELS = {
    "original": "原程序",
    "fcfs": "FCFS",
    "sstf": "SSTF",
    "scan": "SCAN",
    "look": "LOOK",
    "zoning": "分区",
    "zoning_call": "呼叫分区",
    "dd_eta": "ETA派梯",
    "dd_group": "目的层分组",
}

#: 只有"目的地已知"（方法 2）才能用的算法
DESTINATION_ONLY = ("dd_eta", "dd_group")
#: 只有"上/下按钮"（方法 1）才有意义的算法
HALL_ONLY = ("zoning_call",)

#: 表格里的展示顺序（也是预期从差到好的顺序）
ORDER = [cls.key for cls in ALGORITHMS]


def build_dispatcher(key: str) -> Dispatcher:
    try:
        return ALGO_BY_KEY[key]()
    except KeyError:
        raise SystemExit(
            f"未知算法 {key!r}，可选：{', '.join(ORDER)}"
        ) from None
