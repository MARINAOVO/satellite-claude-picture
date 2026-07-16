from __future__ import annotations

from pathlib import Path

import requests
from PySide6.QtCore import QPoint, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QLinearGradient, QMouseEvent, QPainter, QPen, QPixmap, QWheelEvent
from PySide6.QtWidgets import QWidget

from .config import CACHE_DIR


BASEMAP_URL = "https://gibs.earthdata.nasa.gov/wms/epsg4326/best/wms.cgi"
BASEMAP_PATH = CACHE_DIR / "nasa_blue_marble_basemap.png"
MIN_ZOOM = 0.75
MAX_ZOOM = 64.0


class MapSelectorWidget(QWidget):
    bbox_changed = Signal(tuple)

    def __init__(self, bbox: tuple[float, float, float, float]) -> None:
        super().__init__()
        self.setMinimumSize(560, 400)
        self.setMouseTracking(True)
        self._bbox = _normalize_bbox(bbox)
        self._zoom = 1.0
        self._center_lon = 0.0
        self._center_lat = 0.0
        self._drag_start: QPoint | None = None
        self._drag_mode: str | None = None
        self._pan_start: tuple[float, float] | None = None
        self._basemap = self._load_basemap()

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        return self._bbox

    def set_bbox(self, bbox: tuple[float, float, float, float], emit: bool = False) -> None:
        self._bbox = _normalize_bbox(bbox)
        self.update()
        if emit:
            self.bbox_changed.emit(self._bbox)

    def zoom_in(self) -> None:
        self._set_zoom_at(QPoint(self.width() // 2, self.height() // 2), 1.5)

    def zoom_out(self) -> None:
        self._set_zoom_at(QPoint(self.width() // 2, self.height() // 2), 1 / 1.5)

    def reset_view(self) -> None:
        self._zoom = 1.0
        self._center_lon = 0.0
        self._center_lat = 0.0
        self.update()

    def zoom_to_selection(self) -> None:
        min_lon, min_lat, max_lon, max_lat = self._bbox
        lon_span = max(max_lon - min_lon, 0.05)
        lat_span = max(max_lat - min_lat, 0.05)
        usable_width = max(self.width() - 96, 120)
        usable_height = max(self.height() - 96, 120)
        base_scale = min(self.width() / 360.0, self.height() / 180.0)
        target_scale = min(usable_width / lon_span, usable_height / lat_span)
        self._zoom = _clamp(target_scale / base_scale, MIN_ZOOM, MAX_ZOOM)
        self._center_lon = _clamp((min_lon + max_lon) / 2, -180.0, 180.0)
        self._center_lat = _clamp((min_lat + max_lat) / 2, -85.0, 85.0)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._draw_background(painter)
        self._draw_graticule(painter)
        self._draw_selection(painter)
        self._draw_overlay_text(painter)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start = event.position().toPoint()
            self._drag_mode = "select"
        elif event.button() in (Qt.MouseButton.RightButton, Qt.MouseButton.MiddleButton):
            self._drag_start = event.position().toPoint()
            self._pan_start = (self._center_lon, self._center_lat)
            self._drag_mode = "pan"

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._drag_start is None or self._drag_mode is None:
            return

        current = event.position().toPoint()
        if self._drag_mode == "pan" and self._pan_start is not None:
            dx = current.x() - self._drag_start.x()
            dy = current.y() - self._drag_start.y()
            scale = self._scale()
            self._center_lon = _clamp(self._pan_start[0] - dx / scale, -180.0, 180.0)
            self._center_lat = _clamp(self._pan_start[1] + dy / scale, -85.0, 85.0)
            self.update()
            return

        if self._drag_mode == "select":
            lon1, lat1 = self._screen_to_geo(self._drag_start)
            lon2, lat2 = self._screen_to_geo(current)
            self._bbox = _normalize_bbox((lon1, lat1, lon2, lat2))
            self.bbox_changed.emit(self._bbox)
            self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self._drag_start = None
        self._drag_mode = None
        self._pan_start = None

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._set_zoom_at(event.position().toPoint(), 2.0)
        elif event.button() == Qt.MouseButton.RightButton:
            self._set_zoom_at(event.position().toPoint(), 0.5)

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        factor = 1.35 if event.angleDelta().y() > 0 else 1 / 1.35
        self._set_zoom_at(event.position().toPoint(), factor)

    def _set_zoom_at(self, point: QPoint, factor: float) -> None:
        before_lon, before_lat = self._screen_to_geo(point)
        self._zoom = _clamp(self._zoom * factor, MIN_ZOOM, MAX_ZOOM)
        after_lon, after_lat = self._screen_to_geo(point)
        self._center_lon += before_lon - after_lon
        self._center_lat += before_lat - after_lat
        self._center_lon = _clamp(self._center_lon, -180.0, 180.0)
        self._center_lat = _clamp(self._center_lat, -85.0, 85.0)
        self.update()

    def _scale(self) -> float:
        return min(self.width() / 360.0, self.height() / 180.0) * self._zoom

    def _geo_to_screen(self, lon: float, lat: float) -> tuple[float, float]:
        scale = self._scale()
        x = self.width() / 2 + (lon - self._center_lon) * scale
        y = self.height() / 2 - (lat - self._center_lat) * scale
        return x, y

    def _screen_to_geo(self, point: QPoint) -> tuple[float, float]:
        scale = self._scale()
        lon = self._center_lon + (point.x() - self.width() / 2) / scale
        lat = self._center_lat - (point.y() - self.height() / 2) / scale
        return _clamp(lon, -180.0, 180.0), _clamp(lat, -90.0, 90.0)

    def _draw_background(self, painter: QPainter) -> None:
        if not self._basemap.isNull():
            x1, y1 = self._geo_to_screen(-180, 90)
            x2, y2 = self._geo_to_screen(180, -90)
            target = QRectF(min(x1, x2), min(y1, y2), abs(x2 - x1), abs(y2 - y1))
            painter.fillRect(self.rect(), QColor("#07131d"))
            painter.drawPixmap(target, self._basemap, QRectF(self._basemap.rect()))
            return

        gradient = QLinearGradient(0, 0, 0, self.height())
        gradient.setColorAt(0, QColor("#d9edf5"))
        gradient.setColorAt(1, QColor("#b9d8e5"))
        painter.fillRect(self.rect(), gradient)
        painter.setPen(QColor("#244653"))
        painter.drawText(24, 36, "NASA 底图暂时无法加载，请检查网络。")

    def _draw_graticule(self, painter: QPainter) -> None:
        step = _grid_step_for_zoom(self._zoom)
        lon = -180
        while lon <= 180:
            major = lon % (step * 3) == 0
            painter.setPen(QPen(QColor(255, 255, 255, 150 if major else 70), 1))
            x1, y1 = self._geo_to_screen(lon, -90)
            x2, y2 = self._geo_to_screen(lon, 90)
            painter.drawLine(int(x1), int(y1), int(x2), int(y2))
            if major and -60 <= x1 <= self.width() + 20:
                painter.setPen(QColor(255, 255, 255, 210))
                painter.drawText(int(x1) + 4, 22, f"{lon}°")
            lon += step

        lat = -90
        while lat <= 90:
            major = lat % (step * 3) == 0
            painter.setPen(QPen(QColor(255, 255, 255, 145 if major else 65), 1))
            x1, y1 = self._geo_to_screen(-180, lat)
            x2, y2 = self._geo_to_screen(180, lat)
            painter.drawLine(int(x1), int(y1), int(x2), int(y2))
            if major and -20 <= y1 <= self.height() + 20:
                painter.setPen(QColor(255, 255, 255, 210))
                painter.drawText(12, int(y1) - 4, f"{lat}°")
            lat += step

    def _draw_selection(self, painter: QPainter) -> None:
        min_lon, min_lat, max_lon, max_lat = self._bbox
        x1, y1 = self._geo_to_screen(min_lon, max_lat)
        x2, y2 = self._geo_to_screen(max_lon, min_lat)
        rect = QRectF(min(x1, x2), min(y1, y2), abs(x2 - x1), abs(y2 - y1))

        painter.setPen(QPen(QColor("#f04d37"), 2))
        painter.setBrush(QColor(240, 77, 55, 52))
        painter.drawRoundedRect(rect, 4, 4)

        painter.setPen(QPen(QColor("#ffffff"), 1))
        painter.setBrush(QColor("#d63b2a"))
        for point in (rect.topLeft(), rect.topRight(), rect.bottomLeft(), rect.bottomRight()):
            painter.drawEllipse(point, 5, 5)

        center = rect.center()
        painter.setPen(QPen(QColor("#f04d37"), 1))
        painter.drawLine(int(center.x() - 8), int(center.y()), int(center.x() + 8), int(center.y()))
        painter.drawLine(int(center.x()), int(center.y() - 8), int(center.x()), int(center.y() + 8))

    def _draw_overlay_text(self, painter: QPainter) -> None:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255, 225))
        painter.drawRoundedRect(QRectF(14, 14, 360, 64), 8, 8)
        painter.setPen(QColor("#16363f"))
        painter.drawText(30, 38, "NASA 真实底图框选")
        painter.setPen(QColor("#496772"))
        painter.drawText(30, 60, "左键框选，滚轮/按钮放大，右键拖动，双击放大")

        min_lon, min_lat, max_lon, max_lat = self._bbox
        text = f"经度 {min_lon:.2f} 至 {max_lon:.2f}    纬度 {min_lat:.2f} 至 {max_lat:.2f}    缩放 {self._zoom:.1f}x"
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(22, 43, 50, 220))
        painter.drawRoundedRect(QRectF(14, self.height() - 48, min(660, self.width() - 28), 34), 8, 8)
        painter.setPen(QColor("#ffffff"))
        painter.drawText(32, self.height() - 26, text)

    def _load_basemap(self) -> QPixmap:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        if not BASEMAP_PATH.exists() or BASEMAP_PATH.stat().st_size < 50_000:
            _download_basemap(BASEMAP_PATH)
        return QPixmap(str(BASEMAP_PATH))


def _download_basemap(path: Path) -> None:
    params = {
        "SERVICE": "WMS",
        "VERSION": "1.1.1",
        "REQUEST": "GetMap",
        "LAYERS": "BlueMarble_ShadedRelief_Bathymetry,Reference_Features,Reference_Labels",
        "STYLES": ",,",
        "SRS": "EPSG:4326",
        "BBOX": "-180,-90,180,90",
        "WIDTH": "1440",
        "HEIGHT": "720",
        "FORMAT": "image/png",
        "TRANSPARENT": "false",
    }
    try:
        response = requests.get(BASEMAP_URL, params=params, timeout=30)
        response.raise_for_status()
        if "image" in response.headers.get("Content-Type", "").lower() and len(response.content) > 50_000:
            path.write_bytes(response.content)
    except requests.RequestException:
        return


def _normalize_bbox(bbox: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    lon1, lat1, lon2, lat2 = bbox
    min_lon = _clamp(min(lon1, lon2), -180.0, 180.0)
    max_lon = _clamp(max(lon1, lon2), -180.0, 180.0)
    min_lat = _clamp(min(lat1, lat2), -90.0, 90.0)
    max_lat = _clamp(max(lat1, lat2), -90.0, 90.0)
    if max_lon - min_lon < 0.01:
        max_lon = min(180.0, min_lon + 0.01)
    if max_lat - min_lat < 0.01:
        max_lat = min(90.0, min_lat + 0.01)
    return min_lon, min_lat, max_lon, max_lat


def _grid_step_for_zoom(zoom: float) -> int:
    if zoom >= 32:
        return 1
    if zoom >= 16:
        return 2
    if zoom >= 8:
        return 5
    if zoom >= 4:
        return 10
    if zoom >= 2:
        return 15
    return 30


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))
