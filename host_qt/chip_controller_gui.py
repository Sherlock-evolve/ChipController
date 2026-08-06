#!/usr/bin/env python3
from collections import deque
import csv
from datetime import datetime
from pathlib import Path
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
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
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
PROJECT_ROOT = Path(__file__).resolve().parents[1]
CHIP_TEMPERATURE_REFERENCE_RESISTANCE_OHM = 40.230272
CHIP_TEMPERATURE_REFERENCE_TEMPERATURE_C = 20.776
CHIP_TEMPERATURE_TCR_PER_C = 0.002353946928

EXPERIMENT_LOG_FIELDS = [
    "timestamp",
    "I_nA",
    "V_uV",
    "R_uOhm",
    "chip_temp_C",
    "note",
    "elapsed_s",
    "current_adc_status",
    "voltage_adc_status",
    "control_mode",
    "control_enabled",
    "control_fault",
    "control_status",
    "target_current_mA",
    "measured_current_mA",
    "measured_voltage_mV",
    "measured_resistance_ohm",
    "target_temp_C",
    "measured_temp_C",
    "temperature_error_C",
    "temperature_integral_mA",
    "drive_mV",
    "power_uW",
]


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
    TrendSeries("target_temp_c", "目标温度", "temperature", "#56B4E9", 2, True, True),
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
            for segment in self._series_segments(series.key):
                values.extend(value for _, value in segment)

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
            pen = QPen(QColor(series.color), 2)
            if series.dashed:
                pen.setStyle(Qt.DashLine)
            painter.setPen(pen)
            for segment in self._series_segments(series.key):
                points = []
                for timestamp, value in segment:
                    x = area.left() + (timestamp - x_min) / (x_max - x_min) * area.width()
                    y = area.bottom() - (value - y_min) / (y_max - y_min) * area.height()
                    points.append(QPointF(x, y))

                if len(points) == 1:
                    painter.drawEllipse(points[0], 3.0, 3.0)
                else:
                    for point_index in range(1, len(points)):
                        painter.drawLine(points[point_index - 1], points[point_index])

    def _series_segments(self, key):
        segments = []
        segment = []
        for timestamp, values in self._samples:
            value = values.get(key)
            if value is None:
                if segment:
                    segments.append(segment)
                    segment = []
                continue
            segment.append((timestamp, value))
        if segment:
            segments.append(segment)
        return segments

    def _latest_value(self, key):
        if not self._samples:
            return None
        return self._samples[-1][1].get(key)

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


def chip_temperature_from_resistance(resistance_ohm):
    if resistance_ohm is None or resistance_ohm <= 0.0:
        return None
    return CHIP_TEMPERATURE_REFERENCE_TEMPERATURE_C + (
        resistance_ohm - CHIP_TEMPERATURE_REFERENCE_RESISTANCE_OHM
    ) / (
        CHIP_TEMPERATURE_TCR_PER_C * CHIP_TEMPERATURE_REFERENCE_RESISTANCE_OHM
    )


class ExperimentCsvLogger:
    def __init__(self):
        self._file = None
        self._writer = None
        self.path = None
        self.started_monotonic = None
        self.sample_count = 0
        self.missed_count = 0

    @property
    def active(self):
        return self._file is not None

    def start(self, path):
        if self.active:
            raise RuntimeError("实验日志已经在记录")

        output_path = Path(path).expanduser()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_file = output_path.open("w", newline="", encoding="utf-8-sig", buffering=1)
        writer = csv.DictWriter(
            output_file,
            fieldnames=EXPERIMENT_LOG_FIELDS,
            extrasaction="ignore",
        )
        try:
            writer.writeheader()
            output_file.flush()
        except Exception:
            output_file.close()
            raise

        self._file = output_file
        self._writer = writer
        self.path = output_path
        self.started_monotonic = time.monotonic()
        self.sample_count = 0
        self.missed_count = 0

    def append(self, values, missed=False):
        if not self.active:
            raise RuntimeError("实验日志尚未开始")

        row = {field: "" for field in EXPERIMENT_LOG_FIELDS}
        row.update(values)
        row["timestamp"] = datetime.now().isoformat(sep=" ", timespec="milliseconds")
        row["elapsed_s"] = f"{time.monotonic() - self.started_monotonic:.3f}"
        self._writer.writerow(row)
        self._file.flush()

        if missed:
            self.missed_count += 1
        else:
            self.sample_count += 1

    def close(self):
        output_file = self._file
        self._file = None
        self._writer = None
        self.started_monotonic = None
        if output_file is not None:
            try:
                output_file.flush()
            finally:
                output_file.close()


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

    def set_temperature_c(self, temperature_c):
        self.send_command(f"tc temp {temperature_c:.3f}")

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
        self.control_values = {}
        self.experiment_logger = ExperimentCsvLogger()
        self._record_path_custom = False
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

        self.record_status_timer = QTimer(self)
        self.record_status_timer.timeout.connect(self._update_record_status)

    def _build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)

        top = QHBoxLayout()
        top.addWidget(self._build_chip_group(), 1)
        top.addWidget(self._build_control_group(), 1)
        layout.addLayout(top)

        layout.addWidget(self._build_measure_group())

        layout.addWidget(self._build_record_group())

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
        group = QGroupBox("温控与采样")
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

        self.temperature_c = QDoubleSpinBox()
        self.temperature_c.setRange(-200.0, 100.0)
        self.temperature_c.setDecimals(3)
        self.temperature_c.setSingleStep(0.5)
        self.temperature_c.setValue(20.0)
        self.set_temperature = QPushButton("设置恒温")

        temperature_row = QHBoxLayout()
        temperature_row.addWidget(self.temperature_c)
        temperature_row.addWidget(self.set_temperature)
        form.addRow("目标温度 C", temperature_row)

        self.filter_period = QSpinBox()
        self.filter_period.setRange(100, 60000)
        self.filter_period.setValue(500)
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
        self.target_temp = QLabel("--")
        self.temperature_error = QLabel("--")

        labels = [
            ("电流 ADC", self.current_label),
            ("电压 ADC", self.voltage_label),
            ("外接电阻", self.resistance_label),
            ("ADC 状态", self.adc_status_label),
            ("控制模式", self.control_mode),
            ("驱动电压", self.control_drive),
            ("芯片温度", self.chip_temp),
            ("目标温度", self.target_temp),
            ("温度误差", self.temperature_error),
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

    def _build_record_group(self):
        group = QGroupBox("实验数据记录")
        form = QFormLayout(group)

        self.record_path = QLineEdit(str(self._suggest_log_path()))
        self.record_path.setToolTip("CSV 文件兼容 tools/adcf_logger.py 与现有温度绘图脚本")
        self.record_browse = QPushButton("选择文件")

        path_row = QHBoxLayout()
        path_row.addWidget(self.record_path, 1)
        path_row.addWidget(self.record_browse)
        form.addRow("CSV 文件", path_row)

        self.record_note = QLineEdit()
        self.record_note.setPlaceholderText("可选；当前内容会写入每条记录的 note 列")
        form.addRow("实验备注", self.record_note)

        self.start_recording = QPushButton("开始记录")
        self.stop_recording = QPushButton("停止记录")
        self.stop_recording.setEnabled(False)
        self.record_status = QLabel("未记录")

        action_row = QHBoxLayout()
        action_row.addWidget(self.start_recording)
        action_row.addWidget(self.stop_recording)
        action_row.addWidget(self.record_status, 1)
        form.addRow("记录状态", action_row)
        return group

    def _connect_signals(self):
        self.chip_refresh.clicked.connect(self.refresh_ports)
        self.chip_connect.clicked.connect(self._toggle_chip)
        self.set_current.clicked.connect(self._set_current)
        self.set_temperature.clicked.connect(self._set_temperature)
        self.stop_current.clicked.connect(self._stop_current)
        self.start_stream.clicked.connect(self._start_stream)
        self.stop_stream.clicked.connect(self._stop_stream)
        self.filter_period.valueChanged.connect(self._filter_period_changed)
        self.clear_trend.clicked.connect(self._clear_trend)
        self.record_browse.clicked.connect(self._choose_record_path)
        self.record_path.textEdited.connect(self._record_path_edited)
        self.start_recording.clicked.connect(self._start_recording)
        self.stop_recording.clicked.connect(self._stop_recording)

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
        if not connected:
            self.adc_filter_timer.stop()
            self.adc_filter_watchdog.stop()
            self._finish_recording("串口已断开")

    def _set_current(self):
        target_ma = self.current_ma.value()
        self.chip.set_current_ma(target_ma)
        if self.chip.is_open():
            self._set_local_control_mode("CURRENT", target_current_ma=target_ma)

    def _set_temperature(self):
        target_c = self.temperature_c.value()
        self.chip.set_temperature_c(target_c)
        if self.chip.is_open():
            self._set_local_control_mode("TEMPERATURE", target_temp_c=target_c)

    def _stop_current(self):
        self.chip.stop_control()
        self.chip.send_command("zero")
        if self.chip.is_open():
            self._set_local_control_mode("OFF", drive_mv=0.0)

    def _start_stream(self):
        if not self.chip.is_open():
            QMessageBox.warning(self, "滤波采样", "请先连接 ChipController 串口")
            return
        self.chip.stop_stream()
        self._request_filtered_adc()
        self.adc_filter_timer.start(self.filter_period.value())

    def _stop_stream(self):
        self.adc_filter_timer.stop()
        self.adc_filter_watchdog.stop()
        self.chip.stop_stream()
        if self.experiment_logger.active:
            self._finish_recording("滤波采样已停止")

    def _filter_period_changed(self, period_ms):
        if self.adc_filter_timer.isActive():
            self.adc_filter_timer.setInterval(period_ms)

    def _request_filtered_adc(self):
        if self.chip.is_open():
            if self.chip.request_filtered_adc(ADC_FILTER_SAMPLE_COUNT):
                self.adc_filter_watchdog.start(max(5000, self.filter_period.value() * 3))

    def _adcf_timeout(self):
        self.chip.clear_filtered_adc_pending()
        self._append_log("adcf timeout: previous filtered sample request was released")
        self._write_experiment_timeout()

    def _poll_chip_status(self):
        if self.poll_status.isChecked() and self.chip.is_open():
            self.chip.request_status()
            if not self.adc_filter_timer.isActive():
                self.chip.request_temperature()

    @Slot(str)
    def _append_log(self, line):
        self.log.appendPlainText(line)

    def _clear_trend(self):
        self.telemetry_values.clear()
        self.trend_plot.clear()

    @staticmethod
    def _suggest_log_path():
        base = PROJECT_ROOT / f"adcf_log_{datetime.now():%Y%m%d_%H%M%S}.csv"
        if not base.exists():
            return base
        for index in range(1, 1000):
            candidate = base.with_name(f"{base.stem}_{index}.csv")
            if not candidate.exists():
                return candidate
        return base.with_name(f"{base.stem}_{time.time_ns()}.csv")

    def _record_path_edited(self, _text):
        self._record_path_custom = True

    def _choose_record_path(self):
        selected, _ = QFileDialog.getSaveFileName(
            self,
            "选择实验 CSV 文件",
            self.record_path.text().strip() or str(self._suggest_log_path()),
            "CSV 文件 (*.csv);;所有文件 (*)",
        )
        if selected:
            if not selected.lower().endswith(".csv"):
                selected += ".csv"
            self.record_path.setText(selected)
            self._record_path_custom = True

    def _start_recording(self):
        if self.experiment_logger.active:
            return
        if not self.chip.is_open():
            QMessageBox.warning(self, "实验记录", "请先连接 ChipController 串口")
            return

        path_text = self.record_path.text().strip()
        if not path_text:
            path_text = str(self._suggest_log_path())
            self.record_path.setText(path_text)
        output_path = Path(path_text).expanduser()

        if output_path.exists():
            answer = QMessageBox.question(
                self,
                "覆盖实验日志",
                f"文件已经存在，是否覆盖？\n{output_path}",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return

        try:
            self.experiment_logger.start(output_path)
        except (OSError, RuntimeError) as exc:
            QMessageBox.critical(self, "无法开始记录", str(exc))
            return

        self.record_path.setEnabled(False)
        self.record_browse.setEnabled(False)
        self.start_recording.setEnabled(False)
        self.stop_recording.setEnabled(True)
        self.record_status_timer.start(1000)
        self._update_record_status()
        self._append_log(f"实验记录开始: {output_path}")

        if not self.adc_filter_timer.isActive():
            self._start_stream()

    def _stop_recording(self):
        self._finish_recording("用户停止")

    def _finish_recording(self, reason):
        if not self.experiment_logger.active:
            return

        path = self.experiment_logger.path
        samples = self.experiment_logger.sample_count
        missed = self.experiment_logger.missed_count
        try:
            self.experiment_logger.close()
        except OSError as exc:
            self._append_log(f"实验日志关闭失败: {exc}")

        self.record_status_timer.stop()
        self.record_path.setEnabled(True)
        self.record_browse.setEnabled(True)
        self.start_recording.setEnabled(True)
        self.stop_recording.setEnabled(False)
        self.record_status.setText(f"已停止：{samples} 条，{missed} 次超时")
        self.record_status.setToolTip(str(path))
        self._append_log(
            f"实验记录结束: {path}，成功={samples}，超时={missed}，原因={reason}"
        )

        if not self._record_path_custom:
            self.record_path.setText(str(self._suggest_log_path()))

    def _update_record_status(self):
        if not self.experiment_logger.active:
            return
        elapsed = max(0, int(time.monotonic() - self.experiment_logger.started_monotonic))
        hours, remainder = divmod(elapsed, 3600)
        minutes, seconds = divmod(remainder, 60)
        self.record_status.setText(
            f"记录中 {hours:02d}:{minutes:02d}:{seconds:02d}，"
            f"{self.experiment_logger.sample_count} 条，"
            f"{self.experiment_logger.missed_count} 次超时"
        )
        self.record_status.setToolTip(str(self.experiment_logger.path))

    @staticmethod
    def _scaled_control_value(values, key, scale):
        value = values.get(key)
        if value is None:
            return ""
        try:
            return int(value) / scale
        except (TypeError, ValueError):
            return ""

    def _control_log_values(self):
        values = self.control_values
        mode = str(values.get("mode", "")).upper()
        temperature_mode = mode == "TEMPERATURE"
        active_mode = mode in ("CURRENT", "TEMPERATURE")
        return {
            "control_mode": values.get("mode", ""),
            "control_enabled": values.get("enabled", ""),
            "control_fault": values.get("fault", ""),
            "control_status": values.get("status", ""),
            "target_current_mA": (
                self._scaled_control_value(values, "target_current_uA", 1000.0)
                if active_mode
                else ""
            ),
            "measured_current_mA": self._scaled_control_value(values, "measured_current_uA", 1000.0),
            "measured_voltage_mV": self._scaled_control_value(values, "measured_voltage_mV", 1.0),
            "measured_resistance_ohm": self._scaled_control_value(
                values, "measured_resistance_mOhm", 1000.0
            ),
            "target_temp_C": (
                self._scaled_control_value(values, "target_temp_mC", 1000.0)
                if temperature_mode
                else ""
            ),
            "measured_temp_C": self._scaled_control_value(values, "measured_temp_mC", 1000.0),
            "temperature_error_C": (
                self._scaled_control_value(values, "temperature_error_mC", 1000.0)
                if temperature_mode
                else ""
            ),
            "temperature_integral_mA": (
                self._scaled_control_value(values, "temperature_integral_uA", 1000.0)
                if temperature_mode
                else ""
            ),
            "drive_mV": self._scaled_control_value(values, "target_drive_mV", 1.0),
            "power_uW": self._scaled_control_value(values, "measured_power_uW", 1.0),
        }

    def _combined_record_note(self, system_note=""):
        parts = [part for part in (system_note, self.record_note.text().strip()) if part]
        return "; ".join(parts)

    def _write_experiment_sample(self, sample, chip_temp_c):
        if not self.experiment_logger.active:
            return

        values = {
            "I_nA": sample.current_na,
            "V_uV": sample.voltage_uv,
            "R_uOhm": sample.resistance_uohm,
            "chip_temp_C": "" if chip_temp_c is None else f"{chip_temp_c:.6f}",
            "note": self._combined_record_note(),
            "current_adc_status": f"0x{sample.current_adc_status:02X}",
            "voltage_adc_status": f"0x{sample.voltage_adc_status:02X}",
        }
        values.update(self._control_log_values())
        try:
            self.experiment_logger.append(values)
        except (OSError, RuntimeError) as exc:
            self._finish_recording("写入失败")
            QMessageBox.critical(self, "实验日志写入失败", str(exc))
            return
        self._update_record_status()

    def _write_experiment_timeout(self):
        if not self.experiment_logger.active:
            return
        values = {
            "note": self._combined_record_note("timeout/no-match"),
        }
        values.update(self._control_log_values())
        try:
            self.experiment_logger.append(values, missed=True)
        except (OSError, RuntimeError) as exc:
            self._finish_recording("写入失败")
            QMessageBox.critical(self, "实验日志写入失败", str(exc))
            return
        self._update_record_status()

    def _record_telemetry(self, clear_keys=(), **updates):
        changed = False
        for key in clear_keys:
            if key in self.telemetry_values:
                del self.telemetry_values[key]
                changed = True
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

    def _set_local_control_mode(
        self,
        mode,
        target_current_ma=None,
        target_temp_c=None,
        drive_mv=None,
    ):
        mode = str(mode).upper()
        self.control_values["mode"] = mode

        if mode == "CURRENT":
            for key in ("target_temp_mC", "temperature_error_mC", "temperature_integral_uA"):
                self.control_values.pop(key, None)
            if target_current_ma is not None:
                self.control_values["target_current_uA"] = str(round(target_current_ma * 1000.0))
            self.target_temp.setText("--")
            self.temperature_error.setText("--")
            self._record_telemetry(
                clear_keys=("target_temp_c",),
                target_current_ma=target_current_ma,
                drive_mv=drive_mv,
            )
            return

        if mode == "TEMPERATURE":
            self.control_values.pop("target_current_uA", None)
            self.control_values.pop("temperature_error_mC", None)
            self.control_values.pop("temperature_integral_uA", None)
            if target_temp_c is not None:
                self.control_values["target_temp_mC"] = str(round(target_temp_c * 1000.0))
                self.target_temp.setText(f"{target_temp_c:.3f} C")
            self.temperature_error.setText("--")
            self._record_telemetry(
                clear_keys=("target_current_ma",),
                target_temp_c=target_temp_c,
                drive_mv=drive_mv,
            )
            return

        for key in (
            "target_current_uA",
            "target_temp_mC",
            "temperature_error_mC",
            "temperature_integral_uA",
        ):
            self.control_values.pop(key, None)
        self.target_temp.setText("--")
        self.temperature_error.setText("--")
        self._record_telemetry(
            clear_keys=("target_current_ma", "target_temp_c"),
            drive_mv=drive_mv,
        )

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
        resistance_ohm = sample.resistance_uohm / 1_000_000.0
        chip_temp_c = chip_temperature_from_resistance(resistance_ohm)
        self.current_label.setText(
            f"{sample.current_na / 1_000_000.0:.6f} mA  ({sample.current_na} nA)"
        )
        self.voltage_label.setText(
            f"{sample.voltage_uv / 1000.0:.3f} mV  ({sample.voltage_uv} uV)"
        )
        self.resistance_label.setText(f"{resistance_ohm:.6f} ohm")
        self.adc_status_label.setText(
            f"current=0x{sample.current_adc_status:02X}, voltage=0x{sample.voltage_adc_status:02X}"
        )
        if chip_temp_c is not None:
            self.chip_temp.setText(f"{chip_temp_c:.3f} C")
        self._record_telemetry(
            current_ma=sample.current_na / 1_000_000.0,
            voltage_mv=sample.voltage_uv / 1000.0,
            resistance_ohm=resistance_ohm,
            chip_temp_c=chip_temp_c,
        )
        self._write_experiment_sample(sample, chip_temp_c)

    @Slot(dict)
    def _update_control_status(self, values):
        values = dict(values)
        mode = str(values.get("mode", self.control_values.get("mode", ""))).upper()
        if mode == "CURRENT":
            inactive_control_keys = (
                "target_temp_mC",
                "temperature_error_mC",
                "temperature_integral_uA",
            )
            inactive_telemetry_keys = ("target_temp_c",)
        elif mode == "OFF":
            inactive_control_keys = (
                "target_current_uA",
                "target_temp_mC",
                "temperature_error_mC",
                "temperature_integral_uA",
            )
            inactive_telemetry_keys = ("target_current_ma", "target_temp_c")
        else:
            inactive_control_keys = ()
            inactive_telemetry_keys = ()

        for key in inactive_control_keys:
            values.pop(key, None)
            self.control_values.pop(key, None)
        self.control_values.update(values)

        enabled = values.get("enabled")
        fault = values.get("fault")
        status = values.get("status")
        if mode:
            self.control_mode.setText(f"{mode}, enabled={enabled}, fault={fault}, status={status}")

        drive = values.get("target_drive_mV") or values.get("drive") or values.get("drive_mV")
        if drive is not None:
            self.control_drive.setText(f"{drive} mV")

        target_current_ua = self._int_value(values.get("target_current_uA"))
        measured_current_ua = self._int_value(values.get("measured_current_uA"))
        measured_voltage_mv = self._int_value(values.get("measured_voltage_mV"))
        measured_resistance_mohm = self._int_value(values.get("measured_resistance_mOhm"))
        target_temp_mc = self._int_value(values.get("target_temp_mC"))
        measured_temp_mc = self._int_value(values.get("measured_temp_mC"))
        temperature_error_mc = self._int_value(values.get("temperature_error_mC"))
        drive_mv = self._int_value(drive)

        if mode == "TEMPERATURE" and target_temp_mc is not None:
            self.target_temp.setText(f"{target_temp_mc / 1000.0:.3f} C")
        elif mode in ("CURRENT", "OFF"):
            self.target_temp.setText("--")
        if measured_temp_mc is not None:
            self.chip_temp.setText(f"{measured_temp_mc / 1000.0:.3f} C")
        if mode == "TEMPERATURE" and temperature_error_mc is not None:
            self.temperature_error.setText(f"{temperature_error_mc / 1000.0:.3f} C")
        elif mode in ("CURRENT", "OFF"):
            self.temperature_error.setText("--")

        self._record_telemetry(
            clear_keys=inactive_telemetry_keys,
            target_current_ma=None if target_current_ua is None else target_current_ua / 1000.0,
            current_ma=None if measured_current_ua is None else measured_current_ua / 1000.0,
            voltage_mv=measured_voltage_mv,
            resistance_ohm=None if measured_resistance_mohm is None else measured_resistance_mohm / 1000.0,
            target_temp_c=None if target_temp_mc is None else target_temp_mc / 1000.0,
            chip_temp_c=None if measured_temp_mc is None else measured_temp_mc / 1000.0,
            drive_mv=drive_mv,
        )

    @Slot(dict)
    def _update_board_temperature(self, values):
        chip_temp = values.get("chip_mC")
        chip_status = values.get("chip_status")
        chip_temp_c = None

        if chip_temp is not None:
            try:
                chip_temp_c = int(chip_temp) / 1000.0
                self.chip_temp.setText(f"{chip_temp_c:.3f} C")
            except ValueError:
                self.chip_temp.setText(str(chip_temp))
        elif chip_status is not None:
            # NO_CURRENT etc.: temperature only valid while current flows.
            self.chip_temp.setText("--")

        self._record_telemetry(chip_temp_c=chip_temp_c)

    def closeEvent(self, event):
        self._finish_recording("窗口关闭")
        self.adc_filter_timer.stop()
        self.adc_filter_watchdog.stop()
        self.status_timer.stop()
        self.chip.close()
        event.accept()


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
