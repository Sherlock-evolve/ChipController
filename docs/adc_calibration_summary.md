# ADC Calibration Summary

本文档记录当前 ChipController 固件中已经实现的 ADC 校准内容、测量方法、最终系数和代码实现位置。

## 适用范围

当前校准只应用于外部测量路径：

- `CHIP_MEASURE_PATH_EXTERNAL`
- 外部端子 `I+ / I-`、`V+ / V-`
- `tc current`、`tc status`、`adcs <n>`、外部路径功率/电阻/保护判断

内部 R42 自检路径不使用这组外部路径零点和增益校准，避免用外部精密负载校准影响内部 30 ohm 自检。

## 当前校准系数

代码位置：`Core/Src/chip_measure.c`

```c
#define CHIP_MEASURE_CURRENT_ZERO_A       -0.000000800737f
#define CHIP_MEASURE_VOLTAGE_ZERO_V       0.000004739f
#define CHIP_MEASURE_CURRENT_GAIN         1.000740870f
#define CHIP_MEASURE_VOLTAGE_GAIN         1.00329f
```

含义：

- `CHIP_MEASURE_CURRENT_ZERO_A`：电流通道带载有效零点，当前为 `-0.800737 µA`
- `CHIP_MEASURE_VOLTAGE_ZERO_V`：电压通道开路/短路物理零点，当前为 `+4.739 µV`
- `CHIP_MEASURE_CURRENT_GAIN`：150.002 Ω、0.3–12 mA 多电流带载拟合得到的电流比例修正
- `CHIP_MEASURE_VOLTAGE_GAIN`：独立建立并保留的外部电压路径比例修正

## 校准层级

当前 ADC 校准分为两层：

1. AD7190 芯片内部校准
2. 板级外部路径软件校准

这两层解决的问题不同，应同时保留。

### G128 / FS480 最终外部路径校准（2026-08-06）

本轮校准分成两个明确阶段，不能只执行其中一个阶段。

第一阶段在 `I+/I-` 悬空、`V+/V-` 短接条件下使用 `adcs 100` 测量物理零点，得到
中间系数：

```text
current physical zero = -0.585095 µA
voltage physical zero = +4.739 µV
```

写入中间系数后的 100 个同步原始样本统计为：

```text
I_mean = +3.93 nA,  I_std = 12.73 nA, range = -39 ... +40 nA
V_mean = +0.34 µV, V_std = 0.54 µV,  range = -1 ... +1 µV
```

第二阶段连接 150.002 Ω 四线精密电阻，通过 Qt 周期性采集 `adcf 1`，记录
[`adcf_log_20260806_162559.csv`](../adcf_log_20260806_162559.csv)。测试覆盖
0.3、0.5、0.7、1、2、3、5、7、9、
10、11、12 mA；每档持续 154–205 s，拟合使用每档最后 60 s 的稳态 I/V 数据。
13 mA 因距离 2 V 过压保护过近而不纳入标定。

物理零点系数下，150.002 Ω 的电阻误差从 0.3 mA 的 `+99.533 mΩ` 随电流增加，
变化到 5 mA 的 `+0.053 mΩ` 和 12 mA 的 `-5.555 mΩ`。这说明开路物理零点虽然
准确，但不能单独消除带载工作点的等效偏置和比例误差。

以各电流档的电阻误差等权、保持电压通道系数不变，对电流通道做仿射拟合：

```text
I_final ≈ 215.8 nA + 0.9999539 × I_physical-zero-calibrated
```

换算为固件最终系数即：

```text
CHIP_MEASURE_CURRENT_ZERO_A = -0.800737 µA
CHIP_MEASURE_CURRENT_GAIN   = 1.000740870
```

使用最后 30、60、90、120 s 四种稳态窗口重复拟合，最终 `CURRENT_ZERO` 仅变化约
0.8 nA，`CURRENT_GAIN` 仅变化约 0.4 ppm。以 60 s 窗口回算，12 个电流档的电阻
误差 RMS 约为 1.04 mΩ，最大约为 1.64 mΩ；最终系数的实机复测满足当前要求。

`CURRENT_ZERO` 因此是**带载有效零点**，不是开路物理零点。最终固件在开路条件下
预计显示约 `+0.22 µA`，但该值低于 `CHIP_MEASURE_MIN_CURRENT_A = 1 µA`，零输出时
仍报告 `R = 0`。若强制要求开路电流显示为 0，同时又保持当前带载精度，需要增加
独立的带载工作点补偿参数，不能只依赖现有 zero/gain 两个宏。

### AD7190 芯片内部校准

代码位置：

- `Core/Src/ad7190.c`
- `Core/Inc/ad7190.h`
- `Core/Src/chip_measure.c`

驱动实现了两个 AD7190 内部校准命令：

```c
AD7190_Status AD7190_CalibrateZeroScale(AD7190_Handle *adc);
AD7190_Status AD7190_CalibrateFullScale(AD7190_Handle *adc);
```

对应 AD7190 mode：

```c
#define AD7190_MODE_INTERNAL_ZERO_SCALE (0x80u << 16)
#define AD7190_MODE_INTERNAL_FULL_SCALE (0xA0u << 16)
```

启动初始化时，固件会对两颗 AD7190 分别执行：

```c
AD7190_Configure(...);
AD7190_CalibrateZeroScale(...);
AD7190_CalibrateFullScale(...);
```

当前流程：

```text
current ADC:
  AD7190_Init
  AD7190_Configure(AIN1-AIN2, gain=128, bipolar)
  AD7190_CalibrateZeroScale
  AD7190_CalibrateFullScale

voltage ADC:
  AD7190_Init
  AD7190_Configure(AIN1-AIN2, gain=1, bipolar)
  AD7190_CalibrateZeroScale
  AD7190_CalibrateFullScale
```

两路 ADC 当前均使用 `FS = 480`、sinc4、chop 关闭；标称输出数据率约 10 Hz，
单次转换需要约 400 ms 建立时间。电流通道采用高增益以降低 300 uA 测量时的
等效电流噪声，电压通道保留增益 1 以维持原有 2 V 过压测量范围。

原始码进入最外侧 5% 满量程时返回饱和状态；控制环收到该状态后立即清零输出并
锁存 `ADC_SATURATED` 故障。

这层校准修正的是 AD7190 芯片内部的零点和满量程误差。它发生在 ADC 原始码转电压之前，属于芯片级校准。

### 板级外部路径软件校准

板级软件校准发生在 `AD7190_Reading.voltage` 已经计算出来之后，用于补偿整块板外部路径的误差，包括：

- 实际参考源误差
- 电流采样电阻实际误差
- 外部测量路径偏移
- 继电器、走线、端子和模拟前端带来的比例误差
- ADC 内部校准无法覆盖的系统级误差

当前板级校准只应用于 `CHIP_MEASURE_PATH_EXTERNAL`。内部 R42 路径不使用这组外部路径软件 offset/gain。

## 代码实现方式

电流通道校准：

```c
current_sense_v =
  (raw_sense_voltage_v - (CHIP_MEASURE_CURRENT_ZERO_A * CHIP_MEASURE_CURRENT_SHUNT_OHM)) *
  CHIP_MEASURE_CURRENT_GAIN;

current_a = current_sense_v / CHIP_MEASURE_CURRENT_SHUNT_OHM;
```

电压通道校准：

```c
load_voltage_v =
  (raw_voltage_v - CHIP_MEASURE_VOLTAGE_ZERO_V) *
  CHIP_MEASURE_VOLTAGE_GAIN;
```

实现函数：

- `chip_measure_calibrate_current_sense()`
- `chip_measure_calibrate_load_voltage()`

调用路径：

- `ChipMeasure_ReadCurrent()`
- `ChipMeasure_ReadLoadVoltage()`
- `ChipMeasure_ReadSynchronized()`

因此 `tc status`、`adcs <n>`、控制环保护判断和外部路径电阻/功率计算使用的是校准后的值。

## 零点校准

### 接线条件

零点校准使用如下接线：

```text
I+ / I- 悬空
V+ / V- 短接
外部负载断开
板子正常供电
```

执行命令：

```text
tc stop
zero
adcs 100
```

### 物理零点结果与最终有效零点

物理零点测量得到的中间系数是：

```text
current physical zero = -0.585095 µA
voltage physical zero = +4.739 µV
```

此时 `adcs 100` 的均值为 `I = +3.93 nA`、`V = +0.34 µV`，说明开路/短路物理
零点已经准确。电压零点 `+4.739 µV` 直接保留为最终系数。

电流通道随后还要执行带载多电流拟合，所以最终固件使用：

```text
current effective zero = -0.800737 µA
```

最终有效零点会使开路电流显示约 `+0.22 µA`。这不是零点测量失败，而是现有仿射
校准模型为消除带载等效偏置所作的工作点修正。因为该值低于 1 µA 电阻有效门限，
零输入时 `R = 0`，不会产生无电流电阻读数。

## 增益校准

### 校准负载

使用四线测量得到的标准负载：

```text
R_ref = 150.002 ohm
```

### 测量方法

接线：

```text
I+ ---- 标准负载 ---- I-
V+ 接标准负载高端
V- 接标准负载低端
```

采集流程：

```text
tc current <mA>
等待至少 90 s，建议 120 s
Qt 周期性采集 adcf 1
取该档最后 60 s 的 I_nA、V_uV 稳态数据
```

已测试范围：

```text
0.3 mA、0.5 mA、0.7 mA、1 mA、2 mA、3 mA、5 mA、7 mA、
9 mA、10 mA、11 mA、12 mA
```

`adcs` 和 `adcf` 使用相同的板级校准路径；`adcf` 只是在校准后的 I/V 上增加
`alpha = 0.05` 一阶低通，因此不改变稳态直流比例。零点测量优先使用 `adcs` 观察
原始偏置和噪声，带载增益标定及 Qt 最终验收使用 `adcf` 稳态数据。

注意：使用 150.002 Ω 负载时，不使用 13 mA 或更高档位进行标定：

```text
150.002 ohm * 13 mA = 1.950 V
150.002 ohm * 14 mA = 2.100 V
```

13 mA 已过于接近 `THERMAL_CONTROL_MAX_LOAD_VOLTAGE_V = 2.000 V`，控制暂态可能
触发过压；14 mA 的理论负载电压则已经超过保护阈值。

### 当前增益来源

`CHIP_MEASURE_CURRENT_GAIN = 1.000740870f`

- 来源：[`adcf_log_20260806_162559.csv`](../adcf_log_20260806_162559.csv)
- 参考负载：150.002 Ω 四线精密电阻
- 范围：0.3–12 mA，共 12 个电流档
- 方法：每档最后 60 s 的 I/V 稳态数据，各档电阻误差等权拟合
- 与 `CURRENT_ZERO = -0.800737 µA` 配套使用，不能只更新其中一个宏

`CHIP_MEASURE_VOLTAGE_GAIN = 1.00329f`

- 保留自独立 DMM 电压与板载电压路径校准
- 本轮多电流拟合保持该值不变，只修正电流通道的有效零点和比例

## 验证结果

对 [`adcf_log_20260806_162559.csv`](../adcf_log_20260806_162559.csv) 每档最后
60 s 数据应用最终电流系数后，按固件相同公式回算如下：

| 目标电流 | 更新前误差 | 最终系数回算误差 |
| ---: | ---: | ---: |
| 0.3 mA | +99.533 mΩ | -1.390 mΩ |
| 0.5 mA | +58.634 mΩ | +0.722 mΩ |
| 0.7 mA | +40.517 mΩ | +1.148 mΩ |
| 1 mA | +26.192 mΩ | +0.744 mΩ |
| 2 mA | +10.874 mΩ | +1.636 mΩ |
| 3 mA | +4.680 mΩ | +0.835 mΩ |
| 5 mA | +0.053 mΩ | +0.495 mΩ |
| 7 mA | -2.112 mΩ | +0.182 mΩ |
| 9 mA | -4.069 mΩ | -0.742 mΩ |
| 10 mA | -4.655 mΩ | -0.972 mΩ |
| 11 mA | -5.296 mΩ | -1.321 mΩ |
| 12 mA | -5.555 mΩ | -1.331 mΩ |

12 档回算误差 RMS 为 1.04 mΩ，最大绝对误差为 1.64 mΩ。最终宏写入固件后的
实机复测已确认达到当前要求。

## 保护限制

当前高电流验证受以下限制影响：

```c
THERMAL_CONTROL_MAX_TARGET_CURRENT_A = 0.020f; // 20 mA
THERMAL_CONTROL_MAX_CURRENT_A        = 0.050f; // 50 mA
THERMAL_CONTROL_MAX_LOAD_VOLTAGE_V   = 2.000f; // 2 V
THERMAL_CONTROL_MAX_POWER_W          = 0.100f; // 100 mW
BOARD_OUTPUT_MAX_DRIVE_V             = 0.500f; // 500 mV DAC drive command
```

其中 `2 V` 过压保护是外部负载两端电压限制。使用 150.002 ohm 负载时：

```text
13 mA -> 1.950 V，接近但低于保护
14 mA -> 2.100 V，会触发或接近触发过压保护
```

如果后续要验证 10 mA、15 mA、20 mA，应更换较低阻值的精密负载，例如 50 ohm 或 75 ohm。

## 后续建议

1. 若要做仪器级校准，应把校准值从硬编码迁移到 Flash/NVM，并加入 magic、version、CRC。
2. 建议增加串口命令输出当前校准系数，便于现场确认固件版本。
3. 若更换测量线、端子、ADC 配置或修改 AD7190 内部校准流程，应依次重做物理零点测量和带载多电流拟合；不能只更新开路零点。
4. 若要扩展到 20 mA，应使用低阻精密负载重新验证高电流区线性。
