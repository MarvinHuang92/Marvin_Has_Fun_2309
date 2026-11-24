# -*- coding: utf-8 -*-
"""车辆参数预设与自定义存档（纯标准库，可单测）。

- 固定预设槽位 1 买菜车 / 2 性能车 / 3 超跑：只能加载，不在 GUI 里改文件；
- 自定义：用户手动改任一性能参数后自动切到 4 自定义，可保存/加载多个 JSON；
- 预设只包含车辆性能相关分组，不包含 world / render / audio 等。
"""
import json
import os

PRESET_SECTIONS = ("vehicle", "tires", "drivetrain", "engine", "aero",
                   "brakes", "controls")
CUSTOM_SECTIONS = ("world",) + PRESET_SECTIONS

PRESET_SLOTS = (
    (1, "买菜车", "grocery", "preset_1_grocery.json"),
    (2, "性能车", "sport", "preset_2_sport.json"),
    (3, "超跑", "supercar", "preset_3_supercar.json"),
)


def vehicles_dir(project_dir):
    return os.path.join(str(project_dir), "cfg", "vehicles")


def preset_path(project_dir, slot):
    for number, _name, _key, filename in PRESET_SLOTS:
        if int(slot) == number:
            return os.path.join(vehicles_dir(project_dir), filename)
    raise ValueError("未知预设槽位：%s" % slot)


def slot_by_key(key):
    for number, name, slot_key, _filename in PRESET_SLOTS:
        if key == slot_key:
            return number, name
    return None


def extract(config, sections=PRESET_SECTIONS):
    values = {}
    for section in sections:
        group = config.get(section)
        if isinstance(group, dict):
            values[section] = json.loads(json.dumps(group))
    return values


def apply(config, values):
    result = json.loads(json.dumps(config))
    for section, group in (values or {}).items():
        if isinstance(group, dict):
            target = result.setdefault(section, {})
            target.update(json.loads(json.dumps(group)))
    return result


def save_preset(project_dir, slot, config):
    path = preset_path(project_dir, slot)
    folder = os.path.dirname(path)
    if not os.path.isdir(folder):
        os.makedirs(folder)
    payload = {
        "slot": int(slot),
        "sections": extract(config, PRESET_SECTIONS),
    }
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return path


def load_preset(project_dir, slot):
    path = preset_path(project_dir, slot)
    with open(path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return payload.get("sections") or extract(payload)


def save_custom(path, config):
    folder = os.path.dirname(os.path.abspath(path))
    if folder and not os.path.isdir(folder):
        os.makedirs(folder)
    payload = {
        "kind": "mini-race-custom-vehicle",
        "sections": extract(config, CUSTOM_SECTIONS),
    }
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return path


def load_custom(path):
    with open(path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    sections = payload.get("sections")
    if not isinstance(sections, dict):
        raise ValueError("不是有效的车辆自定义存档：%s" % path)
    return sections
