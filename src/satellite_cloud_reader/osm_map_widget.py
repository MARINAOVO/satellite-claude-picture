from __future__ import annotations

from PySide6.QtCore import QObject, QUrl, Signal, Slot
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QVBoxLayout, QWidget


class BoundsBridge(QObject):
    bounds_changed = Signal(tuple)

    @Slot(float, float, float, float)
    def setBoundsFromMap(self, min_lon: float, min_lat: float, max_lon: float, max_lat: float) -> None:  # noqa: N802
        self.bounds_changed.emit(_normalize_bbox((min_lon, min_lat, max_lon, max_lat)))


class OSMMapSelectorWidget(QWidget):
    bbox_changed = Signal(tuple)

    def __init__(self, bbox: tuple[float, float, float, float]) -> None:
        super().__init__()
        self.setMinimumSize(560, 400)
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

    def _on_load_finished(self, ok: bool) -> None:
        self._loaded = ok
        if ok:
            self.set_bbox(self._bbox)

    def _on_bridge_bounds_changed(self, bbox: tuple[float, float, float, float]) -> None:
        self._bbox = bbox
        self.bbox_changed.emit(self._bbox)

    def _html(self) -> str:
        min_lon, min_lat, max_lon, max_lat = self._bbox
        return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="initial-scale=1, width=device-width">
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
  <style>
    html, body, #map {{
      width: 100%;
      height: 100%;
      margin: 0;
      overflow: hidden;
      font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif;
    }}
    .leaflet-container {{
      background: #cfe4ec;
    }}
    .leaflet-control-attribution {{
      font-size: 11px;
    }}
    #hint {{
      position: absolute;
      left: 16px;
      top: 16px;
      z-index: 800;
      background: rgba(255, 255, 255, 0.94);
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
      bottom: 18px;
      z-index: 800;
      background: rgba(20, 45, 53, 0.88);
      color: #fff;
      border-radius: 8px;
      padding: 9px 14px;
      font-size: 13px;
    }}
    .resize-handle {{
      width: 13px;
      height: 13px;
      margin-left: -6px;
      margin-top: -6px;
      border-radius: 50%;
      background: #d63b2a;
      border: 2px solid #fff;
      box-shadow: 0 1px 5px rgba(0, 0, 0, 0.35);
    }}
  </style>
  <script src="qrc:///qtwebchannel/qwebchannel.js"></script>
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
</head>
<body>
  <div id="map"></div>
  <div id="hint"><strong>真实地图框选</strong><br>拖动红框移动区域，拖动四角调整大小</div>
  <div id="coords"></div>
  <script>
    let map;
    let rectangle;
    let bridge;
    let handles = {{}};
    let suppressNotify = false;
    let notifyTimer = null;
    let draggingRect = false;
    let dragStart = null;
    let dragStartBounds = null;

    function clamp(value, min, max) {{
      return Math.max(min, Math.min(max, value));
    }}

    function normalizeBounds(bounds) {{
      const south = clamp(bounds.getSouth(), -85, 85);
      const north = clamp(bounds.getNorth(), -85, 85);
      const west = clamp(bounds.getWest(), -180, 180);
      const east = clamp(bounds.getEast(), -180, 180);
      return {{
        minLon: Math.min(west, east),
        minLat: Math.min(south, north),
        maxLon: Math.max(west, east),
        maxLat: Math.max(south, north)
      }};
    }}

    function boundsFromValues(minLon, minLat, maxLon, maxLat) {{
      return L.latLngBounds(
        [clamp(minLat, -85, 85), clamp(minLon, -180, 180)],
        [clamp(maxLat, -85, 85), clamp(maxLon, -180, 180)]
      );
    }}

    function updateCoords() {{
      const b = normalizeBounds(rectangle.getBounds());
      document.getElementById("coords").textContent =
        `经度 ${{b.minLon.toFixed(3)}} 至 ${{b.maxLon.toFixed(3)}}    纬度 ${{b.minLat.toFixed(3)}} 至 ${{b.maxLat.toFixed(3)}}`;
    }}

    function updateHandles() {{
      const b = normalizeBounds(rectangle.getBounds());
      handles.nw.setLatLng([b.maxLat, b.minLon]);
      handles.ne.setLatLng([b.maxLat, b.maxLon]);
      handles.sw.setLatLng([b.minLat, b.minLon]);
      handles.se.setLatLng([b.minLat, b.maxLon]);
    }}

    function notifyPython() {{
      if (suppressNotify || !bridge || !rectangle) return;
      updateCoords();
      clearTimeout(notifyTimer);
      notifyTimer = setTimeout(() => {{
        const b = normalizeBounds(rectangle.getBounds());
        bridge.setBoundsFromMap(b.minLon, b.minLat, b.maxLon, b.maxLat);
      }}, 120);
    }}

    function setRectangleBounds(bounds, fit) {{
      rectangle.setBounds(bounds);
      updateHandles();
      updateCoords();
      if (fit) map.fitBounds(bounds, {{ padding: [28, 28], maxZoom: 8 }});
      notifyPython();
    }}

    function onHandleDrag(name) {{
      const b = normalizeBounds(rectangle.getBounds());
      const p = handles[name].getLatLng();
      let minLon = b.minLon;
      let minLat = b.minLat;
      let maxLon = b.maxLon;
      let maxLat = b.maxLat;

      if (name.includes("n")) maxLat = p.lat;
      if (name.includes("s")) minLat = p.lat;
      if (name.includes("e")) maxLon = p.lng;
      if (name.includes("w")) minLon = p.lng;
      setRectangleBounds(boundsFromValues(minLon, minLat, maxLon, maxLat), false);
    }}

    function initHandles() {{
      const icon = L.divIcon({{ className: "resize-handle", iconSize: [13, 13] }});
      ["nw", "ne", "sw", "se"].forEach(name => {{
        handles[name] = L.marker([0, 0], {{ draggable: true, icon, zIndexOffset: 1000 }}).addTo(map);
        handles[name].on("drag", () => onHandleDrag(name));
        handles[name].on("dragend", notifyPython);
      }});
      updateHandles();
    }}

    function initRectangleDrag() {{
      rectangle.on("mousedown", function(event) {{
        draggingRect = true;
        dragStart = event.latlng;
        dragStartBounds = normalizeBounds(rectangle.getBounds());
        map.dragging.disable();
        L.DomEvent.stop(event);
      }});
      map.on("mousemove", function(event) {{
        if (!draggingRect || !dragStart || !dragStartBounds) return;
        const dLat = event.latlng.lat - dragStart.lat;
        const dLon = event.latlng.lng - dragStart.lng;
        setRectangleBounds(
          boundsFromValues(
            dragStartBounds.minLon + dLon,
            dragStartBounds.minLat + dLat,
            dragStartBounds.maxLon + dLon,
            dragStartBounds.maxLat + dLat
          ),
          false
        );
      }});
      map.on("mouseup", function() {{
        if (!draggingRect) return;
        draggingRect = false;
        dragStart = null;
        dragStartBounds = null;
        map.dragging.enable();
        notifyPython();
      }});
    }}

    window.setSelectionBounds = function(minLon, minLat, maxLon, maxLat) {{
      if (!rectangle || !map) return;
      suppressNotify = true;
      setRectangleBounds(boundsFromValues(minLon, minLat, maxLon, maxLat), true);
      setTimeout(() => suppressNotify = false, 150);
    }};

    function initMap() {{
      new QWebChannel(qt.webChannelTransport, function(channel) {{
        bridge = channel.objects.boundsBridge;
      }});

      const initialBounds = boundsFromValues({min_lon}, {min_lat}, {max_lon}, {max_lat});
      map = L.map("map", {{
        worldCopyJump: true,
        zoomControl: true,
        attributionControl: true
      }});
      L.tileLayer("https://tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png", {{
        maxZoom: 18,
        attribution: "&copy; OpenStreetMap contributors"
      }}).addTo(map);
      rectangle = L.rectangle(initialBounds, {{
        color: "#d63b2a",
        weight: 2,
        fillColor: "#d63b2a",
        fillOpacity: 0.18
      }}).addTo(map);
      initHandles();
      initRectangleDrag();
      map.fitBounds(initialBounds, {{ padding: [28, 28], maxZoom: 8 }});
      updateCoords();
      notifyPython();
    }}

    if (window.L) {{
      initMap();
    }} else {{
      document.getElementById("hint").innerHTML =
        "<strong>地图加载失败</strong><br>请检查网络，或在地图设置中使用其他方式。";
    }}
  </script>
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
