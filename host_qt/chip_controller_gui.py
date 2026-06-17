#!/usr/bin/env python3
import math
import struct
import sys
from dataclasses import dataclass
from typing import Optional

from PySide6.QtCore import QObject, QTimer, Qt, Signal, Slot
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
    QVBoxLayout,
    QWidget,
)


CSV_HEADER = "index,tick_ms,status,current_nA,voltage_uV,resistance_mOhm,current_adc_status,voltage_adc_status"
CHIP_COMMAND_CHAR_DELAY_MS = 5


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

    def start_stream(self, period_ms):
        self.send_command("adcstream stop")
        self.send_command(f"adcstream start {period_ms}")

    def stop_stream(self):
        self.send_command("adcstream stop")

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
            self._last_tc.update(parse_key_values(line))
            return

        if line.startswith("TC measured: "):
            self._last_tc.update(parse_key_values(line))
            self.controlStatusReceived.emit(dict(self._last_tc))


def crc16_modbus(data):
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc & 0xFFFF


class TemperatureProtocolClient(QObject):
    connectedChanged = Signal(bool)
    logLine = Signal(str)
    chipTemperatureReceived = Signal(float, int)
    stageTemperatureReceived = Signal(float, int)

    CMD_SHOW_CHIP_TEMP = 0x1E
    CMD_SHOW_STAGE_TEMP = 0x1F

    def __init__(self, parent=None):
        super().__init__(parent)
        self.port = QSerialPort(self)
        self.port.readyRead.connect(self._on_ready_read)
        self.port.errorOccurred.connect(self._on_error)
        self._rx = bytearray()
        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self.poll_once)
        self._next_cmd = self.CMD_SHOW_CHIP_TEMP

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
        self._poll_timer.stop()
        if self.port.isOpen():
            self.port.close()
        self.connectedChanged.emit(False)

    def start_polling(self, interval_ms):
        self._poll_timer.start(interval_ms)
        self.poll_once()

    def stop_polling(self):
        self._poll_timer.stop()

    def poll_once(self):
        if not self.port.isOpen():
            return
        self._send_read(self._next_cmd)
        self._next_cmd = (
            self.CMD_SHOW_STAGE_TEMP
            if self._next_cmd == self.CMD_SHOW_CHIP_TEMP
            else self.CMD_SHOW_CHIP_TEMP
        )

    def _send_read(self, main_cmd):
        payload = b"\x00"
        frame = bytearray([0x5A, 0xA5, 0x51, main_cmd, 0x00, 0xFF])
        frame += struct.pack("<H", len(payload))
        frame += payload
        crc = crc16_modbus(frame[1:])
        frame += struct.pack("<H", crc)
        frame += b"\x0D\x0A"
        self.port.write(bytes(frame))
        self.logLine.emit("TEMP TX " + " ".join(f"{b:02X}" for b in frame))

    @Slot()
    def _on_ready_read(self):
        self._rx.extend(bytes(self.port.readAll()))
        self._parse_frames()

    @Slot(QSerialPort.SerialPortError)
    def _on_error(self, error):
        if error == QSerialPort.NoError:
            return
        if self.port.isOpen():
            self.logLine.emit(f"Temp serial error: {self.port.errorString()}")

    def _parse_frames(self):
        while True:
            start = self._rx.find(0xAA)
            if start < 0:
                self._rx.clear()
                return
            if start > 0:
                del self._rx[:start]
            if len(self._rx) < 12:
                return

            length = self._rx[6] | (self._rx[7] << 8)
            total = 12 + length
            if len(self._rx) < total:
                return
            frame = bytes(self._rx[:total])
            del self._rx[:total]

            if frame[-2:] != b"\x0D\x0A":
                self.logLine.emit("TEMP RX bad end frame")
                continue

            expected_crc = frame[-4] | (frame[-3] << 8)
            actual_crc = crc16_modbus(frame[1:-4])
            if expected_crc not in (0x0000, actual_crc):
                self.logLine.emit(f"TEMP RX bad crc expected=0x{expected_crc:04X} actual=0x{actual_crc:04X}")
                continue

            addr, msg_type, main_cmd, sub_cmd, status = frame[1], frame[2], frame[3], frame[4], frame[5]
            payload = frame[8:-4]
            self.logLine.emit("TEMP RX " + " ".join(f"{b:02X}" for b in frame))

            if addr != 0xA5 or msg_type != 0x61 or sub_cmd != 0x00:
                continue
            if status != 0x00:
                self.logLine.emit(f"TEMP status error cmd=0x{main_cmd:02X} status=0x{status:02X}")
                continue
            if len(payload) < 2:
                continue

            raw = int.from_bytes(payload[:2], byteorder="little", signed=True)
            temperature_c = float(raw)
            if main_cmd == self.CMD_SHOW_CHIP_TEMP:
                self.chipTemperatureReceived.emit(temperature_c, raw)
            elif main_cmd == self.CMD_SHOW_STAGE_TEMP:
                self.stageTemperatureReceived.emit(temperature_c, raw)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ChipController Host")
        self.resize(1120, 760)

        self.chip = ChipAsciiClient(self)
        self.temp = TemperatureProtocolClient(self)
        self._build_ui()
        self._connect_signals()
        self.refresh_ports()

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
        top.addWidget(self._build_temp_group(), 1)
        layout.addLayout(top)

        layout.addWidget(self._build_measure_group())

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(1000)
        layout.addWidget(self.log, 1)

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

        self.stream_period = QSpinBox()
        self.stream_period.setRange(50, 60000)
        self.stream_period.setValue(500)
        self.stream_period.setSuffix(" ms")
        self.start_stream = QPushButton("开始ADC流")
        self.stop_stream = QPushButton("停止ADC流")
        stream_row = QHBoxLayout()
        stream_row.addWidget(self.stream_period)
        stream_row.addWidget(self.start_stream)
        stream_row.addWidget(self.stop_stream)
        form.addRow("采样周期", stream_row)

        self.poll_status = QCheckBox("轮询 tc status")
        self.poll_status.setChecked(True)
        form.addRow("", self.poll_status)
        return group

    def _build_temp_group(self):
        group = QGroupBox("温度设备协议")
        form = QFormLayout(group)

        self.temp_port = QComboBox()
        self.temp_baud = QComboBox()
        self.temp_baud.addItems(["115200", "19200", "9600"])
        self.temp_refresh = QPushButton("刷新")
        self.temp_connect = QPushButton("连接")

        row = QHBoxLayout()
        row.addWidget(self.temp_port, 1)
        row.addWidget(self.temp_refresh)
        row.addWidget(self.temp_connect)
        form.addRow("端口", row)
        form.addRow("波特率", self.temp_baud)

        self.temp_interval = QSpinBox()
        self.temp_interval.setRange(200, 60000)
        self.temp_interval.setValue(1000)
        self.temp_interval.setSuffix(" ms")
        self.temp_start = QPushButton("开始读温度")
        self.temp_stop = QPushButton("停止")
        poll_row = QHBoxLayout()
        poll_row.addWidget(self.temp_interval)
        poll_row.addWidget(self.temp_start)
        poll_row.addWidget(self.temp_stop)
        form.addRow("读取周期", poll_row)

        hint = QLabel("命令: 0x1E 芯片温度, 0x1F 冷台温度")
        hint.setWordWrap(True)
        form.addRow("协议", hint)
        return group

    def _build_measure_group(self):
        group = QGroupBox("实时数据")
        grid = QGridLayout(group)

        self.sample_index = QLabel("--")
        self.sample_tick = QLabel("--")
        self.current_label = QLabel("--")
        self.voltage_label = QLabel("--")
        self.resistance_label = QLabel("--")
        self.adc_status_label = QLabel("--")
        self.control_mode = QLabel("--")
        self.control_drive = QLabel("--")
        self.board_temp = QLabel("--")
        self.chip_temp = QLabel("--")
        self.stage_temp = QLabel("--")

        labels = [
            ("样本", self.sample_index),
            ("tick", self.sample_tick),
            ("电流 ADC", self.current_label),
            ("电压 ADC", self.voltage_label),
            ("外接电阻", self.resistance_label),
            ("ADC 状态", self.adc_status_label),
            ("控制模式", self.control_mode),
            ("驱动电压", self.control_drive),
            ("板载/控制温度", self.board_temp),
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
        self.temp_refresh.clicked.connect(self.refresh_ports)
        self.chip_connect.clicked.connect(self._toggle_chip)
        self.temp_connect.clicked.connect(self._toggle_temp)
        self.set_current.clicked.connect(self._set_current)
        self.stop_current.clicked.connect(self._stop_current)
        self.start_stream.clicked.connect(self._start_stream)
        self.stop_stream.clicked.connect(self.chip.stop_stream)
        self.temp_start.clicked.connect(self._start_temp_poll)
        self.temp_stop.clicked.connect(self.temp.stop_polling)

        self.chip.connectedChanged.connect(self._chip_connected_changed)
        self.chip.logLine.connect(self._append_log)
        self.chip.sampleReceived.connect(self._update_sample)
        self.chip.controlStatusReceived.connect(self._update_control_status)
        self.chip.boardTemperatureReceived.connect(self._update_board_temperature)

        self.temp.connectedChanged.connect(self._temp_connected_changed)
        self.temp.logLine.connect(self._append_log)
        self.temp.chipTemperatureReceived.connect(self._update_chip_temp)
        self.temp.stageTemperatureReceived.connect(self._update_stage_temp)

    def refresh_ports(self):
        current_chip = self.chip_port.currentData()
        current_temp = self.temp_port.currentData()
        ports = list_serial_ports()
        for combo, current in ((self.chip_port, current_chip), (self.temp_port, current_temp)):
            combo.blockSignals(True)
            combo.clear()
            for system_location, label in ports:
                combo.addItem(label, system_location)
            if current:
                idx = combo.findData(current)
                if idx >= 0:
                    combo.setCurrentIndex(idx)
            combo.blockSignals(False)

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

    def _toggle_temp(self):
        if self.temp.is_open():
            self.temp.close()
            return
        port = self.temp_port.currentData()
        if not port:
            QMessageBox.warning(self, "串口", "没有可用的温度设备串口")
            return
        try:
            self.temp.open(port, int(self.temp_baud.currentText()))
        except RuntimeError as exc:
            QMessageBox.critical(self, "串口打开失败", str(exc))

    def _chip_connected_changed(self, connected):
        self.chip_connect.setText("断开" if connected else "连接")
        self._append_log("ChipController connected" if connected else "ChipController disconnected")

    def _temp_connected_changed(self, connected):
        self.temp_connect.setText("断开" if connected else "连接")
        self._append_log("Temperature device connected" if connected else "Temperature device disconnected")

    def _set_current(self):
        self.chip.set_current_ma(self.current_ma.value())

    def _stop_current(self):
        self.chip.stop_control()
        self.chip.send_command("zero")

    def _start_stream(self):
        self.chip.start_stream(self.stream_period.value())

    def _start_temp_poll(self):
        self.temp.start_polling(self.temp_interval.value())

    def _poll_chip_status(self):
        if self.poll_status.isChecked() and self.chip.is_open():
            self.chip.request_status()
            self.chip.request_temperature()

    @Slot(str)
    def _append_log(self, line):
        self.log.appendPlainText(line)

    @Slot(object)
    def _update_sample(self, sample):
        self.sample_index.setText(str(sample.index))
        self.sample_tick.setText(f"{sample.tick_ms} ms")
        self.current_label.setText(f"{sample.current_na / 1_000_000.0:.6f} mA  ({sample.current_na} nA)")
        self.voltage_label.setText(f"{sample.voltage_uv / 1000.0:.3f} mV  ({sample.voltage_uv} uV)")
        self.resistance_label.setText(f"{sample.resistance_mohm / 1000.0:.6f} ohm")
        self.adc_status_label.setText(f"current=0x{sample.current_adc_status:02X}, voltage=0x{sample.voltage_adc_status:02X}")

    @Slot(dict)
    def _update_control_status(self, values):
        mode = values.get("mode")
        enabled = values.get("enabled")
        fault = values.get("fault")
        status = values.get("status")
        if mode is not None:
            self.control_mode.setText(f"{mode}, enabled={enabled}, fault={fault}, status={status}")

        drive = values.get("drive") or values.get("drive_mV")
        if drive is not None:
            self.control_drive.setText(f"{drive} mV")

        temp = values.get("temp") or values.get("temp_mC")
        target = values.get("target") or values.get("target_mC")
        if temp is not None:
            try:
                temp_c = int(temp) / 1000.0
                if target is not None:
                    target_c = int(target) / 1000.0
                    self.board_temp.setText(f"{temp_c:.3f} C / target {target_c:.3f} C")
                else:
                    self.board_temp.setText(f"{temp_c:.3f} C")
            except ValueError:
                self.board_temp.setText(str(temp))

    @Slot(dict)
    def _update_board_temperature(self, values):
        chip_temp = values.get("chip_mC")
        stage_temp = values.get("stage_mC")
        stage_status = values.get("stage_status")

        if chip_temp is not None:
            try:
                temp_c = int(chip_temp) / 1000.0
                self.board_temp.setText(f"{temp_c:.3f} C")
                self.chip_temp.setText(f"{temp_c:.3f} C")
            except ValueError:
                self.chip_temp.setText(str(chip_temp))

        if stage_temp is not None:
            try:
                temp_c = int(stage_temp) / 1000.0
                self.stage_temp.setText(f"{temp_c:.3f} C")
            except ValueError:
                self.stage_temp.setText(str(stage_temp))
        elif stage_status is not None:
            self.stage_temp.setText(stage_status)

    @Slot(float, int)
    def _update_chip_temp(self, temperature_c, raw):
        if math.isfinite(temperature_c):
            self.chip_temp.setText(f"{temperature_c:.2f} C  (raw={raw})")
        else:
            self.chip_temp.setText("NaN")

    @Slot(float, int)
    def _update_stage_temp(self, temperature_c, raw):
        if math.isfinite(temperature_c):
            self.stage_temp.setText(f"{temperature_c:.2f} C  (raw={raw})")
        else:
            self.stage_temp.setText("NaN")


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
