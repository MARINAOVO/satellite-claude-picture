from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

import numpy as np
from PIL import Image


class Confidence(StrEnum):
    HIGH = "高"
    MEDIUM = "中"
    LOW = "低"


@dataclass(slots=True)
class CloudEstimate:
    cloud_percent: float
    confidence: Confidence
    method: str
    valid_coverage_percent: float


@dataclass(slots=True)
class WeatherAdvice:
    headline: str
    sky_condition: str
    precipitation_risk: str
    short_term_change: str
    visibility: str
    travel: str
    outdoor: str
    drying: str
    confidence_summary: str
    note: str

    def as_lines(self) -> list[str]:
        return [
            f"综合判断：{self.headline}",
            f"天空状况：{self.sky_condition}",
            f"降水风险：{self.precipitation_risk}",
            f"后续变化：{self.short_term_change}",
            f"能见度/路面：{self.visibility}",
            f"出行建议：{self.travel}",
            f"户外安排：{self.outdoor}",
            f"晾晒建议：{self.drying}",
            f"判读可信度：{self.confidence_summary}",
            f"使用说明：{self.note}",
        ]


def is_blank_image(image: Image.Image) -> bool:
    rgba = image.convert("RGBA")
    arr = np.asarray(rgba)
    alpha = arr[:, :, 3]
    if float(np.mean(alpha > 8)) < 0.01:
        return True

    valid = alpha > 8
    if not np.any(valid):
        return True

    valid_rgb = arr[:, :, :3][valid]
    if valid_rgb.size == 0:
        return True

    sample = valid_rgb.reshape(-1, 3)
    step = max(1, len(sample) // 5000)
    unique_sample = np.unique(sample[::step], axis=0)
    return len(unique_sample) <= 2


def estimate_cloud_fraction_layer(image: Image.Image) -> CloudEstimate | None:
    rgba = image.convert("RGBA")
    arr = np.asarray(rgba).astype(np.float32)
    alpha = arr[:, :, 3]
    valid = alpha > 8
    valid_coverage = float(np.mean(valid) * 100.0)

    if valid_coverage < 1.0:
        return None

    rgb = arr[:, :, :3][valid] / 255.0
    # GIBS cloud fraction layers are rendered color-ramp images. Without source
    # science pixels, luminance plus saturation gives a practical UI estimate.
    luminance = rgb[:, 0] * 0.2126 + rgb[:, 1] * 0.7152 + rgb[:, 2] * 0.0722
    saturation = np.max(rgb, axis=1) - np.min(rgb, axis=1)
    value = np.clip((luminance * 0.8) + (saturation * 0.2), 0.0, 1.0)
    cloud_percent = float(np.mean(value) * 100.0)

    if valid_coverage >= 60.0:
        confidence = Confidence.HIGH
    elif valid_coverage >= 25.0:
        confidence = Confidence.MEDIUM
    else:
        confidence = Confidence.LOW

    return CloudEstimate(
        cloud_percent=cloud_percent,
        confidence=confidence,
        method="Cloud Fraction 图层颜色/透明度估算",
        valid_coverage_percent=valid_coverage,
    )


def estimate_true_color_clouds(image: Image.Image) -> CloudEstimate | None:
    rgba = image.convert("RGBA")
    arr = np.asarray(rgba).astype(np.float32)
    alpha = arr[:, :, 3]
    valid = alpha > 8
    valid_coverage = float(np.mean(valid) * 100.0)

    if valid_coverage < 1.0:
        return None

    rgb = arr[:, :, :3][valid]
    brightness = np.mean(rgb, axis=1)
    spread = np.max(rgb, axis=1) - np.min(rgb, axis=1)
    blue_bias = rgb[:, 2] - np.maximum(rgb[:, 0], rgb[:, 1])

    bright_white = (brightness > 150) & (spread < 65)
    cold_bright_cloud = (brightness > 175) & (blue_bias > -20)
    cloud_mask = bright_white | cold_bright_cloud
    cloud_percent = float(np.mean(cloud_mask) * 100.0)

    return CloudEstimate(
        cloud_percent=cloud_percent,
        confidence=Confidence.LOW,
        method="真彩图亮度/白度粗略估算",
        valid_coverage_percent=valid_coverage,
    )


def describe_trend(
    latest_percent: float,
    previous_percent: float | None,
    threshold_percent: float,
) -> tuple[str, str]:
    if previous_percent is None:
        return "有效对比影像不足", "暂无趋势"

    diff = latest_percent - previous_percent
    if abs(diff) < threshold_percent:
        return f"较上一有效日变化 {diff:+.0f} 个百分点", "基本稳定"
    if diff > 0:
        return f"较上一有效日增加 {diff:.0f} 个百分点", "云量增加"
    return f"较上一有效日减少 {abs(diff):.0f} 个百分点", "云量减少"


def build_weather_advice(
    cloud_percent: float,
    trend_label: str,
    confidence: Confidence,
    valid_coverage_percent: float,
) -> WeatherAdvice:
    if cloud_percent < 20:
        headline = "以晴好天气为主，云量少，出现大范围降水的信号弱。"
        sky = "晴到少云，日照条件较好。"
        rain = "低。卫星云图未显示明显连续云雨带。"
        visibility = "整体有利于能见度维持；若当地有雾霾、沙尘或低云，仍需看实况。"
        travel = "适合出行，白天注意防晒和补水。"
        outdoor = "适合安排户外活动；高温时段建议避开午后强日照。"
        drying = "适合晾晒，衣物干燥条件较好。"
    elif cloud_percent < 45:
        headline = "多云为主，仍有间歇性日照，整体天气条件较平稳。"
        sky = "多云间晴，局地可能短时转阴。"
        rain = "偏低到中等。若云带继续增厚，局地小雨或阵雨风险会上升。"
        visibility = "多数时段能见度影响不大；云层增厚时光照会明显减弱。"
        travel = "一般适合出行，建议随身带轻便雨具。"
        outdoor = "户外活动基本可安排，关注后续云量是否快速增加。"
        drying = "可以短时晾晒，但不建议长时间无人看管。"
    elif cloud_percent < 70:
        headline = "云量较多，天气偏阴，出现零星小雨或阵雨的可能性增加。"
        sky = "阴到多云，日照条件较差。"
        rain = "中等。若云层厚且持续覆盖，可能出现小雨、阵雨或间歇性降水。"
        visibility = "阴雨时段可能伴随能见度下降，路面湿滑风险需要留意。"
        travel = "出行建议备伞，路面湿滑风险需结合当地雷达或实况确认。"
        outdoor = "户外活动建议留备用方案，避免安排对天气敏感的长时段活动。"
        drying = "不太适合晾晒，衣物干燥速度可能较慢。"
    else:
        headline = "阴天特征明显，云雨背景较强，需按可能有降水来安排。"
        sky = "大范围云层覆盖，阴天或阴雨天气特征明显。"
        rain = "中等到偏高。云图显示较强阴雨天气背景，但是否正在降水还需结合雷达、地面观测和正式预报。"
        visibility = "若伴随降水，能见度和路面条件可能变差，驾驶需放慢速度。"
        travel = "建议带伞，驾车注意能见度和湿滑路面。"
        outdoor = "不建议安排长时间户外活动，尤其是露天施工、登山、骑行等。"
        drying = "不建议晾晒，建议改为室内通风或烘干。"

    if trend_label == "云量增加":
        change = "云量正在增加，后续转阴、降水或能见度转差的风险上升。"
        headline = f"{headline} 后续有转差趋势。"
    elif trend_label == "云量减少":
        change = "云量正在减少，后续天气有转好、转晴或降水减弱的趋势。"
        headline = f"{headline} 后续有转好趋势。"
    elif trend_label == "基本稳定":
        change = "云量变化不大，短时天气形势相对稳定。"
    else:
        change = "历史对比不足，暂不判断变化方向。"

    if confidence == Confidence.LOW or valid_coverage_percent < 30:
        confidence_summary = "偏低。有效覆盖不足或使用了真彩图粗略估算，结论只适合作为背景参考。"
        note = "这是卫星云图辅助判读，不是正式天气预报。建议结合当地天气预报、雷达回波和实况观测。"
    elif confidence == Confidence.MEDIUM:
        confidence_summary = "中等。适合判断区域天气背景，但局地降水、雷暴和短时强天气仍需看雷达和实况。"
        note = "这是卫星云图辅助判读，不替代气象台正式天气预报。"
    else:
        confidence_summary = "较高。云量背景可信，但降水强度、雷暴和风力无法仅靠云图准确给出。"
        note = "这是卫星云图辅助判读；降水强度、温度和风力仍需结合正式预报。"

    return WeatherAdvice(
        headline=headline,
        sky_condition=sky,
        precipitation_risk=rain,
        short_term_change=change,
        visibility=visibility,
        travel=travel,
        outdoor=outdoor,
        drying=drying,
        confidence_summary=confidence_summary,
        note=note,
    )
