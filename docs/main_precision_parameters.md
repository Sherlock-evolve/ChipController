# main 精密分支参数文档

适用对象：当前 `main` 分支，也就是精密测量分支。本文不覆盖
`feature/high-rate-sampling` 分支。

- 分支：`main`
- 当前提交：`313e566a0c7d`
- 提交时间：`2026-07-07 16:40:44 +0800`
- 提交说明：`对大于150欧姆的阻值进行补偿,消除高阻值下AD7190动态负载导致的测量偏小现象`
- 文档生成日期：`2026-07-07`

主要依据文件：

- `Core/Src/ad7190.c`
- `Core/Src/chip_measure.c`
- `Core/Src/chip_temperature.c`
- `Core/Src/board_output.c`
- `Core/Src/thermal_control.c`
- `Core/Src/main.c`
- `host_qt/chip_controller_gui.py`
- `tools/adcf_logger.py`
- `docs/AD7190BRUZ.pdf`
- `docs/adc_calibration_summary.md`
- `docs/high_resistance_measurement_compensation.md`

## 1. 总体测量模式

当前分支是命令触发的精密测量模式，不是连续高速流式采样模式。

一次同步测量由两颗 AD7190 同时完成：

- U12 电流 ADC：SPI1，测量 1 ohm 采样电阻两端电压。
- U14 电压 ADC：SPI2，测量外接负载两端电压。
- 固件通过两路 `SYNC` GPIO 做软同步：先拉低同步脚，分别启动两颗
  AD7190 的单次转换，再释放同步脚，等待两颗 ADC 的 RDY 后读取数据。
- 每次调用 `ChipMeasure_ReadSynchronized()` 都会重新选择测量路径，并等待
  继电器稳定。

主要源码位置：

- `Core/Src/chip_measure.c`
- `Core/Src/ad7190.c`
- `Core/Src/main.c`

## 2. AD7190 ADC 参数

| 项目 | 电流 ADC U12 | 电压 ADC U14 | 说明 |
| --- | --- | --- | --- |
| 驱动实例 | `s_current_adc` | `s_voltage_adc` | `Core/Src/chip_measure.c` |
| SPI | `hspi1` / SPI1 | `hspi2` / SPI2 | 两路独立 SPI |
| 输入通道 | `AIN1-AIN2` | `AIN1-AIN2` | 差分输入 |
| 参考电压 | `5.0 V` | `5.0 V` | `CHIP_MEASURE_ADC_VREF` |
| PGA 增益 | `16` | `1` | 电流通道提高分辨率 |
| 极性 | bipolar | bipolar | `bipolar = 1` |
| 输入 buffer | disabled | disabled | `buffer_enabled = 0` |
| chop | disabled | disabled | `chop_enabled = 0` |
| REFDET | enabled | enabled | 配置寄存器置 `REFDET` |
| 滤波器 | sinc4 默认 | sinc4 默认 | 未设置 `SINC3` 位 |
| ADC 超时 | `1000 ms` | `1000 ms` | `CHIP_MEASURE_ADC_TIMEOUT_MS` |
| ID 检查 | 低 4 bit 为 `0x04` | 低 4 bit 为 `0x04` | 实测/启动打印通常为 `0x84` |

初始化流程：

1. `AD7190_Reset()`：发送 6 字节 `0xFF` 复位。
2. `AD7190_ReadId()`：检查芯片 ID。
3. `AD7190_Configure()`：配置差分通道、增益、bipolar、无 buffer、无 chop。
4. `AD7190_CalibrateZeroScale()`：内部零点校准。
5. `AD7190_CalibrateFullScale()`：内部满量程校准。

## 3. 采样率与时序

### 3.1 ADC 配置输出数据率

源码中的模式寄存器 FS 字段为：

```c
#define AD7190_MODE_FS_16HZ 96u
```

注意：这个宏名里的 `16HZ` 与实际配置不一致。实际写入 AD7190 的 FS 值是
`96`。

AD7190 数据手册给出的未启用 chop 时输出数据率公式为：

```text
fADC = fCLK / (1024 * FS)
```

按 AD7190 标称内部时钟 `fCLK = 4.92 MHz`、`FS = 96` 计算：

```text
fADC = 4.92 MHz / (1024 * 96) = 50.05 Hz
```

因此当前 ADC 配置对应的连续输出数据率约为 `50 Hz`。在 FS=96、sinc4、
chop disabled 的条件下，数据手册还给出：

- 转换时间约 `20 ms`。
- sinc4 完全建立时间约 `80 ms`。

当前固件使用 `AD7190_MODE_SINGLE` 单次转换模式。单次转换会启动 ADC、等待
滤波器建立和转换完成，RDY 有效后读取数据，并不是持续运行的连续转换流。
因此实际命令吞吐率不能简单等同于 `50 Hz`，需要同时考虑单次模式建立时间、
继电器等待、SPI 读写、串口文本输出和上位机轮询周期。

### 3.2 同步样本流程

`ChipMeasure_ReadSynchronized()` 的一次样本流程：

1. `ChipMeasure_SelectPath(path)`。
2. 继电器稳定等待 `5 ms`。
3. 两颗 AD7190 的 `SYNC` 同时拉低。
4. 依次对电流 ADC、电压 ADC 写入 single conversion mode。
5. 释放两路 `SYNC`。
6. 等待电流 ADC RDY。
7. 等待电压 ADC RDY。
8. 读取两路 data register 和状态字节。
9. 应用外部路径零点/增益校准。

当前没有固件侧固定频率的 `adcstream` 循环；`adcs` 和 `adcf` 都是命令触发。

### 3.3 固件命令采样参数

| 参数 | 当前值 | 说明 |
| --- | --- | --- |
| `APP_ADC_SAMPLE_DEFAULT_COUNT` | `10` | `adcs` / `adcf` 不带参数时默认样本数 |
| `APP_ADC_SAMPLE_MAX_COUNT` | `100` | 命令允许的最大样本数 |
| `APP_ADC_FILTER_ALPHA` | `0.25` | `adcf` 一阶低通系数 |
| 温度/阻值有效最小电流 | `1 uA` | 小于该值认为无有效阻值/温度 |

`adcf` 的一阶低通公式：

```text
filtered = filtered + alpha * (sample - filtered)
alpha = 0.25
```

滤波状态跨 `adcf` 调用保留；执行 `zero`、`r42test`、`tc stop`、`tc current`、
`tc temp` 等改变输出/控制状态的命令后会重置滤波状态。

输出格式：

```text
AD7190 filtered samples: count=<n> alpha=250 mpermil
adcf <index>: I=<nA> nA V=<uV> uV R=<uOhm> uOhm status current=0xXX voltage=0xXX
```

## 4. 上位机采样参数

Qt 上位机 `host_qt/chip_controller_gui.py` 默认参数：

| 参数 | 当前值 | 说明 |
| --- | --- | --- |
| ChipController 串口默认选择 | `115200` | 固件 USART2 实际配置为 115200 8N1 |
| 可选波特率 | `115200`, `230400`, `921600` | UI 可选项，当前固件仍是 115200 |
| 命令逐字节发送间隔 | `5 ms` | `CHIP_COMMAND_CHAR_DELAY_MS` |
| 每次滤波采样请求 | `adcf 1` | `ADC_FILTER_SAMPLE_COUNT = 1` |
| 采样周期范围 | `100 ms` 到 `60000 ms` | UI spinbox 限制 |
| 默认采样周期 | `200 ms` | 默认约 `5 Hz` 主机轮询 |
| `adcf` watchdog | `max(5000 ms, 3 * 采样周期)` | 防止 pending 卡死 |
| `tc status` / `temp` 轮询 | `2000 ms` | 勾选轮询时生效 |
| 趋势图最大点数 | `900` | `TREND_MAX_POINTS` |

命令行长期漂移采集脚本 `tools/adcf_logger.py` 默认参数：

| 参数 | 当前值 |
| --- | --- |
| 串口 | `/dev/ttyUSB1` |
| 波特率 | `115200` |
| 采样间隔 | `1.0 s` |
| 单次读取超时 | `0.8 s` |
| 请求命令 | `adcf 1` |

## 5. 板级校准参数

板级软件校准只应用于外部 CN9 路径
`CHIP_MEASURE_PATH_EXTERNAL`。内部 R42 自检路径不使用这组外部路径 offset/gain。

| 参数 | 当前值 | 说明 |
| --- | --- | --- |
| `CHIP_MEASURE_CURRENT_SHUNT_OHM` | `1.0 ohm` | 电流采样电阻 |
| `CHIP_MEASURE_CURRENT_ZERO_A` | `-0.000000535 A` | 外部路径电流零点，约 `-0.535 uA` |
| `CHIP_MEASURE_VOLTAGE_ZERO_V` | `0.00000603 V` | 外部路径电压零点，约 `+6.03 uV` |
| `CHIP_MEASURE_CURRENT_GAIN` | `1.00079` | 外部路径电流增益修正 |
| `CHIP_MEASURE_VOLTAGE_GAIN` | `1.00329` | 外部路径电压增益修正 |

电流通道计算：

```text
current_sense_v = (raw_sense_voltage_v - current_zero_a * 1 ohm) * current_gain
current_a = current_sense_v / 1 ohm
```

电压通道计算：

```text
load_voltage_v = (raw_voltage_v - voltage_zero_v) * voltage_gain
```

内部 R42 路径只对电压极性做软件取反，不使用外部路径校准系数。

## 6. 外部阻值计算与高阻补偿

基础阻值计算：

```text
Rraw = abs(load_voltage_v) / abs(total_current_a)
```

有效电流门限：

```text
abs(total_current_a) >= 1 uA
```

高阻补偿参数：

| 参数 | 当前值 | 说明 |
| --- | --- | --- |
| `CHIP_MEASURE_RESISTANCE_ANCHOR_OHM` | `150.007 ohm` | 标定锚点 |
| `CHIP_MEASURE_VOLTAGE_SENSE_LOAD_OHM` | `330000 ohm` | U14 无缓冲转换引入的等效电压采样负载 |

补偿逻辑：

- 当 `Rraw <= 150.007 ohm` 时，直接返回 `Rraw`。
- 当 `Rraw > 150.007 ohm` 时，按 `V / 330000 ohm` 估算电压采样支路电流。
- 外部负载电流按 `total_current - sense_branch_current` 计算。
- 为保持 150.007 ohm 标定点不跳变，会扣除锚点处对应的补偿增量。
- 该补偿只影响计算出的阻值 `R`，不反向修改已经上报的 `I` 和 `V`。

相关说明文档：

- `docs/adc_calibration_summary.md`
- `docs/high_resistance_measurement_compensation.md`

## 7. 温度换算参数

当前 `main` 分支的芯片温度来自 CN9 外接负载阻值，不再通过 CN4 RS485 查询外部
温度板。

`temp` 命令流程：

1. 执行一次 `ChipMeasure_ReadSynchronized(CHIP_MEASURE_PATH_EXTERNAL)`。
2. 若电流小于 `1 uA`，输出 `Temperature: chip_status=NO_CURRENT`。
3. 计算外部阻值。
4. 通过 `ChipTemperature_FromResistance()` 将阻值换算为芯片温度。

当前温度换算使用分段线性 R-T 表：

| 电阻 ohm | 温度 degC |
| --- | --- |
| 21.0 | -175 |
| 22.0 | -169 |
| 24.0 | -158 |
| 25.0 | -148 |
| 27.0 | -122 |
| 28.0 | -102 |
| 30.0 | -84 |
| 32.0 | -56 |
| 33.0 | -36 |
| 35.0 | -13 |
| 36.0 | 10 |
| 37.0 | 23 |

表内线性插值；低于 21 ohm 时按第一段外推，高于 37 ohm 时按最后一段外推。

注意：`Core/Inc/chip_temperature.h` 的注释仍保留旧的线性模型描述，当前真实实现
以 `Core/Src/chip_temperature.c` 的分段表为准。

## 8. 输出 DAC 与安全限制

AD5667R DAC 参数：

| 参数 | 当前值 |
| --- | --- |
| I2C | `I2C1` |
| 7-bit 地址 | `0x0F` |
| 内部参考 | enabled |
| DAC 满量程 | `5.0 V` |
| I2C 超时 | `100 ms` |
| 固件驱动电压限幅 | `0.0 V` 到 `0.500 V` |
| 写入通道 | A/B 同时写入 |

`BoardOutput_SetDriveVoltage()` 会把请求电压夹到 `0.0 V` 到 `0.500 V`。
`zero` / 停止 / 故障路径会清零 DAC 输出。

## 9. R42 自检参数

内部 R42 路径用于安全自检，不参与外部路径高精度校准。

| 参数 | 当前值 |
| --- | --- |
| 目标电流 | `5 mA` |
| 最大允许电流 | `50 mA` |
| 最小有效电流 | `0.5 mA` |
| DAC 步进 | `20 mV` |
| 每步稳定时间 | `20 ms` |
| 期望阻值 | `30 ohm` |
| 允许误差 | `±6 ohm` |
| 自检通过范围 | `24 ohm` 到 `36 ohm` |

## 10. 控制环参数

热/电流控制在主循环中周期服务：

| 参数 | 当前值 | 说明 |
| --- | --- | --- |
| `THERMAL_CONTROL_SERVICE_PERIOD_MS` | `500 ms` | 控制服务周期 |
| 目标温度范围 | `0 degC` 到 `80 degC` | `tc temp <degC>` |
| 过温保护 | `85 degC` | 超过后故障停机 |
| 目标电流范围 | `0 mA` 到 `20 mA` | `tc current <mA>` |
| 过流保护 | `50 mA` | 实测电流 |
| 过压保护 | `2.000 V` | 实测负载电压 |
| 过功率保护 | `0.100 W` | `I * V` |
| 电流环比例 | `4.0 V/A` | drive 增量 = 电流误差 * 4.0 |
| drive 斜率限制 | `20 mV / service` | 每 500 ms 最多改变 20 mV |
| 有效阻值最小电流 | `1 uA` | 低于该值阻值/温度无效 |

温度 PI 参数：

| 参数 | 当前值 |
| --- | --- |
| `Kp` | `0.001 A/degC`，即 `1 mA/degC` |
| `Ki` | `0.00005 A/(degC*s)`，即 `50 uA/(degC*s)` |
| 积分下限 | `0 mA` |
| 积分上限 | `20 mA` |
| 积分 dt 上限 | `5 s` |

温度模式下，如果当前电流不足导致阻值无效，控制器只使用比例项启动加热，不积分；
有有效阻值后再计算温度并进入 PI。

## 11. 串口、SPI、I2C 参数

### USART2 Type-C 调试口

| 参数 | 当前值 |
| --- | --- |
| 外设 | `USART2` |
| 波特率 | `115200` |
| 数据位 | `8` |
| 停止位 | `1` |
| 校验 | none |
| 硬件流控 | none |
| 过采样 | 16x |

这是 Qt 和 `tools/adcf_logger.py` 使用的主通信口。

### USART1 RS485

| 参数 | 当前值 |
| --- | --- |
| 外设 | `USART1` |
| 波特率 | `19200` |
| 数据位 | `8` |
| 停止位 | `1` |
| 校验 | none |
| 硬件流控 | none |
| RS485 方向切换延时 | `1 ms` |

`RE485` 方向脚：发送时拉低，接收时拉高。

### SPI1 / SPI2

两路 AD7190 SPI 配置一致：

| 参数 | 当前值 |
| --- | --- |
| Mode | master |
| Direction | 2 lines |
| Data size | 8 bit |
| CPOL | high |
| CPHA | second edge |
| NSS | hard output |
| BaudRatePrescaler | 256 |
| First bit | MSB |
| CRC | disabled |
| NSS polarity | low |

### I2C1

| 参数 | 当前值 |
| --- | --- |
| Timing | `0x209093DD` |
| Addressing | 7-bit |
| Analog filter | enabled |
| Digital filter | `0` |

## 12. 常用 Type-C 命令

| 命令 | 作用 |
| --- | --- |
| `help` | 打印帮助 |
| `id` | 读取两颗 AD7190 ID |
| `zero` | 停止控制并清零 DAC 输出 |
| `r42test` | 内部 30 ohm R42 安全自检 |
| `temp` | 由外部阻值换算芯片温度 |
| `adcs` / `adcs <n>` | 读取同步 ADC 样本，默认 10，最大 100 |
| `adcf` / `adcf <n>` | 读取一阶低通滤波 ADC 样本，默认 10，最大 100 |
| `tc status` | 打印控制状态 |
| `tc stop` | 停止控制并清零输出 |
| `tc current <mA>` | 启动恒流控制 |
| `tc temp <degC>` | 启动温度控制 |

## 13. 高速采样分支对照点

当前精密分支的关键限制点：

- AD7190 运行在 single conversion mode。
- 每次同步样本都会走 `ChipMeasure_SelectPath()`，包含 `5 ms` 继电器稳定等待。
- 采样由 ASCII 命令触发，返回为文本格式。
- Qt 默认轮询周期是 `200 ms`，约 `5 Hz`。
- 固件中已移除旧的 `adcstream start/stop` 连续流命令。
- `adcf` 滤波状态跨命令保留，适合稳定读数，不适合原始高速波形采集。

高速采样分支若要提升吞吐，应优先对照以上几点，而不是只调整上位机轮询周期。
