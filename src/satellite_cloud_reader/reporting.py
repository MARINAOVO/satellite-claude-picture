from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import date, timedelta
from math import sqrt
from pathlib import Path
from typing import Callable

from .analysis import (
    CloudEstimate,
    Confidence,
    WeatherAdvice,
    build_weather_advice,
    describe_trend,
    estimate_cloud_fraction_layer,
    estimate_true_color_clouds,
)
from .config import AppConfig
from .gibs_client import GibsClient, GibsError, ImageResult


@dataclass(slots=True)
class DailyMetric:
    date: date
    layer: str
    image_path: Path
    from_cache: bool
    estimate: CloudEstimate


@dataclass(slots=True)
class CloudReport:
    bbox: tuple[float, float, float, float]
    requested_date: date
    latest: DailyMetric
    history: list[DailyMetric]
    preview: ImageResult
    trend_detail: str
    trend_label: str
    conclusion: str
    weather_advice: WeatherAdvice


def build_cloud_report(
    client: GibsClient,
    config: AppConfig,
    bbox: tuple[float, float, float, float],
    requested_date: date,
    progress: Callable[[str], None] | None = None,
    force_refresh: bool = False,
) -> CloudReport:
    history: list[DailyMetric] = []
    errors: list[str] = []
    image_width, image_height = image_size_for_bbox(config, bbox)

    max_scan_days = max(config.lookback_days, config.trend_count + 2)
    for offset in range(max_scan_days + 1):
        current_date = requested_date - timedelta(days=offset)
        if progress:
            progress(f"正在查找 {current_date.isoformat()} 的云图...")
        metric = _fetch_metric_for_date(
            client,
            config,
            bbox,
            current_date,
            image_width,
            image_height,
            force_refresh=force_refresh,
        )
        if metric is not None:
            history.append(metric)
            if len(history) >= config.trend_count:
                break
        else:
            errors.append(current_date.isoformat())

    if not history:
        raise GibsError(f"最近 {config.lookback_days} 天未找到有效云图：{', '.join(errors)}")

    latest = history[0]
    preview = _fetch_preview(
        client,
        config,
        bbox,
        latest.date,
        latest.image_path,
        latest.layer,
        image_width,
        image_height,
        force_refresh=force_refresh,
    )
    previous = history[1].estimate.cloud_percent if len(history) > 1 else None
    trend_detail, trend_label = describe_trend(
        latest.estimate.cloud_percent,
        previous,
        config.stable_threshold_percent,
    )
    weather_advice = build_weather_advice(
        latest.estimate.cloud_percent,
        trend_label,
        latest.estimate.confidence,
        latest.estimate.valid_coverage_percent,
    )
    conclusion = (
        f"最近有效影像：{latest.date.isoformat()}；"
        f"估算云量 {latest.estimate.cloud_percent:.0f}%；"
        f"{trend_detail}；趋势：{trend_label}。"
    )

    return CloudReport(
        bbox=bbox,
        requested_date=requested_date,
        latest=latest,
        history=history,
        preview=preview,
        trend_detail=trend_detail,
        trend_label=trend_label,
        conclusion=conclusion,
        weather_advice=weather_advice,
    )


def image_size_for_bbox(config: AppConfig, bbox: tuple[float, float, float, float]) -> tuple[int, int]:
    min_lon, min_lat, max_lon, max_lat = bbox
    lon_span = max(abs(max_lon - min_lon), 0.01)
    lat_span = max(abs(max_lat - min_lat), 0.01)
    aspect = max(0.25, min(4.0, lon_span / lat_span))
    target_area = max(config.image_width * config.image_height, 320 * 320)
    width = int(round(sqrt(target_area * aspect)))
    height = int(round(width / aspect))
    width = max(320, min(1600, width))
    height = max(320, min(1200, height))
    return width, height


def export_report(report: CloudReport, reports_dir: Path) -> tuple[Path, Path]:
    reports_dir.mkdir(parents=True, exist_ok=True)
    timestamp = report.latest.date.isoformat()
    image_out = reports_dir / f"cloud_preview_{timestamp}.png"
    text_out = reports_dir / f"cloud_report_{timestamp}.txt"

    shutil.copyfile(report.preview.path, image_out)
    min_lon, min_lat, max_lon, max_lat = report.bbox
    lines = [
        "卫星云图自主读取报告",
        "",
        f"请求日期：{report.requested_date.isoformat()}",
        f"最近有效影像：{report.latest.date.isoformat()}",
        f"区域：经度 {min_lon:.3f} 至 {max_lon:.3f}，纬度 {min_lat:.3f} 至 {max_lat:.3f}",
        f"图层：{report.latest.layer}",
        f"估算云量：{report.latest.estimate.cloud_percent:.1f}%",
        f"趋势：{report.trend_label}",
        f"趋势说明：{report.trend_detail}",
        f"可信度：{report.latest.estimate.confidence.value}",
        f"算法：{report.latest.estimate.method}",
        f"有效像素覆盖：{report.latest.estimate.valid_coverage_percent:.1f}%",
        "",
        report.conclusion,
        "",
        "天气预报式判读",
        *report.weather_advice.as_lines(),
        "",
        "说明：该结果为卫星影像辅助分析，不替代正式天气预报、雷达回波和地面观测。",
    ]
    text_out.write_text("\n".join(lines), encoding="utf-8")
    return image_out, text_out


def _fetch_metric_for_date(
    client: GibsClient,
    config: AppConfig,
    bbox: tuple[float, float, float, float],
    target_date: date,
    image_width: int,
    image_height: int,
    force_refresh: bool = False,
) -> DailyMetric | None:
    for layer in config.cloud_layers:
        try:
            image_result = client.get_map(
                layer,
                target_date,
                bbox,
                image_width,
                image_height,
                force_refresh=force_refresh,
            )
        except GibsError:
            continue

        estimate = estimate_cloud_fraction_layer(image_result.image)
        if estimate is not None:
            return DailyMetric(target_date, layer, image_result.path, image_result.from_cache, estimate)

    for layer in config.preview_layers:
        try:
            image_result = client.get_map(
                layer,
                target_date,
                bbox,
                image_width,
                image_height,
                force_refresh=force_refresh,
            )
        except GibsError:
            continue

        estimate = estimate_true_color_clouds(image_result.image)
        if estimate is not None:
            return DailyMetric(target_date, layer, image_result.path, image_result.from_cache, estimate)

    return None


def _fetch_preview(
    client: GibsClient,
    config: AppConfig,
    bbox: tuple[float, float, float, float],
    target_date: date,
    fallback_path: Path,
    preferred_source_layer: str,
    image_width: int,
    image_height: int,
    force_refresh: bool = False,
) -> ImageResult:
    preview_layers = _prefer_matching_sensor(config.preview_layers, preferred_source_layer)
    try:
        return client.get_first_valid(
            preview_layers,
            target_date,
            bbox,
            image_width,
            image_height,
            force_refresh=force_refresh,
        )
    except GibsError:
        from PIL import Image

        image = Image.open(fallback_path).convert("RGBA")
        return ImageResult(image, fallback_path, "cloud-analysis-layer", target_date, True, "")


def _prefer_matching_sensor(layers: tuple[str, ...], source_layer: str) -> tuple[str, ...]:
    sensor = ""
    if "Terra" in source_layer:
        sensor = "Terra"
    elif "Aqua" in source_layer:
        sensor = "Aqua"

    if not sensor:
        return layers

    preferred = [layer for layer in layers if sensor in layer]
    rest = [layer for layer in layers if layer not in preferred]
    return tuple(preferred + rest)


def confidence_text(confidence: Confidence) -> str:
    if confidence == Confidence.HIGH:
        return "可信度：高。优先使用云量图层，有效覆盖较好。"
    if confidence == Confidence.MEDIUM:
        return "可信度：中。影像覆盖尚可，局部缺图可能影响估算。"
    return "可信度：低。使用粗略估算或有效覆盖不足，建议结合原图人工判断。"
