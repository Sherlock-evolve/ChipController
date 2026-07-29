# 数据采集与绘图工具

`tools/` 保持六个入口脚本，按四类测试使用。不同采集链使用不同的默认
文件名前缀，避免绘图脚本自动选中不兼容的 CSV。

| 测试 | 采集/输入 | 绘图 | 默认输出 |
| --- | --- | --- | --- |
| 板级长期温漂 | `temp_drift_test.py` | `plot_temp_drift.py` | `temp_drift_<时间>.csv`、同名 PNG |
| 控温测试（无 Qt） | `adcf_logger.py` | `plot_temperature_resistance.py` | `adcf_log_<时间>.csv`、两张温度 PNG |
| 控温测试（Qt） | `host_qt/chip_controller_gui.py` | `plot_temperature_resistance.py` | Qt 选择的 CSV、两张温度 PNG |
| 多电阻测试 | `mutiR.txt` | `plot_mutiR.py` | `mutiR_chart.png`、`mutiR_summary.csv` |
| 线性度验证 | `verify.txt` | `plot_verify.py` | `verify_chart.png`、`verify_summary.csv` |

## 1. 板级长期温漂

这组工具关注固定测试条件下 I/V/R 的长期漂移。CSV 额外保存
`monotonic_s`、单次采样耗时和 ADC 状态，不做 TCR 温度换算。

```bash
python3 tools/temp_drift_test.py --init "tc current 5"
python3 tools/plot_temp_drift.py
```

旧版以 `adcf_log_*.csv` 命名的温漂文件仍可显式传入：

```bash
python3 tools/plot_temp_drift.py -i adcf_log_旧文件.csv
```

## 2. 控温测试

不启动 Qt 时，用简易脚本采集：

```bash
python3 tools/adcf_logger.py --init "tc temp 35"
python3 tools/plot_temperature_resistance.py
```

Qt 上位机日志是同一基础格式的扩展版，也可直接绘图：

```bash
python3 tools/plot_temperature_resistance.py -i adcf_log_某次测试.csv
```

绘图脚本读取 `timestamp` 和 `chip_temp_C`，生成全程温度图以及末尾
30 分钟的细微波动图。

## 3. 多电阻测试

```bash
python3 tools/plot_mutiR.py
```

默认读取项目根目录的 `mutiR.txt`。也可以用 `-i` 指定其他日志。

## 4. 线性度验证

```bash
python3 tools/plot_verify.py
```

默认读取项目根目录的 `verify.txt`，用于检查恒流精度、电阻测量一致性和
V-I 线性度。
