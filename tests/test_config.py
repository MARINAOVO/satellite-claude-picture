from __future__ import annotations

import json

from satellite_cloud_reader.config import load_config
from satellite_cloud_reader.reporting import _prefer_matching_sensor


def test_load_config_reads_google_maps_key_from_file(tmp_path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "default_bbox": [70.0, 15.0, 140.0, 55.0],
                "google_maps_api_key": "file-key",
            }
        ),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.google_maps_api_key == "file-key"


def test_env_google_maps_key_overrides_file(tmp_path, monkeypatch) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"google_maps_api_key": "file-key"}),
        encoding="utf-8",
    )
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "env-key")

    config = load_config(config_path)

    assert config.google_maps_api_key == "env-key"


def test_preview_layers_prefer_matching_sensor() -> None:
    layers = (
        "MODIS_Aqua_CorrectedReflectance_TrueColor",
        "MODIS_Terra_CorrectedReflectance_TrueColor",
    )

    ordered = _prefer_matching_sensor(layers, "MODIS_Terra_Cloud_Fraction_Day")

    assert ordered[0] == "MODIS_Terra_CorrectedReflectance_TrueColor"
