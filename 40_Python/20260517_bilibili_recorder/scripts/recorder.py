# -*- coding: utf-8 -*-

# 使用python控制鼠标键盘，自动操作foxmail（或其它任何邮件客户端）发送邮件

import os, sys, time
import pandas as pd
import pyautogui as pag

from common_config import (
    VideoInfo,
    Vector,
)

# 窗口按钮坐标（需要根据实际情况调整）
# record_timer_base_coords = Vector(0, 0)  # 录屏计时器左上角坐标，此处仅默认值，会在脚本开始运行时询问用户
explorer_base_coords = Vector(0, 0)  # 副屏网页播放器左上角坐标
safe_coords_when_recording = Vector(0, 0)  # 录屏时鼠标安全位置坐标，避免误操作导致录屏中断

# 以下为窗口内部相对坐标，不需要调整
mouse_locations = [
{"usage":"Set Hour", "coords": Vector(0, 0)},  # 此处仅默认值，会在脚本开始运行时询问用户
{"usage":"Set Minute", "coords": Vector(0, 0)},  # 此处仅默认值，会在脚本开始运行时询问用户
{"usage":"Set Second", "coords": Vector(0, 0)},  # 此处仅默认值，会在脚本开始运行时询问用户
{"usage":"Start Record", "coords": Vector(0, 0)},  # 此处仅默认值，会在脚本开始运行时询问用户
{"usage":"Explorer Tab", "coords": explorer_base_coords + (0, 0)},  # 浏览器网页坐标，用于激活和关闭标签页
{"usage":"Maximize Screen", "coords": explorer_base_coords + (0, 0)},  # 浏览器视频全屏按钮
{"usage":"Play Video", "coords": explorer_base_coords + (0, 0)},  # 浏览器视频播放按钮
{"usage":"Safe Position", "coords": safe_coords_when_recording},  # 录屏时鼠标安全位置
]

keyboard_inputs = [
{"usage":"Input Hour", "input": "0"},  # 录屏计时器输入框：时(仅初始值)
{"usage":"Input Minute", "input": "0"},  # 录屏计时器输入框：分(仅初始值)
{"usage":"Input Second", "input": "0"},  # 录屏计时器输入框：秒(仅初始值)
]

# 等待时间(s)
video_duration_offset = 5  # 录屏时间比视频时长多等待的时间，确保录屏结束前视频就结束了
interval_after_recording = 5  # 两次录屏之间的间隔时间

def get_mouse_coords(usage):
    for item in mouse_locations:
        if item["usage"] == usage:
            return item["coords"]
    return None

def set_mouse_coords(usage, value):
    global mouse_locations
    for item in mouse_locations:
        if item["usage"] == usage:
            index = mouse_locations.index(item)
            break
    else:
        return False
    mouse_locations[index]["coords"] = value
    return True

def get_keyboard_input(usage):
    for item in keyboard_inputs:
        if item["usage"] == usage:
            return item["input"]
    return None

def set_keyboard_input(usage, value):
    global keyboard_inputs
    for item in keyboard_inputs:
        if item["usage"] == usage:
            index = keyboard_inputs.index(item)
            break
    else:
        return False
    keyboard_inputs[index]["input"] = value
    return True

pag.PAUSE = 1               # 每个autogui功能都自动暂停1秒，防止失控
pag.FAILSAFE = False        # 禁用鼠标快速移动到左上角的“自动防故障”功能

# width, height = pag.size()  # 获得当前屏幕分辨率
# pag.moveTo(500, 500, duration = 0.5)
# pag.moveRel(50, -50, duration = 0.5)

if __name__ == '__main__':

    # Get inputs from command line arguments
    if len(sys.argv) != 2:
        print('Usage: python recorder.py <input_csv>')
        sys.exit(1)
    input_csv = str(sys.argv[1]).strip()  # Input CSV file

    if not os.path.isfile(input_csv):
        print('[Error] Input CSV file does not exist: %s' % input_csv)
    else:
        # get the coordinates of the recording timer from user input, and save to global variable
        while True:
            try:
                user_input = input('Please enter the base coordinates of the recording timer (format: x,y): ')
                x_str, y_str = user_input.split(',')
                x = int(x_str.strip())
                y = int(y_str.strip())
                print('Recording timer coordinates set to: (%d, %d)' % (x, y))
                set_mouse_coords("Set Hour", Vector(x, y) + (235, 215))  # 录屏计时器输入框：时
                set_mouse_coords("Set Minute", Vector(x, y) + (392, 215))  # 录屏计时器输入框：分
                set_mouse_coords("Set Second", Vector(x, y) + (540, 215))  # 录屏计时器输入框：秒
                set_mouse_coords("Start Record", Vector(x, y) + (540, 215))  # 录屏开始按钮坐标
                break
            except Exception as e:
                print('[Error] Invalid input format. Please enter coordinates in the format: x,y (e.g., 100,200). Error details: %s' % e)

        # get video info from input csv
        # Skip the first row, then read columns 2-5 (index 1-4) for every remaining row
        try:
            df = pd.read_csv(input_csv, header=None, dtype=str)
            if df.shape[0] < 2:
                raise ValueError('Input CSV has no data rows after skipping the first row')

            video_info_list = []
            for video_index, (_, row) in enumerate(df.iloc[1:].iterrows(), start=1):
                # Columns 2-5 (1-based) -> indices 1,2,3,4
                video_name = row[1] if 1 in row.index else ''
                if not str(video_name).strip():
                    video_name = 'video_%d' % video_index
                video_duration_hour = row[2] if 2 in row.index else '0'
                video_duration_min = row[3] if 3 in row.index else '0'
                video_duration_sec = row[4] if 4 in row.index else '0'

                try:
                    video_duration_hour = int(float(video_duration_hour))
                except Exception:
                    video_duration_hour = 0
                try:
                    video_duration_min = int(float(video_duration_min))
                except Exception:
                    video_duration_min = 0
                try:
                    video_duration_sec = int(float(video_duration_sec))
                except Exception:
                    video_duration_sec = 0

                video_info_list.append(
                    VideoInfo(
                        video_name,
                        video_duration_hour,
                        video_duration_min,
                        video_duration_sec,
                    )
                )

        except Exception as e:
            print('[Error] Failed to read input CSV: %s' % e)
            sys.exit(1)

        # for debug
        for video_info in video_info_list:
            video_info.print_info()
        
        # Start mouse and keyboard automation loop, to record videos
        i = 1
        video_counts = len(video_info_list)
        for video_info in video_info_list:
            print("[%d%%] [%d/%d] Processing video record: %s" % (100.0*i/video_counts, i, video_counts, video_info.name))

            # Set video duration input for keyboard automation
            video_info.offset_duration(video_duration_offset)  # 计算添加偏移量后的视频时长
            set_keyboard_input("Input Hour", video_info.duration_hour)
            set_keyboard_input("Input Minute", video_info.duration_min)
            set_keyboard_input("Input Second", video_info.duration_sec)

            # Mouse and keyboard operations
            pag.click(get_mouse_coords("Set Hour"))  # Click hour input box to set focus
            pag.typewrite(get_keyboard_input("Input Hour"))  # Type hour value
            time.sleep(1)
            pag.click(get_mouse_coords("Set Minute"))  # Click minute input box to set focus
            pag.typewrite(get_keyboard_input("Input Minute"))  # Type minute value
            time.sleep(1)
            pag.click(get_mouse_coords("Set Second"))  # Click second input box to set focus
            pag.typewrite(get_keyboard_input("Input Second"))  # Type second value
            time.sleep(1)

            # activate explorer tab
            pag.click(get_mouse_coords("Explorer Tab"))
            time.sleep(1)

            # maximize video screen
            pag.click(get_mouse_coords("Maximize Screen"))
            time.sleep(1)

            # start recording (also starts the video)
            pag.click(get_mouse_coords("Start Record"))
            pag.click(get_mouse_coords("Play Video"))
            # move mouse to safe position
            pag.moveTo(get_mouse_coords("Safe Position"))
            time.sleep(video_info.duration + video_duration_offset + interval_after_recording)

            # close current explorer tab
            pag.click(get_mouse_coords("Explorer Tab"))  # select current explorer tab
            pag.hotkey('ctrl', 'w')  # press Ctrl + W to close the current tab
            time.sleep(1)

        print("") # blank line
            

    # End of script