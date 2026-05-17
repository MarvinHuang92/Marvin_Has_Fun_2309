# -*- coding: utf-8 -*-

# import os
import datetime, time

def get_datetime_list(type="long", offset_sec=0):
    datetime_now = datetime.datetime.now()
    if offset_sec != 0:
        datetime_positive_delta = datetime_now + datetime.timedelta(seconds=offset_sec)
        datetime_negative_delta = datetime_now - datetime.timedelta(seconds=offset_sec)
    else:
        datetime_positive_delta = datetime_now
        datetime_negative_delta = datetime_now
    
    output = []
    for dt in [datetime_negative_delta, datetime_now, datetime_positive_delta]:
        if type == "long":
            output.append(dt.strftime("%Y-%m-%d_%H-%M-%S"))
        else:  # "short"
            output.append(dt.strftime("%Y%m%d_%H%M%S"))

    return output

# 获取浏览器网页特定标签页的中心点X坐标
def get_explorer_tab_x_coord(start_x, end_x, max_width, num_tabs, tab_index):
    tab_index -= 1  # 转换为0-based索引
    available_width = min(end_x - start_x, max_width * num_tabs)
    tab_width = available_width / num_tabs
    if tab_width <= 70:  # 最小宽度限制，避免标签页过窄
        print(f"Error: Tab width {tab_width:.2f}px is too narrow, please open less tabs.")
        time.sleep(5)  # 等待5秒钟让用户看到错误提示
        exit(-1)
    return start_x + (tab_index * tab_width) + ((tab_width - 40) / 2)  # 40是标签页右侧的关闭按钮宽度，需要减去

class VideoInfo():
    # 成员变量类型声明
    name: str
    duration_hour: int
    duration_min: int
    duration_sec: int
    duration: int

    def __init__(self, name, duration_hour, duration_min, duration_sec):
        self.name = name
        self.duration_hour = duration_hour
        self.duration_min = duration_min
        self.duration_sec = duration_sec
        self.duration = duration_sec + duration_min * 60 + duration_hour * 3600 
    
    def offset_duration(self, offset_sec: int):
        self.duration += offset_sec
        self.duration_hour = self.duration // 3600
        self.duration_min = (self.duration % 3600) // 60
        self.duration_sec = self.duration % 60

    # 输出视频信息，用于debug
    def print_info(self):
        print('Video Name: %s, Duration: %02d:%02d:%02d (Total Seconds: %d)' % (
            self.name,
            self.duration_hour,
            self.duration_min,
            self.duration_sec,
            self.duration
        ))

class Vector(tuple):
    """
    # 支持加减操作的元组子类
    # 使用示例
    v1 = Vector(1, 2)
    v2 = Vector(3, 4)
    v3 = v1 + v2
    print(v3)  # 输出: (4, 6)
    print(v3[0], v3[1])  # 输出: 4 6

    # 与普通元组混合使用
    v4 = v1 + (5, 6)
    print(v4)  # 输出: (6, 8)

    v5 = (10, 10) - v1
    print(v5)  # 输出: (9, 8)

    # 可以像普通元组一样使用
    x, y = v1
    print(x, y)  # 输出: 1 2
    """
    
    def __new__(cls, *args):
        # 确保只有两个元素
        if len(args) != 2:
            raise ValueError("Vector must contain exactly two elements")
        return super().__new__(cls, args)
    
    def __add__(self, other):
        """实现加法操作"""
        if not isinstance(other, (tuple, Vector)) or len(other) != 2:
            raise TypeError("Can only add with another 2-element tuple/Vector")
        return Vector(self[0] + other[0], self[1] + other[1])
    
    def __sub__(self, other):
        """实现减法操作"""
        if not isinstance(other, (tuple, Vector)) or len(other) != 2:
            raise TypeError("Can only subtract with another 2-element tuple/Vector")
        return Vector(self[0] - other[0], self[1] - other[1])
    
    # 支持反向操作（如 (1,2) + Vector(3,4)）
    def __radd__(self, other):
        return self.__add__(other)
    
    def __rsub__(self, other):
        if not isinstance(other, (tuple, Vector)) or len(other) != 2:
            raise TypeError("Can only subtract with another 2-element tuple/Vector")
        return Vector(other[0] - self[0], other[1] - self[1])

class MouseLocation():
    usage: str
    coords: Vector

    def __init__(self, usage, coords):
        self.usage = usage
        self.coords = coords

class MouseLocationList():
    items: list[MouseLocation]

    def __init__(self, items=[]):
        self.items = items

    def get_mouse_coords(self, usage):
        for item in self.items:
            if item.usage == usage:
                return item.coords
        return None
    
    def set_mouse_coords(self, usage, value):
        for item in self.items:
            if item.usage == usage:
                index = self.items.index(item)
                break
        else:
            return False
        self.items[index].coords = value
        return True

class KeyboardInput():
    usage: str
    inputs: str

    def __init__(self, usage, inputs):
        self.usage = usage
        self.inputs = inputs

class KeyboardInputList():
    items: list[KeyboardInput]

    def __init__(self, items=[]):
        self.items = items

    def get_keyboard_input(self, usage):
        for item in self.items:
            if item.usage == usage:
                return item.inputs
        return None

    def set_keyboard_input(self, usage, value):
        for item in self.items:
            if item.usage == usage:
                index = self.items.index(item)
                break
        else:
            return False
        self.items[index].inputs = value
        return True