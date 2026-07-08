# ChipController V1.0.0

> 基于 STM32H753IIT 的芯片精密测量与温控控制器：四线制电阻/电流/电压测量、双 AD7190 24-bit ΣΔ ADC、安全温控闭环，以及 `feature/high-rate-sampling` 分支引入的 **4.8 kHz 高速采样**能力。

固件语言为 C，配套 Python 上位机与数据分析脚本。命令行通过 Type-C 调试串口（USB CDC UART）交互，另有 RS485 口。

---

## 🆕 本分支：高速采样（feature/high-rate-sampling）

本分支在不破坏精密测量与安全保护的前提下，把 AD7190 的输出数据率推到芯片物理上限，用于瞬态/爬坡捕捉与上位机实时波形。

### 采样率（源码 + 数据手册双源核对）

AD7190 使用内部 4.92 MHz 主时钟，**chop 关闭、sinc4 滤波**，输出数据率：

```text
ODR = MCLK / (1024 × FS) = 4.92 MHz / (1024 × FS)
```

| 采样模式 | 滤波字 FS | 理论 ODR | 说明 |
| --- | --- | --- | --- |
| `PRECISION`（开机默认） | 96 | **≈ 50.05 Hz** | 50 Hz 工频抑制，控制环与精密测量用 |
| `HIGH_RATE`（本分支新增） | 1 | **≈ 4804.7 Hz（4.8 kHz）** | **AD7190 支持的最大输出数据率** |

- 滤波字定义见 [`Core/Inc/ad7190.h`](Core/Inc/ad7190.h)（`FS_MIN=1`、`FS_DEFAULT=96`、`FS_MAX=1023`）。
- 模式映射见 [`Core/Src/chip_measure.c`](Core/Src/chip_measure.c)：`PRECISION→96`、`HIGH_RATE→1`。
- 数据手册（`docs/AD7190BRUZ.pdf`）规格：内部时钟下 ODR 范围 **4.7 Hz ~ 4.8 kHz（无 chop）**；FS=1 即 4.8 kHz 上限。
- SPI 提速：[`Core/Src/main.c`](Core/Src/main.c) 将 SPI1/SPI2 预分频设为 `SPI_BAUDRATEPRESCALER_8`（约 14 MHz），支撑双 ADC 在 4.8 kHz 周期内的连续读取。

> 因此 **HIGH_RATE 模式已运行在芯片绝对上限**；`adch` 实测持续吞吐约 4 kHz（双 ADC 同步读取 + 串口打印开销使稳定值略低于 4800 理论上限）。

### 高速采样用法

```text
sample mode highrate     # 切到高速模式（会先 zero 输出并停控制环）
adch 200                 # 连续流式抓取 200 点，带 TIM3 高分辨率时间戳
sample status            # 查看当前模式与滤波字
sample mode precision    # 切回精密模式
```

`adch <n>` 在抓取结束后会打印实测速率：

```text
AD7190 high-rate samples: count=200 capture_us=... avg_period_us=... rate_hz=...
```

切换模式时固件自动停控制环、清零 DAC、重配两颗 AD7190（`gain`/`bipolar`/`filter_word`）并重新执行内部零点/满量程校准，保证两种模式各自独立校准。

---

## 功能特性

- **双通道 24-bit 测量**：电流 ADC（U12，SPI1，gain=16，1 Ω 采样电阻 R64）+ 电压 ADC（U14，SPI2，gain=1，测 V+/V- 负载电压）。
- **安全温控闭环**：PI 温度环 → 电流环 → DAC 驱动电压（AD5667），全程带过流/过压/过功率/过温保护。
- **电阻/温度推算**：`R = V_load / I_load`（含高阻段补偿），再经分段线性 R-T 表换算温度（TCR 拟合）。
- **两层校准**：AD7190 芯片内部零点/满量程校准 + 板级外部路径软件零点/增益校准。
- **高阻段补偿**：补偿 U14 无缓冲采样支路对负载的动态加载，把 150–220 Ω 段误差压到数 mΩ。
- **内部自检**：`r42test` 用板载 30 Ω（R42）做安全自测试，无需外接负载。
- **高速采样**：见上文。
- **上位机**：PySide6 实时波形 GUI + 一组 Python 分析脚本。

## 硬件平台

| 部件 | 说明 |
| --- | --- |
| MCU | STM32H753IITx，SYSCLK 450 MHz，APB1/APB2 112.5 MHz |
| ADC ×2 | AD7190BRUZ（24-bit ΣΔ），内部 4.92 MHz 时钟，bipolar，buffer off，chop off |
| DAC | AD5667RBRMZ（驱动电压，最大 500 mV） |
| 通信 | Type-C USB 调试串口（115200 8N1，命令行）+ RS485 |
| 对外端子 | CN9 四线制：`I+ / I-`（电流）、`V+ / V-`（电压） |

引脚与时钟配置见 [`ChipController V1.ioc`](ChipController%20V1.ioc)（CubeMX），原理图/网络表见 `docs/`。

## 串口命令接口

通过 Type-C 调试串口发送纯文本命令（`\r\n` 结尾）。完整列表也可用 `help` 查询。

| 命令 | 作用 |
| --- | --- |
| `help` / `?` | 显示帮助 |
| `id` | 读取两颗 AD7190 的 ID |
| `zero` | DAC 强制置 0 V |
| `drive <mV>` | 开环 DAC 驱动电压（0–500 mV） |
| `r42test` | 板载 30 Ω 安全自检 |
| `temp` | 由电阻推算芯片温度 |
| `adcs <n>` | 读取 n 个同步 AD7190 样本 |
| `adcf <n>` | 读取 n 个一阶低通滤波样本（I/V/R + 状态字节） |
| `adch <n>` | 高速流式抓取 n 个样本（HIGH_RATE 模式） |
| `sample status` | 查看当前采样模式与滤波字 |
| `sample mode precision` | 切到精密模式（FS=96，≈50 Hz） |
| `sample mode highrate` | 切到高速模式（FS=1，≈4.8 kHz） |
| `tc status` | 查看控制环状态 |
| `tc stop` | 停控制环并清零输出 |
| `tc current <mA>` | 启动恒流环 |
| `tc temp <degC>` | 启动恒温环 |

> 说明：`tc current` / `tc temp` / `r42test` 会自动切回 `PRECISION` 模式，因为控制环与精密测量需要 50 Hz 工频抑制。

## 安全保护限制

温控环服务周期 500 ms，参数见 [`Core/Src/thermal_control.c`](Core/Src/thermal_control.c)：

| 限制项 | 值 |
| --- | --- |
| 目标电流上限 | 20 mA |
| 瞬时电流上限 | 50 mA |
| 负载电压上限 | 2.0 V |
| 功率上限 | 100 mW |
| 目标温度范围 | −200 ~ 100 °C |
| 板温上限 | 100 °C |
| DAC 驱动电压上限 | 500 mV |

任一保护触发会停止输出并置 fault，需 `tc stop` 后重新启动。

## 测量与校准

- **AD7190 内部校准**：[`Core/Src/ad7190.c`](Core/Src/ad7190.c) 的 `AD7190_CalibrateZeroScale` / `CalibrateFullScale`，每次配置后自动执行。
- **板级软件校准**：[`Core/Src/chip_measure.c`](Core/Src/chip_measure.c) 的零点/增益宏（`CURRENT_ZERO_A`、`VOLTAGE_ZERO_V`、`CURRENT_GAIN`、`VOLTAGE_GAIN`）。
- **高阻段补偿**：等效采样支路负载 330 kΩ + 150.007 Ω 锚点，见 `ChipMeasure_ComputeExternalResistance`。
- **R → T 换算**：分段线性表，见 [`Core/Src/chip_temperature.c`](Core/Src/chip_temperature.c)。

详细记录见 [`docs/adc_calibration_summary.md`](docs/adc_calibration_summary.md) 与 [`docs/high_resistance_measurement_compensation.md`](docs/high_resistance_measurement_compensation.md)。

## 目录结构

```text
Core/
  Inc/            板级驱动与应用头文件（ad7190/ad5667/chip_measure/thermal_control/...）
  Src/            实现（main.c 为应用层与命令行；其余为各驱动模块）
Drivers/          STM32 HAL / CMSIS
docs/             数据手册、原理图、网络表、校准与补偿文档、TCR 表
host_qt/          PySide6 实时波形上位机（chip_controller_gui.py）
tools/            数据采集与分析脚本
ChipController V1.ioc   CubeMX 工程配置
STM32H753IITX_FLASH.ld  / _RAM.ld   GCC 链接脚本
```

## 构建与烧录

### 方式一：STM32CubeIDE（推荐）

1. 用 STM32CubeIDE 导入本目录（已含 `.project` / `.cproject`）。
2. 选择 `ChipController V1 Debug` 配置，构建后烧录。
3. 调试配置见 `ChipController V1 Debug.launch`。

### 方式二：命令行 GCC ARM

- 链接脚本：[`STM32H753IITX_FLASH.ld`](STM32H753IITX_FLASH.ld)（Flash）/ [`STM32H753IITX_RAM.ld`](STM32H753IITX_RAM.ld)（RAM）。
- 工具链：arm-none-eabi-gcc（STM32H7 支持）。

烧录后接上 Type-C，串口工具（115200 8N1）即可使用上述命令行。

## 上位机与分析脚本

均基于 Python 3，绘图脚本另需 `numpy` / `matplotlib`。

| 文件 | 作用 |
| --- | --- |
| [`host_qt/chip_controller_gui.py`](host_qt/chip_controller_gui.py) | PySide6 + QSerialPort 实时波形 GUI（依赖 `PySide6`） |
| [`tools/adcf_logger.py`](tools/adcf_logger.py) | 周期发 `adcf`，采集 I/V/R 到 CSV，仅依赖标准库 |
| [`tools/plot_drift.py`](tools/plot_drift.py) | 由 CSV 画长时间温漂趋势（ppm 偏离） |
| [`tools/plot_mutiR.py`](tools/plot_mutiR.py) | 解析多电阻线性扫描日志，画电阻线性度 |
| [`tools/plot_verify.py`](tools/plot_verify.py) | 解析恒流扫描日志，验证电流控制与电阻测量精度 |

## 文档

- [`docs/AD7190BRUZ.pdf`](docs/AD7190BRUZ.pdf) — ADC 数据手册
- [`docs/AD5667RBRMZ.pdf`](docs/AD5667RBRMZ.pdf) — DAC 数据手册
- [`docs/ChipThermCtrl V1.0.0.pdf`](docs/ChipThermCtrl%20V1.0.0.pdf) — 板子说明
- [`docs/Netlist_GZL_SAMPLECHIP_CONTROL_V1.0_2026-05-26.tel`](docs/Netlist_GZL_SAMPLECHIP_CONTROL_V1.0_2026-05-26.tel) — 网络表
- `docs/03 冷冻台 和 04 芯片通信协议2026-06-02.xlsx` — 通信协议
- `docs/TCR.xlsx` — TCR 拟合数据
