# -*- coding: utf-8 -*-
"""赛道管理器/启动选择自检。"""
import json
import os
import shutil
import sys
import tempfile

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT, "scripts"))

import track_manager as tm  # noqa: E402

_passed = 0
_failed = []


def check(name, condition, detail=""):
    global _passed
    if condition:
        _passed += 1
        print("[PASS] %s" % name)
    else:
        _failed.append(name)
        print("[FAIL] %s  %s" % (name, detail))


def maps(ids):
    return [{"id": map_id, "number": index, "file": "cfg/%s.json" % map_id}
            for index, map_id in enumerate(ids)]


def main():
    all_maps = maps(["circle", "oval", "shanghai", "auto_1"])
    manager = {"disabled": ["oval", "auto_1"]}
    available = tm.available_maps(all_maps, manager)
    check("只保留启用赛道", [item["id"] for item in available]
          == ["circle", "shanghai"])
    check("上次赛道被禁用则找下一条",
          tm.select_map_index(all_maps, available, None, "oval", "circle") == 1)
    check("上次赛道被禁用且是最后一条则回绕",
          tm.select_map_index(all_maps, available, None, "auto_1",
                              "circle") == 0)
    check("GUI 指定的下次启动优先",
          tm.select_map_index(all_maps, available, "shanghai", "circle",
                              "circle") == 1)
    check("下次启动赛道被禁用则找下一条",
          tm.select_map_index(all_maps, available, "oval", "circle",
                              "circle") == 1)
    check("没有可用赛道返回 None",
          tm.select_map_index(all_maps, [], None, "circle", "circle") is None)
    check("默认赛道不可用时取第一条可用",
          tm.select_map_index(all_maps, available, None, "missing",
                              "oval") == 0)

    folder = tempfile.mkdtemp(prefix="track_manager_test_")
    try:
        os.makedirs(os.path.join(folder, "cfg"))
        main_cfg = {
            "maps": {
                "default": "circle",
                "session_file": "data/last_map.json",
                "list": maps(["circle", "oval"]),
            }
        }
        with open(os.path.join(folder, "cfg", "sim.json"), "w",
                  encoding="utf-8") as handle:
            json.dump(main_cfg, handle)
        tm.set_startup_id("oval", folder)
        loaded = tm.load_main_config(folder)
        check("startup 写入主配置 sim.json",
              loaded["maps"].get("startup") == "oval")
        startup = tm.take_startup_id(folder)
        after = tm.load_main_config(folder)
        check("startup 一次性读取后清除",
              startup == "oval" and after["maps"].get("startup") is None)
        tm.append_map({"id": "random_1", "number": 3,
                       "file": "cfg/tracks/track_random_1.json"}, folder)
        check("追加随机赛道",
              any(item["id"] == "random_1"
                  for item in tm.map_list(tm.load_main_config(folder))))
        tm.remove_map("random_1", folder)
        check("删除随机赛道",
              not any(item["id"] == "random_1"
                      for item in tm.map_list(tm.load_main_config(folder))))
        check("随机赛道识别",
              tm.is_random_map({"id": "auto_2"})
              and tm.is_random_map({"id": "random_9"})
              and not tm.is_random_map({"id": "shanghai"}))
        seed_path = tm.create_seed_file(
            folder, "1.0.0", 12345, {"lap_length_m": [1200, 1800]},
            "random_seed_test", "cfg/tracks/track_random_seed_test.json",
            timestamp="20260101_120000")
        seed_name = os.path.basename(seed_path)
        check("种子文件名含版本/时间戳/种子号",
              "v1.0.0" in seed_name and "20260101_120000" in seed_name
              and "12345" in seed_name)
        check("随机赛道 uid 由种子文件区分",
              tm.track_uid({"id": "random_x", "random": True,
                            "seed_file": "cfg/seeds/a.json"}) !=
              tm.track_uid({"id": "random_x", "random": True,
                            "seed_file": "cfg/seeds/b.json"}))
        check("固定赛道 uid 稳定",
              tm.track_uid({"id": "shanghai"}) ==
              tm.track_uid({"id": "shanghai"}))
        migrated = tm.migrate_best_laps(
            {"random_x": 61.2},
            [{"id": "random_x", "random": True,
              "seed_file": "cfg/seeds/a.json"}], folder)
        check("旧 map id 圈速迁移到种子文件键",
              list(migrated.values()) == [61.2]
              and list(migrated.keys())[0].startswith("seed:"))
        with open(os.path.join(folder, seed_path), "r", encoding="utf-8") as handle:
            seed_record = json.load(handle)
        check("种子文件记录版本和参数",
              seed_record.get("generator_version") == "1.0.0"
              and seed_record.get("seed") == 12345
              and seed_record.get("params") == {"lap_length_m": [1200, 1800]})
        tm.append_map({"id": "random_seed_test", "number": 4,
                       "file": "cfg/tracks/track_random_seed_test.json",
                       "seed_file": seed_path}, folder)
        tm.remove_map("random_seed_test", folder)
        check("删除赛道不删除种子文件",
              os.path.isfile(os.path.join(folder, seed_path)))
    finally:
        shutil.rmtree(folder, ignore_errors=True)

    print("\n%d/%d 项通过" % (_passed, _passed + len(_failed)))
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())
