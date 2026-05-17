# -*- coding: utf-8 -*-

# 获取当前鼠标坐标，调整mouse_locations中的坐标值以适配不同屏幕分辨率或邮件客户端界面布局

import time
import msvcrt
# import tkinter as tk
import pyautogui as pag


# def copy_to_clipboard(text):
#     root = tk.Tk()
#     root.withdraw()
#     root.clipboard_clear()
#     root.clipboard_append(text)
#     root.update()
#     root.destroy()


if __name__ == '__main__':

    print("Tracking mouse position and RGB in real time.")
    print("Press Space to freeze/copy; press Space again to resume; press Ctrl+C to stop.")
    frozen = False
    frozen_x = 0
    frozen_y = 0
    frozen_color = (0, 0, 0)
    try:
        while True:
            if msvcrt.kbhit():
                key = msvcrt.getwch()
                if key == " ":
                    if not frozen:
                        frozen_x, frozen_y = pag.position()
                        frozen_color = pag.pixel(frozen_x, frozen_y)
                        frozen = True
                        copied_text = "({}, {}) | RGB: {}".format(frozen_x, frozen_y, frozen_color)
                        # copy_to_clipboard(copied_text)
                        print("\n[Frozen] Copied to clipboard: {}".format(copied_text))
                    else:
                        frozen = False
                        print("\n[Resume] Live tracking resumed.")

            if frozen:
                display_x, display_y = frozen_x, frozen_y
                display_color = frozen_color
                status = "FROZEN"
            else:
                display_x, display_y = pag.position()
                display_color = pag.pixel(display_x, display_y)
                status = "LIVE"

            print("\r[{}] Current mouse position: ({}, {}) | RGB: {}".format(status, display_x, display_y, display_color), end="", flush=True)
            time.sleep(0.05)
    except KeyboardInterrupt:
        print("\nStopped.")

    # End of script