# ChipController Qt Host

PySide6 上位机，用于当前 ChipController 板的调试和后续温控联调。

## 功能

- 连接 ChipController Type-C 调试串口。
- 设置恒流目标：发送 `tc current <mA>`。
- 停止/归零：发送 `tc stop` 和 `zero`。
- 启动/停止 ADC 连续采样：发送 `adcstream start <ms>` / `adcstream stop`。
- 实时显示：
  - 电流 ADC：`current_nA`
  - 电压 ADC：`voltage_uV`
  - 外接负载电阻：`resistance_mOhm`
  - 两个 AD7190 状态字节
  - `tc status` 中的控制状态、驱动电压、板载/控制温度
- 可选连接项目温度设备串口，按 `docs/03 冷冻台 和 04 芯片通信协议2026-06-02.xlsx` 的二进制协议读取：
  - `0x1E`：显示芯片当前温度
  - `0x1F`：显示冷台当前温度

## 运行

在项目根目录执行：

```bash
python3 host_qt/chip_controller_gui.py
```

当前环境已验证 `PySide6` 和 `QtSerialPort` 可导入，不需要 `pyserial`。

## 串口分工

- `ChipController 串口`：接 Type-C 调试口，默认 `115200`。
- `温度设备协议`：接冷冻台/温度控制相关固件的串口，默认 `115200`，可按实际设备改成 `19200` 或 `9600`。

如果同时插了 Type-C 和 USB-RS485，建议用 `/dev/serial/by-id/` 识别实际设备。

## 温度协议假设

Excel 中说明：

- 发送帧同步字：`0x5A`
- 回复帧同步字：`0xAA`
- 地址：`0xA5`
- 读指令：`0x51`
- 读回复：`0x61`
- 子命令：`0x00`
- CRC：CRC16-Modbus，计算内容不包含同步字，低字节在前
- 结束帧：`0x0D 0x0A`

当前程序把温度回复 payload 的前 2 字节按 little-endian signed int16 解析，并直接显示为摄氏度原始值。如果实测协议单位是 0.1°C 或 0.01°C，只需要调整 `TemperatureProtocolClient._parse_frames()` 里的 `temperature_c = float(raw)`。
