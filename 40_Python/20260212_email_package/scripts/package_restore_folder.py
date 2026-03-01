# -*- coding: utf-8 -*-

import os
import sys
import shutil

from common_config import (
    delimiter_for_display,
    format_timestamp_value,
    ignore_extension_list,
    keep_extension,
    read_timestamp_from_structure,
)

def _should_ignore_file(file_name):
    _, extension = os.path.splitext(file_name)
    return extension.lower() in [item.lower() for item in ignore_extension_list]

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


def _build_structure_lines(root_dir, counter, level=0, base_root=None, ignored_counter=None):
    if base_root is None:
        base_root = root_dir
    if ignored_counter is None:
        ignored_counter = {"value": 1}
    lines = []
    file_entries = []
    ignored_files = []
    dirs, files = _list_dir_entries(root_dir)
    for name in dirs:
        prefix = "" if level == 0 else "| " * (level - 1) + "|-"
        line_text = _format_id_line(counter, "[D] " + prefix + name)
        lines.append(line_text)
        child_dir = os.path.join(root_dir, name)
        child_lines, child_files, child_ignored_files = _build_structure_lines(child_dir, counter, level + 1, base_root, ignored_counter)
        lines.extend(child_lines)
        file_entries.extend(child_files)
        ignored_files.extend(child_ignored_files)
    for name in files:
        src_path = os.path.join(root_dir, name)
        if _should_ignore_file(name):
            relative_path = os.path.relpath(src_path, base_root).replace("\\", "/")
            ignored_index_text = str(ignored_counter["value"]).zfill(2)
            ignored_counter["value"] += 1
            print("[Ignored] [{0}] Skip file: {1}".format(ignored_index_text, relative_path))
            ignored_files.append(relative_path)
            continue
        prefix = "" if level == 0 else "| " * (level - 1) + "|-"
        line_text = _format_id_line(counter, "[F] " + prefix + name)
        lines.append(line_text)
        file_entries.append((line_text.split("  ", 1)[0], src_path))
    return lines, file_entries, ignored_files


def _prepare_package_dir(attachment_dir):
    package_dir = os.path.join(attachment_dir, "package")
    if os.path.isdir(package_dir):
        print("") # blank line
        print("[Warning] package directory exists, clearing: {0}".format(package_dir))
        for entry in os.listdir(package_dir):
            entry_path = os.path.join(package_dir, entry)
            if os.path.isdir(entry_path):
                shutil.rmtree(entry_path)
            else:
                os.remove(entry_path)
    else:
        os.makedirs(package_dir)
    return package_dir


def _build_packaged_filename(file_id, src_path):
    if not keep_extension:
        return file_id
    _, extension = os.path.splitext(src_path)
    if not extension:
        return file_id
    return "{0}{1}".format(file_id, extension)


def _find_packaged_file_path(package_dir, entry_id, original_name):
    exact_path = os.path.join(package_dir, entry_id)
    if os.path.isfile(exact_path):
        return exact_path

    _, original_extension = os.path.splitext(original_name)
    if original_extension:
        candidate_with_ext = os.path.join(package_dir, "{0}{1}".format(entry_id, original_extension))
        if os.path.isfile(candidate_with_ext):
            return candidate_with_ext

    prefix = "{0}.".format(entry_id)
    try:
        for package_name in os.listdir(package_dir):
            if package_name.startswith(prefix):
                matched_path = os.path.join(package_dir, package_name)
                if os.path.isfile(matched_path):
                    return matched_path
    except OSError:
        return None

    return None


def generate_dir_structure_doc(input_dir, attachment_dir):
    root_path = os.path.abspath(input_dir)
    counter = {"value": 1}
    structure_lines, file_entries, ignored_files = _build_structure_lines(root_path, counter)
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
    lines.append(delimiter_for_display)
    lines.append("")
    lines.append("dir structure:")
    lines.extend(structure_lines)
    lines.append("")
    lines.append("ignored_files:")
    if ignored_files:
        number_width = max(2, len(str(len(ignored_files))))
        for index, ignored_path in enumerate(ignored_files, start=1):
            lines.append("{0}. {1}".format(str(index).zfill(number_width), ignored_path))
    else:
        lines.append("N/A")
    lines.append("")
    lines.append(delimiter_for_display)
    lines.append("")
    lines.append("date & time:")
    lines.append(__import__('datetime').datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    if not os.path.isdir(attachment_dir):
        os.makedirs(attachment_dir)

    output_path = os.path.join(attachment_dir, "dir_structure.txt")
    with open(output_path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))

    package_dir = _prepare_package_dir(attachment_dir)
    for file_id, src_path in file_entries:
        packaged_name = _build_packaged_filename(file_id, src_path)
        dest_path = os.path.join(package_dir, packaged_name)
        shutil.copyfile(src_path, dest_path)
    return output_path


def _read_structure_entries(dir_structure_file_path):
    with open(dir_structure_file_path, "r", encoding="utf-8") as handle:
        raw_lines = [line.rstrip("\n") for line in handle]

    start_index = None
    end_index = None
    for idx, line in enumerate(raw_lines):
        if line.strip() == "dir structure:":
            start_index = idx + 1
        elif start_index is not None and line.strip() in ["ignored_files:", delimiter_for_display]:
            end_index = idx
            break
    if start_index is None:
        return [], ""
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

    timestamp_suffix = format_timestamp_value(read_timestamp_from_structure(dir_structure_file_path))

    return entries, timestamp_suffix


def restore_from_package(attachment_dir, output_dir):
    if not os.path.isdir(output_dir):
        os.makedirs(output_dir)

    dir_structure_file_path = os.path.join(attachment_dir, "dir_structure.txt")
    if not os.path.isfile(dir_structure_file_path):
        print("[Error] dir_structure.txt not found in: {0}".format(attachment_dir))
        return

    entries, timestamp_suffix = _read_structure_entries(dir_structure_file_path)
    package_dir = os.path.join(attachment_dir, "package")
    if not os.path.isdir(package_dir):
        print("[Error] package directory not found in: {0}".format(attachment_dir))
        return

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
    missing_file_count = 0
    missing_dir_count = 0
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
            try:
                os.makedirs(dir_path, exist_ok=True)
                stack = stack[:depth] + [name]
            except FileNotFoundError as e:
                print('Error: id {0} directory "{1}": {2}'.format(entry_id, name, str(e)))
                missing_dir_count += 1
                continue
        else:
            file_path = os.path.join(output_root, *stack, name)
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            src_path = _find_packaged_file_path(package_dir, entry_id, name)
            if (not src_path) or (not os.path.isfile(src_path)):
                print('Warning: id {0} file "{1}" missing'.format(entry_id, name))
                missing_file_count += 1
                continue
            try:
                shutil.copyfile(src_path, file_path)
                restored_count += 1
            except FileNotFoundError as e:
                print('Error: id {0} file "{1}": {2}'.format(entry_id, name, str(e)))
                missing_file_count += 1
                continue

    print("[Done] Output: {0}".format(output_root))
    print("[Done] Restored files: {0}, missing files: {1}, missing directories: {2}".format(restored_count, missing_file_count, missing_dir_count))

    dir_structure_copy_name = "dir_structure_{0}.txt".format(timestamp_suffix)
    dir_structure_copy_path = os.path.join(output_dir, dir_structure_copy_name)
    shutil.copyfile(dir_structure_file_path, dir_structure_copy_path)




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

    print(delimiter_for_display)
    if command_type == "package":
        generate_dir_structure_doc(input_dir, attachment_dir)
    elif command_type == "restore":
        restore_from_package(attachment_dir, output_dir)

    print(delimiter_for_display)
    # End of script