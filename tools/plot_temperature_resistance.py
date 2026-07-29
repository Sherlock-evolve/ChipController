#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""绘制控温测试曲线。

输入可以是 tools/adcf_logger.py 生成的简易 CSV，也可以是 Qt 上位机
生成的扩展 CSV；两者都必须包含 timestamp 和 chip_temp_C 列。
输出全程温度曲线和末尾 30 分钟温度细微波动图。
"""

import argparse
import csv
import glob
import math
import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", os.path.join(tempfile.gettempdir(),
                                                   "matplotlib-chipcontroller"))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.ticker import AutoMinorLocator, FormatStrFormatter, MultipleLocator


for font_name in ("Noto Sans CJK JP", "Noto Sans CJK SC", "WenQuanYi Zen Hei", "SimHei"):
    if any(font.name == font_name for font in font_manager.fontManager.ttflist):
        plt.rcParams["font.sans-serif"] = [font_name]
        plt.rcParams["axes.unicode_minus"] = False
        break


def latest_log(root):
    paths = glob.glob(os.path.join(root, "adcf_log_*.csv"))
    return max(paths, key=os.path.getmtime) if paths else None


def finite_float(value):
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def parse_timestamp(value):
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def load_csv(path):
    timestamps = []
    temperatures = []
    with Path(path).open(newline="", encoding="utf-8-sig") as source:
        reader = csv.DictReader(source)
        if not reader.fieldnames or "chip_temp_C" not in reader.fieldnames:
            raise ValueError("CSV 缺少 chip_temp_C 列")
        for row in reader:
            temperature = finite_float(row.get("chip_temp_C"))
            if temperature is None:
                continue
            timestamps.append(parse_timestamp(row.get("timestamp")))
            temperatures.append(temperature)
    if not temperatures:
        raise ValueError("CSV 中没有可绘制的有效温度")
    return timestamps, temperatures


def make_time_axis(timestamps):
    if all(timestamp is not None for timestamp in timestamps):
        elapsed_seconds = [(timestamp - timestamps[0]).total_seconds()
                           for timestamp in timestamps]
        duration = elapsed_seconds[-1]
        if duration >= 7200.0:
            return [value / 3600.0 for value in elapsed_seconds], "运行时间 (h)"
        if duration >= 120.0:
            return [value / 60.0 for value in elapsed_seconds], "运行时间 (min)"
        return elapsed_seconds, "运行时间 (s)"
    return list(range(len(timestamps))), "样本序号"


def add_fine_grid(axis):
    axis.grid(which="major", alpha=0.35, lw=0.7)
    axis.grid(which="minor", alpha=0.16, lw=0.45)
    axis.tick_params(which="minor", length=3)


def set_time_ticks(axis, time_values, time_label):
    """按记录时长设置更细的时间刻度。"""
    duration = time_values[-1] - time_values[0]
    if time_label.endswith("(h)") and duration <= 12.0:
        axis.xaxis.set_major_locator(MultipleLocator(0.25))  # 15 min
        axis.xaxis.set_minor_locator(MultipleLocator(0.05))  # 3 min
    elif time_label.endswith("(min)") and duration <= 120.0:
        axis.xaxis.set_major_locator(MultipleLocator(5.0))
        axis.xaxis.set_minor_locator(MultipleLocator(1.0))
    elif time_label.endswith("(s)") and duration <= 120.0:
        axis.xaxis.set_major_locator(MultipleLocator(10.0))
        axis.xaxis.set_minor_locator(MultipleLocator(2.0))
    else:
        axis.xaxis.set_minor_locator(AutoMinorLocator(5))


def select_stable_30_minutes(timestamps, temperatures):
    """取日志末尾 30 分钟；无有效时间戳时按 1 Hz 退化为最后 1801 点。"""
    if all(timestamp is not None for timestamp in timestamps):
        cutoff = timestamps[-1] - timedelta(minutes=30)
        start = next((index for index, timestamp in enumerate(timestamps)
                      if timestamp >= cutoff), 0)
    else:
        start = max(0, len(temperatures) - 1801)
    return timestamps[start:], temperatures[start:]


def nice_major_step(span, target_intervals=8):
    """为放大图选择易读的 1/2/5 × 10^n 主刻度。"""
    if span <= 0.0:
        return 0.001
    raw_step = span / target_intervals
    magnitude = 10.0 ** math.floor(math.log10(raw_step))
    fraction = raw_step / magnitude
    if fraction <= 1.5:
        nice_fraction = 1.0
    elif fraction <= 3.0:
        nice_fraction = 2.0
    elif fraction <= 7.0:
        nice_fraction = 5.0
    else:
        nice_fraction = 10.0
    return nice_fraction * magnitude


def plot_temperature_time(time_values, time_label, temperatures, output_path, dpi):
    figure, axis = plt.subplots(figsize=(16, 9))
    axis.plot(time_values, temperatures, color="C0", lw=0.55, alpha=0.95)
    axis.scatter(time_values, temperatures, color="C0", s=0.6, alpha=0.18,
                 rasterized=True)
    axis.set_title(f"温度—时间（{len(temperatures)} 条）", fontsize=14)
    axis.set_xlabel(time_label)
    axis.set_ylabel("温度 (°C)")
    set_time_ticks(axis, time_values, time_label)
    axis.yaxis.set_major_locator(MultipleLocator(5.0))
    axis.yaxis.set_minor_locator(MultipleLocator(1.0))
    axis.xaxis.set_major_formatter(FormatStrFormatter("%.3f"))
    axis.yaxis.set_major_formatter(FormatStrFormatter("%.3f"))
    axis.margins(x=0.01)
    add_fine_grid(axis)
    figure.tight_layout()
    figure.savefig(output_path, dpi=dpi)
    plt.close(figure)


def plot_stable_temperature(time_values, time_label, temperatures, output_path, dpi):
    figure, axis = plt.subplots(figsize=(16, 9))
    axis.plot(time_values, temperatures, color="C1", lw=0.65, alpha=0.95)
    axis.scatter(time_values, temperatures, color="C1", s=1.0, alpha=0.22,
                 rasterized=True)
    temperature_min = min(temperatures)
    temperature_max = max(temperatures)
    temperature_span = temperature_max - temperature_min
    axis.set_title(f"温度稳定后 30 分钟细微波动（{len(temperatures)} 条，"
                   f"峰峰值 {temperature_span:.6f} °C）", fontsize=14)
    axis.set_xlabel(time_label)
    axis.set_ylabel("温度 (°C)")
    set_time_ticks(axis, time_values, time_label)
    major_step = nice_major_step(temperature_span)
    axis.yaxis.set_major_locator(MultipleLocator(major_step))
    axis.yaxis.set_minor_locator(MultipleLocator(major_step / 5.0))
    axis.xaxis.set_major_formatter(FormatStrFormatter("%.3f"))
    axis.yaxis.set_major_formatter(FormatStrFormatter("%.6f"))
    padding = max(temperature_span * 0.08, major_step * 0.5)
    axis.set_ylim(temperature_min - padding, temperature_max + padding)
    axis.margins(x=0.01)
    add_fine_grid(axis)
    figure.tight_layout()
    figure.savefig(output_path, dpi=dpi)
    plt.close(figure)


def main():
    project_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(
        description="绘制 adcf_logger/Qt 控温日志的全程温度图和末尾 30 分钟波动图"
    )
    parser.add_argument(
        "-i", "--input",
        help="adcf_logger 或 Qt 采集 CSV（默认查找最新 adcf_log_*.csv）",
    )
    parser.add_argument("-o", "--output-prefix",
                        help="输出文件前缀（默认使用输入 CSV 文件名）")
    parser.add_argument("--dpi", type=int, default=300, help="输出 DPI（默认 300）")
    args = parser.parse_args()

    input_name = args.input or latest_log(str(project_root)) or latest_log(os.getcwd())
    if not input_name:
        sys.exit("找不到 adcf_log_*.csv，请用 -i 指定")
    input_path = Path(input_name)
    output_prefix = Path(args.output_prefix) if args.output_prefix else input_path.with_suffix("")
    time_output = Path(str(output_prefix) + "_temperature_time.png")
    stable_output = Path(str(output_prefix) + "_temperature_stable_30min.png")

    try:
        timestamps, temperatures = load_csv(input_path)
    except (OSError, ValueError) as exc:
        sys.exit(str(exc))
    time_values, time_label = make_time_axis(timestamps)
    stable_timestamps, stable_temperatures = select_stable_30_minutes(timestamps, temperatures)
    stable_time_values, stable_time_label = make_time_axis(stable_timestamps)

    plot_temperature_time(time_values, time_label, temperatures, time_output, args.dpi)
    plot_stable_temperature(stable_time_values, stable_time_label,
                            stable_temperatures, stable_output, args.dpi)
    print(f"saved: {time_output}")
    print(f"saved: {stable_output}")


if __name__ == "__main__":
    main()
