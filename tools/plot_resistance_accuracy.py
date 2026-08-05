#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""提取各电流档的电阻测量值，并绘制电阻测量精度图。"""

import argparse
import csv
import math
import os
import statistics
import sys
import tempfile
from dataclasses import dataclass
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


@dataclass
class CurrentSegment:
    target_current_mA: float
    rows: list[dict[str, str]]


@dataclass
class MeasurementResult:
    target_current_mA: float
    sample_start: str
    sample_end: str
    sample_count: int
    resistance_mean_ohm: float
    resistance_std_ohm: float
    resistance_sem_ohm: float
    resistance_min_ohm: float
    resistance_max_ohm: float
    error_mohm: float
    error_ppm: float
    relative_error_percent: float


def finite_float(value: str | None) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def load_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as source:
        reader = csv.DictReader(source)
        required = {
            "timestamp",
            "elapsed_s",
            "target_current_mA",
            "R_uOhm",
            "current_adc_status",
            "voltage_adc_status",
            "control_status",
        }
        missing = required.difference(reader.fieldnames or [])
        if missing:
            raise ValueError(f"CSV 缺少列：{', '.join(sorted(missing))}")
        rows = list(reader)
    if not rows:
        raise ValueError("CSV 没有数据行")
    return rows


def split_current_segments(rows: list[dict[str, str]]) -> list[CurrentSegment]:
    segments: list[CurrentSegment] = []
    segment_rows: list[dict[str, str]] = []
    current_target: float | None = None

    for row in rows:
        target = finite_float(row.get("target_current_mA"))
        if target is None:
            continue
        if current_target is None or target != current_target:
            if segment_rows and current_target is not None:
                segments.append(CurrentSegment(current_target, segment_rows))
            current_target = target
            segment_rows = []
        segment_rows.append(row)

    if segment_rows and current_target is not None:
        segments.append(CurrentSegment(current_target, segment_rows))
    if not segments:
        raise ValueError("CSV 中没有有效的目标电流分档")
    return segments


def valid_measurement(row: dict[str, str]) -> bool:
    return (
        row.get("current_adc_status", "0x00") == "0x00"
        and row.get("voltage_adc_status", "0x00") == "0x00"
        and row.get("control_status", "OK") == "OK"
        and finite_float(row.get("R_uOhm")) is not None
        and finite_float(row.get("elapsed_s")) is not None
    )


def aggregate_measurements(
    segments: list[CurrentSegment], reference_ohm: float, discard_seconds: float
) -> list[MeasurementResult]:
    results: list[MeasurementResult] = []
    for segment in segments:
        first_elapsed = finite_float(segment.rows[0].get("elapsed_s"))
        if first_elapsed is None:
            continue
        cutoff = first_elapsed + discard_seconds
        sample_rows = [
            row
            for row in segment.rows
            if valid_measurement(row)
            and (finite_float(row.get("elapsed_s")) or 0.0) >= cutoff
        ]
        if not sample_rows:
            raise ValueError(
                f"{segment.target_current_mA:g} mA 档在丢弃前 "
                f"{discard_seconds:g} 秒后没有有效样本"
            )

        values = [float(row["R_uOhm"]) / 1e6 for row in sample_rows]
        mean_ohm = statistics.mean(values)
        std_ohm = statistics.stdev(values) if len(values) > 1 else 0.0
        sem_ohm = std_ohm / math.sqrt(len(values))
        error_ohm = mean_ohm - reference_ohm
        results.append(
            MeasurementResult(
                target_current_mA=segment.target_current_mA,
                sample_start=sample_rows[0]["timestamp"],
                sample_end=sample_rows[-1]["timestamp"],
                sample_count=len(values),
                resistance_mean_ohm=mean_ohm,
                resistance_std_ohm=std_ohm,
                resistance_sem_ohm=sem_ohm,
                resistance_min_ohm=min(values),
                resistance_max_ohm=max(values),
                error_mohm=error_ohm * 1e3,
                error_ppm=error_ohm / reference_ohm * 1e6,
                relative_error_percent=error_ohm / reference_ohm * 100.0,
            )
        )
    return results


def write_summary(path: Path, results: list[MeasurementResult]) -> None:
    fields = [
        "target_current_mA",
        "sample_start",
        "sample_end",
        "sample_count",
        "resistance_mean_ohm",
        "resistance_std_ohm",
        "resistance_sem_ohm",
        "resistance_min_ohm",
        "resistance_max_ohm",
        "error_mohm",
        "error_ppm",
        "relative_error_percent",
    ]
    with path.open("w", newline="", encoding="utf-8-sig") as destination:
        writer = csv.DictWriter(destination, fieldnames=fields)
        writer.writeheader()
        for result in results:
            row = result.__dict__.copy()
            row["target_current_mA"] = f"{result.target_current_mA:.6g}"
            for name in (
                "resistance_mean_ohm",
                "resistance_std_ohm",
                "resistance_sem_ohm",
                "resistance_min_ohm",
                "resistance_max_ohm",
            ):
                row[name] = f"{getattr(result, name):.9f}"
            row["error_mohm"] = f"{result.error_mohm:+.6f}"
            row["error_ppm"] = f"{result.error_ppm:+.3f}"
            row["relative_error_percent"] = (
                f"{result.relative_error_percent:+.9f}"
            )
            writer.writerow(row)


def add_grid(axis) -> None:
    axis.grid(which="major", alpha=0.32, linewidth=0.7)
    axis.grid(which="minor", alpha=0.14, linewidth=0.45)
    axis.xaxis.set_minor_locator(AutoMinorLocator(2))
    axis.yaxis.set_minor_locator(AutoMinorLocator(2))


def plot_accuracy(
    path: Path,
    results: list[MeasurementResult],
    reference_ohm: float,
    discard_seconds: float,
    dpi: int,
) -> None:
    currents = [result.target_current_mA for result in results]
    positions = list(range(len(results)))
    means = [result.resistance_mean_ohm for result in results]
    stds = [result.resistance_std_ohm for result in results]
    errors_mohm = [result.error_mohm for result in results]
    stds_mohm = [result.resistance_std_ohm * 1e3 for result in results]

    figure, (resistance_axis, error_axis) = plt.subplots(
        2, 1, figsize=(13, 9), sharex=True, gridspec_kw={"height_ratios": [1, 1.08]}
    )
    figure.suptitle(
        f"电阻 {reference_ohm:.3f} Ω", fontsize=15
    )

    resistance_axis.axhline(
        reference_ohm,
        color="C3",
        linestyle="--",
        linewidth=1.4,
        label=f"精确值 {reference_ohm:.3f} Ω",
    )
    resistance_axis.errorbar(
        positions,
        means,
        yerr=stds,
        fmt="o-",
        color="C0",
        ecolor="C0",
        elinewidth=0.8,
        capsize=3,
        markersize=4.5,
        linewidth=1.25,
        label="测量均值 ± 1σ",
    )
    resistance_axis.set_ylabel("测得电阻 (Ω)")
    resistance_axis.yaxis.set_major_formatter(FormatStrFormatter("%.4f"))
    resistance_axis.legend(loc="best")
    add_grid(resistance_axis)

    error_axis.axhline(0.0, color="0.35", linestyle="--", linewidth=1.0)
    error_axis.errorbar(
        positions,
        errors_mohm,
        yerr=stds_mohm,
        fmt="o-",
        color="C1",
        ecolor="C1",
        elinewidth=0.8,
        capsize=3,
        markersize=4.5,
        linewidth=1.25,
        label="均值误差 ± 1σ",
    )
    error_axis.set_xlabel("电流 (mA)")
    error_axis.set_ylabel("测量误差（测量值 − 精确值）(mΩ)")
    error_axis.legend(loc="best")
    add_grid(error_axis)

    def mohm_to_ppm(value: float) -> float:
        return value * 1e3 / reference_ohm

    def ppm_to_mohm(value: float) -> float:
        return value * reference_ohm / 1e3

    ppm_axis = error_axis.secondary_yaxis(
        "right", functions=(mohm_to_ppm, ppm_to_mohm)
    )
    ppm_axis.set_ylabel("相对误差 (ppm)")

    mean_bias_mohm = statistics.mean(errors_mohm)
    max_result = max(results, key=lambda result: abs(result.error_mohm))
    annotation = (
        f"平均偏差：{mean_bias_mohm:+.3f} mΩ\n"
        f"最大 |均值误差|：{abs(max_result.error_mohm):.3f} mΩ\n"
        f"对应：{abs(max_result.error_ppm):.2f} ppm "
        f"@ {max_result.target_current_mA:g} mA"
    )
    error_axis.text(
        0.985,
        0.04,
        annotation,
        transform=error_axis.transAxes,
        ha="right",
        va="bottom",
        fontsize=9.5,
        bbox={"boxstyle": "round,pad=0.35", "facecolor": "white", "alpha": 0.82},
    )

    error_axis.set_xticks(positions)
    error_axis.set_xticklabels([f"{current:g}" for current in currents], rotation=45)
    error_axis.margins(x=0.025)
    figure.tight_layout(rect=(0.02, 0.02, 0.98, 0.96))
    figure.savefig(path, dpi=dpi)
    plt.close(figure)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="adcf_log CSV 文件")
    parser.add_argument(
        "--reference-ohm", type=float, default=150.002, help="精确电阻值，默认 150.002 Ω"
    )
    parser.add_argument(
        "--discard-seconds", type=float, default=5.0, help="每个电流档前段不计入的秒数，默认 5 s"
    )
    parser.add_argument("--dpi", type=int, default=240, help="PNG 分辨率，默认 240 DPI")
    parser.add_argument("--output-prefix", type=Path, help="输出文件前缀")
    args = parser.parse_args()

    if args.reference_ohm <= 0.0:
        sys.exit("精确电阻值必须大于 0")
    if args.discard_seconds < 0.0:
        sys.exit("前段不计时间不能小于 0")

    prefix = args.output_prefix or args.input.with_suffix("")
    summary_path = Path(f"{prefix}_resistance_summary.csv")
    plot_path = Path(f"{prefix}_resistance_accuracy.png")

    try:
        rows = load_rows(args.input)
        segments = split_current_segments(rows)
        results = aggregate_measurements(
            segments, args.reference_ohm, args.discard_seconds
        )
        write_summary(summary_path, results)
        plot_accuracy(
            plot_path,
            results,
            args.reference_ohm,
            args.discard_seconds,
            args.dpi,
        )
    except (OSError, ValueError) as exc:
        sys.exit(str(exc))

    errors = [result.error_mohm for result in results]
    worst = max(results, key=lambda result: abs(result.error_mohm))
    print(f"电流档数: {len(results)}")
    print(f"每档前 {args.discard_seconds:g} s 不计入")
    print(f"平均偏差: {statistics.mean(errors):+.6f} mΩ")
    print(
        f"最大绝对均值误差: {abs(worst.error_mohm):.6f} mΩ "
        f"({abs(worst.error_ppm):.3f} ppm) @ {worst.target_current_mA:g} mA"
    )
    print(f"saved: {summary_path}")
    print(f"saved: {plot_path}")


if __name__ == "__main__":
    main()
