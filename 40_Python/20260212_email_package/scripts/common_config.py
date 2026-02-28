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
    