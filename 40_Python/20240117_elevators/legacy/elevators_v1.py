from time import sleep
import random
from name_list import generate_name_list

# 定义大楼的最高，最低楼层
MAX_FLOOR = 20
MIN_FLOOR = 1
# 电梯容量
MAX_PEOPLE_IN_ELEVATOR = 8

# 2份乘客名单，每份26个人名
name_list_1, name_list_2 = generate_name_list()

# 绝对时间
TIME = 0

class Elevator(object):
    m_identification = 0
    m_floor = 1
    m_passengers = []
    m_passenger_num = 0
    m_target_direction = "Up"

    def __init__(self, identification, floor=1):
        self.m_identification = identification
        self.m_floor = floor
        # 必须初始化列表，否则多个实例会共用同一个列表
        self.m_passengers = []
    
    def move_by(self, increment=1):
        self.m_floor += increment
        self.check_floor_range()
    
    def move_to(self, destination=1):
        self.m_floor = destination
        self.check_floor_range()
    
    def check_floor_range(self):
        if self.m_floor > MAX_FLOOR:
            self.m_floor = MAX_FLOOR
        elif self.m_floor < MIN_FLOOR:
            self.m_floor = MIN_FLOOR
    
    def show_info(self):
        show_time()
        self.m_passenger_num = len(self.m_passengers)
        print("%d号电梯在%d楼，有%d名乘客，运行方向：%s" % (self.m_identification, self.m_floor, self.m_passenger_num, self.m_target_direction))
        print("%d号电梯的乘客分别是：%s" % (self.m_identification, str(self.m_passengers)))


class Passenger(object):
    m_name = "No name"
    m_current_floor = 1
    m_target_floor = 1
    m_state = "No Action"
    m_target_direction = "Up"
    m_in_which_elevator = 0

    def __init__(self, name, current_floor, target_floor=1):
        self.m_name = name
        self.m_current_floor = current_floor
        self.m_target_floor = target_floor
        # self.check_state()

    def check_state(self):
        # 电梯内的乘客
        if self.m_state == "In Elevator":
            # 进入到达状态，准备离开电梯
            if self.m_target_floor == self.m_current_floor:
                self.m_state = "Arrived"
        elif self.m_state == "Arrived":
            # 已经到达，保持该状态
            pass
        # 电梯外的乘客
        else:
            # 去按电梯
            if self.m_target_floor != self.m_current_floor:
                self.m_state = "Wait for Elevator"
                if self.m_target_floor > self.m_current_floor:
                    self.m_target_direction = "Up"
                elif self.m_target_floor < self.m_current_floor:
                    self.m_target_direction = "Down"
            # 什么也不做
            else:
                self.m_state = "No Action"

    
    def show_info(self):
        # if self.m_state in ("In Elevator", "Arrived"):
        #     print("乘客名字：%s，当前楼层：%d，要去楼层：%d，状态：%s (%d)" % (self.m_name, self.m_current_floor, self.m_target_floor, self.m_state, self.m_in_which_elevator))
        # else:
        #     print("乘客名字：%s，当前楼层：%d，要去楼层：%d，状态：%s" % (self.m_name, self.m_current_floor, self.m_target_floor, self.m_state))
        pass


class World(object):
    m_elevators = []
    m_passengers = []

    def __init__(self, elevators, passengers):
        self.m_elevators = elevators
        self.m_passengers = passengers
    
    # 检查是否所有人都到了目的地
    def check_finished(self):
        finished = True
        for p in self.m_passengers:
            p.check_state()
            if p.m_state != "No Action":
                finished = False
                break
        return finished
    
    def run(self, first_run=False):
        global TIME

        # 读取乘客状态


        # 更新电梯状态和策略（设置目标路径等）
        # 在顶层，底层，强制电梯换向
        for ele in self.m_elevators:
            if ele.m_floor == MIN_FLOOR:
                ele.m_target_direction = "Up"
            elif ele.m_floor == MAX_FLOOR:
                ele.m_target_direction = "Down"
            
            # 其他可能换向的条件
            if Strategy_01:
                if ele.m_target_direction == "Up":
                    return_flag = True
                    for p in self.m_passengers:
                        # 电梯中的乘客，还有目的地在前方的，电梯不换向
                        if p.m_name in ele.m_passengers and p.m_target_floor > ele.m_floor:
                            return_flag = False
                            break
                        # 电梯外的乘客，有在前方等待的，或者同层等待且顺向的，电梯不换向
                        elif p.m_state == "Wait for Elevator":
                            if (p.m_current_floor > ele.m_floor) or \
                                (p.m_current_floor == ele.m_floor and p.m_target_direction == "Up"):
                                return_flag = False
                                break
                    # 执行换向
                    if return_flag:
                        ele.m_target_direction = "Down"
                        print("%d号电梯换向，当前方向：%s" % (ele.m_identification, ele.m_target_direction))
                
                elif ele.m_target_direction == "Down":
                    return_flag = True
                    for p in self.m_passengers:
                        # 电梯中的乘客，还有目的地在前方的，电梯不换向
                        if p.m_name in ele.m_passengers and p.m_target_floor < ele.m_floor:
                            return_flag = False
                            break
                        # 电梯外的乘客，有在前方等待的，或者同层等待且顺向的，电梯不换向
                        elif p.m_state == "Wait for Elevator":
                            if (p.m_current_floor < ele.m_floor) or \
                                (p.m_current_floor == ele.m_floor and p.m_target_direction == "Down"):
                                return_flag = False
                                break
                    # 执行换向
                    if return_flag:
                        ele.m_target_direction = "Up"
                        print("%d号电梯换向，当前方向：%s" % (ele.m_identification, ele.m_target_direction))
                    
            if first_run:
                ele.show_info()
        
        # 电梯开门，更新乘客状态（上下电梯等）
        for ele in self.m_elevators:
            # 准备上下乘客名单
            passengers_take_on = []
            passengers_take_off = []
            print("")
            for p in self.m_passengers:
                # 更新每个乘客状态
                p.check_state()
                p.show_info()
                # 让顺向等待的乘客上电梯，且电梯不可超员
                if p.m_state == "Wait for Elevator" and \
                        len(ele.m_passengers) < MAX_PEOPLE_IN_ELEVATOR and \
                        p.m_current_floor == ele.m_floor and \
                        p.m_target_direction == ele.m_target_direction:
                    p.m_state = "In Elevator"
                    p.m_in_which_elevator = ele.m_identification
                    passengers_take_on.append(p.m_name)
                    ele.m_passengers.append(p.m_name)
                # 让到达的乘客下电梯
                elif p.m_state == "Arrived" and p.m_in_which_elevator == ele.m_identification:
                    p.m_state = "No Action"
                    passengers_take_off.append(p.m_name)
                    ele.m_passengers.remove(p.m_name)
            print("\n%d号电梯开门，乘客上下电梯中..." % ele.m_identification)
            if not passengers_take_on == []:
                print("%s登上电梯" % str(passengers_take_on))
            else: 
                print("无人登上电梯")
            if not passengers_take_off == []:
                print("%s离开电梯" % str(passengers_take_off))
            else: 
                print("无人离开电梯")
            print("")

        # 更新电梯状态

        # 电梯移动
        for ele in self.m_elevators:
            # 电梯移动一层
            print("%d号电梯关门，移动中..." % ele.m_identification)
            if ele.m_target_direction == "Up":
                ele.move_by(1)
            elif ele.m_target_direction == "Down":
                ele.move_by(-1)
            print("%d号电梯到达%d层\n" % (ele.m_identification, ele.m_floor))

        # 到达新楼层，更新电梯状态和内部乘客状态
        for ele in self.m_elevators:
            # 将所有“在电梯中”的乘客楼层与电梯楼层同步
            for p in self.m_passengers:
                if p.m_state == "In Elevator" and p.m_in_which_elevator == ele.m_identification:
                    p.m_current_floor = ele.m_floor
                p.check_state()
                # p.show_info()

        # 时间加1，并显示电梯状态
        TIME += 1
        for ele in self.m_elevators:
            ele.show_info()
        
        print("\n===========================第%d轮循环结束===========================" % TIME)




def show_time():
    print("\n当前时间：%d" % TIME)


if __name__ == "__main__":
    # 换向策略01
    Strategy_01 = True

    # 初始化电梯(编号，初始楼层)
    elevators = []
    elevators.append(Elevator(1, 1))
    # elevators.append(Elevator(2, 6))
    # elevators.append(Elevator(3, 11))
    # elevators.append(Elevator(4, 16))

    # 初始化乘客，不要超过52名
    passengers = []
    for i in range(52):
        if i < 26:
            name = name_list_1[i]
        else:
            name = name_list_2[i-26]
        passengers.append(Passenger(name, 1, random.randint(MIN_FLOOR, MAX_FLOOR)))
        # passengers[i].show_info()

    # 将电梯和乘客加入世界
    world = World(elevators, passengers)
    
    # 运行世界循环，直到所有乘客被送到目的地
    world.run(first_run=True)
    while True:
        if world.check_finished():
            break
        else:
            world.run()
