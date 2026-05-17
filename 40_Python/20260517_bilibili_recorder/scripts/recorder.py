# -*- coding: utf-8 -*-

# 使用python控制鼠标键盘，自动操作foxmail（或其它任何邮件客户端）发送邮件

import os, sys, time
import pandas as pd
import pyautogui as pag

from common_config import (
    format_timestamp_value,
    Vector,
)

# 窗口按钮坐标（需要根据实际情况调整）
record_timer_base_coords = Vector(0, 0)  # 录屏计时器左上角坐标
explorer_base_coords = Vector(0, 0)  # 副屏网页播放器左上角坐标

# 以下为窗口内部相对坐标，不需要调整
mouse_locations = [
{"usage":"Set Hour", "coords": record_timer_base_coords + (235, 215)},  # 录屏计时器输入框：时
{"usage":"Set Minute", "coords": record_timer_base_coords + (392, 215)},  # 录屏计时器输入框：分
{"usage":"Set Second", "coords": record_timer_base_coords + (540, 215)},  # 录屏计时器输入框：秒
]

keyboard_inputs = [
{"usage":"Input Hour", "input": "example@example.com"},  # 录屏计时器输入框：时
{"usage":"Input Minute", "input": "example@example.com"},  # 录屏计时器输入框：分
{"usage":"Input Second", "input": "example@example.com"},  # 录屏计时器输入框：秒
# {"usage":"Mail Subject", "input": "dummy"},  # 邮件主题输入框
# {"usage":"Attachment Folder", "input": "dummy"},  # 附件文件夹输入框
]

# 等待时间(s)
video_duration_offset = 3
interval_after_recording = 5  # 与上一个参数累加

def get_mouse_coords(usage):
    for item in mouse_locations:
        if item["usage"] == usage:
            return item["coords"]
    return None

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
        print('Usage: python recorder.py <INPUT_CSV>')
        sys.exit(1)
    input_csv = str(sys.argv[1]).strip()  # Input CSV file

    if not os.path.isfile(input_csv):
        print('[Error] Input CSV file does not exist: %s' % input_csv)
    else:
        # get video info from input csv
        # Read first row and extract columns 2-5 (index 1-4)
        try:
            df = pd.read_csv(input_csv, header=None, dtype=str)
            # Ensure there is at least one row
            if df.shape[0] < 1:
                raise ValueError('Input CSV is empty')

            row0 = df.iloc[0]
            # Columns 2-5 (1-based) -> indices 1,2,3,4
            video_name = row0[1] if 1 in row0.index else ''
            video_duration_hour = row0[2] if 2 in row0.index else '0'
            video_duration_min = row0[3] if 3 in row0.index else '0'
            video_duration_sec = row0[4] if 4 in row0.index else '0'

            # Normalize numeric duration parts to integers (if possible)
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

        except Exception as e:
            print('[Error] Failed to read input CSV: %s' % e)
            sys.exit(1)
        
        print(video_name)
        print(video_duration_hour)
        print(video_duration_min)
        print(video_duration_sec)

        # video_duration_hour = pd.read_csv(input_csv)['video_duration'].iloc[2] # 第3列，视频时长：时
        # video_duration_min = pd.read_csv(input_csv)['video_duration'].iloc[2] # 第4列，视频时长：分
        # video_duration_sec = pd.read_csv(input_csv)['video_duration'].iloc[2] # 第5列，视频时长：秒
        # timestamp_suffix = format_timestamp_value(read_timestamp_from_structure(dir_structure_file_path))
        # mail_package_root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "mails/mail_%s/package" % timestamp_suffix))
        # print('Attachment folder: %s' % attachment_dir)
        # print('Mail package root directory: %s' % mail_package_root_dir)

        # # get mail package total count
        # mail_packages_count = 0
        # if os.path.isdir(mail_package_root_dir):
        #     for item in os.listdir(mail_package_root_dir):
        #         item_path = os.path.join(mail_package_root_dir, item)
        #         if os.path.isdir(item_path):
        #             mail_packages_count += 1
        # print('Total mail packages found: %d' % mail_packages_count)
        
        # # Set recipient input for keyboard automation
        # set_keyboard_input("Recipient", receiver)

        # # Start mouse and keyboard automation loop, to send email
        # for i in range(start_attch_id, mail_packages_count + 1):
        #     mail_subject = "mail_{0}".format(i)
        #     mail_package_dir = os.path.join(mail_package_root_dir, str(i))
        #     print("[%d%%] [%d/%d] Processing mail package: %s" % (100.0*i/mail_packages_count, i, mail_packages_count, mail_package_dir))

        #     # Set mail subject and attachment folder input for keyboard automation
        #     set_keyboard_input("Mail Subject", mail_subject)
        #     set_keyboard_input("Attachment Folder", mail_package_dir)

        #     # Mouse and keyboard operations
        #     pag.click(get_mouse_coords("New Email"))  # Click "New Email" button
        #     time.sleep(2)  # Wait for the new email dialog to open

        #     # recipient
        #     pag.click(get_mouse_coords("Recipient"))  # Click recipient input box
        #     pag.typewrite(get_keyboard_input("Recipient"))  # Type recipient email address

        #     # mail subject
        #     pag.click(get_mouse_coords("Mail Subject"))  # Click mail subject input box
        #     pag.typewrite(get_keyboard_input("Mail Subject"))  # Type mail subject

        #     # attachment
        #     pag.click(get_mouse_coords("Add Attachment"))  # Click "Add Attachment" button
        #     time.sleep(2)  # Wait for the file dialog to open
        #     pag.click(get_mouse_coords("Attachment Folder"))  # Click "Attachment Folder" input box
        #     if send_mail_switch:  # to avoid delete files in demo mode
        #         pag.hotkey("ctrl", "a")  # Ctrl + A to select all existing text
        #         pag.hotkey("del")  # Delete existing text
        #     pag.typewrite(get_keyboard_input("Attachment Folder"))  # Type attachment folder path
        #     pag.hotkey("enter")  # Press Enter to confirm the folder path
        #     pag.click(get_mouse_coords("Attachment Folder Inside"))  # Click "Attachment Folder" input box inside the file dialog to ensure it has focus
        #     if send_mail_switch:  # to avoid delete files in demo mode
        #         pag.hotkey("ctrl", "a")  # Ctrl + A to select all existing text
        #     pag.click(get_mouse_coords("Attachment Confirm"))  # Click "Confirm" button to add attachment
        #     time.sleep(10)  # Wait for the attachment to be added
            
        #     # Send email or demo only?
        #     if send_mail_switch:
        #         pag.click(get_mouse_coords("Confirm Send"))  # Click "Send" button to send email
        #         time.sleep(send_mail_interval)
        #     else:
        #         print('[Demo] Email not sent. The loop will break after the first iteration.')
        #         break  # Demo only, break after the first iteration

        # print("") # blank line
            

    # End of script