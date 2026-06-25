# ChipController Qt Host

PySide6 上位机，用于当前 ChipController 板的调试和后续温控联调。

## 功能

- 连接 ChipController Type-C 调试串口。
- 设置恒流目标：发送 `tc current <mA>`。
- 停止/归零：发送 `tc stop` 和 `zero`。
- 启动/停止 ADC 滤波采样：按设定周期发送固定的 `adcf 1`，默认周期 `200 ms`。
- 实时显示：
  - 电流 ADC：一阶低通滤波后的第 `n` 点结果
  - 电压 ADC：一阶低通滤波后的第 `n` 点结果
  - 外接负载电阻：由滤波后的电压/电流计算
  - 两个 AD7190 状态字节
  - `tc status` 中的控制状态、驱动电压
  - ChipController `temp` 命令返回的芯片温度（由 CN9 注入电流测得电阻、按线性 R-T 反推）

## 运行

在项目根目录执行：

```bash
python3 host_qt/chip_controller_gui.py
```

当前环境已验证 `PySide6` 和 `QtSerialPort` 可导入，不需要 `pyserial`。

## 串口分工

- 电脑只连接 `ChipController 串口`，也就是 Type-C 调试口，默认 `115200`。
- 温度由 ChipController 本地测量，不再经 CN4 RS485 查询外部板。

## 温度来源

芯片接在 `CN9`（4 线开尔文：`I+/I-/V+/V-`）。ChipController 注入电流加热芯片的同时，用两片 AD7190 同步测得电流 I（1Ω 采样电阻）和端电压 V，计算 `R = V/I`，再按线性 R-T 模型反推温度：

- `R = R0 * (1 + alpha * (T - T0))`  =>  `T = T0 + (R - R0) / (alpha * R0)`

标定常量 `R0`、`alpha`、`T0` 在 `Core/Src/chip_temperature.c` 顶部定义（需替换占位值为芯片实测标定）。`temp` 命令返回 `Temperature: chip_mC=<值>`；无电流（待机）时返回 `Temperature: chip_status=NO_CURRENT`，上位机显示 `--`。
