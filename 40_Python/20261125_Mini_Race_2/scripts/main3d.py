# -*- coding: utf-8 -*-
"""Panda3D 3D 原型启动器。

用法：
    python scripts/main3d.py
    python scripts/main3d.py --map shanghai
    python scripts/main3d.py --screenshot data/3d_oval.png --map oval
"""
import argparse
import os
import sys

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_DIR, "scripts"))


def main():
    parser = argparse.ArgumentParser(description="Mini Race 2 Panda3D 3D 原型")
    parser.add_argument("--map", default=None, help="circle / oval / shanghai")
    parser.add_argument("--screenshot", default=None,
                        help="离屏渲染并保存 PNG 后退出")
    parser.add_argument("--frames", type=int, default=12,
                        help="截图前渲染帧数")
    parser.add_argument("--car-at", default=None,
                        help="可选：把车放到赛道中心线进度 0..1（截图用）")
    parser.add_argument("--camera", choices=("rear", "front"), default="rear",
                        help="截图用相机视角")
    args = parser.parse_args()

    from minirace3d.app3d import App3D
    app = App3D(map_id=args.map, offscreen=bool(args.screenshot))
    try:
        if args.camera == "front":
            app.cam_mode = 1
            app._update_camera(0.0, snap=True)
        if args.car_at:
            progress = float(args.car_at)
            track = app.sim.track
            points = track.points
            index = int(progress * len(points)) % len(points)
            nxt = (index + 1) % len(points)
            x, y = points[index]
            heading = __import__("math").atan2(points[nxt][1] - y,
                                                points[nxt][0] - x)
            app.sim.vehicle.reset(x, y, heading)
            app.sim.trail.clear()
            app.sim.telemetry = None
            app._place_car()
            app._update_camera(0.0, snap=True)
            app.taskMgr.step()
        if args.screenshot:
            app.screenshot(args.screenshot, frames=args.frames)
        else:
            app.run()
    finally:
        app.destroy()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
