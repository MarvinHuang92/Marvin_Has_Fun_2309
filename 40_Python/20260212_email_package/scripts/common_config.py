# -*- coding: utf-8 -*-

import os
from datetime import datetime

# Set to False to ignore file extensions when packaging/restoring
keep_extension = True

# Ignore these extensions when packaging files
ignore_extension_list = [".rar", ".zip", ".mprx"]

delimiter_for_display = "-" * 41
delimiter_for_html = "=" * 44

# get the date and time from attachments/dir_structure.txt
def read_timestamp_from_structure(dir_structure_file_path):
    if not dir_structure_file_path or not os.path.isfile(dir_structure_file_path):
        return ""
    try:
        with open(dir_structure_file_path, "r", encoding="utf-8") as handle:
            lines = [line.rstrip("\n") for line in handle]
    except OSError:
        return ""

    for idx, line in enumerate(lines):
        if line.strip() == "date & time:":
            for next_line in lines[idx + 1:]:
                if next_line.strip():
                    return next_line.strip()
            return ""
    return ""

def format_timestamp_value(timestamp_value):
    if not timestamp_value:
        return datetime.now().strftime("%Y%m%d_%H%M%S")
    try:
        parsed = datetime.strptime(timestamp_value, "%Y-%m-%d %H:%M:%S")
        return parsed.strftime("%Y%m%d_%H%M%S")
    except ValueError:
        return datetime.now().strftime("%Y%m%d_%H%M%S")
    
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


    