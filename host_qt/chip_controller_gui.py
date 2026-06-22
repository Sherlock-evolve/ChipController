#!/usr/bin/env python3
from collections import deque
import re
import sys
import time
from dataclasses import dataclass
from typing import Optional

from PySide6.QtCore import QPointF, QRectF, QObject, QTimer, Qt, Signal, Slot
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtSerialPort import QSerialPort, QSerialPortInfo
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)


CSV_HEADER = "index,tick_ms,status,current_nA,voltage_uV,resistance_mOhm,current_adc_status,voltage_adc_status"
CHIP_COMMAND_CHAR_DELAY_MS = 5
ADC_FILTER_SAMPLE_COUNT = 1
TREND_MAX_POINTS = 900


@dataclass
class AdcSample:
    index: int
    tick_ms: int
    status: int
    current_na: int
    voltage_uv: int
    resistance_mohm: int
    current_adc_status: int
    voltage_adc_status: int


@dataclass
class AdcFilteredSample:
    index: int
    current_na: int
    voltage_uv: int
    resistance_uohm: int
    current_adc_status: int
    voltage_adc_status: int


@dataclass(frozen=True)
class TrendSeries:
    key: str
    label: str
    band: str
    color: str
    decimals: int
    default_visible: bool = True
    dashed: bool = False


TREND_BANDS = [
    ("current", "电流", "mA", True),
    ("voltage", "电压", "mV", True),
    ("resistance", "电阻", "ohm", True),
    ("temperature", "温度", "C", False),
    ("drive", "驱动", "mV", True),
]

TREND_SERIES = [
    TrendSeries("current_ma", "实测电流", "current", "#0072B2", 4),
    TrendSeries("target_current_ma", "目标电流", "current", "#D55E00", 4, True, True),
    TrendSeries("voltage_mv", "电压", "voltage", "#009E73", 3),
    TrendSeries("resistance_ohm", "电阻", "resistance", "#CC79A7", 3),
    TrendSeries("chip_temp_c", "芯片温度", "temperature", "#E69F00", 2),
    TrendSeries("stage_temp_c", "冷台温度", "temperature", "#56B4E9", 2),
    TrendSeries("drive_mv", "驱动电压", "drive", "#000000", 1),
]


class TrendPlotWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._samples = deque(maxlen=TREND_MAX_POINTS)
        self._start_time = time.monotonic()
        self._visible = {series.key: series.default_visible for series in TREND_SERIES}
        self.setMinimumHeight(260)

    def add_sample(self, values):
        clean = {}
        for series in TREND_SERIES:
            value = values.get(series.key)
            if value is None:
                continue
            try:
                clean[series.key] = float(value)
            except (TypeError, ValueError):
                continue
        if not clean:
            return
        self._samples.append((time.monotonic() - self._start_time, clean))
        self.update()

    def clear(self):
        self._samples.clear()
        self._start_time = time.monotonic()
        self.update()

    def set_series_visible(self, key, visible):
        self._visible[key] = bool(visible)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#ffffff"))

        if not self._samples:
            painter.setPen(QColor("#667085"))
            painter.drawText(self.rect(), Qt.AlignCenter, "等待采样数据")
            return

        visible_series = [series for series in TREND_SERIES if self._visible.get(series.key, True)]
        bands = []
        for band_key, band_label, unit, zero_based in TREND_BANDS:
            band_series = [series for series in visible_series if series.band == band_key]
            if band_series:
                bands.append((band_key, band_label, unit, zero_based, band_series))

        if not bands:
            painter.setPen(QColor("#667085"))
            painter.drawText(self.rect(), Qt.AlignCenter, "未选择曲线")
            return

        margin_left = 88.0
        margin_right = 16.0
        margin_top = 12.0
        margin_bottom = 28.0
        band_gap = 8.0
        plot_rect = QRectF(
            margin_left,
            margin_top,
            max(40.0, self.width() - margin_left - margin_right),
            max(40.0, self.height() - margin_top - margin_bottom),
        )
        band_height = max(28.0, (plot_rect.height() - band_gap * (len(bands) - 1)) / len(bands))

        x_min = self._samples[0][0]
        x_max = self._samples[-1][0]
        if x_max <= x_min:
            x_max = x_min + 1.0

        for index, (_, band_label, unit, zero_based, band_series) in enumerate(bands):
            top = plot_rect.top() + index * (band_height + band_gap)
            area = QRectF(plot_rect.left(), top, plot_rect.width(), band_height)
            self._draw_band(painter, area, band_label, unit, zero_based, band_series, x_min, x_max)

        painter.setPen(QColor("#667085"))
        painter.drawText(
            QRectF(plot_rect.left(), self.height() - 22, 120, 18),
            Qt.AlignLeft | Qt.AlignVCenter,
            self._format_elapsed(x_min),
        )
        painter.drawText(
            QRectF(plot_rect.right() - 120, self.height() - 22, 120, 18),
            Qt.AlignRight | Qt.AlignVCenter,
            self._format_elapsed(x_max),
        )

    def _draw_band(self, painter, area, band_label, unit, zero_based, band_series, x_min, x_max):
        values = []
        for series in band_series:
            values.extend(value for _, value in self._series_points(series.key))

        painter.setPen(QPen(QColor("#D0D7E2"), 1))
        painter.setBrush(QColor("#FBFCFE"))
        painter.drawRect(area)

        if not values:
            painter.setPen(QColor("#667085"))
            painter.drawText(QRectF(6, area.top(), 76, area.height()), Qt.AlignLeft | Qt.AlignVCenter, band_label)
            return

        y_min = min(values)
        y_max = max(values)
        if zero_based:
            y_min = min(0.0, y_min)
            y_max = max(0.0, y_max)
        if y_max <= y_min:
            pad = max(abs(y_max) * 0.1, 1.0)
            y_min -= pad
            y_max += pad
        else:
            pad = (y_max - y_min) * 0.08
            if zero_based:
                y_max += pad
                y_min = min(0.0, y_min)
            else:
                y_min -= pad
                y_max += pad

        painter.setPen(QPen(QColor("#E5EAF1"), 1))
        for frac in (0.25, 0.5, 0.75):
            y = area.top() + area.height() * frac
            painter.drawLine(QPointF(area.left(), y), QPointF(area.right(), y))

        painter.setPen(QColor("#344054"))
        painter.drawText(QRectF(6, area.top() + 3, 78, 16), Qt.AlignLeft | Qt.AlignVCenter, f"{band_label} ({unit})")
        painter.setPen(QColor("#667085"))
        painter.drawText(
            QRectF(6, area.top() + 20, 78, 16),
            Qt.AlignLeft | Qt.AlignVCenter,
            self._format_value(y_max, 3),
        )
        painter.drawText(
            QRectF(6, area.bottom() - 18, 78, 16),
            Qt.AlignLeft | Qt.AlignVCenter,
            self._format_value(y_min, 3),
        )

        latest_parts = []
        for series in band_series:
            latest = self._latest_value(series.key)
            if latest is not None:
                latest_parts.append(f"{series.label} {latest:.{series.decimals}f}")
        if latest_parts:
            painter.drawText(
                QRectF(area.left() + 6, area.top() + 3, area.width() - 12, 16),
                Qt.AlignRight | Qt.AlignVCenter,
                "  ".join(latest_parts),
            )

        for series in band_series:
            points = []
            for timestamp, value in self._series_points(series.key):
                x = area.left() + (timestamp - x_min) / (x_max - x_min) * area.width()
                y = area.bottom() - (value - y_min) / (y_max - y_min) * area.height()
                points.append(QPointF(x, y))

            if not points:
                continue

            pen = QPen(QColor(series.color), 2)
            if series.dashed:
                pen.setStyle(Qt.DashLine)
            painter.setPen(pen)
            if len(points) == 1:
                painter.drawEllipse(points[0], 3.0, 3.0)
            else:
                for point_index in range(1, len(points)):
                    painter.drawLine(points[point_index - 1], points[point_index])

    def _series_points(self, key):
        points = []
        for timestamp, values in self._samples:
            value = values.get(key)
            if value is not None:
                points.append((timestamp, value))
        return points

    def _latest_value(self, key):
        for _, values in reversed(self._samples):
            value = values.get(key)
            if value is not None:
                return value
        return None

    @staticmethod
    def _format_value(value, decimals):
        return f"{value:.{decimals}f}"

    @staticmethod
    def _format_elapsed(seconds):
        seconds = max(0, int(seconds))
        minutes, sec = divmod(seconds, 60)
        return f"{minutes:02d}:{sec:02d}"


def list_serial_ports():
    ports = []
    for info in QSerialPortInfo.availablePorts():
        label = info.systemLocation()
        desc = info.description()
        serial = info.serialNumber()
        if desc or serial:
            label = f"{label} ({desc} {serial})".strip()
        ports.append((info.systemLocation(), label))
    return ports


def parse_key_values(text):
    result = {}
    for token in text.split():
        if "=" not in token:
            continue
        key, value = token.split("=", 1)
        result[key] = value.rstrip(",")
    return result


def parse_csv_sample(line):
    fields = line.split(",")
    if len(fields) != 8:
        return None
    if not fields[0].isdigit() or not fields[1].isdigit():
        return None
    try:
        return AdcSample(
            index=int(fields[0]),
            tick_ms=int(fields[1]),
            status=int(fields[2]),
            current_na=int(fields[3]),
            voltage_uv=int(fields[4]),
            resistance_mohm=int(fields[5]),
            current_adc_status=int(fields[6]),
            voltage_adc_status=int(fields[7]),
        )
    except ValueError:
        return None


class ChipAsciiClient(QObject):
    connectedChanged = Signal(bool)
    logLine = Signal(str)
    sampleReceived = Signal(object)
    filteredSampleReceived = Signal(object)
    controlStatusReceived = Signal(dict)
    boardTemperatureReceived = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.port = QSerialPort(self)
        self.port.readyRead.connect(self._on_ready_read)
        self.port.errorOccurred.connect(self._on_error)
        self._rx = ""
        self._tx_queue = []
        self._tx_timer = QTimer(self)
        self._tx_timer.timeout.connect(self._send_next_byte)
        self._last_tc = {}
        self._adcf_pending = False
        self._adcf_expected_count = 0
        self._adcf_last_sample = None

    def is_open(self):
        return self.port.isOpen()

    def open(self, port_name, baud):
        if self.port.isOpen():
            self.close()
        self.port.setPortName(port_name)
        self.port.setBaudRate(baud)
        self.port.setDataBits(QSerialPort.Data8)
        self.port.setParity(QSerialPort.NoParity)
        self.port.setStopBits(QSerialPort.OneStop)
        self.port.setFlowControl(QSerialPort.NoFlowControl)
        if not self.port.open(QSerialPort.ReadWrite):
            raise RuntimeError(self.port.errorString())
        self.connectedChanged.emit(True)

    def close(self):
        self._tx_timer.stop()
        self._tx_queue.clear()
        self._adcf_pending = False
        if self.port.isOpen():
            self.port.close()
        self.connectedChanged.emit(False)

    def send_command(self, command):
        if not self.port.isOpen():
            return
        for byte in (command + "\r\n").encode("ascii", errors="ignore"):
            self._tx_queue.append(bytes([byte]))
        if not self._tx_timer.isActive():
            self._tx_timer.start(CHIP_COMMAND_CHAR_DELAY_MS)

    def set_current_ma(self, current_ma):
        self.send_command(f"tc current {current_ma:.3f}")

    def stop_control(self):
        self.send_command("tc stop")

    def stop_stream(self):
        self._adcf_pending = False
        self._adcf_expected_count = 0
        self._adcf_last_sample = None

    def request_filtered_adc(self, count):
        if self._adcf_pending:
            return False
        self._adcf_pending = True
        self._adcf_expected_count = int(count)
        self._adcf_last_sample = None
        self.send_command(f"adcf {count}")
        return True

    def clear_filtered_adc_pending(self):
        self._adcf_pending = False
        self._adcf_expected_count = 0
        self._adcf_last_sample = None

    def request_status(self):
        self.send_command("tc status")

    def request_temperature(self):
        self.send_command("temp")

    @Slot()
    def _send_next_byte(self):
        if not self._tx_queue or not self.port.isOpen():
            self._tx_timer.stop()
            return
        self.port.write(self._tx_queue.pop(0))

    @Slot()
    def _on_ready_read(self):
        data = bytes(self.port.readAll()).decode("ascii", errors="ignore")
        for char in data:
            if char in "\r\n":
                line = self._rx.strip()
                self._rx = ""
                if line:
                    self._handle_line(line)
            else:
                self._rx += char

    @Slot(QSerialPort.SerialPortError)
    def _on_error(self, error):
        if error == QSerialPort.NoError:
            return
        if self.port.isOpen():
            self.logLine.emit(f"Chip serial error: {self.port.errorString()}")

    def _handle_line(self, line):
        if self._handle_filtered_adc_line(line):
            return

        self.logLine.emit(line)
        if line == CSV_HEADER:
            return
        sample = parse_csv_sample(line)
        if sample is not None:
            self.sampleReceived.emit(sample)
            return

        if line.startswith("OK TC "):
            self.controlStatusReceived.emit(parse_key_values(line))
            return

        if line.startswith("Temperature: "):
            self.boardTemperatureReceived.emit(parse_key_values(line))
            return

        if line.startswith("TC: "):
            self._last_tc.update(parse_key_values(line))
            return

        if line.startswith("TC target: "):
            values = parse_key_values(line)
            self._last_tc.update(values)
            for old_key, new_key in (
                ("temp", "target_temp_mC"),
                ("error", "temperature_error_mC"),
                ("current", "target_current_uA"),
                ("integral", "temperature_integral_uA"),
                ("drive", "target_drive_mV"),
            ):
                if old_key in values:
                    self._last_tc[new_key] = values[old_key]
            return

        if line.startswith("TC measured: "):
            values = parse_key_values(line)
            self._last_tc.update(values)
            for old_key, new_key in (
                ("temp", "measured_temp_mC"),
                ("current", "measured_current_uA"),
                ("voltage", "measured_voltage_mV"),
                ("power", "measured_power_uW"),
                ("R", "measured_resistance_mOhm"),
            ):
                if old_key in values:
                    self._last_tc[new_key] = values[old_key]
            self.controlStatusReceived.emit(dict(self._last_tc))

    def _handle_filtered_adc_line(self, line):
        if line.startswith("AD7190 filtered samples:"):
            values = parse_key_values(line)
            try:
                self._adcf_expected_count = int(values.get("count", self._adcf_expected_count))
            except ValueError:
                pass
            self._adcf_last_sample = None
            return True

        if line.startswith("adcf:"):
            self._adcf_pending = False
            self._adcf_expected_count = 0
            self._adcf_last_sample = None
            return False

        m = re.match(
            r"^adcf (\d+): I=(-?\d+) nA V=(-?\d+) uV R=(-?\d+) (mOhm|uOhm) "
            r"status current=(0x[0-9A-Fa-f]+) voltage=(0x[0-9A-Fa-f]+)$",
            line,
        )
        if not m:
            return False

        try:
            resistance_value = int(m.group(4))
            resistance_uohm = resistance_value * 1000 if m.group(5) == "mOhm" else resistance_value
            sample = AdcFilteredSample(
                index=int(m.group(1)),
                current_na=int(m.group(2)),
                voltage_uv=int(m.group(3)),
                resistance_uohm=resistance_uohm,
                current_adc_status=int(m.group(6), 16),
                voltage_adc_status=int(m.group(7), 16),
            )
            self._adcf_last_sample = sample
            if self._adcf_expected_count <= 0 or sample.index >= self._adcf_expected_count:
                self._adcf_pending = False
                self._adcf_expected_count = 0
                self.filteredSampleReceived.emit(sample)
        except (TypeError, ValueError):
            self._adcf_pending = False
            pass
        return True


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ChipController Host")
        self.resize(1040, 720)

        self.chip = ChipAsciiClient(self)
        self.telemetry_values = {}
        self._build_ui()
        self._connect_signals()
        self.refresh_ports()

        self.adc_filter_timer = QTimer(self)
        self.adc_filter_timer.timeout.connect(self._request_filtered_adc)
        self.adc_filter_watchdog = QTimer(self)
        self.adc_filter_watchdog.setSingleShot(True)
        self.adc_filter_watchdog.timeout.connect(self._adcf_timeout)

        self.status_timer = QTimer(self)
        self.status_timer.timeout.connect(self._poll_chip_status)
        self.status_timer.start(2000)

    def _build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)

        top = QHBoxLayout()
        top.addWidget(self._build_chip_group(), 1)
        top.addWidget(self._build_control_group(), 1)
        layout.addLayout(top)

        layout.addWidget(self._build_measure_group())

        layout.addWidget(self._build_trend_tabs(), 1)

    def _build_trend_tabs(self):
        tabs = QTabWidget()

        trend_page = QWidget()
        trend_layout = QVBoxLayout(trend_page)
        controls = QHBoxLayout()
        self.trend_checks = {}
        for series in TREND_SERIES:
            checkbox = QCheckBox(series.label)
            checkbox.setChecked(series.default_visible)
            checkbox.toggled.connect(lambda checked, key=series.key: self.trend_plot.set_series_visible(key, checked))
            self.trend_checks[series.key] = checkbox
            controls.addWidget(checkbox)
        controls.addStretch(1)
        self.clear_trend = QPushButton("清空曲线")
        controls.addWidget(self.clear_trend)
        trend_layout.addLayout(controls)

        self.trend_plot = TrendPlotWidget()
        trend_layout.addWidget(self.trend_plot, 1)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(1000)

        tabs.addTab(trend_page, "趋势图")
        tabs.addTab(self.log, "诊断")
        return tabs

    def _build_chip_group(self):
        group = QGroupBox("ChipController 串口")
        form = QFormLayout(group)

        self.chip_port = QComboBox()
        self.chip_baud = QComboBox()
        self.chip_baud.addItems(["115200", "230400", "921600"])
        self.chip_refresh = QPushButton("刷新")
        self.chip_connect = QPushButton("连接")

        row = QHBoxLayout()
        row.addWidget(self.chip_port, 1)
        row.addWidget(self.chip_refresh)
        row.addWidget(self.chip_connect)

        form.addRow("端口", row)
        form.addRow("波特率", self.chip_baud)
        return group

    def _build_control_group(self):
        group = QGroupBox("电流与采样")
        form = QFormLayout(group)

        self.current_ma = QDoubleSpinBox()
        self.current_ma.setRange(0.0, 20.0)
        self.current_ma.setDecimals(3)
        self.current_ma.setSingleStep(0.1)
        self.current_ma.setValue(1.0)

        self.set_current = QPushButton("设置电流")
        self.stop_current = QPushButton("停止/归零")

        current_row = QHBoxLayout()
        current_row.addWidget(self.current_ma)
        current_row.addWidget(self.set_current)
        current_row.addWidget(self.stop_current)
        form.addRow("目标电流 mA", current_row)

        self.filter_period = QSpinBox()
        self.filter_period.setRange(100, 60000)
        self.filter_period.setValue(200)
        self.filter_period.setSuffix(" ms")

        self.start_stream = QPushButton("开始滤波采样")
        self.stop_stream = QPushButton("停止滤波采样")

        filter_row = QHBoxLayout()
        filter_row.addWidget(self.filter_period)
        filter_row.addWidget(self.start_stream)
        filter_row.addWidget(self.stop_stream)
        form.addRow("采样周期", filter_row)

        self.poll_status = QCheckBox("轮询 tc status")
        self.poll_status.setChecked(True)
        form.addRow("", self.poll_status)
        return group

    def _build_measure_group(self):
        group = QGroupBox("实时数据")
        grid = QGridLayout(group)

        self.current_label = QLabel("--")
        self.voltage_label = QLabel("--")
        self.resistance_label = QLabel("--")
        self.adc_status_label = QLabel("--")
        self.control_mode = QLabel("--")
        self.control_drive = QLabel("--")
        self.chip_temp = QLabel("--")
        self.stage_temp = QLabel("--")

        labels = [
            ("电流 ADC", self.current_label),
            ("电压 ADC", self.voltage_label),
            ("外接电阻", self.resistance_label),
            ("ADC 状态", self.adc_status_label),
            ("控制模式", self.control_mode),
            ("驱动电压", self.control_drive),
            ("芯片温度", self.chip_temp),
            ("冷台温度", self.stage_temp),
        ]

        for index, (name, widget) in enumerate(labels):
            row = index // 3
            col = (index % 3) * 2
            title = QLabel(name)
            title.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            widget.setMinimumWidth(170)
            grid.addWidget(title, row, col)
            grid.addWidget(widget, row, col + 1)
        return group

    def _connect_signals(self):
        self.chip_refresh.clicked.connect(self.refresh_ports)
        self.chip_connect.clicked.connect(self._toggle_chip)
        self.set_current.clicked.connect(self._set_current)
        self.stop_current.clicked.connect(self._stop_current)
        self.start_stream.clicked.connect(self._start_stream)
        self.stop_stream.clicked.connect(self._stop_stream)
        self.clear_trend.clicked.connect(self._clear_trend)

        self.chip.connectedChanged.connect(self._chip_connected_changed)
        self.chip.logLine.connect(self._append_log)
        self.chip.sampleReceived.connect(self._update_sample)
        self.chip.filteredSampleReceived.connect(self._update_filtered_sample)
        self.chip.controlStatusReceived.connect(self._update_control_status)
        self.chip.boardTemperatureReceived.connect(self._update_board_temperature)

    def refresh_ports(self):
        current_chip = self.chip_port.currentData()
        ports = list_serial_ports()
        self.chip_port.blockSignals(True)
        self.chip_port.clear()
        for system_location, label in ports:
            self.chip_port.addItem(label, system_location)
        if current_chip:
            idx = self.chip_port.findData(current_chip)
            if idx >= 0:
                self.chip_port.setCurrentIndex(idx)
        self.chip_port.blockSignals(False)

    def _toggle_chip(self):
        if self.chip.is_open():
            self.chip.close()
            return
        port = self.chip_port.currentData()
        if not port:
            QMessageBox.warning(self, "串口", "没有可用的 ChipController 串口")
            return
        try:
            self.chip.open(port, int(self.chip_baud.currentText()))
        except RuntimeError as exc:
            QMessageBox.critical(self, "串口打开失败", str(exc))

    def _chip_connected_changed(self, connected):
        self.chip_connect.setText("断开" if connected else "连接")
        self._append_log("ChipController connected" if connected else "ChipController disconnected")

    def _set_current(self):
        target_ma = self.current_ma.value()
        self.chip.set_current_ma(target_ma)
        if self.chip.is_open():
            self._record_telemetry(target_current_ma=target_ma)

    def _stop_current(self):
        self.chip.stop_control()
        self.chip.send_command("zero")
        if self.chip.is_open():
            self._record_telemetry(target_current_ma=0.0, drive_mv=0.0)

    def _start_stream(self):
        self.chip.stop_stream()
        self._request_filtered_adc()
        self.adc_filter_timer.start(self.filter_period.value())

    def _stop_stream(self):
        self.adc_filter_timer.stop()
        self.adc_filter_watchdog.stop()
        self.chip.stop_stream()

    def _request_filtered_adc(self):
        if self.chip.is_open():
            if self.chip.request_filtered_adc(ADC_FILTER_SAMPLE_COUNT):
                self.adc_filter_watchdog.start(max(5000, self.filter_period.value() * 3))

    def _adcf_timeout(self):
        self.chip.clear_filtered_adc_pending()
        self._append_log("adcf timeout: previous filtered sample request was released")

    def _poll_chip_status(self):
        if self.poll_status.isChecked() and self.chip.is_open():
            self.chip.request_status()
            self.chip.request_temperature()

    @Slot(str)
    def _append_log(self, line):
        self.log.appendPlainText(line)

    def _clear_trend(self):
        self.telemetry_values.clear()
        self.trend_plot.clear()

    def _record_telemetry(self, **updates):
        changed = False
        for key, value in updates.items():
            if value is None:
                continue
            try:
                self.telemetry_values[key] = float(value)
            except (TypeError, ValueError):
                continue
            changed = True
        if changed:
            self.trend_plot.add_sample(self.telemetry_values)

    @staticmethod
    def _int_value(value):
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @Slot(object)
    def _update_sample(self, sample):
        self.current_label.setText(f"{sample.current_na / 1_000_000.0:.6f} mA  ({sample.current_na} nA)")
        self.voltage_label.setText(f"{sample.voltage_uv / 1000.0:.3f} mV  ({sample.voltage_uv} uV)")
        self.resistance_label.setText(f"{sample.resistance_mohm / 1000.0:.6f} ohm")
        self.adc_status_label.setText(f"current=0x{sample.current_adc_status:02X}, voltage=0x{sample.voltage_adc_status:02X}")
        self._record_telemetry(
            current_ma=sample.current_na / 1_000_000.0,
            voltage_mv=sample.voltage_uv / 1000.0,
            resistance_ohm=sample.resistance_mohm / 1000.0,
        )

    @Slot(object)
    def _update_filtered_sample(self, sample):
        self.adc_filter_watchdog.stop()
        self.current_label.setText(
            f"{sample.current_na / 1_000_000.0:.6f} mA  ({sample.current_na} nA)"
        )
        self.voltage_label.setText(
            f"{sample.voltage_uv / 1000.0:.3f} mV  ({sample.voltage_uv} uV)"
        )
        self.resistance_label.setText(f"{sample.resistance_uohm / 1_000_000.0:.6f} ohm")
        self.adc_status_label.setText(
            f"current=0x{sample.current_adc_status:02X}, voltage=0x{sample.voltage_adc_status:02X}"
        )
        self._record_telemetry(
            current_ma=sample.current_na / 1_000_000.0,
            voltage_mv=sample.voltage_uv / 1000.0,
            resistance_ohm=sample.resistance_uohm / 1_000_000.0,
        )

    @Slot(dict)
    def _update_control_status(self, values):
        mode = values.get("mode")
        enabled = values.get("enabled")
        fault = values.get("fault")
        status = values.get("status")
        if mode is not None:
            self.control_mode.setText(f"{mode}, enabled={enabled}, fault={fault}, status={status}")

        drive = values.get("target_drive_mV") or values.get("drive") or values.get("drive_mV")
        if drive is not None:
            self.control_drive.setText(f"{drive} mV")

        target_current_ua = self._int_value(values.get("target_current_uA"))
        measured_current_ua = self._int_value(values.get("measured_current_uA"))
        measured_voltage_mv = self._int_value(values.get("measured_voltage_mV"))
        measured_resistance_mohm = self._int_value(values.get("measured_resistance_mOhm"))
        drive_mv = self._int_value(drive)

        self._record_telemetry(
            target_current_ma=None if target_current_ua is None else target_current_ua / 1000.0,
            current_ma=None if measured_current_ua is None else measured_current_ua / 1000.0,
            voltage_mv=measured_voltage_mv,
            resistance_ohm=None if measured_resistance_mohm is None else measured_resistance_mohm / 1000.0,
            drive_mv=drive_mv,
        )

    @Slot(dict)
    def _update_board_temperature(self, values):
        chip_temp = values.get("chip_mC")
        stage_temp = values.get("stage_mC")
        stage_status = values.get("stage_status")
        chip_temp_c = None
        stage_temp_c = None

        if chip_temp is not None:
            try:
                chip_temp_c = int(chip_temp) / 1000.0
                self.chip_temp.setText(f"{chip_temp_c:.3f} C")
            except ValueError:
                self.chip_temp.setText(str(chip_temp))

        if stage_temp is not None:
            try:
                stage_temp_c = int(stage_temp) / 1000.0
                self.stage_temp.setText(f"{stage_temp_c:.3f} C")
            except ValueError:
                self.stage_temp.setText(str(stage_temp))
        elif stage_status is not None:
            self.stage_temp.setText(stage_status)

        self._record_telemetry(chip_temp_c=chip_temp_c, stage_temp_c=stage_temp_c)


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
