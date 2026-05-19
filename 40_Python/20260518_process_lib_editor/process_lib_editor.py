# Process Lib Editor
from operator import index
import logging, os

ignore_pattern = ['DAS Process Landscape - Release 26.1',
                  'Intern / Printouts and local copies of this']
invalid_characters = ['<', '>', ':', '"', '/', '\\', '|', '?', '*']
print_info_01 = False
print_info_02 = False
create_folder_switch = False

class DirectoryInfo:
    def __init__(self, section, directory_name, parent_index):
        self.section = section
        self.directory_name = directory_name
        self.parent_index = parent_index
        self.is_bottom_level = True
        self.full_path = None

# 删除字符串中的连续三个.字符，以及以后的内容
def remove_dots_and_after(input_string):
    if "..." in input_string:
        return input_string.split("...")[0]
    return input_string

# 读取目录信息txt文件
def read_directory_info():
    directories = []
    try:
        with open("directory_info.txt", "r") as file:
            contents = file.readlines()
    except FileNotFoundError:
        logging.error("directory_info.txt not found.")
        return 1
    
    # 解析目录信息
    for line in contents:
        # 如果一行内包含连续三个.字符
        if "..." in line:
            # 如果开头第一个有效字符是数字（代表章节号），则认为这一行是有效信息，去掉连续三个.字符以及以后的内容后添加到目录列表中
            stripped_line = line.strip()
            if stripped_line and stripped_line[0].isdigit():
                directories.append(remove_dots_and_after(stripped_line))
            # 如果不是数字开头，则将这一行作为上一行的结尾，与上一行合并成一个新行，替换掉上一行的内容，
            # 并且保留本行连续三个.字符之前的部分
            else:
                if directories:
                    previous_line = directories[-1]
                    # 上一行一定已经去掉连续三个.字符以及以后的内容了，所以这里不需要处理上一行，只处理本行即可
                    new_line = previous_line + " " + remove_dots_and_after(line.strip())
                    directories[-1] = new_line
                else:
                    logging.warning(f"Ignoring invalid line (no previous line to merge): {line.strip()}")
        else:  # 如果一行内不包含连续三个.字符
            # 如果 ignore_pattern 中的任意一个字符串出现在 line 中，则认为是无效信息，忽略
            if any(pattern in line for pattern in ignore_pattern):
                logging.warning(f"Ignoring line due to ignore pattern: {line.strip()}")
                continue
            # 否则，认为是普通行（例如太长一行写不下），可以添加到目录列表中
            stripped_line = line.strip()
            if stripped_line:
                directories.append(stripped_line)
    
    # 打印解析后的目录列表
    if print_info_01:
        logging.info("Parsed directories:")
        for directory in directories:
            logging.info(f" - {directory}")

    return directories

# 转换目录格式，将文本列表转换为DirectoryInfo对象列表
def convert_directory_format(directories):
    converted_directories = []
    for directory in directories:
        # 用空格切分目录信息，第一个空格之前部分为section，所有部分(包含section + 空格)为 directory_name, 其中不包含 parent_index，其等到稍后处理
        parts = directory.split()
        if len(parts) >= 2:
            section = parts[0]
            directory_name = directory.strip()
            # 删除 directory_name 中的无效字符
            for char in invalid_characters:
                directory_name = directory_name.replace(char, "")
            # section 去掉最后一个.字符及以后部分，将剩余部分在已经存在的列表元素中查找，如和某一个元素的section一致，将此元素的index作为 parent_index
            # 并且将 parent_index 对应的元素的 is_bottom_level 设置为 False
            parent_index = None
            section_base = section.rsplit('.', 1)[0] if '.' in section else section
            for i, existing_directory in enumerate(converted_directories):
                existing_section = existing_directory.section
                if existing_section == section_base:
                    parent_index = i
                    converted_directories[i].is_bottom_level = False
                    break
            converted_directories.append(DirectoryInfo(section, directory_name, parent_index))
        else:
            logging.warning(f"Ignoring invalid directory format: {directory}")
    
    # 根据 parent_index 构建 full_path
    for directory in converted_directories:
        if directory.parent_index is not None:
            parent_directory = converted_directories[directory.parent_index]
            # 优先使用 parent_directory.full_path，如果为空，则使用 parent_directory.directory_name
            directory.full_path = os.path.join(parent_directory.full_path or parent_directory.directory_name, directory.directory_name)
        else:
            directory.full_path = directory.directory_name

    # 打印目录信息
    if print_info_02:
        logging.info("Converted directories:")
        for directory in converted_directories:
            logging.info(f" - {directory.section} {directory.directory_name} (parent_index: {directory.parent_index}, full_path: {directory.full_path})")

    return converted_directories

# 根据目录创建文件夹结构
def create_folder_structure(root_path="."):

    directories = read_directory_info()
    if directories == 1:  # 读取目录信息失败，返回错误码
        return 1
    
    converted_directories = convert_directory_format(directories)

    if create_folder_switch:
        for directory in converted_directories:
            dir_path = os.path.join(root_path, directory.full_path)
            # 如果 bottom_level 属性为真，则忽略此目录，不创建文件夹
            if dir_path and not directory.is_bottom_level:
                try:
                    # 创建文件夹，如果已经存在则忽略
                    os.makedirs(dir_path, exist_ok=True)
                    logging.info(f"Created folder: {dir_path}")
                except Exception as e:
                    logging.error(f"Error creating folder {dir_path}: {e}")
                    continue
    return 0


if __name__ == "__main__":
    # 设置 logging.info 显示在控制台
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

    # print_info_01 = True
    # print_info_02 = True
    create_folder_switch = True

    create_folder_structure("./output")
