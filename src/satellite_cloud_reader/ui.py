from __future__ import annotations

from datetime import date

from PySide6.QtCore import QDate, QThread, Qt, QTimer, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QDateEdit,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStyle,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .config import CACHE_DIR, REPORTS_DIR, AppConfig, load_config, save_config
from .gibs_client import GibsClient, GibsError
from .google_map_widget import GoogleMapSelectorWidget
from .map_widget import MapSelectorWidget
from .reporting import CloudReport, build_cloud_report, confidence_text, export_report


PRESETS: dict[str, tuple[float, float, float, float]] = {
    "中国/东亚": (70.0, 15.0, 140.0, 55.0),
    "欧洲": (-12.0, 35.0, 42.0, 72.0),
    "北美": (-130.0, 20.0, -60.0, 58.0),
    "南美": (-84.0, -56.0, -34.0, 14.0),
    "全球": (-180.0, -70.0, 180.0, 80.0),
}


class FetchWorker(QThread):
    progress = Signal(str)
    finished_report = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        config: AppConfig,
        bbox: tuple[float, float, float, float],
        requested_date: date,
        force_refresh: bool = False,
    ) -> None:
        super().__init__()
        self.config = config
        self.bbox = bbox
        self.requested_date = requested_date
        self.force_refresh = force_refresh

    def run(self) -> None:
        try:
            client = GibsClient(CACHE_DIR)
            report = build_cloud_report(
                client,
                self.config,
                self.bbox,
                self.requested_date,
                progress=self.progress.emit,
                force_refresh=self.force_refresh,
            )
        except GibsError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # pragma: no cover - defensive UI boundary
            self.failed.emit(f"程序处理失败：{exc}")
        else:
            self.finished_report.emit(report)


class MetricCard(QFrame):
    def __init__(self, title: str, value: str = "-", detail: str = "") -> None:
        super().__init__()
        self.setObjectName("metricCard")
        self.setMinimumHeight(104)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(6)

        self.title_label = QLabel(title)
        self.title_label.setObjectName("metricTitle")
        self.value_label = QLabel(value)
        self.value_label.setObjectName("metricValue")
        self.detail_label = QLabel(detail)
        self.detail_label.setObjectName("metricDetail")
        self.detail_label.setWordWrap(True)

        layout.addWidget(self.title_label)
        layout.addWidget(self.value_label)
        layout.addWidget(self.detail_label)

    def set_values(self, value: str, detail: str = "") -> None:
        self.value_label.setText(value)
        self.detail_label.setText(detail)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.config = load_config()
        self.current_report: CloudReport | None = None
        self.worker: FetchWorker | None = None
        self._syncing_bbox = False
        self._preview_pixmap: QPixmap | None = None
        self._last_report_key: tuple | None = None
        self.map_widget: GoogleMapSelectorWidget | MapSelectorWidget | None = None

        self.setWindowTitle("卫星云图自主读取")
        self._build_ui()
        self._apply_bbox(self.config.default_bbox, update_map=True)
        QTimer.singleShot(450, self._start_fetch)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._refresh_preview_size()

    def _build_ui(self) -> None:
        central = QWidget()
        central.setObjectName("appRoot")
        root = QVBoxLayout(central)
        root.setContentsMargins(18, 18, 18, 14)
        root.setSpacing(14)

        root.addWidget(self._build_header())

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self._make_scroll_area(self._build_left_panel()))
        splitter.addWidget(self._make_scroll_area(self._build_right_panel()))
        splitter.setStretchFactor(0, 5)
        splitter.setStretchFactor(1, 4)
        root.addWidget(splitter, 1)

        root.addWidget(self._build_status_bar())
        self.setCentralWidget(central)
        self._apply_style()

    def _make_scroll_area(self, widget: QWidget) -> QScrollArea:
        scroll_area = QScrollArea()
        scroll_area.setObjectName("panelScrollArea")
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll_area.setWidget(widget)
        return scroll_area

    def _build_header(self) -> QWidget:
        header = QFrame()
        header.setObjectName("header")
        layout = QHBoxLayout(header)
        layout.setContentsMargins(18, 14, 18, 14)

        title_block = QVBoxLayout()
        title = QLabel("卫星云图自主读取")
        title.setObjectName("appTitle")
        subtitle = QLabel("NASA GIBS / Worldview 公共影像 · 云量估算 · 最近趋势")
        subtitle.setObjectName("appSubtitle")
        title_block.addWidget(title)
        title_block.addWidget(subtitle)
        layout.addLayout(title_block, 1)

        self.source_badge = QLabel("云图来源：NASA GIBS WMS")
        self.source_badge.setObjectName("sourceBadge")
        layout.addWidget(self.source_badge)
        return header

    def _build_left_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        self.map_container = QWidget()
        self.map_container_layout = QVBoxLayout(self.map_container)
        self.map_container_layout.setContentsMargins(0, 0, 0, 0)
        self._install_map_widget()
        layout.addWidget(self.map_container, 1)

        presets = QHBoxLayout()
        presets.addWidget(QLabel("快速区域"))
        for name, bbox in PRESETS.items():
            button = QPushButton(name)
            button.setObjectName("presetButton")
            button.clicked.connect(lambda checked=False, b=bbox: self._apply_bbox(b, update_map=True))
            presets.addWidget(button)
        self.zoom_in_button = QPushButton("放大")
        self.zoom_in_button.setObjectName("presetButton")
        self.zoom_in_button.clicked.connect(lambda: self._call_map_action("zoom_in"))
        presets.addWidget(self.zoom_in_button)
        self.zoom_out_button = QPushButton("缩小")
        self.zoom_out_button.setObjectName("presetButton")
        self.zoom_out_button.clicked.connect(lambda: self._call_map_action("zoom_out"))
        presets.addWidget(self.zoom_out_button)
        self.zoom_to_selection_button = QPushButton("缩放到选区")
        self.zoom_to_selection_button.setObjectName("presetButton")
        self.zoom_to_selection_button.clicked.connect(lambda: self._call_map_action("zoom_to_selection"))
        presets.addWidget(self.zoom_to_selection_button)
        self.reset_map_button = QPushButton("复位")
        self.reset_map_button.setObjectName("presetButton")
        self.reset_map_button.clicked.connect(lambda: self._call_map_action("reset_view"))
        presets.addWidget(self.reset_map_button)
        self.map_settings_button = QPushButton("地图设置")
        self.map_settings_button.setObjectName("presetButton")
        self.map_settings_button.clicked.connect(self._open_map_settings)
        presets.addWidget(self.map_settings_button)
        self.map_provider_label = QLabel()
        self.map_provider_label.setObjectName("mutedLabel")
        presets.addWidget(self.map_provider_label)
        presets.addStretch(1)
        layout.addLayout(presets)

        bbox_box = QGroupBox("精确经纬度")
        grid = QGridLayout(bbox_box)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(8)
        self.min_lon = self._coord_spin(-180, 180)
        self.min_lat = self._coord_spin(-90, 90)
        self.max_lon = self._coord_spin(-180, 180)
        self.max_lat = self._coord_spin(-90, 90)
        for spin in (self.min_lon, self.min_lat, self.max_lon, self.max_lat):
            spin.valueChanged.connect(self._on_spin_bbox_changed)

        grid.addWidget(QLabel("最小经度"), 0, 0)
        grid.addWidget(self.min_lon, 0, 1)
        grid.addWidget(QLabel("最小纬度"), 0, 2)
        grid.addWidget(self.min_lat, 0, 3)
        grid.addWidget(QLabel("最大经度"), 1, 0)
        grid.addWidget(self.max_lon, 1, 1)
        grid.addWidget(QLabel("最大纬度"), 1, 2)
        grid.addWidget(self.max_lat, 1, 3)
        layout.addWidget(bbox_box)

        controls = QFrame()
        controls.setObjectName("controlStrip")
        control_layout = QHBoxLayout(controls)
        control_layout.setContentsMargins(12, 10, 12, 10)
        self.date_edit = QDateEdit(QDate.currentDate())
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("yyyy-MM-dd")
        control_layout.addWidget(QLabel("起始日期"))
        control_layout.addWidget(self.date_edit)

        self.fetch_button = QPushButton("获取最新")
        self.fetch_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload))
        self.fetch_button.clicked.connect(lambda: self._start_fetch(force_refresh=True))
        control_layout.addWidget(self.fetch_button)

        self.export_button = QPushButton("导出报告")
        self.export_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton))
        self.export_button.clicked.connect(self._export_current_report)
        self.export_button.setEnabled(False)
        control_layout.addWidget(self.export_button)
        control_layout.addStretch(1)
        layout.addWidget(controls)
        return panel

    def _install_map_widget(self) -> None:
        old_widget = self.map_widget
        if old_widget is not None:
            old_widget.setParent(None)
            old_widget.deleteLater()

        key = self.config.google_maps_api_key.strip()
        if key:
            try:
                self.map_widget = GoogleMapSelectorWidget(key, self.config.default_bbox)
                provider_text = "当前地图：Google Maps"
            except Exception as exc:
                self.map_widget = MapSelectorWidget(self.config.default_bbox)
                provider_text = f"Google 地图不可用，已切换 NASA 底图：{exc}"
        else:
            self.map_widget = MapSelectorWidget(self.config.default_bbox)
            provider_text = "当前地图：NASA Blue Marble"

        self.map_widget.bbox_changed.connect(self._on_map_bbox_changed)
        self.map_container_layout.addWidget(self.map_widget)
        if hasattr(self, "map_provider_label"):
            self.map_provider_label.setText(provider_text)
        if hasattr(self, "source_badge"):
            if isinstance(self.map_widget, GoogleMapSelectorWidget):
                map_name = "Google Maps"
            else:
                map_name = "NASA Blue Marble"
            self.source_badge.setText(f"云图来源：NASA GIBS WMS · 地图：{map_name}")

    def _open_map_settings(self) -> None:
        key, accepted = QInputDialog.getText(
            self,
            "地图设置",
            "Google Maps API Key（可留空使用 NASA Blue Marble 底图）：",
            QLineEdit.EchoMode.Password,
            self.config.google_maps_api_key,
        )
        if not accepted:
            return

        self.config.google_maps_api_key = key.strip()
        self.config.default_bbox = self._selected_bbox()
        save_config(self.config)
        self._install_map_widget()
        self._apply_bbox(self.config.default_bbox, update_map=True)

    def _call_map_action(self, action_name: str) -> None:
        if self.map_widget is None:
            return
        action = getattr(self.map_widget, action_name, None)
        if callable(action):
            action()

    def _build_right_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        image_frame = QFrame()
        image_frame.setObjectName("imageFrame")
        image_layout = QVBoxLayout(image_frame)
        image_layout.setContentsMargins(12, 12, 12, 12)
        image_layout.setSpacing(8)
        image_header = QHBoxLayout()
        title = QLabel("云图预览")
        title.setObjectName("sectionTitle")
        self.image_meta_label = QLabel("来源：NASA GIBS WMS，正在准备")
        self.image_meta_label.setObjectName("mutedLabel")
        image_header.addWidget(title)
        image_header.addStretch(1)
        image_header.addWidget(self.image_meta_label)
        image_layout.addLayout(image_header)

        self.preview_label = QLabel("尚未获取云图")
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setObjectName("previewLabel")
        self.preview_label.setMinimumSize(480, 240)
        self.preview_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        image_layout.addWidget(self.preview_label, 1)
        layout.addWidget(image_frame, 4)

        metrics = QHBoxLayout()
        self.cloud_card = MetricCard("估算云量")
        self.trend_card = MetricCard("趋势")
        self.confidence_card = MetricCard("可信度")
        metrics.addWidget(self.cloud_card)
        metrics.addWidget(self.trend_card)
        metrics.addWidget(self.confidence_card)
        layout.addLayout(metrics)

        self.result_text = QTextEdit()
        self.result_text.setObjectName("resultText")
        self.result_text.setReadOnly(True)
        self.result_text.setMinimumHeight(230)
        self.result_text.setPlainText(
            "云图来源：NASA GIBS WMS / Worldview 公共影像。\n"
            "程序启动后会自动获取最近可用云图，也可以点击“获取最新”手动刷新。"
        )
        layout.addWidget(self.result_text, 3)

        self.history_table = QTableWidget(0, 4)
        self.history_table.setObjectName("historyTable")
        self.history_table.setHorizontalHeaderLabels(["日期", "云量", "图层", "来源"])
        self.history_table.verticalHeader().setVisible(False)
        self.history_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.history_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.history_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.history_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.history_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.history_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.history_table.setMinimumHeight(96)
        layout.addWidget(self.history_table)
        return panel

    def _build_status_bar(self) -> QWidget:
        status = QFrame()
        status.setObjectName("bottomStatus")
        layout = QHBoxLayout(status)
        layout.setContentsMargins(12, 8, 12, 8)
        self.status_label = QLabel("就绪")
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedWidth(160)
        self.progress_bar.setVisible(False)
        layout.addWidget(self.status_label, 1)
        layout.addWidget(self.progress_bar)
        return status

    def _coord_spin(self, minimum: float, maximum: float) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(minimum, maximum)
        spin.setDecimals(3)
        spin.setSingleStep(1.0)
        spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.PlusMinus)
        spin.setMinimumWidth(110)
        return spin

    def _on_map_bbox_changed(self, bbox: tuple[float, float, float, float]) -> None:
        self._apply_bbox(bbox, update_map=False)
        self._mark_selection_dirty()

    def _on_spin_bbox_changed(self) -> None:
        if self._syncing_bbox:
            return
        bbox = (self.min_lon.value(), self.min_lat.value(), self.max_lon.value(), self.max_lat.value())
        if self.map_widget is not None:
            self.map_widget.set_bbox(bbox)
        self._mark_selection_dirty()

    def _apply_bbox(self, bbox: tuple[float, float, float, float], update_map: bool) -> None:
        self._syncing_bbox = True
        self.min_lon.setValue(bbox[0])
        self.min_lat.setValue(bbox[1])
        self.max_lon.setValue(bbox[2])
        self.max_lat.setValue(bbox[3])
        self._syncing_bbox = False
        if update_map and self.map_widget is not None:
            self.map_widget.set_bbox(bbox)

    def _selected_bbox(self) -> tuple[float, float, float, float]:
        lon1, lon2 = sorted((self.min_lon.value(), self.max_lon.value()))
        lat1, lat2 = sorted((self.min_lat.value(), self.max_lat.value()))
        return lon1, lat1, lon2, lat2

    def _selected_date(self) -> date:
        qdate = self.date_edit.date()
        return date(qdate.year(), qdate.month(), qdate.day())

    def _report_key(self) -> tuple:
        bbox = tuple(round(x, 4) for x in self._selected_bbox())
        return bbox, self._selected_date().isoformat()

    def _mark_selection_dirty(self) -> None:
        if self.current_report is None:
            return
        if self._report_key() == self._last_report_key:
            return
        self.status_label.setText("选区或日期已改变，请点击“获取最新”刷新云图")
        self.image_meta_label.setText("选区已改变，等待重新获取")
        self.result_text.setPlainText(
            "当前右侧云图还是上一次获取的结果。\n"
            "请点击“获取最新”，程序会按新的框选区域重新下载 NASA 云图。"
        )

    def _start_fetch(self, force_refresh: bool = True) -> None:
        if self.worker is not None and self.worker.isRunning():
            return
        bbox = self._selected_bbox()
        self.config.default_bbox = bbox
        save_config(self.config)
        self._set_busy(True)
        self.status_label.setText("正在连接 NASA GIBS...")
        self.result_text.setPlainText("正在获取云图和计算云量...")
        self.image_meta_label.setText("请求中")

        self.worker = FetchWorker(self.config, bbox, self._selected_date(), force_refresh=force_refresh)
        self.worker.progress.connect(self.status_label.setText)
        self.worker.finished_report.connect(self._on_report_ready)
        self.worker.failed.connect(self._on_fetch_failed)
        self.worker.finished.connect(lambda: self._set_busy(False))
        self.worker.start()

    def _on_report_ready(self, report: CloudReport) -> None:
        self.current_report = report
        self._last_report_key = self._report_key()
        pixmap = QPixmap(str(report.preview.path))
        if not pixmap.isNull():
            self._set_preview_pixmap(pixmap)
        else:
            self.preview_label.setText("云图预览无法加载")

        latest = report.latest
        source = "缓存" if latest.from_cache else "在线获取"
        self.image_meta_label.setText(f"{report.preview.layer} · {report.preview.date.isoformat()}")
        self.cloud_card.set_values(f"{latest.estimate.cloud_percent:.0f}%", f"有效覆盖 {latest.estimate.valid_coverage_percent:.1f}%")
        self.trend_card.set_values(report.trend_label, report.trend_detail)
        self.confidence_card.set_values(latest.estimate.confidence.value, confidence_text(latest.estimate.confidence))

        min_lon, min_lat, max_lon, max_lat = report.bbox
        weather_lines = "\n".join(report.weather_advice.as_lines())
        preview_size = f"{report.preview.image.width} x {report.preview.image.height}"
        self.result_text.setPlainText(
            f"{report.conclusion}\n\n"
            f"天气预报式判读：\n{weather_lines}\n\n"
            f"区域：经度 {min_lon:.3f} 至 {max_lon:.3f}，纬度 {min_lat:.3f} 至 {max_lat:.3f}\n"
            f"分析图层：{latest.layer}\n"
            f"预览图层：{report.preview.layer}\n"
            f"来源：{source}\n"
            f"算法：{latest.estimate.method}\n\n"
            "说明：该结果为卫星影像辅助分析，不替代正式天气预报、雷达回波和地面观测。"
        )
        self.result_text.append(f"\nNASA 请求尺寸：{preview_size}（按当前框选区域比例生成）")
        self.result_text.append("黑色或透明斜带通常是当天卫星轨道未覆盖/无数据区域，不是图片压缩。")
        self._fill_history_table(report)
        self.export_button.setEnabled(True)
        self.status_label.setText("完成")

    def _fill_history_table(self, report: CloudReport) -> None:
        self.history_table.setRowCount(len(report.history))
        for row, item in enumerate(report.history):
            values = [
                item.date.isoformat(),
                f"{item.estimate.cloud_percent:.0f}%",
                item.layer,
                "缓存" if item.from_cache else "在线",
            ]
            for col, value in enumerate(values):
                table_item = QTableWidgetItem(value)
                if col == 1:
                    table_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.history_table.setItem(row, col, table_item)

    def _on_fetch_failed(self, message: str) -> None:
        self.current_report = None
        self.export_button.setEnabled(False)
        self.image_meta_label.setText("获取失败")
        self.status_label.setText("获取失败")
        self.result_text.setPlainText(message)
        QMessageBox.warning(self, "获取失败", message)

    def _export_current_report(self) -> None:
        if self.current_report is None:
            return
        image_path, text_path = export_report(self.current_report, REPORTS_DIR)
        QMessageBox.information(self, "导出完成", f"图片：{image_path}\n报告：{text_path}")

    def _set_preview_pixmap(self, pixmap: QPixmap) -> None:
        self._preview_pixmap = pixmap
        self._refresh_preview_size()

    def _refresh_preview_size(self) -> None:
        if self._preview_pixmap is None or self._preview_pixmap.isNull():
            return
        scaled = self._preview_pixmap.scaled(
            self.preview_label.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.preview_label.setPixmap(scaled)

    def _set_busy(self, busy: bool) -> None:
        self.fetch_button.setEnabled(not busy)
        self.export_button.setEnabled((not busy) and self.current_report is not None)
        self.date_edit.setEnabled(not busy)
        self.progress_bar.setVisible(busy)
        if busy:
            self.progress_bar.setRange(0, 0)
        else:
            self.progress_bar.setRange(0, 1)

    def _apply_style(self) -> None:
        self.setStyleSheet(
            """
            QWidget#appRoot {
                background: #eef3f5;
                color: #18323a;
                font-family: "Microsoft YaHei", "Segoe UI", sans-serif;
                font-size: 13px;
            }
            QFrame#header, QFrame#controlStrip, QFrame#bottomStatus,
            QFrame#imageFrame, QFrame#metricCard {
                background: #ffffff;
                border: 1px solid #d5dde1;
                border-radius: 8px;
            }
            QScrollArea#panelScrollArea {
                background: transparent;
                border: 0;
            }
            QScrollArea#panelScrollArea > QWidget > QWidget {
                background: transparent;
            }
            QLabel#appTitle {
                font-size: 24px;
                font-weight: 700;
                color: #102f38;
            }
            QLabel#appSubtitle, QLabel#mutedLabel, QLabel#metricDetail {
                color: #60757d;
            }
            QLabel#sourceBadge {
                background: #e7f0f3;
                color: #28525e;
                border: 1px solid #c6d8de;
                border-radius: 12px;
                padding: 6px 12px;
            }
            QLabel#sectionTitle {
                font-size: 16px;
                font-weight: 700;
            }
            QLabel#previewLabel {
                background: #132329;
                color: #c8d5da;
                border-radius: 6px;
            }
            QLabel#metricTitle {
                color: #60757d;
                font-size: 13px;
                font-weight: 700;
            }
            QLabel#metricValue {
                font-size: 30px;
                font-weight: 800;
                color: #173c46;
            }
            QLabel#metricDetail {
                font-size: 13px;
                font-weight: 600;
                line-height: 1.35;
            }
            QGroupBox {
                background: #ffffff;
                border: 1px solid #d5dde1;
                border-radius: 8px;
                margin-top: 10px;
                padding: 10px;
                font-weight: 600;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 6px;
                color: #284a53;
            }
            QPushButton {
                min-height: 30px;
                padding: 5px 12px;
                border: 1px solid #b9c9cf;
                border-radius: 6px;
                background: #f8fafb;
            }
            QPushButton:hover {
                background: #eef5f7;
                border-color: #88aeb8;
            }
            QPushButton:pressed {
                background: #dfecef;
            }
            QPushButton:disabled {
                color: #9aa7ab;
                background: #f0f2f3;
            }
            QPushButton#presetButton {
                min-height: 26px;
                padding: 3px 10px;
            }
            QDateEdit, QDoubleSpinBox {
                min-height: 28px;
                border: 1px solid #c5d0d4;
                border-radius: 5px;
                padding: 2px 6px;
                background: #ffffff;
            }
            QTextEdit#resultText, QTableWidget#historyTable {
                background: #ffffff;
                border: 1px solid #d5dde1;
                border-radius: 8px;
                padding: 10px;
                color: #18323a;
            }
            QTextEdit#resultText {
                font-size: 16px;
                font-weight: 650;
                line-height: 1.5;
            }
            QTableWidget#historyTable {
                font-size: 13px;
                font-weight: 600;
            }
            QHeaderView::section {
                background: #edf3f5;
                border: 0;
                border-right: 1px solid #d5dde1;
                padding: 6px;
                font-weight: 600;
            }
            QProgressBar {
                border: 1px solid #c5d0d4;
                border-radius: 6px;
                background: #ffffff;
            }
            QProgressBar::chunk {
                background: #397b8d;
                border-radius: 6px;
            }
            QScrollBar:vertical {
                background: #edf3f5;
                width: 10px;
                margin: 0;
                border-radius: 5px;
            }
            QScrollBar::handle:vertical {
                background: #b8c9cf;
                min-height: 34px;
                border-radius: 5px;
            }
            QScrollBar::handle:vertical:hover {
                background: #8faab3;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0;
            }
            QScrollBar:horizontal {
                background: #edf3f5;
                height: 10px;
                margin: 0;
                border-radius: 5px;
            }
            QScrollBar::handle:horizontal {
                background: #b8c9cf;
                min-width: 34px;
                border-radius: 5px;
            }
            QScrollBar::handle:horizontal:hover {
                background: #8faab3;
            }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
                width: 0;
            }
            """
        )
