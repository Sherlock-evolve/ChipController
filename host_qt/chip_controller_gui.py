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
ADC_HIGH_RATE_SAMPLE_COUNT_DEFAULT = 20
BOARD_OUTPUT_MAX_DRIVE_MV = 500
TREND_MAX_POINTS = 900

SAMPLE_MODE_PRECISION = "precision"
SAMPLE_MODE_HIGH_RATE = "high_rate"


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


@dataclass
class HighRateSample:
    index: int
    t_us: int
    dt_us: int
    current_na: int
    voltage_uv: int
    current_adc_status: int
    voltage_adc_status: int
    t_monotonic: float = 0.0


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

    def add_sample(self, values, timestamp=None):
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
        if timestamp is None:
            when = time.monotonic() - self._start_time
        else:
            when = timestamp - self._start_time
        self._samples.append((when, clean))
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
    highRateSampleReceived = Signal(object)
    highRateInfoReceived = Signal(dict)
    sampleModeReceived = Signal(str, int)
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
        self._adch_pending = False
        self._adch_last_rate_hz = None
        self._adch_burst_base_t = None
        self._adch_expected_count = 0
        self._adch_seen_count = 0
        self._adch_summary = None

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
        self._adch_pending = False
        self._adch_expected_count = 0
        self._adch_seen_count = 0
        self._adch_summary = None
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

    def set_drive_mv(self, drive_mv):
        self.send_command(f"drive {drive_mv:.1f}")

    def set_temperature_c(self, temperature_c):
        self.send_command(f"tc temp {temperature_c:.3f}")

    def stop_control(self):
        self.send_command("tc stop")

    def stop_stream(self):
        self._adcf_pending = False
        self._adcf_expected_count = 0
        self._adcf_last_sample = None
        self._adch_pending = False
        self._adch_burst_base_t = None
        self._adch_expected_count = 0
        self._adch_seen_count = 0
        self._adch_summary = None

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

    def request_high_rate_adc(self, count):
        if self._adch_pending:
            return False
        self._adch_pending = True
        self._adch_expected_count = int(count)
        self._adch_seen_count = 0
        self._adch_summary = None
        self._adch_burst_base_t = None
        self.send_command(f"adch {int(count)}")
        return True

    def clear_high_rate_adc_pending(self):
        self._adch_pending = False
        self._adch_burst_base_t = None
        self._adch_expected_count = 0
        self._adch_seen_count = 0
        self._adch_summary = None

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

        if self._handle_high_rate_line(line):
            return

        if line.startswith("Sample mode: "):
            values = parse_key_values(line[len("Sample mode: "):])
            mode_text = ""
            for key in ("mode", "Mode"):
                if key in values:
                    mode_text = values[key]
                    break
            if not mode_text:
                tail = line[len("Sample mode: "):].split()
                if tail:
                    mode_text = tail[0]
            try:
                filter_word = int(values.get("filter_word", 0))
            except ValueError:
                filter_word = 0
            self.sampleModeReceived.emit(mode_text, filter_word)
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

    def _handle_high_rate_line(self, line):
        if line.startswith("AD7190 high-rate capture:"):
            # Start of a new burst; reset the intra-burst time reference.
            values = parse_key_values(line)
            try:
                self._adch_expected_count = int(values.get("count", self._adch_expected_count))
            except ValueError:
                pass
            self._adch_seen_count = 0
            self._adch_summary = None
            self._adch_burst_base_t = None
            return True

        m = re.match(
            r"^adch (\d+): t=(\d+) us dt=(\d+) us I=(-?\d+) nA V=(-?\d+) uV "
            r"status current=(0x[0-9A-Fa-f]+) voltage=(0x[0-9A-Fa-f]+)$",
            line,
        )
        if m:
            try:
                now = time.monotonic()
                t_us = int(m.group(2))
                if self._adch_burst_base_t is None:
                    self._adch_burst_base_t = now - t_us / 1_000_000.0
                index = int(m.group(1))
                sample = HighRateSample(
                    index=index,
                    t_us=t_us,
                    dt_us=int(m.group(3)),
                    current_na=int(m.group(4)),
                    voltage_uv=int(m.group(5)),
                    current_adc_status=int(m.group(6), 16),
                    voltage_adc_status=int(m.group(7), 16),
                    t_monotonic=self._adch_burst_base_t + t_us / 1_000_000.0,
                )
                self.highRateSampleReceived.emit(sample)
                self._adch_seen_count = max(self._adch_seen_count, index)
                self._finish_high_rate_burst_if_complete()
            except (TypeError, ValueError):
                pass
            return True

        if line.startswith("AD7190 high-rate samples:"):
            values = parse_key_values(line)
            try:
                rate_hz = int(values.get("rate_hz", 0))
            except ValueError:
                rate_hz = 0
            self._adch_summary = {
                "rate_hz": rate_hz,
                "count": values.get("count"),
                "capture_us": values.get("capture_us"),
                "avg_period_us": values.get("avg_period_us"),
            }
            self._finish_high_rate_burst_if_complete()
            return True

        return False

    def _finish_high_rate_burst_if_complete(self):
        if not self._adch_pending or self._adch_summary is None:
            return
        if self._adch_expected_count > 0 and self._adch_seen_count < self._adch_expected_count:
            return

        summary = self._adch_summary
        self._adch_last_rate_hz = summary.get("rate_hz")
        self._adch_pending = False
        self._adch_burst_base_t = None
        self._adch_expected_count = 0
        self._adch_seen_count = 0
        self._adch_summary = None
        self.highRateInfoReceived.emit(summary)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ChipController Host")
        self.resize(1040, 720)

        self.chip = ChipAsciiClient(self)
        self.telemetry_values = {}
        self.sample_mode = SAMPLE_MODE_PRECISION
        self._build_ui()
        self._connect_signals()
        self.refresh_ports()
        self._apply_mode_controls()

        self.adc_filter_timer = QTimer(self)
        self.adc_filter_timer.timeout.connect(self._request_filtered_adc)
        self.adc_filter_watchdog = QTimer(self)
        self.adc_filter_watchdog.setSingleShot(True)
        self.adc_filter_watchdog.timeout.connect(self._adcf_timeout)

        self.high_rate_timer = QTimer(self)
        self.high_rate_timer.timeout.connect(self._request_high_rate_adc)
        self.high_rate_watchdog = QTimer(self)
        self.high_rate_watchdog.setSingleShot(True)
        self.high_rate_watchdog.timeout.connect(self._adch_timeout)

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
        group = QGroupBox("温控与采样")
        form = QFormLayout(group)

        self.sample_mode_combo = QComboBox()
        self.sample_mode_combo.addItem("精密模式", SAMPLE_MODE_PRECISION)
        self.sample_mode_combo.addItem("高速模式", SAMPLE_MODE_HIGH_RATE)
        form.addRow("采样模式", self.sample_mode_combo)

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
        form.addRow("恒流目标 mA", current_row)

        self.drive_mv = QDoubleSpinBox()
        self.drive_mv.setRange(0.0, float(BOARD_OUTPUT_MAX_DRIVE_MV))
        self.drive_mv.setDecimals(1)
        self.drive_mv.setSingleStep(10.0)
        self.drive_mv.setValue(0.0)
        self.drive_mv.setSuffix(" mV")

        self.set_drive = QPushButton("设置驱动")
        self.stop_drive = QPushButton("停止/归零")

        drive_row = QHBoxLayout()
        drive_row.addWidget(self.drive_mv)
        drive_row.addWidget(self.set_drive)
        drive_row.addWidget(self.stop_drive)
        form.addRow("驱动电压 mV", drive_row)

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
        self.filter_period.setValue(200)
        self.filter_period.setSuffix(" ms")

        self.start_stream = QPushButton("开始滤波采样")
        self.stop_stream = QPushButton("停止滤波采样")

        filter_row = QHBoxLayout()
        filter_row.addWidget(self.filter_period)
        filter_row.addWidget(self.start_stream)
        filter_row.addWidget(self.stop_stream)
        form.addRow("滤波采样周期", filter_row)

        self.high_rate_period = QSpinBox()
        self.high_rate_period.setRange(50, 10000)
        self.high_rate_period.setValue(200)
        self.high_rate_period.setSuffix(" ms")

        self.high_rate_count = QSpinBox()
        self.high_rate_count.setRange(1, 100)
        self.high_rate_count.setValue(ADC_HIGH_RATE_SAMPLE_COUNT_DEFAULT)

        self.start_highrate = QPushButton("开始高速采样")
        self.stop_highrate = QPushButton("停止高速采样")

        highrate_row = QHBoxLayout()
        highrate_row.addWidget(self.high_rate_period)
        highrate_row.addWidget(QLabel("样本数"))
        highrate_row.addWidget(self.high_rate_count)
        highrate_row.addWidget(self.start_highrate)
        highrate_row.addWidget(self.stop_highrate)
        form.addRow("高速采样", highrate_row)

        self.poll_status = QCheckBox("轮询 tc status")
        self.poll_status.setChecked(True)
        form.addRow("", self.poll_status)

        self.mode_info_label = QLabel("精密模式")
        self.mode_info_label.setStyleSheet("color: #344054;")
        form.addRow("当前模式", self.mode_info_label)
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

    def _connect_signals(self):
        self.chip_refresh.clicked.connect(self.refresh_ports)
        self.chip_connect.clicked.connect(self._toggle_chip)
        self.sample_mode_combo.currentIndexChanged.connect(self._on_sample_mode_changed)
        self.set_current.clicked.connect(self._set_current)
        self.set_temperature.clicked.connect(self._set_temperature)
        self.stop_current.clicked.connect(self._stop_output)
        self.set_drive.clicked.connect(self._set_drive)
        self.stop_drive.clicked.connect(self._stop_output)
        self.start_stream.clicked.connect(self._start_stream)
        self.stop_stream.clicked.connect(self._stop_stream)
        self.start_highrate.clicked.connect(self._start_highrate)
        self.stop_highrate.clicked.connect(self._stop_highrate)
        self.clear_trend.clicked.connect(self._clear_trend)

        self.chip.connectedChanged.connect(self._chip_connected_changed)
        self.chip.logLine.connect(self._append_log)
        self.chip.sampleReceived.connect(self._update_sample)
        self.chip.filteredSampleReceived.connect(self._update_filtered_sample)
        self.chip.highRateSampleReceived.connect(self._update_high_rate_sample)
        self.chip.highRateInfoReceived.connect(self._update_high_rate_info)
        self.chip.sampleModeReceived.connect(self._update_sample_mode)
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
        if connected:
            # Sync the GUI mode with whatever mode the firmware booted into.
            self.chip.send_command("sample status")

    def _set_current(self):
        target_ma = self.current_ma.value()
        self.chip.set_current_ma(target_ma)
        if self.chip.is_open():
            self._record_telemetry(target_current_ma=target_ma)

    def _set_drive(self):
        target_mv = self.drive_mv.value()
        self.chip.set_drive_mv(target_mv)
        # Open-loop: commanded value is the applied value (spinbox is clamped to the
        # same 0-500 mV as the firmware). Update the display directly because the
        # drive-voltage field is otherwise only fed by tc status, which we don't
        # poll in high-rate mode.
        applied_mv = min(target_mv, BOARD_OUTPUT_MAX_DRIVE_MV)
        self._apply_drive_display(applied_mv)
        self._append_log(f"drive -> {applied_mv:.1f} mV (open-loop)")

    def _apply_drive_display(self, drive_mv):
        self.control_drive.setText(f"{drive_mv:.0f} mV")
        self._record_telemetry(drive_mv=drive_mv)

    def _stop_output(self):
        # Shared stop/zero for both modes: stop the control loop + force DAC to 0V.
        self.chip.stop_control()
        self.chip.send_command("zero")
        self._apply_drive_display(0.0)
        if self.chip.is_open():
            self._record_telemetry(target_current_ma=0.0, target_temp_c=0.0, drive_mv=0.0)

    def _set_temperature(self):
        target_c = self.temperature_c.value()
        self.chip.set_temperature_c(target_c)
        if self.chip.is_open():
            self._record_telemetry(target_temp_c=target_c)

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

    def _start_highrate(self):
        self.chip.stop_stream()
        # Pause slow status polling: adch blocks the firmware main loop for many
        # ms per capture, and an interleaved temp poll could overrun the UART.
        self.status_timer.stop()
        self._request_high_rate_adc()
        self.high_rate_timer.start(self.high_rate_period.value())

    def _stop_highrate(self):
        self.high_rate_timer.stop()
        self.high_rate_watchdog.stop()
        self.chip.stop_stream()
        self._ensure_status_timer()

    def _ensure_status_timer(self):
        if self.poll_status.isChecked():
            self.status_timer.start(2000)
        else:
            self.status_timer.stop()

    def _request_high_rate_adc(self):
        if self.chip.is_open():
            if self.chip.request_high_rate_adc(self.high_rate_count.value()):
                self.high_rate_watchdog.start(max(5000, self.high_rate_period.value() * 3))

    def _adch_timeout(self):
        self.chip.clear_high_rate_adc_pending()
        self._append_log("adch timeout: previous high-rate capture request was released")

    def _on_sample_mode_changed(self, index):
        # Blocking signals lets us restore the index without re-triggering this handler.
        new_mode = self.sample_mode_combo.itemData(index)
        if new_mode is None or new_mode == self.sample_mode:
            return

        self.sample_mode_combo.blockSignals(True)
        try:
            # 1. Stop all sampling (both sides) and clear pending requests.
            self.adc_filter_timer.stop()
            self.adc_filter_watchdog.stop()
            self.high_rate_timer.stop()
            self.high_rate_watchdog.stop()
            self.chip.stop_stream()

            # 2. Stop output + zero (defensive; firmware also zeroes on mode switch).
            self.chip.stop_control()
            self.chip.send_command("zero")
            self._apply_drive_display(0.0)

            # 3. Switch the ADC sample mode. Firmware reconfigures the ADC.
            if new_mode == SAMPLE_MODE_HIGH_RATE:
                self.chip.send_command("sample mode highrate")
            else:
                self.chip.send_command("sample mode precision")

            # 4. Apply local state + per-mode control enablement.
            self.sample_mode = new_mode
            self._apply_mode_controls()

            # 5. Drop mixed precision/high-rate data from the trend.
            self._clear_trend()

            # 6. Resume slow status polling (paused while high-rate streaming).
            self._ensure_status_timer()

            # 7. Ask the firmware to confirm (response updates the mode info label).
            self.chip.send_command("sample status")
            self._append_log(f"切换采样模式 -> {self._mode_label(new_mode)}")
        finally:
            self.sample_mode_combo.blockSignals(False)

    def _apply_mode_controls(self):
        precision = self.sample_mode == SAMPLE_MODE_PRECISION
        # Precision-only (closed-loop current + filtered sampling + its stop/zero).
        self.current_ma.setEnabled(precision)
        self.set_current.setEnabled(precision)
        self.stop_current.setEnabled(precision)
        self.temperature_c.setEnabled(precision)
        self.set_temperature.setEnabled(precision)
        self.filter_period.setEnabled(precision)
        self.start_stream.setEnabled(precision)
        self.stop_stream.setEnabled(precision)
        # High-rate-only (open-loop drive + high-rate sampling + its stop/zero).
        self.drive_mv.setEnabled(not precision)
        self.set_drive.setEnabled(not precision)
        self.stop_drive.setEnabled(not precision)
        self.high_rate_period.setEnabled(not precision)
        self.high_rate_count.setEnabled(not precision)
        self.start_highrate.setEnabled(not precision)
        self.stop_highrate.setEnabled(not precision)
        self._refresh_mode_info()

    @staticmethod
    def _mode_label(mode):
        return "高速模式" if mode == SAMPLE_MODE_HIGH_RATE else "精密模式"

    def _refresh_mode_info(self, rate_hz=None):
        if self.sample_mode == SAMPLE_MODE_HIGH_RATE:
            if rate_hz is None:
                rate_hz = self.chip._adch_last_rate_hz
            if rate_hz:
                self.mode_info_label.setText(f"高速模式  采样率 {rate_hz} Hz")
            else:
                self.mode_info_label.setText("高速模式  采样率 --")
        else:
            self.mode_info_label.setText("精密模式  滤波 α=0.25")

    def _poll_chip_status(self):
        if self.poll_status.isChecked() and self.chip.is_open():
            # tc status reflects the (off) control loop; only meaningful in precision mode.
            if self.sample_mode == SAMPLE_MODE_PRECISION:
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

    @Slot(object)
    def _update_high_rate_sample(self, sample):
        current_ma = sample.current_na / 1_000_000.0
        voltage_mv = sample.voltage_uv / 1000.0
        self.current_label.setText(f"{current_ma:.6f} mA  ({sample.current_na} nA)")
        self.voltage_label.setText(f"{voltage_mv:.3f} mV  ({sample.voltage_uv} uV)")
        if sample.current_na != 0:
            resistance_ohm = sample.voltage_uv / sample.current_na * 1000.0
            self.resistance_label.setText(f"{resistance_ohm:.6f} ohm")
        else:
            resistance_ohm = None
            self.resistance_label.setText("--")
        self.adc_status_label.setText(
            f"current=0x{sample.current_adc_status:02X}, voltage=0x{sample.voltage_adc_status:02X}"
        )
        # Feed the trend directly with a fresh dict + firmware timestamp, bypassing
        # the shared telemetry_values accumulator (which would mix in stale
        # precision/temp values at high rate).
        self.trend_plot.add_sample(
            {
                "current_ma": current_ma,
                "voltage_mv": voltage_mv,
                "resistance_ohm": resistance_ohm,
            },
            timestamp=sample.t_monotonic,
        )

    @Slot(dict)
    def _update_high_rate_info(self, info):
        self.adc_filter_watchdog.stop()
        self.high_rate_watchdog.stop()
        rate_hz = info.get("rate_hz")
        if rate_hz:
            self._append_log(
                f"adch burst: count={info.get('count')} rate={rate_hz} Hz "
                f"avg_period={info.get('avg_period_us')} us"
            )
        self._refresh_mode_info(rate_hz)

    @Slot(str, int)
    def _update_sample_mode(self, mode_text, filter_word):
        normalized = SAMPLE_MODE_HIGH_RATE if mode_text.upper().startswith("HIGH") else SAMPLE_MODE_PRECISION
        self._append_log(f"固件采样模式: {mode_text} filter_word={filter_word}")
        if normalized != self.sample_mode:
            # Firmware mode drifted from the dropdown (e.g. tc current forced precision).
            # Sync the dropdown silently to reflect reality.
            self.sample_mode = normalized
            self.sample_mode_combo.blockSignals(True)
            target_index = self.sample_mode_combo.findData(normalized)
            if target_index >= 0:
                self.sample_mode_combo.setCurrentIndex(target_index)
            self.sample_mode_combo.blockSignals(False)
            self._apply_mode_controls()
        else:
            self._refresh_mode_info()

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
        target_temp_mc = self._int_value(values.get("target_temp_mC"))
        measured_temp_mc = self._int_value(values.get("measured_temp_mC"))
        temperature_error_mc = self._int_value(values.get("temperature_error_mC"))
        drive_mv = self._int_value(drive)

        if target_temp_mc is not None:
            self.target_temp.setText(f"{target_temp_mc / 1000.0:.3f} C")
        if measured_temp_mc is not None:
            self.chip_temp.setText(f"{measured_temp_mc / 1000.0:.3f} C")
        if temperature_error_mc is not None:
            self.temperature_error.setText(f"{temperature_error_mc / 1000.0:.3f} C")

        self._record_telemetry(
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


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
