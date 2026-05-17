# -*- coding: utf-8 -*-

# 使用python控制鼠标键盘，自动操作foxmail（或其它任何邮件客户端）发送邮件

import os, sys, time
import pandas as pd
import pyautogui as pag

from common_config import (
    get_datetime_list,
    get_explorer_tab_x_coord,
    VideoInfo,
    Vector,
    MouseLocation,
    MouseLocationList,
    KeyboardInput,
    KeyboardInputList,
)

# OBS默认保存路径，确保这个路径和OBS设置中的一致，否则脚本无法正确找到录制的视频文件
default_video_save_path = r"E:\GIGABYTE\Videos\OBS Output"

# 窗口按钮坐标（需要根据实际情况调整）
width, height = pag.size()  # 获得当前屏幕分辨率
explorer_base_coords = Vector(0, 0)  # 网页播放器左上角坐标（主屏幕最大化就是0，0）
safe_position_coords = Vector(width, height / 2)  # 鼠标安全位置坐标，避免误操作导致录屏中断（屏幕最右侧中间位置）

# 以下为窗口内部相对坐标，不需要调整
mouse_locations = MouseLocationList([
    MouseLocation("OBS on taskbar", Vector(0, 0)),  # 此处仅默认值，会在脚本开始运行时询问用户
    MouseLocation("Explorer on taskbar", Vector(0, 0)),  # 此处仅默认值，会在脚本开始运行时询问用户
    MouseLocation("Set Hour", Vector(0, 0)),  # 此处仅默认值，会在脚本开始运行时询问用户
    MouseLocation("Set Minute", Vector(0, 0)),  # 此处仅默认值，会在脚本开始运行时询问用户
    MouseLocation("Set Second", Vector(0, 0)),  # 此处仅默认值，会在脚本开始运行时询问用户
    MouseLocation("Start Record", Vector(0, 0)),  # 此处仅默认值，会在脚本开始运行时询问用户
    MouseLocation("Explorer Tab", Vector(0, 25)),  # 浏览器网页坐标，X为默认值，后续会动态更新
    MouseLocation("Maximize Screen", explorer_base_coords + (1190, 908)),  # 浏览器视频进入全屏按钮
    MouseLocation("Recover Screen", explorer_base_coords + (1866, 1150)),  # 浏览器视频退出全屏按钮
    MouseLocation("Safe Position", safe_position_coords),  # 录屏时鼠标安全位置
    ])

keyboard_inputs = KeyboardInputList([
    KeyboardInput("Input Hour", "0"),  # 录屏计时器输入框：时(仅初始值)
    KeyboardInput("Input Minute", "0"),  # 录屏计时器输入框：分(仅初始值)
    KeyboardInput("Input Second", "0"),  # 录屏计时器输入框：秒(仅初始值)
    ])

# 等待时间(s)
video_duration_offset = 6  # 录屏时间比视频时长多等待的时间，确保录屏结束前视频就结束了
interval_after_recording = 3  # 两次录屏之间的间隔时间

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
                user_input = input('Please enter the base coordinates of the OBS recording timer (format: x,y): ')
                x_str, y_str = user_input.split(',')
                x = int(x_str.strip())
                y = int(y_str.strip())
                print('OBS Recording timer coordinates set to: (%d, %d)' % (x, y))
                mouse_locations.set_mouse_coords("Set Hour", Vector(x, y) + (220, 170))  # 录屏计时器输入框：时
                mouse_locations.set_mouse_coords("Set Minute", Vector(x, y) + (372, 170))  # 录屏计时器输入框：分
                mouse_locations.set_mouse_coords("Set Second", Vector(x, y) + (515, 170))  # 录屏计时器输入框：秒
                mouse_locations.set_mouse_coords("Start Record", Vector(x, y) + (640, 170))  # 录屏开始按钮坐标
                break
            except Exception as e:
                print('[Error] Invalid input format. Please enter coordinates in the format: x,y (e.g., 100,200). Error details: %s' % e)
        
        # OBS on taskbar coordinates
        while True:
            try:
                user_input = input('Please enter the coordinates of the OBS on taskbar (format: x,y): ')
                x_str, y_str = user_input.split(',')
                x = int(x_str.strip())
                y = int(y_str.strip())
                print('OBS on taskbar coordinates set to: (%d, %d)' % (x, y))
                mouse_locations.set_mouse_coords("OBS on taskbar", Vector(x, y))
                break
            except Exception as e:
                print('[Error] Invalid input format. Please enter coordinates in the format: x,y (e.g., 100,200). Error details: %s' % e)
        
        # Explorer on taskbar coordinates
        while True:
            try:
                user_input = input('Please enter the coordinates of the Explorer on taskbar (format: x,y): ')
                x_str, y_str = user_input.split(',')
                x = int(x_str.strip())
                y = int(y_str.strip())
                print('Explorer on taskbar coordinates set to: (%d, %d)' % (x, y))
                mouse_locations.set_mouse_coords("Explorer on taskbar", Vector(x, y))
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
        # for video_info in video_info_list:
        #     video_info.print_info()
        
        # Start mouse and keyboard automation loop, to record videos
        i = 1
        video_counts = len(video_info_list)
        for video_info in video_info_list:
            print("") # blank line
            print("[%d%%] [%d/%d] Processing video record: %s" % (100.0*i/video_counts, i, video_counts, video_info.name))

            # 获取浏览器标签数量（当前视频及剩余的视频，每个视频需要一个标签，再加上目录）
            num_tabs = video_counts - i + 2
            # 获取浏览器第二个标签的X坐标
            x_coord_of_2nd_tab = get_explorer_tab_x_coord(
                start_x=50, end_x=1650, max_width=300, num_tabs=num_tabs, tab_index=2)
            # 更新浏览器标签坐标
            mouse_locations.set_mouse_coords("Explorer Tab", explorer_base_coords + (x_coord_of_2nd_tab, 25))

            # Set video duration input for keyboard automation
            video_info.offset_duration(video_duration_offset)  # 计算添加偏移量后的视频时长
            keyboard_inputs.set_keyboard_input("Input Hour", str(video_info.duration_hour))
            keyboard_inputs.set_keyboard_input("Input Minute", str(video_info.duration_min))
            keyboard_inputs.set_keyboard_input("Input Second", str(video_info.duration_sec))

            # Mouse and keyboard operations
            pag.click(mouse_locations.get_mouse_coords("OBS on taskbar"))  # activate OBS window by clicking its icon on the taskbar
            time.sleep(1)
            pag.click(mouse_locations.get_mouse_coords("Set Hour"))  # Click hour input box to set focus
            pag.hotkey('ctrl', 'a')  # press Ctrl + A to select all text in the input box
            pag.hotkey('del')  # press Delete to clear the input box
            pag.typewrite(keyboard_inputs.get_keyboard_input("Input Hour"))  # Type hour value
            time.sleep(1)
            pag.click(mouse_locations.get_mouse_coords("Set Minute"))  # Click minute input box to set focus
            pag.hotkey('ctrl', 'a')  # press Ctrl + A to select all text in the input box
            pag.hotkey('del')  # press Delete to clear the input box
            pag.typewrite(keyboard_inputs.get_keyboard_input("Input Minute"))  # Type minute value
            time.sleep(1)
            pag.click(mouse_locations.get_mouse_coords("Set Second"))  # Click second input box to set focus
            pag.hotkey('ctrl', 'a')  # press Ctrl + A to select all text in the input box
            pag.hotkey('del')  # press Delete to clear the input box
            pag.typewrite(keyboard_inputs.get_keyboard_input("Input Second"))  # Type second value
            time.sleep(1)

            # start recording (also get the video filename)
            default_video_filename_list = get_datetime_list("long", offset_sec=1)  # 默认视频文件名（不带扩展名），格式为 "YYYY-MM-DD_HH-MM-SS"
            video_filename_suffix_str = get_datetime_list("short")[1]  # 用于重命名的视频文件名后缀（不带扩展名），格式为 "YYYYMMDD_HHMMSS"
            pag.click(mouse_locations.get_mouse_coords("Start Record"))

            # activate explorer window by clicking its icon on the taskbar
            pag.click(mouse_locations.get_mouse_coords("Explorer on taskbar"))
            # activate explorer tab
            pag.click(mouse_locations.get_mouse_coords("Explorer Tab"))
            # maximize video screen
            pag.click(mouse_locations.get_mouse_coords("Maximize Screen"))
            # press Space to play the video
            pag.hotkey('space')
            # move mouse to safe position
            pag.moveTo(mouse_locations.get_mouse_coords("Safe Position"))
            time.sleep(video_info.duration + video_duration_offset + interval_after_recording)

            # recover screen
            pag.click(mouse_locations.get_mouse_coords("Recover Screen"))
            time.sleep(1)

            # close current explorer tab
            pag.click(mouse_locations.get_mouse_coords("Explorer Tab"))  # select current explorer tab
            pag.hotkey('ctrl', 'w')  # press Ctrl + W to close the current tab
            time.sleep(1)

            # rename the recorded video file
            # The recorded video file will be saved to the default location set in OBS,
            # and the filename will be the current date and time (e.g., "2024-06-01_12-00-00.mp4").
            # The script will rename this file to match the video name specified in the input CSV.
            
            # try 3 possible default filenames (with 1 second interval) to find the recorded video file,
            # since there might be some delay in file saving and the exact timestamp might not be accurate.
            default_video_filename_candidates = [
                default_video_filename_list[0] + ".mp4",
                default_video_filename_list[1] + ".mp4",
                default_video_filename_list[2] + ".mp4",
                ]
            found_video_file = False
            for candidate in default_video_filename_candidates:
                candidate_filepath = os.path.join(default_video_save_path, candidate)
                if os.path.isfile(candidate_filepath):
                    default_video_filename = candidate
                    default_video_filepath = candidate_filepath
                    found_video_file = True
                    break
            if found_video_file:
                updated_video_filename = video_info.name + "_" + video_filename_suffix_str + ".mp4"
                updated_video_filepath = os.path.join(default_video_save_path, updated_video_filename)
                try:
                    os.rename(default_video_filepath, updated_video_filepath)
                    print("Renamed recorded video file to: %s" % updated_video_filename)
                except Exception as e:
                    print('[Error] Failed to rename video file: %s. Error details: %s' % (default_video_filename, e))
            else:
                print('[Error] Failed to find recorded video file.')

            i += 1
            print("") # blank line
            

    # End of script