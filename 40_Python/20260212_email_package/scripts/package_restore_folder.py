# -*- coding: utf-8 -*-

import os
import sys
import shutil
from datetime import datetime


def _list_dir_entries(current_dir):
    entries = []
    try:
        entries = os.listdir(current_dir)
    except OSError:
        return [], []
    dirs = []
    files = []
    for name in entries:
        full_path = os.path.join(current_dir, name)
        if os.path.isdir(full_path):
            dirs.append(name)
        else:
            files.append(name)
    dirs.sort(key=lambda s: s.lower())
    files.sort(key=lambda s: s.lower())
    return dirs, files


def _format_id_line(counter, line_text):
    id_value = counter["value"]
    counter["value"] += 1
    id_text = str(id_value).zfill(4)
    return "{0}  {1}".format(id_text, line_text)


def _build_structure_lines(root_dir, counter, level=0):
    lines = []
    file_entries = []
    dirs, files = _list_dir_entries(root_dir)
    for name in dirs:
        prefix = "" if level == 0 else "| " * (level - 1) + "|-"
        line_text = _format_id_line(counter, "[D] " + prefix + name)
        lines.append(line_text)
        child_dir = os.path.join(root_dir, name)
        child_lines, child_files = _build_structure_lines(child_dir, counter, level + 1)
        lines.extend(child_lines)
        file_entries.extend(child_files)
    for name in files:
        prefix = "" if level == 0 else "| " * (level - 1) + "|-"
        line_text = _format_id_line(counter, "[F] " + prefix + name)
        lines.append(line_text)
        file_entries.append((line_text.split("  ", 1)[0], os.path.join(root_dir, name)))
    return lines, file_entries


def _prepare_package_dir(attachment_dir):
    package_dir = os.path.join(attachment_dir, "package")
    if os.path.isdir(package_dir):
        print("Warning: package directory exists, clearing: {0}".format(package_dir))
        for entry in os.listdir(package_dir):
            entry_path = os.path.join(package_dir, entry)
            if os.path.isdir(entry_path):
                shutil.rmtree(entry_path)
            else:
                os.remove(entry_path)
    else:
        os.makedirs(package_dir)
    return package_dir


def generate_dir_structure_doc(input_dir, attachment_dir):
    root_path = os.path.abspath(input_dir)
    counter = {"value": 1}
    structure_lines, file_entries = _build_structure_lines(root_path, counter)
    if file_entries:
        first_attachment = os.path.basename(file_entries[0][1])
    else:
        first_attachment = "N/A"
    lines = []
    lines.append("root path:")
    lines.append(root_path)
    lines.append("")
    lines.append("first attachment:")
    lines.append(first_attachment)
    lines.append("")
    lines.append("==================================")
    lines.append("")
    lines.append("dir structure:")
    lines.extend(structure_lines)
    lines.append("")
    lines.append("==================================")
    lines.append("")
    lines.append("date & time:")
    lines.append(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    if not os.path.isdir(attachment_dir):
        os.makedirs(attachment_dir)

    output_path = os.path.join(attachment_dir, "dir_structure.txt")
    with open(output_path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))

    package_dir = _prepare_package_dir(attachment_dir)
    for file_id, src_path in file_entries:
        dest_path = os.path.join(package_dir, file_id)
        shutil.copyfile(src_path, dest_path)
    return output_path


def _read_structure_entries(structure_path):
    with open(structure_path, "r", encoding="utf-8") as handle:
        raw_lines = [line.rstrip("\n") for line in handle]

    start_index = None
    end_index = None
    for idx, line in enumerate(raw_lines):
        if line.strip() == "dir structure:":
            start_index = idx + 1
        elif start_index is not None and line.strip() == "==================================":
            end_index = idx
            break
    if start_index is None:
        return []
    if end_index is None:
        end_index = len(raw_lines)

    entries = []
    for line in raw_lines[start_index:end_index]:
        if not line.strip():
            continue
        parts = line.split("  ", 1)
        if len(parts) != 2:
            continue
        entry_id = parts[0].strip()
        content = parts[1].strip()
        is_dir = None
        if content.startswith("[D] "):
            is_dir = True
            content = content[4:]
        elif content.startswith("[F] "):
            is_dir = False
            content = content[4:]

        if "|-" in content:
            prefix, name = content.split("|-", 1)
            depth = prefix.count("| ") + 1
            name = name.strip()
        else:
            depth = 0
            name = content.strip()
        entries.append((entry_id, name, depth, is_dir))

    timestamp_value = ""
    for idx, line in enumerate(raw_lines):
        if line.strip() == "date & time:":
            for next_line in raw_lines[idx + 1:]:
                if next_line.strip():
                    timestamp_value = next_line.strip()
                    break
            break

    return entries, timestamp_value


def _format_timestamp_value(timestamp_value):
    if not timestamp_value:
        return datetime.now().strftime("%Y%m%d_%H%M%S")
    try:
        parsed = datetime.strptime(timestamp_value, "%Y-%m-%d %H:%M:%S")
        return parsed.strftime("%Y%m%d_%H%M%S")
    except ValueError:
        return datetime.now().strftime("%Y%m%d_%H%M%S")


def restore_from_package(attachment_dir, output_dir):
    if not os.path.isdir(output_dir):
        os.makedirs(output_dir)

    structure_path = os.path.join(attachment_dir, "dir_structure.txt")
    if not os.path.isfile(structure_path):
        print("[Error] dir_structure.txt not found in: {0}".format(attachment_dir))
        return

    entries, timestamp_value = _read_structure_entries(structure_path)
    package_dir = os.path.join(attachment_dir, "package")
    if not os.path.isdir(package_dir):
        print("[Error] package directory not found in: {0}".format(attachment_dir))
        return

    timestamp_suffix = _format_timestamp_value(timestamp_value)
    output_root = os.path.join(output_dir, "package_{0}".format(timestamp_suffix))
    if os.path.isdir(output_root):
        print("Warning: output directory exists, clearing: {0}".format(output_root))
        for entry in os.listdir(output_root):
            entry_path = os.path.join(output_root, entry)
            if os.path.isdir(entry_path):
                shutil.rmtree(entry_path)
            else:
                os.remove(entry_path)
    else:
        os.makedirs(output_root)

    stack = []
    restored_count = 0
    missing_count = 0
    for index, entry in enumerate(entries):
        entry_id, name, depth, is_dir = entry
        next_depth = None
        while len(stack) > depth:
            stack.pop()

        if is_dir is None:
            next_depth = entries[index + 1][2] if index + 1 < len(entries) else -1
            is_dir = next_depth > depth
        if is_dir:
            dir_path = os.path.join(output_root, *stack, name)
            os.makedirs(dir_path, exist_ok=True)
            stack = stack[:depth] + [name]
        else:
            file_path = os.path.join(output_root, *stack, name)
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            src_path = os.path.join(package_dir, entry_id)
            if not os.path.isfile(src_path):
                print('Warning: id {0} file "{1}" missing'.format(entry_id, name))
                missing_count += 1
                continue
            shutil.copyfile(src_path, file_path)
            restored_count += 1

    print("[Done] Output: {0}".format(output_root))
    print("[Done] Restored files: {0}, missing files: {1}".format(restored_count, missing_count))

    structure_copy_name = "dir_structure_{0}.txt".format(timestamp_suffix)
    structure_copy_path = os.path.join(output_dir, structure_copy_name)
    shutil.copyfile(structure_path, structure_copy_path)




if __name__ == '__main__':
    
    # Get inputs from command line arguments
    if (len(sys.argv) != 4) or (str(sys.argv[1]).strip() not in ["package", "restore"]):
        print('Usage: python package_restore_folder.py package <input_directory> <attachment_directory>')
        print('   Or: python package_restore_folder.py restore <attachment_directory> <output_directory>')
        sys.exit(1)
    command_type = str(sys.argv[1]).strip()
    input_dir = ""
    attachment_dir = ""
    output_dir = ""
    if command_type == "package":
        input_dir = str(sys.argv[2]).strip()
        attachment_dir = str(sys.argv[3]).strip()
    elif command_type == "restore":
        attachment_dir = str(sys.argv[2]).strip()
        output_dir = str(sys.argv[3]).strip()

    if command_type == "package":
        generate_dir_structure_doc(input_dir, attachment_dir)
    elif command_type == "restore":
        restore_from_package(attachment_dir, output_dir)

    # End of script