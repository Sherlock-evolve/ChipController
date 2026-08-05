#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""绘制指定电流档的电阻测量波动。"""

import argparse
import csv
import math
import os
import statistics
import sys
import tempfile
from pathlib import Path

os.environ.setdefault(
    "MPLCONFIGDIR", os.path.join(tempfile.gettempdir(), "matplotlib-chipcontroller")
)

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.ticker import AutoMinorLocator, FormatStrFormatter


for font_name in (
    "Noto Sans CJK JP",
    "Noto Sans CJK SC",
    "WenQuanYi Zen Hei",
    "SimHei",
):
    if any(font.name == font_name for font in font_manager.fontManager.ttflist):
        plt.rcParams["font.sans-serif"] = [font_name]
        plt.rcParams["axes.unicode_minus"] = False
        break


def finite_float(value: str | None) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def load_current_level(path: Path, target_mA: float) -> tuple[list[float], list[float]]:
    elapsed: list[float] = []
    resistance: list[float] = []
    with path.open(newline="", encoding="utf-8-sig") as source:
        reader = csv.DictReader(source)
        required = {"elapsed_s", "target_current_mA", "R_uOhm"}
        missing = required.difference(reader.fieldnames or [])
        if missing:
            raise ValueError(f"CSV 缺少列：{', '.join(sorted(missing))}")
        for row in reader:
            current = finite_float(row.get("target_current_mA"))
            time_value = finite_float(row.get("elapsed_s"))
            resistance_uohm = finite_float(row.get("R_uOhm"))
            if (
                current is None
                or time_value is None
                or resistance_uohm is None
                or not math.isclose(current, target_mA, rel_tol=0.0, abs_tol=1e-9)
            ):
                continue
            elapsed.append(time_value)
            resistance.append(resistance_uohm / 1e6)

    if not resistance:
        raise ValueError(f"CSV 中没有 {target_mA:g} mA 档的数据")
    start = elapsed[0]
    return [value - start for value in elapsed], resistance


def plot_level(
    output: Path,
    elapsed: list[float],
    resistance: list[float],
    target_mA: float,
    reference_ohm: float,
    dpi: int,
) -> None:
    mean_ohm = statistics.mean(resistance)
    std_ohm = statistics.stdev(resistance) if len(resistance) > 1 else 0.0
    minimum_ohm = min(resistance)
    maximum_ohm = max(resistance)
    peak_to_peak_ohm = maximum_ohm - minimum_ohm

    figure, axis = plt.subplots(figsize=(13, 7.2))
    axis.plot(elapsed, resistance, color="C0", linewidth=0.9, alpha=0.82)
    axis.scatter(
        elapsed,
        resistance,
        color="C0",
        edgecolor="white",
        linewidth=0.3,
        s=22,
        zorder=3,
        label="测量值",
    )
    axis.axhspan(
        mean_ohm - std_ohm,
        mean_ohm + std_ohm,
        color="C2",
        alpha=0.13,
        label="均值 ± 1σ",
    )
    axis.axhline(
        mean_ohm,
        color="C2",
        linestyle="-.",
        linewidth=1.35,
        label=f"均值 {mean_ohm:.6f} Ω",
    )
    axis.axhline(
        reference_ohm,
        color="C3",
        linestyle="--",
        linewidth=1.35,
        label=f"精确值 {reference_ohm:.3f} Ω",
    )

    statistics_text = (
        f"样本数：{len(resistance)}\n"
        f"标准差：{std_ohm * 1e3:.3f} mΩ\n"
        f"最小值：{minimum_ohm:.6f} Ω\n"
        f"最大值：{maximum_ohm:.6f} Ω\n"
        f"峰峰值：{peak_to_peak_ohm * 1e3:.3f} mΩ"
    )
    axis.text(
        0.985,
        0.035,
        statistics_text,
        transform=axis.transAxes,
        ha="right",
        va="bottom",
        fontsize=10,
        bbox={"boxstyle": "round,pad=0.4", "facecolor": "white", "alpha": 0.86},
    )

    padding = max(peak_to_peak_ohm * 0.12, 0.001)
    axis.set_ylim(min(minimum_ohm, reference_ohm) - padding,
                  max(maximum_ohm, reference_ohm) + padding)
    axis.set_title(f"{target_mA:g} mA 档电阻测量波动", fontsize=15)
    axis.set_xlabel("时间 (s)")
    axis.set_ylabel("测得电阻 (Ω)")
    axis.yaxis.set_major_formatter(FormatStrFormatter("%.4f"))
    axis.xaxis.set_minor_locator(AutoMinorLocator(5))
    axis.yaxis.set_minor_locator(AutoMinorLocator(2))
    axis.grid(which="major", alpha=0.32, linewidth=0.7)
    axis.grid(which="minor", alpha=0.14, linewidth=0.45)
    axis.legend(loc="upper right")
    axis.margins(x=0.01)
    figure.tight_layout()
    figure.savefig(output, dpi=dpi)
    plt.close(figure)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="adcf_log CSV 文件")
    parser.add_argument("--current-ma", type=float, required=True, help="目标电流档，单位 mA")
    parser.add_argument(
        "--reference-ohm", type=float, default=150.002, help="精确电阻值，默认 150.002 Ω"
    )
    parser.add_argument("--dpi", type=int, default=240, help="PNG 分辨率，默认 240 DPI")
    parser.add_argument("--output", type=Path, help="输出 PNG 文件名")
    args = parser.parse_args()

    output = args.output or args.input.with_name(
        f"{args.input.stem}_resistance_{args.current_ma:g}mA.png"
    )
    try:
        elapsed, resistance = load_current_level(args.input, args.current_ma)
        plot_level(
            output,
            elapsed,
            resistance,
            args.current_ma,
            args.reference_ohm,
            args.dpi,
        )
    except (OSError, ValueError) as exc:
        sys.exit(str(exc))

    mean_ohm = statistics.mean(resistance)
    std_ohm = statistics.stdev(resistance) if len(resistance) > 1 else 0.0
    peak_to_peak_ohm = max(resistance) - min(resistance)
    print(f"样本数: {len(resistance)}")
    print(f"均值: {mean_ohm:.9f} Ω")
    print(f"标准差: {std_ohm * 1e3:.6f} mΩ")
    print(f"峰峰值: {peak_to_peak_ohm * 1e3:.6f} mΩ")
    print(f"saved: {output}")


if __name__ == "__main__":
    main()
