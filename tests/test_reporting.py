from __future__ import annotations

from satellite_cloud_reader.config import AppConfig
from satellite_cloud_reader.reporting import image_size_for_bbox


def test_image_size_for_bbox_tracks_wide_selection_ratio() -> None:
    config = AppConfig(image_width=900, image_height=520)

    width, height = image_size_for_bbox(config, (76.748, 31.224, 92.917, 37.414))

    assert width > height
    assert abs((width / height) - (16.169 / 6.19)) < 0.02


def test_image_size_for_bbox_tracks_tall_selection_ratio() -> None:
    config = AppConfig(image_width=900, image_height=520)

    width, height = image_size_for_bbox(config, (100.0, -20.0, 120.0, 20.0))

    assert width < height
    assert abs((width / height) - 0.5) < 0.02
