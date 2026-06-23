# ChipController Qt Host

PySide6 上位机，用于当前 ChipController 板的调试和后续温控联调。

## 功能

- 连接 ChipController Type-C 调试串口。
- **采样模式切换**（下拉框「采样模式」）：精密模式 / 高速模式。切换前自动停采样 + `tc stop` + `zero` + 发 `sample mode ...`，固件会重配 ADC；切换不自动重启采样，需手动点开始。
- **精密模式**（默认，`filter_word=96`、带校准的单次转换）：
  - 设置恒流目标：发送 `tc current <mA>`（闭环恒流，靠精密 ADC 反馈）。
  - 启动/停止 ADC 滤波采样：按设定周期发送固定的 `adcf 1`，默认周期 `200 ms`。
- **高速模式**（`filter_word=1`、连续流，内部 ~4 kHz）：
  - 启动/停止高速采样：按周期发送 `adch <n>`（n=样本数，默认 20，最大 100），解析返回的 `adch N: ...` 行并显示固件报告的 `rate_hz`。实际显示速率受串口波特率限制（115200 较慢，921600 明显更快）。
  - 开环驱动：发送 `drive <mV>`（0–500 mV）直接设 DAC 输出电压，不经过闭环、不读 ADC，因此与高速采样互不干扰；实测电流随负载电阻变化，从高速采样流里实时读出。
- 停止/归零：发送 `tc stop` 和 `zero`（两模式通用）。
- 实时显示：
  - 电流 ADC：一阶低通滤波后的第 `n` 点结果（精密）/ 高速流样本（高速）
  - 电压 ADC：同上
  - 外接负载电阻：由电压/电流计算
  - 两个 AD7190 状态字节
  - `tc status` 中的控制状态、驱动电压（仅精密模式轮询）
  - ChipController `temp` 命令返回的芯片温度、冷台温度

> 闭环恒流（`tc current`）依赖精密 ADC 反馈，与高速采样互斥；固件在 `tc current` 前会强制切回精密模式。因此高速模式下电流控制改用开环 `drive`。

## 运行

在项目根目录执行：

```bash
python3 host_qt/chip_controller_gui.py
```

当前环境已验证 `PySide6` 和 `QtSerialPort` 可导入，不需要 `pyserial`。

## 串口分工

- 电脑只连接 `ChipController 串口`，也就是 Type-C 调试口，默认 `115200`。
- 外部芯片板/温度设备接 ChipController 的 `CN4` RS485，由 ChipController 主动发送 `0x1E`、`0x1F` 查询温度。

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

当前固件把温度回复 payload 的前 2 字节按 little-endian signed int16 解析，并直接作为摄氏度原始值上报。如果实测协议单位是 0.1°C 或 0.01°C，需要调整 `Core/Src/board_temperature.c` 里的 `BOARD_TEMPERATURE_EXT_TEMP_SCALE_C_PER_COUNT`。
