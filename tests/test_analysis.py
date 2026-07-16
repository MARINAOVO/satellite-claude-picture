from __future__ import annotations

from PIL import Image

from satellite_cloud_reader.analysis import (
    Confidence,
    build_weather_advice,
    describe_trend,
    estimate_cloud_fraction_layer,
    estimate_true_color_clouds,
    is_blank_image,
)


def test_blank_transparent_image_is_rejected() -> None:
    image = Image.new("RGBA", (20, 20), (0, 0, 0, 0))

    assert is_blank_image(image)


def test_cloud_fraction_layer_estimate_uses_visible_pixels() -> None:
    image = Image.new("RGBA", (10, 10), (230, 230, 230, 255))

    estimate = estimate_cloud_fraction_layer(image)

    assert estimate is not None
    assert estimate.confidence == Confidence.HIGH
    assert estimate.cloud_percent > 70


def test_true_color_estimate_detects_bright_cloud_pixels() -> None:
    image = Image.new("RGBA", (10, 10), (40, 80, 120, 255))
    for x in range(5):
        for y in range(10):
            image.putpixel((x, y), (235, 235, 235, 255))

    estimate = estimate_true_color_clouds(image)

    assert estimate is not None
    assert estimate.confidence == Confidence.LOW
    assert 45 <= estimate.cloud_percent <= 55


def test_trend_threshold_labels_stable_increase_and_decrease() -> None:
    assert describe_trend(52, 50, 5)[1] == "基本稳定"
    assert describe_trend(61, 50, 5)[1] == "云量增加"
    assert describe_trend(39, 50, 5)[1] == "云量减少"
    assert describe_trend(50, None, 5)[1] == "暂无趋势"


def test_weather_advice_for_high_cloud_cover_is_practical() -> None:
    advice = build_weather_advice(82, "云量增加", Confidence.HIGH, 95)

    assert "综合判断：" in advice.as_lines()[0]
    assert "阴天" in advice.sky_condition
    assert "带伞" in advice.travel
    assert "不建议晾晒" in advice.drying
    assert "转差" in advice.headline
    assert "正式预报" in advice.note


def test_weather_advice_for_decreasing_cloud_cover_reads_like_forecast() -> None:
    advice = build_weather_advice(32, "云量减少", Confidence.MEDIUM, 80)

    lines = "\n".join(advice.as_lines())
    assert "多云" in advice.sky_condition
    assert "转好" in advice.headline
    assert "降水风险" in lines
    assert "能见度/路面" in lines
