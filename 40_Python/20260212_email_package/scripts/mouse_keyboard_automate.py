# -*- coding: utf-8 -*-

# 使用python控制鼠标键盘，自动操作foxmail（或其它任何邮件客户端）发送邮件

import os, sys, time
import pyautogui as pag

from common_config import (
    delimiter_for_display,
    format_timestamp_value,
    read_timestamp_from_structure,
)

# 窗口按钮坐标（需要根据实际情况调整）
mouse_locations = [
{"usage":"New Email", "coords": (188, 52)},  # 新建邮件按钮
{"usage":"Recipient", "coords": (590, 404)},  # 收件人输入框
{"usage":"Mail Subject", "coords": (590, 522)},  # 邮件主题输入框
{"usage":"Add Attachment", "coords": (740, 350)},  # 添加附件按钮
{"usage":"Attachment Folder", "coords": (871, 640)},  # 附件文件夹输入框
{"usage":"Attachment Folder Inside", "coords": (871, 585)},  # 附件文件夹输入框内部坐标（用于点击以获得焦点）
{"usage":"Attachment Confirm", "coords": (1270, 640)},  # 确认添加附件按钮
{"usage":"Confirm Send", "coords": (527, 348)},  # 确认发送按钮
]

keyboard_inputs = [
{"usage":"Recipient", "input": "example@example.com"},  # 收件人输入框
{"usage":"Mail Subject", "input": "dummy"},  # 邮件主题输入框
{"usage":"Attachment Folder", "input": "dummy"},  # 附件文件夹输入框
]

# 发送邮件等待时间(s)
send_mail_interval = 25

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
    if len(sys.argv) != 4:
        print('Usage: python send_email_with_auto_packed_attachments.py <receiver> <test_mode_Y/N> <start_attch_id>')
        sys.exit(1)
    receiver = str(sys.argv[1]).strip()  # Email receiver
    test_mode = str(sys.argv[2]).strip()  # Y = demo only, N = send email
    start_attch_id = int(sys.argv[3])  # Start attachment ID for this run (e.g. 1 means start from the first attachment in the list)

    print(delimiter_for_display)

    # Generate Message or Send Email?
    send_mail_switch = test_mode == "N" or test_mode == "n"

    # check if attachment folder exists
    attachment_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "attachments"))
    dir_structure_file_path = os.path.join(attachment_dir, "dir_structure.txt")

    if not os.path.isdir(attachment_dir):
        print('[Error] Attachment folder does not exist: %s' % attachment_dir)
    elif not os.path.isfile(dir_structure_file_path):
        print('[Error] dir_structure.txt does not exist in attachment folder: %s' % dir_structure_file_path)
    else:
        # get the date and time from attachments/dir_structure.txt
        timestamp_suffix = format_timestamp_value(read_timestamp_from_structure(dir_structure_file_path))
        mail_package_root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "mails/mail_%s/package" % timestamp_suffix))
        print('Attachment folder: %s' % attachment_dir)
        print('Mail package root directory: %s' % mail_package_root_dir)

        # get mail package total count
        mail_packages_count = 0
        if os.path.isdir(mail_package_root_dir):
            for item in os.listdir(mail_package_root_dir):
                item_path = os.path.join(mail_package_root_dir, item)
                if os.path.isdir(item_path):
                    mail_packages_count += 1
        print('Total mail packages found: %d' % mail_packages_count)
        
        # Set recipient input for keyboard automation
        set_keyboard_input("Recipient", receiver)

        # Start mouse and keyboard automation loop, to send email
        for i in range(start_attch_id, mail_packages_count + 1):
            mail_subject = "mail_{0}".format(i)
            mail_package_dir = os.path.join(mail_package_root_dir, str(i))
            print("[%d%%] [%d/%d] Processing mail package: %s" % (100.0*i/mail_packages_count, i, mail_packages_count, mail_package_dir))

            # Set mail subject and attachment folder input for keyboard automation
            set_keyboard_input("Mail Subject", mail_subject)
            set_keyboard_input("Attachment Folder", mail_package_dir)

            # Mouse and keyboard operations
            pag.click(get_mouse_coords("New Email"))  # Click "New Email" button
            time.sleep(2)  # Wait for the new email dialog to open

            # recipient
            pag.click(get_mouse_coords("Recipient"))  # Click recipient input box
            pag.typewrite(get_keyboard_input("Recipient"))  # Type recipient email address

            # mail subject
            pag.click(get_mouse_coords("Mail Subject"))  # Click mail subject input box
            pag.typewrite(get_keyboard_input("Mail Subject"))  # Type mail subject

            # attachment
            pag.click(get_mouse_coords("Add Attachment"))  # Click "Add Attachment" button
            time.sleep(2)  # Wait for the file dialog to open
            pag.click(get_mouse_coords("Attachment Folder"))  # Click "Attachment Folder" input box
            if send_mail_switch:  # to avoid delete files in demo mode
                pag.hotkey("ctrl", "a")  # Ctrl + A to select all existing text
                pag.hotkey("del")  # Delete existing text
            pag.typewrite(get_keyboard_input("Attachment Folder"))  # Type attachment folder path
            pag.hotkey("enter")  # Press Enter to confirm the folder path
            pag.click(get_mouse_coords("Attachment Folder Inside"))  # Click "Attachment Folder" input box inside the file dialog to ensure it has focus
            if send_mail_switch:  # to avoid delete files in demo mode
                pag.hotkey("ctrl", "a")  # Ctrl + A to select all existing text
            pag.click(get_mouse_coords("Attachment Confirm"))  # Click "Confirm" button to add attachment
            time.sleep(6)  # Wait for the attachment to be added
            
            # Send email or demo only?
            if send_mail_switch:
                pag.click(get_mouse_coords("Confirm Send"))  # Click "Send" button to send email
                time.sleep(send_mail_interval)
            else:
                print('[Demo] Email not sent. The loop will break after the first iteration.')
                break  # Demo only, break after the first iteration

        print("") # blank line
            

    print(delimiter_for_display)
    # End of script