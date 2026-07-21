#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从采集 CSV 分别绘制温度—阻值图和阻值—时间图。"""

import argparse
import csv
import glob
import math
import os
import sys
import tempfile
from datetime import datetime
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
    resistances = []
    with Path(path).open(newline="", encoding="utf-8-sig") as source:
        reader = csv.DictReader(source)
        if not reader.fieldnames or "chip_temp_C" not in reader.fieldnames:
            raise ValueError("CSV 缺少 chip_temp_C 列")
        for row in reader:
            temperature = finite_float(row.get("chip_temp_C"))
            resistance = finite_float(row.get("R_Ohm"))
            if resistance is None:
                resistance_uohm = finite_float(row.get("R_uOhm"))
                resistance = None if resistance_uohm is None else resistance_uohm * 1e-6
            if temperature is None or resistance is None:
                continue
            timestamps.append(parse_timestamp(row.get("timestamp")))
            temperatures.append(temperature)
            resistances.append(resistance)
    if not temperatures:
        raise ValueError("CSV 中没有可绘制的有效温度和阻值")
    return timestamps, temperatures, resistances


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
    if time_label.endswith("(h)") and duration <= 6.0:
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


def plot_temperature_resistance(temperatures, resistances, output_path, dpi):
    figure, axis = plt.subplots(figsize=(16, 9))
    axis.plot(temperatures, resistances, color="C0", lw=0.45, alpha=0.9)
    axis.scatter(temperatures, resistances, color="C0", s=0.6, alpha=0.22,
                 rasterized=True)
    axis.set_title(f"温度—阻值（{len(temperatures)} 条）", fontsize=14)
    axis.set_xlabel("温度 (°C)")
    axis.set_ylabel("阻值 (Ω)")
    axis.xaxis.set_major_locator(MultipleLocator(10.0))
    axis.xaxis.set_minor_locator(MultipleLocator(2.0))
    axis.yaxis.set_major_locator(MultipleLocator(1.0))
    axis.yaxis.set_minor_locator(MultipleLocator(0.2))
    axis.xaxis.set_major_formatter(FormatStrFormatter("%.3f"))
    axis.yaxis.set_major_formatter(FormatStrFormatter("%.6f"))
    add_fine_grid(axis)
    figure.tight_layout()
    figure.savefig(output_path, dpi=dpi)
    plt.close(figure)


def plot_resistance_time(time_values, time_label, resistances, output_path, dpi):
    figure, axis = plt.subplots(figsize=(16, 9))
    axis.plot(time_values, resistances, color="C1", lw=0.55, alpha=0.95)
    axis.scatter(time_values, resistances, color="C1", s=0.6, alpha=0.18,
                 rasterized=True)
    axis.set_title(f"阻值—时间（{len(resistances)} 条）", fontsize=14)
    axis.set_xlabel(time_label)
    axis.set_ylabel("阻值 (Ω)")
    set_time_ticks(axis, time_values, time_label)
    axis.yaxis.set_major_locator(MultipleLocator(0.5))
    axis.yaxis.set_minor_locator(MultipleLocator(0.1))
    axis.xaxis.set_major_formatter(FormatStrFormatter("%.3f"))
    axis.yaxis.set_major_formatter(FormatStrFormatter("%.6f"))
    axis.margins(x=0.01)
    add_fine_grid(axis)
    figure.tight_layout()
    figure.savefig(output_path, dpi=dpi)
    plt.close(figure)


def main():
    project_root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="绘制温度—阻值图和阻值—时间图")
    parser.add_argument("-i", "--input", help="采集 CSV（默认查找最新 adcf_log_*.csv）")
    parser.add_argument("-o", "--output-prefix",
                        help="输出文件前缀（默认使用输入 CSV 文件名）")
    parser.add_argument("--dpi", type=int, default=300, help="输出 DPI（默认 300）")
    args = parser.parse_args()

    input_name = args.input or latest_log(str(project_root)) or latest_log(os.getcwd())
    if not input_name:
        sys.exit("找不到 adcf_log_*.csv，请用 -i 指定")
    input_path = Path(input_name)
    output_prefix = Path(args.output_prefix) if args.output_prefix else input_path.with_suffix("")
    temperature_output = Path(str(output_prefix) + "_temperature_resistance.png")
    time_output = Path(str(output_prefix) + "_resistance_time.png")

    try:
        timestamps, temperatures, resistances = load_csv(input_path)
    except (OSError, ValueError) as exc:
        sys.exit(str(exc))
    time_values, time_label = make_time_axis(timestamps)

    plot_temperature_resistance(temperatures, resistances, temperature_output, args.dpi)
    plot_resistance_time(time_values, time_label, resistances, time_output, args.dpi)
    print(f"saved: {temperature_output}")
    print(f"saved: {time_output}")


if __name__ == "__main__":
    main()
