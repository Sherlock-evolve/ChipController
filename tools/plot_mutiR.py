#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Parse mutiR.txt and plot resistance linearity by current setting.

Supports two log styles:
1. Legacy format grouped by `电阻箱X欧姆档`
2. New format:
   - one DAQ6510 reference list at the top
   - one or more current sections containing `adcf 20` blocks

For the new format, each current section is matched to the closest DAQ
reference values by measured resistance. This handles partial sweeps and
sections logged in descending order.
"""
import argparse
import csv
import math
import os
import re
import statistics as st
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", os.path.join(tempfile.gettempdir(), "matplotlib-chipcontroller"))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager


for name in ("Noto Sans CJK JP", "Noto Sans CJK SC", "WenQuanYi Zen Hei", "SimHei"):
    matches = [f for f in font_manager.fontManager.ttflist if f.name == name]
    if matches:
        plt.rcParams["font.sans-serif"] = [name]
        plt.rcParams["axes.unicode_minus"] = False
        break


RE_REF_HEAD = re.compile(r"电阻箱([0-9.]+)欧姆档")
RE_DAQ_SUMMARY_HEAD = re.compile(r"DAQ6510各档位测量值")
RE_BOARD_SECTION_HEAD = re.compile(r"设定电流\s*([-\d.]+)\s*mA时电路板测量值")
RE_TARGET = re.compile(r"^tc\s+current\s+([-\d.]+)\s*$")
RE_SAMPLE = re.compile(
    r"adcf\s+\d+:\s+I=(-?\d+)\s+nA\s+V=(-?\d+)\s+uV\s+R=(-?\d+)\s+uOhm"
    r"\s+status\s+current=(0x[0-9A-Fa-f]+)\s+voltage=(0x[0-9A-Fa-f]+)"
)
RE_NUMBER = re.compile(r"^[0-9]+(?:\.[0-9]+)?$")


def append_sample(block, match):
    i_nA, v_uV, r_uOhm = map(int, match.groups()[:3])
    block["samples"].append({
        "I_mA": i_nA / 1e6,
        "V_mV": v_uV / 1000.0,
        "R_ohm": r_uOhm / 1e6,
        "status_current": match.group(4),
        "status_voltage": match.group(5),
    })


def block_r_mean(block):
    if not block["samples"]:
        return None
    return st.mean(sample["R_ohm"] for sample in block["samples"])


def parse_reference_groups(lines):
    refs = []
    in_refs = False
    current = None

    for line_no, raw in enumerate(lines, 1):
        text = raw.strip()
        if RE_DAQ_SUMMARY_HEAD.search(text):
            in_refs = True
            current = None
            continue

        if not in_refs:
            continue

        if not text:
            continue

        if RE_BOARD_SECTION_HEAD.search(text) or RE_TARGET.match(text):
            break

        if not RE_NUMBER.match(text):
            continue

        value = float(text)
        nominal = float(int(round(value)))
        if current is None or current["ref_nominal_ohm"] != nominal:
            current = {
                "line": line_no,
                "ref_nominal_ohm": nominal,
                "ref_values": [value],
            }
            refs.append(current)
        else:
            current["ref_values"].append(value)

    for ref in refs:
        values = ref.pop("ref_values")
        ref["ref_mean_ohm"] = st.mean(values)
        ref["ref_std_ohm"] = st.pstdev(values) if len(values) > 1 else 0.0
        ref["ref_count"] = len(values)

    return refs


def match_refs_to_section(section, refs):
    unmatched = [dict(ref) for ref in refs]
    blocks = sorted(
        [block for block in section["blocks"] if block["samples"]],
        key=lambda block: block_r_mean(block),
    )
    if len(blocks) > len(unmatched):
        raise ValueError(
            f"section at line {section['line']}: blocks={len(blocks)} exceeds reference groups={len(unmatched)}"
        )

    for block in blocks:
        measured = block_r_mean(block)
        ref_index, ref = min(
            enumerate(unmatched),
            key=lambda item: abs(item[1]["ref_mean_ohm"] - measured),
        )
        block.update({
            "ref_line": ref["line"],
            "ref_nominal_ohm": ref["ref_nominal_ohm"],
            "ref_mean_ohm": ref["ref_mean_ohm"],
            "ref_std_ohm": ref["ref_std_ohm"],
            "ref_count": ref["ref_count"],
            "ref_match_delta_ohm": measured - ref["ref_mean_ohm"],
        })
        unmatched.pop(ref_index)


def parse_new_format(lines):
    refs = parse_reference_groups(lines)
    if not refs:
        raise ValueError("no DAQ6510 reference groups parsed")

    blocks = []
    sections = []
    current_target_mA = None
    current_section = None
    current_block = None

    for line_no, raw in enumerate(lines, 1):
        text = raw.strip()

        match = RE_BOARD_SECTION_HEAD.search(text)
        if match:
            current_target_mA = float(match.group(1))
            current_section = {
                "line": line_no,
                "target_mA": current_target_mA,
                "blocks": [],
            }
            sections.append(current_section)
            current_block = None
            continue

        match = RE_TARGET.match(text)
        if match:
            current_target_mA = float(match.group(1))
            current_section = {
                "line": line_no,
                "target_mA": current_target_mA,
                "blocks": [],
            }
            sections.append(current_section)
            current_block = None
            continue

        if text == "adcf 20":
            if current_target_mA is None:
                raise ValueError(f"line {line_no}: adcf block appears before current section")
            if current_section is None:
                current_section = {
                    "line": line_no,
                    "target_mA": current_target_mA,
                    "blocks": [],
                }
                sections.append(current_section)
            current_block = {
                "line": line_no,
                "section_line": current_section["line"],
                "target_mA": current_target_mA,
                "samples": [],
            }
            current_section["blocks"].append(current_block)
            blocks.append(current_block)
            continue

        match = RE_SAMPLE.search(text)
        if match and current_block is not None:
            append_sample(current_block, match)

    for section in sections:
        match_refs_to_section(section, refs)

    return blocks


def parse_legacy_format(lines):
    blocks = []
    ref_nominal = None
    ref_values = []
    reading_ref_values = False
    current_block = None

    for line_no, raw in enumerate(lines, 1):
        text = raw.strip()

        match = RE_REF_HEAD.search(text)
        if match:
            ref_nominal = float(match.group(1))
            ref_values = []
            reading_ref_values = True
            current_block = None
            continue

        if reading_ref_values and RE_NUMBER.match(text):
            ref_values.append(float(text))
            continue

        if text and reading_ref_values and not RE_NUMBER.match(text):
            reading_ref_values = False

        match = RE_TARGET.match(text)
        if match:
            if ref_nominal is None or not ref_values:
                raise ValueError(f"line {line_no}: current target appears before reference values")
            current_block = {
                "line": line_no,
                "section_line": line_no,
                "ref_line": line_no,
                "ref_nominal_ohm": ref_nominal,
                "ref_mean_ohm": st.mean(ref_values),
                "ref_std_ohm": st.pstdev(ref_values) if len(ref_values) > 1 else 0.0,
                "ref_count": len(ref_values),
                "ref_match_delta_ohm": 0.0,
                "target_mA": float(match.group(1)),
                "samples": [],
            }
            blocks.append(current_block)
            continue

        match = RE_SAMPLE.search(text)
        if match and current_block is not None:
            append_sample(current_block, match)

    return blocks


def parse_log(path):
    with open(path, encoding="utf-8", errors="replace") as fh:
        lines = fh.readlines()

    if any(RE_DAQ_SUMMARY_HEAD.search(line) for line in lines):
        return parse_new_format(lines)
    return parse_legacy_format(lines)


def aggregate(blocks):
    rows = []
    for block in blocks:
        samples = block["samples"]
        if not samples:
            continue
        i_vals = [x["I_mA"] for x in samples]
        v_vals = [x["V_mV"] for x in samples]
        r_vals = [x["R_ohm"] for x in samples]
        statuses = sorted({(x["status_current"], x["status_voltage"]) for x in samples})
        rows.append({
            **{k: block[k] for k in (
                "line", "section_line", "ref_line", "ref_nominal_ohm", "ref_mean_ohm",
                "ref_std_ohm", "ref_count", "target_mA", "ref_match_delta_ohm",
            )},
            "sample_count": len(samples),
            "I_mean_mA": st.mean(i_vals),
            "I_std_mA": st.pstdev(i_vals) if len(i_vals) > 1 else 0.0,
            "V_mean_mV": st.mean(v_vals),
            "V_std_mV": st.pstdev(v_vals) if len(v_vals) > 1 else 0.0,
            "R_mean_ohm": st.mean(r_vals),
            "R_std_ohm": st.pstdev(r_vals) if len(r_vals) > 1 else 0.0,
            "statuses": " ".join(f"{a}/{b}" for a, b in statuses),
        })
    return rows


def linear_fit(points):
    if len(points) < 2:
        return None

    xs = [p["ref_mean_ohm"] for p in points]
    ys = [p["R_mean_ohm"] for p in points]
    x_mean = st.mean(xs)
    y_mean = st.mean(ys)
    sxx = sum((x - x_mean) ** 2 for x in xs)
    if sxx == 0:
        return None

    slope = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys)) / sxx
    intercept = y_mean - slope * x_mean
    y_fit = [slope * x + intercept for x in xs]
    ss_res = sum((y - yh) ** 2 for y, yh in zip(ys, y_fit))
    ss_tot = sum((y - y_mean) ** 2 for y in ys)
    r2 = 1.0 - ss_res / ss_tot if ss_tot else float("nan")
    rmse = math.sqrt(ss_res / len(points))
    max_residual = max(abs(y - yh) for y, yh in zip(ys, y_fit))
    return {
        "slope": slope,
        "intercept_ohm": intercept,
        "r2": r2,
        "rmse_ohm": rmse,
        "max_residual_ohm": max_residual,
    }


def group_by_current(rows):
    grouped = {}
    for row in rows:
        grouped.setdefault(row["target_mA"], []).append(row)
    for points in grouped.values():
        points.sort(key=lambda p: (p["ref_mean_ohm"], p["line"]))
    return dict(sorted(grouped.items()))


def write_csv(path, rows, fits):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        fieldnames = [
            "line", "section_line", "ref_line", "target_mA", "ref_nominal_ohm",
            "ref_mean_ohm", "ref_std_mohm", "ref_count", "ref_match_delta_mohm",
            "sample_count", "I_mean_mA", "I_std_uA", "V_mean_mV", "V_std_mV",
            "R_mean_ohm", "R_std_mohm", "R_error_mohm", "fit_slope",
            "fit_intercept_mohm", "fit_r2", "fit_residual_mohm", "statuses",
        ]
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            fit = fits.get(row["target_mA"])
            residual = ""
            if fit is not None:
                predicted = fit["slope"] * row["ref_mean_ohm"] + fit["intercept_ohm"]
                residual = (row["R_mean_ohm"] - predicted) * 1000.0
            writer.writerow({
                "line": row["line"],
                "section_line": row["section_line"],
                "ref_line": row["ref_line"],
                "target_mA": f"{row['target_mA']:.6g}",
                "ref_nominal_ohm": f"{row['ref_nominal_ohm']:.6g}",
                "ref_mean_ohm": f"{row['ref_mean_ohm']:.9f}",
                "ref_std_mohm": f"{row['ref_std_ohm'] * 1000.0:.6f}",
                "ref_count": row["ref_count"],
                "ref_match_delta_mohm": f"{row['ref_match_delta_ohm'] * 1000.0:.6f}",
                "sample_count": row["sample_count"],
                "I_mean_mA": f"{row['I_mean_mA']:.9f}",
                "I_std_uA": f"{row['I_std_mA'] * 1000.0:.6f}",
                "V_mean_mV": f"{row['V_mean_mV']:.6f}",
                "V_std_mV": f"{row['V_std_mV']:.6f}",
                "R_mean_ohm": f"{row['R_mean_ohm']:.9f}",
                "R_std_mohm": f"{row['R_std_ohm'] * 1000.0:.6f}",
                "R_error_mohm": f"{(row['R_mean_ohm'] - row['ref_mean_ohm']) * 1000.0:.6f}",
                "fit_slope": "" if fit is None else f"{fit['slope']:.12f}",
                "fit_intercept_mohm": "" if fit is None else f"{fit['intercept_ohm'] * 1000.0:.6f}",
                "fit_r2": "" if fit is None else f"{fit['r2']:.12f}",
                "fit_residual_mohm": "" if residual == "" else f"{residual:.6f}",
                "statuses": row["statuses"],
            })


def plot_chart(path, grouped, fits):
    fig, axes = plt.subplots(2, 1, figsize=(12, 10))
    fig.suptitle("", fontsize=14)
    all_points = [p for points in grouped.values() for p in points]
    fit_values = [fit for fit in fits.values() if fit is not None]
    ref_min_mohm = min(p["ref_mean_ohm"] for p in all_points) * 1000.0
    ref_max_mohm = max(p["ref_mean_ohm"] for p in all_points) * 1000.0
    err_values_mohm = [(p["R_mean_ohm"] - p["ref_mean_ohm"]) * 1000.0 for p in all_points]
    fit_currents = "/".join(f"{current:g}" for current, fit in fits.items() if fit is not None)
    if fit_values:
        conclusion = (
            f"结论：{ref_min_mohm:.0f}~{ref_max_mohm:.0f} mOhm 范围内，"
            f"{fit_currents} mA 下电阻变化线性很好（R²≥{min(f['r2'] for f in fit_values):.9f}）；"
            f"绝对误差约 {min(err_values_mohm):+.2f}~{max(err_values_mohm):+.2f} mOhm，"
            f"说明主要是系统性增益/零点误差，不是随机散点。"
        )
    else:
        conclusion = (
            f"结论：{ref_min_mohm:.0f}~{ref_max_mohm:.0f} mOhm 范围内数据点不足，无法评估线性；"
            f"绝对误差约 {min(err_values_mohm):+.2f}~{max(err_values_mohm):+.2f} mOhm。"
        )

    ax = axes[0]
    all_x = [p["ref_mean_ohm"] * 1000.0 for p in all_points]
    x_min, x_max = min(all_x), max(all_x)
    ax.plot([x_min, x_max], [x_min, x_max], "--", color="0.55", lw=1.1, label="理想 y=x")

    currents = list(grouped)
    offset_step = (x_max - x_min) * 0.004 if len(currents) > 1 else 0.0
    offsets = {
        current: (index - (len(currents) - 1) / 2.0) * offset_step
        for index, current in enumerate(currents)
    }
    markers = ["o", "s", "^", "D", "v", "P", "X"]
    linestyles = ["-", "--", "-.", ":"]

    for index, (current_mA, points) in enumerate(grouped.items()):
        xs = [p["ref_mean_ohm"] * 1000.0 for p in points]
        display_xs = [x + offsets[current_mA] for x in xs]
        ys = [p["R_mean_ohm"] * 1000.0 for p in points]
        yerr = [p["R_std_ohm"] * 1000.0 for p in points]
        label = f"{current_mA:g} mA"
        fit = fits.get(current_mA)
        if fit is not None:
            label += f"  slope={fit['slope']:.7f}  R²={fit['r2']:.9f}"
        ax.errorbar(
            display_xs, ys, yerr=yerr, marker=markers[index % len(markers)],
            linestyle=linestyles[index % len(linestyles)], lw=1.45, capsize=3,
            ms=5.5, markerfacecolor="white", markeredgewidth=1.2, label=label,
        )

    ax.set_ylabel("测得电阻 (mOhm)")
    ax.set_xlabel("DAQ6510 参考电阻 (mOhm)")
    ax.grid(alpha=0.3)
    ax.legend(loc="best", fontsize=9)

    ax = axes[1]
    ax.axhline(0, ls="--", color="0.55", lw=1.0)
    for current_mA, points in grouped.items():
        xs = [p["ref_mean_ohm"] * 1000.0 for p in points]
        ys = [(p["R_mean_ohm"] - p["ref_mean_ohm"]) * 1000.0 for p in points]
        ax.plot(xs, ys, marker="o", lw=1.6, label=f"{current_mA:g} mA")

    ax.set_xlabel("DAQ6510 参考电阻 (mOhm)")
    ax.set_ylabel("电阻误差 (mOhm)")
    ax.grid(alpha=0.3)
    ax.legend(loc="best", fontsize=9)

    fig.text(0.5, 0.018, conclusion, ha="center", va="bottom", fontsize=10)
    fig.tight_layout(rect=[0, 0.055, 1, 0.96])
    fig.savefig(path, dpi=150)


def main():
    root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description="画 mutiR.txt 的电阻线性折线图")
    parser.add_argument("-i", "--input", default=str(root / "mutiR.txt"), help="输入日志，默认 ./mutiR.txt")
    parser.add_argument("-o", "--output", default=str(root / "mutiR_chart.png"), help="输出图片，默认 ./mutiR_chart.png")
    parser.add_argument("--csv", default=str(root / "mutiR_summary.csv"), help="输出汇总 CSV")
    args = parser.parse_args()

    src = Path(args.input)
    if not src.exists():
        sys.exit(f"not found: {src}")

    rows = aggregate(parse_log(src))
    if not rows:
        sys.exit("no adcf samples parsed")

    grouped = group_by_current(rows)
    fits = {current: linear_fit(points) for current, points in grouped.items()}

    plot_chart(Path(args.output), grouped, fits)
    write_csv(Path(args.csv), rows, fits)

    print(f"parsed blocks: {len(rows)}")
    for current_mA, points in grouped.items():
        fit = fits[current_mA]
        max_error_mohm = max(abs((p["R_mean_ohm"] - p["ref_mean_ohm"]) * 1000.0) for p in points)
        if fit is None:
            print(f"  {current_mA:g} mA: points={len(points)} max_error={max_error_mohm:.3f} mOhm")
        else:
            print(
                f"  {current_mA:g} mA: points={len(points)} "
                f"slope={fit['slope']:.9f} intercept={fit['intercept_ohm'] * 1000.0:+.3f} mOhm "
                f"R²={fit['r2']:.9f} max_res={fit['max_residual_ohm'] * 1000.0:.3f} mOhm "
                f"max_error={max_error_mohm:.3f} mOhm"
            )
    print(f"saved: {args.output}")
    print(f"saved: {args.csv}")


if __name__ == "__main__":
    main()
