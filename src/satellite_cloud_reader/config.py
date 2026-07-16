from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


if getattr(sys, "frozen", False):
    ROOT_DIR = Path(sys.executable).resolve().parent
else:
    ROOT_DIR = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT_DIR / "config.json"
CACHE_DIR = ROOT_DIR / "cache"
REPORTS_DIR = ROOT_DIR / "reports"


@dataclass(slots=True)
class AppConfig:
    default_bbox: tuple[float, float, float, float] = (70.0, 15.0, 140.0, 55.0)
    lookback_days: int = 7
    trend_count: int = 3
    stable_threshold_percent: float = 5.0
    cloud_layers: tuple[str, ...] = (
        "MODIS_Aqua_Cloud_Fraction_Day",
        "MODIS_Terra_Cloud_Fraction_Day",
    )
    preview_layers: tuple[str, ...] = (
        "MODIS_Aqua_CorrectedReflectance_TrueColor",
        "MODIS_Terra_CorrectedReflectance_TrueColor",
    )
    image_width: int = 900
    image_height: int = 520
    google_maps_api_key: str = ""


def _tuple(value: Any, fallback: tuple[Any, ...]) -> tuple[Any, ...]:
    if isinstance(value, list | tuple):
        return tuple(value)
    return fallback


def load_config(path: Path = CONFIG_PATH) -> AppConfig:
    if not path.exists():
        return AppConfig()

    data = json.loads(path.read_text(encoding="utf-8"))
    defaults = AppConfig()
    return AppConfig(
        default_bbox=tuple(float(x) for x in _tuple(data.get("default_bbox"), defaults.default_bbox)),  # type: ignore[arg-type]
        lookback_days=int(data.get("lookback_days", defaults.lookback_days)),
        trend_count=int(data.get("trend_count", defaults.trend_count)),
        stable_threshold_percent=float(
            data.get("stable_threshold_percent", defaults.stable_threshold_percent)
        ),
        cloud_layers=tuple(str(x) for x in _tuple(data.get("cloud_layers"), defaults.cloud_layers)),
        preview_layers=tuple(str(x) for x in _tuple(data.get("preview_layers"), defaults.preview_layers)),
        image_width=int(data.get("image_width", defaults.image_width)),
        image_height=int(data.get("image_height", defaults.image_height)),
        google_maps_api_key=str(os.environ.get("GOOGLE_MAPS_API_KEY") or data.get("google_maps_api_key", "")),
    )


def save_config(config: AppConfig, path: Path = CONFIG_PATH) -> None:
    data = asdict(config)
    data["default_bbox"] = list(config.default_bbox)
    data["cloud_layers"] = list(config.cloud_layers)
    data["preview_layers"] = list(config.preview_layers)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
