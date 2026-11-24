#!/usr/bin/env python3
# -*- coding: utf-8 -*-

' 不是原本的库函数，原来的Vec2d下载不到了，手写类来代替一下 '

__author__ = 'Marvin Huang'

class Vec2d(list):
    def __init__(self, x, y):
        # 调用list类的构造函数，确保Vec2d类可以被解析成二元数组
        super().__init__([x, y])
        self.x = x
        self.y = y
    
    # +, -
    def __add__(self, list):
        return Vec2d(self.x + list[0], self.y + list[1])

    # +=， -=
    def __iadd__(self, list):
        return Vec2d(self.x + list[0], self.y + list[1])

    # *
    def __mul__(self, value):
        return Vec2d(self.x * value, self.y * value)

    # 右乘
    def __rmul__(self, value):
        return Vec2d(self.x * value, self.y * value)
