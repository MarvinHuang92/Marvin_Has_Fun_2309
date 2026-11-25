# -*- coding: utf-8 -*-
"""赛道候选/启用状态/启动选择的公共逻辑。

- 主配置 ``cfg/sim.json``：地图定义、下一局起点 ``maps.startup``；
- 管理器配置 ``cfg/track_manager.json``：禁用列表、排序、GUI 生成参数；
- 种子文件 ``cfg/seeds/``：版本+时间戳+种子号命名，不随 git 追踪。
"""
import copy
import datetime
import hashlib
import json
import os
import tempfile

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAIN_CONFIG = os.path.join(PROJECT, "cfg", "sim.json")
MANAGER_CONFIG = os.path.join(PROJECT, "cfg", "track_manager.json")
SEEDS_DIR = os.path.join(PROJECT, "cfg", "seeds")

DEFAULT_MANAGER = {
    "disabled": [],
    "sort_key": "number",
    "sort_reverse": False,
    "generator": {},
}


def _read_json(path, fallback):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (IOError, OSError, ValueError, TypeError):
        return copy.deepcopy(fallback)


def _write_json(path, data):
    folder = os.path.dirname(os.path.abspath(path))
    if folder and not os.path.isdir(folder):
        os.makedirs(folder)
    fd, temp_path = tempfile.mkstemp(prefix=".tmp_", suffix=".json",
                                     dir=folder)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=1)
            handle.write("\n")
        os.replace(temp_path, path)
    finally:
        try:
            if os.path.exists(temp_path):
                os.remove(temp_path)
        except OSError:
            pass


def load_manager(project=PROJECT):
    path = os.path.join(project, "cfg", "track_manager.json")
    data = _read_json(path, DEFAULT_MANAGER)
    result = copy.deepcopy(DEFAULT_MANAGER)
    result.update(data or {})
    disabled = result.get("disabled") or []
    result["disabled"] = [str(item) for item in disabled]
    return result


def save_manager(manager, project=PROJECT):
    path = os.path.join(project, "cfg", "track_manager.json")
    _write_json(path, manager)


def seed_filename(version, timestamp, seed):
    """文件名包含生成器版本、生成时间戳、种子号。"""
    safe_version = str(version).replace("/", "_").replace("\\", "_")
    return "seed_v%s_%s_%s.json" % (
        safe_version, str(timestamp), str(seed))


def create_seed_file(project, version, seed, params, track_id, track_file,
                     timestamp=None):
    """写一个种子文件；返回相对项目根的路径。不删除旧文件。"""
    folder = os.path.join(project, "cfg", "seeds")
    os.makedirs(folder, exist_ok=True)
    stamp = timestamp or datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    name = seed_filename(version, stamp, seed)
    path = os.path.join(folder, name)
    base, ext = os.path.splitext(name)
    suffix = 2
    while os.path.exists(path):
        name = "%s_%d%s" % (base, suffix, ext)
        path = os.path.join(folder, name)
        suffix += 1
    record = {
        "generator": "scripts/build_random_track.py",
        "generator_version": str(version),
        "seed": int(seed),
        "timestamp": stamp,
        "seed_file": "cfg/seeds/%s" % name,
        "params": copy.deepcopy(params or {}),
        "track_id": str(track_id),
        "track_file": str(track_file),
    }
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(record, handle, ensure_ascii=False, indent=1)
        handle.write("\n")
    return "cfg/seeds/%s" % name


def main_config_path(project=PROJECT):
    return os.path.join(project, "cfg", "sim.json")


def load_main_config(project=PROJECT):
    return _read_json(main_config_path(project), {})


def save_main_config(config, project=PROJECT):
    _write_json(main_config_path(project), config)


def map_list(config):
    return list(((config.get("maps", {}) or {}).get("list") or []))


def is_random_map(map_def):
    if map_def.get("random"):
        return True
    map_id = str(map_def.get("id", ""))
    return map_id.startswith("auto_") or map_id.startswith("random_")


def _track_file_hash(map_def, project):
    path = map_def.get("file", "")
    if path and not os.path.isabs(path):
        path = os.path.join(project, path)
    try:
        with open(path, "rb") as handle:
            return hashlib.sha256(handle.read()).hexdigest()
    except (IOError, OSError):
        return "missing"


def track_uid(map_def, project=PROJECT):
    """最快圈唯一键：固定赛道用 id，随机赛道直接用种子文件名。

    种子文件名包含生成器版本+时间戳+种子号，删除旧赛道再生成新赛道时
    不会与旧记录相撞；即使显示名称/map id 被复用也没有关系。
    """
    map_id = str(map_def.get("id", ""))
    if not is_random_map(map_def):
        return "fixed:%s" % map_id
    seed_file = str(map_def.get("seed_file", "") or "")
    if seed_file:
        # 种子文件名已经包含版本+时间戳+种子号，直接作为唯一键
        return "seed:%s" % os.path.basename(seed_file)
    digest = hashlib.sha256(
        _track_file_hash(map_def, project).encode("utf-8")).hexdigest()[:24]
    return "random:%s" % digest


def migrate_best_laps(best_laps, maps, project=PROJECT):
    """把旧版按 map id 保存的最快圈迁移到新的 uid 键。"""
    by_id = {str(item.get("id", "")): item for item in maps}
    result = {}
    for key, value in (best_laps or {}).items():
        key = str(key)
        if key in by_id:
            result[track_uid(by_id[key], project)] = value
        else:
            result[key] = value
    return result


def available_maps(maps, manager):
    disabled = set(manager.get("disabled") or [])
    return [item for item in maps
            if str(item.get("id", "")) not in disabled]


def _next_available_after(all_maps, available, map_id, fallback_first=True):
    ids = [str(item.get("id", "")) for item in all_maps]
    available_ids = {str(item.get("id", "")) for item in available}
    if not available:
        return None
    if map_id not in ids:
        return str(available[0].get("id", "")) if fallback_first else None
    start = ids.index(map_id)
    for offset in range(1, len(ids) + 1):
        candidate = ids[(start + offset) % len(ids)]
        if candidate in available_ids:
            return candidate
    return None


def select_map_index(all_maps, available, startup_id, saved_id, default_id):
    """返回在 available 列表中的索引；没有可用赛道返回 None。"""
    if not available:
        return None
    available_ids = [str(item.get("id", "")) for item in available]

    # 1) GUI 指定的下次启动赛道（一次性）
    if startup_id and startup_id in available_ids:
        return available_ids.index(startup_id)
    if startup_id:
        candidate = _next_available_after(all_maps, available, startup_id)
        if candidate in available_ids:
            return available_ids.index(candidate)

    # 2) 上次退出的赛道
    if saved_id and saved_id in available_ids:
        return available_ids.index(saved_id)
    if saved_id:
        candidate = _next_available_after(all_maps, available, saved_id)
        if candidate in available_ids:
            return available_ids.index(candidate)

    # 3) 默认赛道
    if default_id and default_id in available_ids:
        return available_ids.index(default_id)
    return 0


def read_session(project=PROJECT, config=None):
    config = config or load_main_config(project)
    maps_cfg = config.get("maps", {}) or {}
    session_file = maps_cfg.get("session_file", "data/last_map.json")
    path = session_file if os.path.isabs(session_file) else os.path.join(
        project, session_file)
    saved = _read_json(path, {})
    return str(saved.get("id", "")), dict(saved.get("best_laps") or {})


def take_startup_id(project=PROJECT):
    """读取并清除 ``maps.startup``（一次性“下次启动”选择）。"""
    config = load_main_config(project)
    maps_cfg = config.setdefault("maps", {})
    startup = maps_cfg.get("startup")
    if startup:
        maps_cfg["startup"] = None
        save_main_config(config, project)
    return str(startup) if startup else None


def set_startup_id(map_id, project=PROJECT):
    config = load_main_config(project)
    maps_cfg = config.setdefault("maps", {})
    maps_cfg["startup"] = map_id
    save_main_config(config, project)


def append_map(map_def, project=PROJECT):
    config = load_main_config(project)
    maps = config.setdefault("maps", {}).setdefault("list", [])
    maps.append(map_def)
    save_main_config(config, project)


def remove_map(map_id, project=PROJECT):
    config = load_main_config(project)
    maps_cfg = config.setdefault("maps", {})
    maps_cfg["list"] = [item for item in (maps_cfg.get("list") or [])
                        if str(item.get("id", "")) != str(map_id)]
    if maps_cfg.get("startup") == map_id:
        maps_cfg["startup"] = None
    save_main_config(config, project)
