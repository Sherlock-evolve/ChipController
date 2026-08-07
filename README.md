# ChipController V1.0.0

> 基于 STM32H7 的精密芯片电阻测量与恒温控制仪器
>
> Precision chip resistance measurement & thermal (temperature) control instrument based on STM32H7.

ChipController 通过四线端子对外部样片或标准电阻施加受控电流，同步采样总电流与负载电压，
实时计算电阻并按 TCR 模型换算为芯片温度，同时提供恒流与恒温两种闭环控制模式。
板载两级 ADC 校准与高阻段测量补偿，在 150–220 Ω 区间将测量误差压制到约 4 mΩ 量级。

---

## 目录

- [核心特性](#核心特性)
- [系统架构](#系统架构)
- [硬件平台](#硬件平台)
- [目录结构](#目录结构)
- [固件模块](#固件模块)
- [串口命令](#串口命令)
- [上位机 GUI](#上位机-gui)
- [测量与校准](#测量与校准)
- [安全保护](#安全保护)
- [数据分析工具](#数据分析工具)
- [构建与烧录](#构建与烧录)
- [文档](#文档)

---

## 核心特性

- **四线测量**：`I+/I-` 输出并采样总电流（1 Ω 采样电阻），`V+/V-` 测量负载两端电压，`R = V_load / I_total`。
- **双 24-bit ΣΔ ADC**：电流通道（增益 128）与电压通道（增益 1）各使用一颗 AD7190，FS = 480（chop 关闭时约 10 Hz），启动时执行片内零点 / 满量程校准。
- **板级软件校准**：在片内校准之上，对电流 / 电压通道做零点与增益修正（约 150 ppm 级）。
- **高阻段补偿**：针对无缓冲 AD7190 电压采样支路的动态负载，用等效并联负载模型补偿，保留 150.007 Ω 锚点。
- **TCR 测温**：分度表分段线性插值，由电阻直接换算芯片温度。
- **双闭环控制**：恒流模式（0–20 mA）与恒温模式（−200 … +100 °C，PI 调节，带抗积分饱和）；控制反馈 α = 0.25，显示 / 日志 α = 0.05。
- **多重安全保护**：1.9 V 非锁存软限压，过流 / 2.0 V 过压 / 过功率 / 过温锁存跳闸，以及驱动电压斜率限制。
- **内部自检**：板载 R42 ≈ 30 Ω 路径，无需外接待测件即可一键自检整条测量链路。
- **Qt 上位机**：PySide6 桌面程序，串口通信、实时数据、多通道趋势图与诊断日志。
- **数据分析脚本**：长期温漂采集与绘图、多点电阻线性度分析、电流扫描验证。

---

## 系统架构

```text
                         ┌─────────────────────────── STM32H753IITx ───────────────────────────┐
                         │                                                                     │
   Type-C 调试串口 ──► │  USART2 (115200 8N1)   ASCII 命令行 + 数据回传                   │
   RS485        ──► │  USART1 (19200 8N1)                                                │
                         │                                                                     │
                         │   ┌──────────── 控制环 (thermal_control.c) ────────────┐   │
                         │   │  恒流 / 恒温(PI)  →  目标驱动电压  →  斜率限制       │   │
                         │   │  过流/过压/过功率/过温保护 + 抗积分饱和              │   │
                         │   └───────────────────────┬───────────────────────────┘   │
                         │                           │ DAC drive                       │
                         │                  ┌────────▼─────────┐                       │
                         │                  │   AD5667 双通道   │  ── I+/I- ──► 待测件 │
                         │                  │   16-bit DAC      │                       │
                         │                  └────────┬─────────┘                       │
                         │                           │                                  │
                         │   ┌──────────── 测量 (chip_measure.c) ────────────┐      │
                         │   │  R64(1Ω)采样 ──► AD7190#1 (gain128) ─► I_total  │      │
                         │   │  V+/V-     ──► AD7190#2 (gain1)  ──► V_load   │      │
                         │   │  校准 + 高阻补偿 ──► R ──► TCR表 ──► 温度       │      │
                         │   └────────────────────────────────────────────────┘      │
                         │                                                                     │
                         │   SPI1 / SPI2 ── AD7190 × 2      I2C1 ── AD5667            │
                         └─────────────────────────────────────────────────────────────┘
                                              ▲
            内部自检 R42 ≈ 30 Ω ──────────────┘
```

---

## 硬件平台

| 项目 | 规格 |
| --- | --- |
| 主控 MCU | STM32H753IITx (ARM Cortex-M7) |
| 电流 ADC | AD7190 (AIN1-AIN2, gain = 128, bipolar)，采样 R64 = 1 Ω 上的压降 |
| 电压 ADC | AD7190 (AIN1-AIN2, gain = 1, bipolar)，采样 V+/V- 负载电压 |
| DAC | AD5667 双通道 16-bit，驱动电流源 |
| 参考电压 | 5.0 V |
| 测量端子 | CN9 四线：`I+ / I- / V+ / V-` |
| 内部自检 | R42 ≈ 30 Ω 路径 |
| 调试串口 | Type-C，USART2，115200 8N1 |
| RS485 | USART1，19200 8N1 |
| 参考电压源 | 见原理图 `docs/ChipThermCtrl V1.0.0.pdf` 与网表 `docs/Netlist_*.tel` |

---

## 目录结构

```text
ChipController V1.0.0/
├── Core/                       # STM32 固件（CubeMX 生成 + 应用代码）
│   ├── Inc/                    # 头文件：ad7190 / ad5667 / chip_measure / thermal_control ...
│   ├── Src/                    # 实现：main.c 命令行 + 各驱动与算法模块
│   └── Startup/                # 启动文件
├── Drivers/                    # STM32 HAL & CMSIS
├── host_qt/                    # PySide6 上位机 GUI
│   └── chip_controller_gui.py
├── tools/                      # Python 数据采集与分析脚本
│   ├── temp_drift_test.py      # 板级长期温漂采集
│   ├── plot_temp_drift.py      # 长期温漂趋势绘图 (ppm)
│   ├── adcf_logger.py          # 不启动 Qt 的简易温度采集
│   ├── plot_temperature_resistance.py # Qt/简易采集控温曲线
│   ├── plot_mutiR.py           # mutiR.txt 多阻值测试出图
│   ├── plot_verify.py          # verify.txt 线性度验证出图
│   └── README.md               # 工具选择与使用方法
├── docs/                       # 设计文档、芯片手册、网表、TCR 表
├── ChipController V1.ioc       # STM32CubeMX 工程文件
└── STM32H753IITX_FLASH.ld      # 链接脚本
```

---

## 固件模块

| 模块 | 文件 | 职责 |
| --- | --- | --- |
| 应用主循环 / 命令行 | `Core/Src/main.c` | 上电初始化、ASCII 命令解析、一阶低通滤波采样 |
| AD7190 驱动 | `Core/Src/ad7190.c` | 初始化、配置、片内零点/满量程校准、单次读取、双极性码值换算 |
| AD5667 驱动 | `Core/Src/ad5667.c` | 双通道 DAC 写入、清零、电压↔码值换算 |
| 板级测量 | `Core/Src/chip_measure.c` | 电流/电压校准、外部/内部路径选择、高阻补偿、R42 自检采样 |
| TCR 测温 | `Core/Src/chip_temperature.c` | 分度表分段线性插值，电阻 → 温度 |
| 热控制环 | `Core/Src/thermal_control.c` | 恒流/恒温闭环、PI 调节、四级保护、斜率限制、抗饱和 |
| 安全输出 | `Core/Src/board_output.c` | DAC 驱动电压安全输出、R42 自检流程 |
| 串口抽象 | `Core/Src/board_uart.c` | 调试 UART 与 RS485 统一读写接口 |

---

## 串口命令

通过 Type-C 调试串口（115200 8N1）输入 ASCII 命令，回车结束。

| 命令 | 说明 |
| --- | --- |
| `help` / `?` | 显示命令帮助 |
| `id` | 读取两颗 AD7190 的 ID |
| `zero` | DAC 输出强制归零 |
| `r42test` | 运行内部 30 Ω 自检 |
| `temp` | 由当前电阻读数换算芯片温度 |
| `adcs <n>` | 连续读取 n 个同步原始 AD7190 样本（n = 1–100） |
| `adcf <n>` | 连续读取 n 个一阶低通滤波样本（α = 0.05） |
| `tc status` | 显示控制环状态（模式 / 目标 / 实测 / 驱动） |
| `tc stop` | 停止控制并归零输出 |
| `tc current <mA>` | 启动恒流控制（0–20 mA） |
| `tc temp <degC>` | 启动恒温控制（−200 … +100 °C） |

典型标定流程见 [docs/adc_calibration_summary.md](docs/adc_calibration_summary.md)。

---

## 上位机 GUI

`host_qt/chip_controller_gui.py` 是基于 PySide6 的桌面程序，提供：

- 串口连接 / 波特率选择
- 恒流 / 恒温设定与一键停止归零
- 周期性滤波采样流（带看门狗超时释放）
- 实验 CSV 日志：选择文件、开始/停止、样本/超时计数、逐行刷新防止长时间实验丢失
- 实时数据面板：电流、电压、外接电阻、ADC 状态、控制模式、驱动电压、芯片温度、目标温度、温度误差
- 多通道趋势图（电流 / 电压 / 电阻 / 温度 / 驱动，900 点滚动窗口，可逐曲线显隐）
- 诊断日志面板

运行依赖：

```bash
pip install PySide6 pyserial
python3 host_qt/chip_controller_gui.py
```

“开始记录”会自动启动滤波采样。CSV 的前六列与 `tools/adcf_logger.py`
兼容（`timestamp,I_nA,V_uV,R_uOhm,chip_temp_C,note`），并额外保存 ADC
状态、控制模式、目标/实测电流、目标/实测温度、温度误差、积分项、驱动电压和功率。
`tools/plot_temperature_resistance.py` 可以直接读取 GUI 生成的日志。

---

## 测量与校准

ChipController 采用两层校准，互不替代：

1. **AD7190 片内校准**——修正芯片自身的零点与满量程误差（上电时对两颗 ADC 分别执行 `CalibrateZeroScale` / `CalibrateFullScale`）。
2. **板级外部路径软件校准**——在片内校准之后，补偿参考源误差、采样电阻误差、继电器 / 走线 / 端子 / 模拟前端带来的系统级偏移与比例误差。

当前板级校准系数（`Core/Src/chip_measure.c`）：

```c
#define CHIP_MEASURE_CURRENT_ZERO_A       -0.000000800737f /* -0.800737 uA */
#define CHIP_MEASURE_VOLTAGE_ZERO_V        0.000004739f    /* +4.739 uV    */
#define CHIP_MEASURE_CURRENT_GAIN          1.000719600f
#define CHIP_MEASURE_VOLTAGE_GAIN          1.00329f
```

AD7190 原始码进入最外侧 5% 满量程时，固件将其判定为饱和。控制模式下该状态会锁存
`ADC_SATURATED` 故障并立即清零 DAC，避免高增益电流通道饱和后掩盖异常电流。

上述 `CURRENT_ZERO` 是 G128 / FS480 配置下的**带载有效零点**，不是开路物理零点。
开路 `I+/I-`、短接 `V+/V-` 的 `adcs 100` 测试先得到物理零点
`current_zero = -0.585095 µA`、`voltage_zero = +4.739 µV`；对应残差均值约为
`I = +3.93 nA`、`V = +0.34 µV`。随后使用 150.002 Ω 精密电阻和 Qt `adcf`
日志在 0.3–12 mA 范围做多电流拟合，得到电流有效零点与初始增益。2026-08-07
首次递增扫描显示各档存在约 −3.186 mΩ 的一致残差，因此仅将电流增益下调
21.25 ppm；按各档最后 60 s 回算，电阻误差 RMS 约 0.736 mΩ，最大约 1.270 mΩ。

因此，最终系数下开路电流可能显示约 `+0.22 µA`；该值低于 1 µA 电阻有效门限，
零输出时仍报告 `R = 0`。物理零点用于诊断，最终有效零点用于保证带载电阻准确度。
完整数据、拟合方法及校准顺序见 [ADC 校准总结](docs/adc_calibration_summary.md)。

### 高阻段测量补偿

扩展到 150 Ω 以上时，无缓冲 AD7190 电压采样支路在转换期间对 V+/V- 呈现动态负载，
使部分总电流未流经被测电阻，导致 `R = V/I_total` 偏小。固件将该支路近似为等效并联负载并锚定 150.007 Ω：

```c
#define CHIP_MEASURE_VOLTAGE_SENSE_LOAD_OHM   330000.0f   /* 330 kOhm 等效负载 */
#define CHIP_MEASURE_RESISTANCE_ANCHOR_OHM    150.007f
```

补偿后 150–220 Ω 段 RMS 误差约 4.1 mΩ，280 Ω 段较补偿前（约 −180 mΩ）显著改善。
完整排查与建模过程见 [docs/high_resistance_measurement_compensation.md](docs/high_resistance_measurement_compensation.md)。

### TCR 测温

`Core/Src/chip_temperature.c` 使用新芯片两点线性 TCR 模型。项目根目录 `tcr` 中的
两个低温测量取均值，得到 −177.699500 °C / 21.434657 Ω，并与
20.776 °C / 40.230272 Ω 参考点计算温度系数 α = 0.002353946928 /°C。
固件按 `R = Rref × (1 + α × (T − Tref))` 反算温度，仅在电流有效时输出温度。

---

## 安全保护

控制环（`thermal_control.c`）在每个服务周期（500 ms）检查。控制反馈使用
α = 0.25；`adcf`、Qt 显示和 CSV 日志继续使用独立的 α = 0.05。安全判断直接使用
未滤波采样值，不受两路滤波延迟影响。

| 保护项 | 阈值 |
| --- | --- |
| 目标电流上限 | 20 mA |
| 过流跳闸 | 50 mA |
| 负载软限压 | 1.9 V；禁止驱动继续上升，报告 `LIMIT_CLAMPED`，不锁存故障 |
| 过压跳闸（负载两端） | 2.0 V |
| 过功率跳闸 | 100 mW |
| 过温跳闸 | 100 °C |
| 驱动电压斜率 | 20 mV / 步 |

> 使用 150 Ω 量级标准电阻标定时，13 mA ≈ 1.95 V 已超过 1.9 V 软限压点，
> 因此标定上限仍为 12 mA。若瞬态继续超过 2.0 V，硬保护会锁存故障并归零输出。

---

## 数据分析工具

`tools/` 下的 Python 脚本（仅依赖标准库，绘图需 matplotlib / numpy）：

| 脚本 | 用途 |
| --- | --- |
| `temp_drift_test.py` | 板级长期温漂专用采集，输出 `temp_drift_*.csv` |
| `plot_temp_drift.py` | 配套读取 `temp_drift_*.csv`，绘制 I/V/R 的 ppm 漂移趋势 |
| `adcf_logger.py` | 不启动 Qt 时的简易采集，输出与 Qt 前六列兼容的 `adcf_log_*.csv` |
| `plot_temperature_resistance.py` | 读取 `adcf_logger.py` 或 Qt 日志，绘制控温全程及末尾 30 分钟温度图 |
| `plot_mutiR.py` | 解析 `mutiR.txt` 多电阻日志，按电流设定绘制线性度并匹配 DAQ6510 参考值 |
| `plot_verify.py` | 解析 `verify.txt` 电流扫描日志，验证恒流精度、电阻一致性和 V-I 线性度 |

具体选择方式和命令示例见 [`tools/README.md`](tools/README.md)。

---

## 构建与烧录

1. 使用 **STM32CubeIDE** 打开 `ChipController V1.ioc`（或直接导入工程）。
2. 工程已配置为 GCC / STM32CubeIDE 工具链，直接 Build 即可生成固件。
3. 通过 ST-Link / J-Link 烧录至 STM32H753IITx。
4. 上电后调试串口（115200 8N1）会打印启动信息，输入 `help` 查看命令。

> 重新生成 CubeMX 代码时，应用代码位于各文件的 `USER CODE BEGIN / END` 段之间，会被保留。

---

## 文档

- [docs/adc_calibration_summary.md](docs/adc_calibration_summary.md) — ADC 校准内容、方法与系数
- [docs/high_resistance_measurement_compensation.md](docs/high_resistance_measurement_compensation.md) — 高阻段测量偏小排查与补偿
- [docs/ChipThermCtrl V1.0.0.pdf](docs/ChipThermCtrl%20V1.0.0.pdf) — 板卡原理图
- [docs/Netlist_GZL_SAMPLECHIP_CONTROL_V1.0_2026-05-26.tel](docs/Netlist_GZL_SAMPLECHIP_CONTROL_V1.0_2026-05-26.tel) — 网表
- [docs/AD7190BRUZ.pdf](docs/AD7190BRUZ.pdf) / [docs/AD5667RBRMZ.pdf](docs/AD5667RBRMZ.pdf) — 芯片手册

---

## 许可

固件中 STMicroelectronics HAL 部分遵循 ST 的许可条款（见代码头注释）。
其余应用代码与上位机 / 工具脚本按本仓库自有用途使用。
