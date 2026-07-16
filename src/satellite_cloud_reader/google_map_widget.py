from __future__ import annotations

import html

from PySide6.QtCore import QObject, QUrl, Signal, Slot
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QVBoxLayout, QWidget


class BoundsBridge(QObject):
    bounds_changed = Signal(tuple)

    @Slot(float, float, float, float)
    def setBoundsFromMap(self, min_lon: float, min_lat: float, max_lon: float, max_lat: float) -> None:  # noqa: N802
        self.bounds_changed.emit(_normalize_bbox((min_lon, min_lat, max_lon, max_lat)))


class GoogleMapSelectorWidget(QWidget):
    bbox_changed = Signal(tuple)

    def __init__(self, api_key: str, bbox: tuple[float, float, float, float]) -> None:
        super().__init__()
        self.setMinimumSize(560, 400)
        self._api_key = api_key.strip()
        self._bbox = _normalize_bbox(bbox)
        self._loaded = False

        self.view = QWebEngineView()
        self.bridge = BoundsBridge()
        self.bridge.bounds_changed.connect(self._on_bridge_bounds_changed)
        self.channel = QWebChannel(self.view.page())
        self.channel.registerObject("boundsBridge", self.bridge)
        self.view.page().setWebChannel(self.channel)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.view)

        self.view.loadFinished.connect(self._on_load_finished)
        self.view.setHtml(self._html(), QUrl("https://localhost/"))

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        return self._bbox

    def set_bbox(self, bbox: tuple[float, float, float, float], emit: bool = False) -> None:
        self._bbox = _normalize_bbox(bbox)
        if self._loaded:
            min_lon, min_lat, max_lon, max_lat = self._bbox
            self.view.page().runJavaScript(
                f"window.setSelectionBounds({min_lon}, {min_lat}, {max_lon}, {max_lat});"
            )
        if emit:
            self.bbox_changed.emit(self._bbox)

    def zoom_in(self) -> None:
        self.view.page().runJavaScript("if (typeof map !== 'undefined' && map) map.setZoom(map.getZoom() + 1);")

    def zoom_out(self) -> None:
        self.view.page().runJavaScript("if (typeof map !== 'undefined' && map) map.setZoom(map.getZoom() - 1);")

    def reset_view(self) -> None:
        self.view.page().runJavaScript(
            "if (typeof map !== 'undefined' && map) { map.setCenter({lat: 0, lng: 0}); map.setZoom(2); }"
        )

    def zoom_to_selection(self) -> None:
        min_lon, min_lat, max_lon, max_lat = self._bbox
        self.view.page().runJavaScript(
            f"window.setSelectionBounds({min_lon}, {min_lat}, {max_lon}, {max_lat});"
        )

    def _on_load_finished(self, ok: bool) -> None:
        self._loaded = ok
        if ok:
            self.set_bbox(self._bbox)

    def _on_bridge_bounds_changed(self, bbox: tuple[float, float, float, float]) -> None:
        self._bbox = bbox
        self.bbox_changed.emit(self._bbox)

    def _html(self) -> str:
        min_lon, min_lat, max_lon, max_lat = self._bbox
        key = html.escape(self._api_key, quote=True)
        return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="initial-scale=1, width=device-width">
  <style>
    html, body, #map {{
      width: 100%;
      height: 100%;
      margin: 0;
      overflow: hidden;
      font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif;
    }}
    #hint {{
      position: absolute;
      left: 16px;
      top: 16px;
      z-index: 5;
      background: rgba(255, 255, 255, 0.92);
      color: #16363f;
      border: 1px solid #d3e0e5;
      border-radius: 8px;
      padding: 10px 14px;
      box-shadow: 0 2px 10px rgba(15, 45, 55, 0.12);
      line-height: 1.45;
      font-size: 13px;
    }}
    #coords {{
      position: absolute;
      left: 16px;
      bottom: 16px;
      z-index: 5;
      background: rgba(20, 45, 53, 0.88);
      color: #fff;
      border-radius: 8px;
      padding: 9px 14px;
      font-size: 13px;
    }}
  </style>
  <script src="qrc:///qtwebchannel/qwebchannel.js"></script>
  <script>
    let map;
    let selection;
    let bridge;
    let suppressNotify = false;
    let notifyTimer = null;

    function normalizeBounds(bounds) {{
      const sw = bounds.getSouthWest();
      const ne = bounds.getNorthEast();
      return {{
        minLon: sw.lng(),
        minLat: sw.lat(),
        maxLon: ne.lng(),
        maxLat: ne.lat()
      }};
    }}

    function updateCoords() {{
      const b = normalizeBounds(selection.getBounds());
      document.getElementById("coords").textContent =
        `经度 ${{b.minLon.toFixed(3)}} 至 ${{b.maxLon.toFixed(3)}}    纬度 ${{b.minLat.toFixed(3)}} 至 ${{b.maxLat.toFixed(3)}}`;
    }}

    function notifyPython() {{
      if (suppressNotify || !bridge || !selection) return;
      updateCoords();
      clearTimeout(notifyTimer);
      notifyTimer = setTimeout(() => {{
        const b = normalizeBounds(selection.getBounds());
        bridge.setBoundsFromMap(b.minLon, b.minLat, b.maxLon, b.maxLat);
      }}, 120);
    }}

    window.setSelectionBounds = function(minLon, minLat, maxLon, maxLat) {{
      if (!selection || !map) return;
      suppressNotify = true;
      const bounds = {{
        south: minLat,
        west: minLon,
        north: maxLat,
        east: maxLon
      }};
      selection.setBounds(bounds);
      map.fitBounds(bounds, 32);
      updateCoords();
      setTimeout(() => suppressNotify = false, 150);
    }};

    window.initMap = function() {{
      new QWebChannel(qt.webChannelTransport, function(channel) {{
        bridge = channel.objects.boundsBridge;
      }});

      const initialBounds = {{
        south: {min_lat},
        west: {min_lon},
        north: {max_lat},
        east: {max_lon}
      }};
      map = new google.maps.Map(document.getElementById("map"), {{
        center: {{ lat: ({min_lat} + {max_lat}) / 2, lng: ({min_lon} + {max_lon}) / 2 }},
        zoom: 4,
        mapTypeId: "hybrid",
        mapTypeControl: true,
        streetViewControl: false,
        fullscreenControl: false,
        clickableIcons: false,
        gestureHandling: "greedy"
      }});
      selection = new google.maps.Rectangle({{
        bounds: initialBounds,
        editable: true,
        draggable: true,
        strokeColor: "#d63b2a",
        strokeOpacity: 0.95,
        strokeWeight: 2,
        fillColor: "#d63b2a",
        fillOpacity: 0.20,
        map
      }});
      selection.addListener("bounds_changed", notifyPython);
      map.fitBounds(initialBounds, 32);
      updateCoords();
      notifyPython();
    }};
  </script>
</head>
<body>
  <div id="map"></div>
  <div id="hint"><strong>Google 地图框选</strong><br>拖动红框或角点调整区域，滚轮缩放地图</div>
  <div id="coords"></div>
  <script async defer src="https://maps.googleapis.com/maps/api/js?key={key}&callback=initMap&v=weekly"></script>
</body>
</html>"""


def _normalize_bbox(bbox: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    lon1, lat1, lon2, lat2 = bbox
    min_lon = _clamp(min(lon1, lon2), -180.0, 180.0)
    max_lon = _clamp(max(lon1, lon2), -180.0, 180.0)
    min_lat = _clamp(min(lat1, lat2), -85.0, 85.0)
    max_lat = _clamp(max(lat1, lat2), -85.0, 85.0)
    if max_lon - min_lon < 0.1:
        max_lon = min(180.0, min_lon + 0.1)
    if max_lat - min_lat < 0.1:
        max_lat = min(85.0, min_lat + 0.1)
    return min_lon, min_lat, max_lon, max_lat


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))
