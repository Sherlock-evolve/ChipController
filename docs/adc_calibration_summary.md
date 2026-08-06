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
#define CHIP_MEASURE_CURRENT_ZERO_A       -0.000000661914f
#define CHIP_MEASURE_VOLTAGE_ZERO_V       0.00002264f
#define CHIP_MEASURE_CURRENT_GAIN         1.000787052f
#define CHIP_MEASURE_VOLTAGE_GAIN         1.00329f
```

含义：

- `CHIP_MEASURE_CURRENT_ZERO_A`: 电流通道外部路径有效零点，单位 A，当前为 `-0.661914 uA`
- `CHIP_MEASURE_VOLTAGE_ZERO_V`: 电压通道外部路径零点，单位 V，当前为 `+22.64 uV`
- `CHIP_MEASURE_CURRENT_GAIN`: 电流通道外部路径增益修正
- `CHIP_MEASURE_VOLTAGE_GAIN`: 电压通道外部路径增益修正

## 校准层级

当前 ADC 校准分为两层：

1. AD7190 芯片内部校准
2. 板级外部路径软件校准

这两层解决的问题不同，应同时保留。

### G128 低电流工作点修正

电流 ADC 改为 G128、两路 ADC 改为 FS480 后，使用 150.002 Ω 精密电阻在
300 uA 恒流下记录 `adcf_log_20260806_102740.csv`。丢弃前 60 秒滤波建立过程后，
775 个样本的平均阻值约为 150.03345 Ω。

保持原电流比例增益和电压通道校准不变，通过固件相同的高阻补偿公式反算，需要将
校准电流提高约 62.84 nA。因此电流通道有效零点由 `-0.599120 uA` 更新为
`-0.661914 uA`，回算平均阻值为 150.002 Ω。该值是 300 uA 工作点修正，不替代
后续独立的开路零点和多电流比例校准。

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

### 最终零点

在当前固件配置下，最终采用：

```text
current_zero = -0.535 uA
voltage_zero = +6.03 uV
```

更新后复查结果：

```text
I_mean = -143.9 nA
I_range = -285 nA 到 +88 nA
V_mean = -1.21 uV
V_range = -2 uV 到 0 uV
```

该残余量级可接受，零输入时 `R=0` 符合预期，因为电流低于 1 uA 时固件不计算电阻。

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

命令流程：

```text
tc current <mA>
等待稳态
adcs 25
```

已测试范围：

```text
1 mA、2 mA、3 mA、5 mA、7 mA、10 mA、12 mA、13 mA
```

注意：使用 150.002 ohm 负载时，不应继续提高到 14 mA 或更高，因为：

```text
150.002 ohm * 14 mA = 2.100 V
```

会超过当前 `THERMAL_CONTROL_MAX_LOAD_VOLTAGE_V = 2.000 V` 的过压保护阈值。

### 当前增益来源

`CHIP_MEASURE_CURRENT_GAIN = 1.00079f`

- `2026-07-06` 复测 `150.007 ohm` 标准电阻，5 mA、8 mA、10 mA、12 mA 的板载电阻均值约为 `149.9876 ohm`
- DMM/DAQ6510 同步电压接近板载电压读数，因此偏差主要归因于电流通道约 `+129 ppm` 的比例偏高
- 原 `1.00091f` 来自 `log/test_03` 中的 DMM 电压、`150.002 ohm` 标准电阻和板载电流读数加权估算，已被本次复测更新
- 用于修正电流通道的整体比例误差

`CHIP_MEASURE_VOLTAGE_GAIN = 1.00329f`

- 根据 `log/test_03` 中的 DMM 电压和板载电压读数加权估算
- 同时使 `adcs` 计算出的电阻接近四线实测值

## 验证结果

`log/test_03` 使用 `150.002 ohm` 精密电阻重新验证。更新前，使用上一轮增益时，1 mA 到 13 mA 的电阻读数已经非常平坦，但整体偏高：

```text
target  R_mean
1 mA    150.12088 ohm
2 mA    150.11316 ohm
3 mA    150.10560 ohm
5 mA    150.10436 ohm
7 mA    150.10312 ohm
10 mA   150.10172 ohm
12 mA   150.10160 ohm
13 mA   150.10096 ohm
```

按 DMM 电压和 `150.002 ohm` 参考电阻加权拟合后：

```text
CHIP_MEASURE_CURRENT_GAIN: 1.00190 -> 1.00091
CHIP_MEASURE_VOLTAGE_GAIN: 1.00495 -> 1.00329
```

用该组新增益回算，`test_03` 的平均电阻约为 `150.006 ohm`，接近四线实测的 `150.002 ohm`。

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
3. 若更换测量线、端子、ADC 配置或重新启用/修改 AD7190 内部校准流程，应重新执行零点校准。
4. 若要扩展到 20 mA，应使用低阻精密负载重新验证高电流区线性。
