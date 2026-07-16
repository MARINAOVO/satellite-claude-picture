from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable

import requests
from PIL import Image, UnidentifiedImageError

from .analysis import is_blank_image


GIBS_WMS_URL = "https://gibs.earthdata.nasa.gov/wms/epsg4326/best/wms.cgi"
WORLDVIEW_BBOX = (-180.0, -90.0, 180.0, 90.0)
WORLDVIEW_REFERENCE_LAYER = "Coastlines"


class GibsError(RuntimeError):
    pass


@dataclass(slots=True)
class ImageResult:
    image: Image.Image
    path: Path
    layer: str
    date: date
    from_cache: bool
    url: str


class GibsClient:
    def __init__(self, cache_dir: Path, timeout_seconds: int = 30) -> None:
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.timeout_seconds = timeout_seconds

    def get_map(
        self,
        layer: str,
        target_date: date,
        bbox: tuple[float, float, float, float],
        width: int,
        height: int,
        force_refresh: bool = False,
    ) -> ImageResult:
        url = self._build_url(layer, target_date, bbox, width, height)
        image_path, meta_path = self._cache_paths(layer, target_date, bbox, width, height)

        if image_path.exists() and not force_refresh:
            try:
                cached = Image.open(image_path).convert("RGBA")
                if not self._is_invalid_file(image_path, cached):
                    return ImageResult(cached, image_path, layer, target_date, True, url)
            except (OSError, UnidentifiedImageError):
                pass
            image_path.unlink(missing_ok=True)

        try:
            response = requests.get(url, timeout=self.timeout_seconds)
            response.raise_for_status()
        except requests.RequestException as exc:
            if image_path.exists():
                cached = Image.open(image_path).convert("RGBA")
                return ImageResult(cached, image_path, layer, target_date, True, url)
            raise GibsError(f"NASA 请求失败：{exc}") from exc

        content_type = response.headers.get("Content-Type", "")
        if "image" not in content_type.lower():
            raise GibsError(f"NASA 返回的不是图片：{content_type}")

        image_path.write_bytes(response.content)
        meta_path.write_text(
            json.dumps(
                {
                    "url": url,
                    "layer": layer,
                    "date": target_date.isoformat(),
                    "bbox": list(bbox),
                    "width": width,
                    "height": height,
                    "content_type": content_type,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        try:
            image = Image.open(image_path).convert("RGBA")
        except (OSError, UnidentifiedImageError) as exc:
            image_path.unlink(missing_ok=True)
            raise GibsError("NASA 返回图片无法解析") from exc

        if self._is_invalid_file(image_path, image):
            image_path.unlink(missing_ok=True)
            meta_path.unlink(missing_ok=True)
            raise GibsError("该日期/区域没有有效影像")

        return ImageResult(image, image_path, layer, target_date, False, url)

    def get_first_valid(
        self,
        layers: Iterable[str],
        target_date: date,
        bbox: tuple[float, float, float, float],
        width: int,
        height: int,
        force_refresh: bool = False,
    ) -> ImageResult:
        errors: list[str] = []
        for layer in layers:
            try:
                return self.get_map(layer, target_date, bbox, width, height, force_refresh=force_refresh)
            except GibsError as exc:
                errors.append(f"{layer}: {exc}")
        raise GibsError("；".join(errors) if errors else "没有可用图层")

    def get_worldview_map(
        self,
        layer: str,
        target_date: date,
        width: int = 1200,
        height: int = 800,
        force_refresh: bool = False,
    ) -> ImageResult:
        composite_layer = f"{layer},{WORLDVIEW_REFERENCE_LAYER}"
        display_layer = f"{layer} + {WORLDVIEW_REFERENCE_LAYER}"
        url = self._build_url(
            composite_layer,
            target_date,
            WORLDVIEW_BBOX,
            width,
            height,
            styles=",",
            transparent=False,
        )
        image_path, meta_path = self._cache_paths(display_layer, target_date, WORLDVIEW_BBOX, width, height)

        if image_path.exists() and not force_refresh:
            try:
                cached = Image.open(image_path).convert("RGBA")
                if not self._is_invalid_file(image_path, cached):
                    return ImageResult(cached, image_path, display_layer, target_date, True, url)
            except (OSError, UnidentifiedImageError):
                pass
            image_path.unlink(missing_ok=True)

        try:
            response = requests.get(url, timeout=self.timeout_seconds)
            response.raise_for_status()
        except requests.RequestException as exc:
            if image_path.exists():
                cached = Image.open(image_path).convert("RGBA")
                return ImageResult(cached, image_path, display_layer, target_date, True, url)
            raise GibsError(f"NASA 请求失败：{exc}") from exc

        content_type = response.headers.get("Content-Type", "")
        if "image" not in content_type.lower():
            raise GibsError(f"NASA 返回的不是图片：{content_type}")

        image_path.write_bytes(response.content)
        meta_path.write_text(
            json.dumps(
                {
                    "url": url,
                    "layer": display_layer,
                    "date": target_date.isoformat(),
                    "bbox": list(WORLDVIEW_BBOX),
                    "width": width,
                    "height": height,
                    "content_type": content_type,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        try:
            image = Image.open(image_path).convert("RGBA")
        except (OSError, UnidentifiedImageError) as exc:
            image_path.unlink(missing_ok=True)
            raise GibsError("NASA 返回图片无法解析") from exc

        if self._is_invalid_file(image_path, image):
            image_path.unlink(missing_ok=True)
            meta_path.unlink(missing_ok=True)
            raise GibsError("该日期没有有效 Worldview 影像")

        return ImageResult(image, image_path, display_layer, target_date, False, url)

    def _build_url(
        self,
        layer: str,
        target_date: date,
        bbox: tuple[float, float, float, float],
        width: int,
        height: int,
        styles: str = "",
        transparent: bool = True,
    ) -> str:
        min_lon, min_lat, max_lon, max_lat = bbox
        params = {
            "SERVICE": "WMS",
            "VERSION": "1.1.1",
            "REQUEST": "GetMap",
            "LAYERS": layer,
            "STYLES": styles,
            "SRS": "EPSG:4326",
            "BBOX": f"{min_lon:.6f},{min_lat:.6f},{max_lon:.6f},{max_lat:.6f}",
            "WIDTH": str(width),
            "HEIGHT": str(height),
            "FORMAT": "image/png",
            "TIME": target_date.isoformat(),
            "TRANSPARENT": "true" if transparent else "false",
        }
        prepared = requests.Request("GET", GIBS_WMS_URL, params=params).prepare()
        if prepared.url is None:
            raise GibsError("无法生成 NASA 请求地址")
        return prepared.url

    def _cache_paths(
        self,
        layer: str,
        target_date: date,
        bbox: tuple[float, float, float, float],
        width: int,
        height: int,
    ) -> tuple[Path, Path]:
        key = json.dumps(
            {
                "layer": layer,
                "date": target_date.isoformat(),
                "bbox": [round(x, 5) for x in bbox],
                "width": width,
                "height": height,
            },
            sort_keys=True,
        )
        digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]
        base = f"{target_date.isoformat()}_{layer}_{digest}"
        safe = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in base)
        return self.cache_dir / f"{safe}.png", self.cache_dir / f"{safe}.json"

    def _is_invalid_file(self, path: Path, image: Image.Image) -> bool:
        if path.exists() and path.stat().st_size < 5000:
            return True
        return is_blank_image(image)
