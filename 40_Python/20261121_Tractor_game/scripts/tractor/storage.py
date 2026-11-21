"""Small JSON storage for deal records and window settings."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, Optional


def save_deal(record: Dict[str, Any], data_dir: Path) -> Optional[Path]:
    """Save one deal record.  Returns the path or None on failure."""
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        deal_no = int(record.get("deal_no", 0))
        path = data_dir / f"deal_{stamp}_{deal_no:03d}.json"
        text = json.dumps(record, ensure_ascii=False, indent=2)
        path.write_text(text, encoding="utf-8")
        (data_dir / "last_deal.json").write_text(text, encoding="utf-8")
        return path
    except OSError:
        return None


def load_window_geometry(cfg_dir: Path) -> Optional[str]:
    path = cfg_dir / "window.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        geo = data.get("geometry")
        if isinstance(geo, str) and "x" in geo:
            return geo
    except (OSError, ValueError):
        pass
    return None


def save_window_geometry(cfg_dir: Path, geometry: str) -> None:
    try:
        cfg_dir.mkdir(parents=True, exist_ok=True)
        (cfg_dir / "window.json").write_text(
            json.dumps({"geometry": geometry}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError:
        pass
