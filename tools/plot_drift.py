#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
读取 adcf_logger.py 产生的 CSV，画长时间温漂趋势图。

每个量 (I/V/R) 以「偏离全程均值的 ppm」为纵轴，便于直接看漂移幅度，且三量量纲一致。
每张子图含：原始秒级散点 + 每小时(可配置)均值折线 + 线性拟合虚线，
标题标注噪声(rms)与净漂移，用于判断是否存在系统性温漂。

用法:
    python3 tools/plot_drift.py                 # 自动找最新的 adcf_log_*.csv
    python3 tools/plot_drift.py -i some.csv -o out.png
    python3 tools/plot_drift.py --bin 1800 --no-raw
"""
import argparse
import csv
import glob
import os
import sys
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

# ---- CJK 字体，与 plot_verify.py 一致 ----
for _name in ("Noto Sans CJK JP", "Noto Sans CJK SC", "WenQuanYi Zen Hei", "SimHei"):
    if [f for f in font_manager.fontManager.ttflist if f.name == _name]:
        plt.rcParams["font.sans-serif"] = [_name]
        plt.rcParams["axes.unicode_minus"] = False
        break


def latest_log(root):
    fs = glob.glob(os.path.join(root, "adcf_log_*.csv"))
    return max(fs, key=os.path.getmtime) if fs else None


def load(path):
    t, I, V, R = [], [], [], []
    ts0 = None
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if not row["I_nA"]:
                continue
            t.append(float(row["monotonic_s"]))
            I.append(float(row["I_nA"]))
            V.append(float(row["V_uV"]))
            R.append(float(row["R_Ohm"]) if row["R_Ohm"] else float("nan"))
            if ts0 is None:
                ts0 = row["timestamp"]
    return (np.array(x) for x in (t, I, V, R)), ts0


def bin_mean(x, y, bin_s, min_frac=0.5):
    """按 bin_s 秒分桶，返回 (桶中心秒, 桶均值)。
    丢弃样本数不足预期一半的首尾不完整桶，避免单点/半点桶污染极差统计。"""
    span = float(x[-1] - x[0])
    expected = len(x) * bin_s / span if span > 0 else float(len(x))
    bid = np.floor(x / bin_s).astype(int)
    ub = np.unique(bid)
    xc, yc = [], []
    for b in ub:
        sel = y[bid == b]
        if len(sel) < expected * min_frac:
            continue
        xc.append((b + 0.5) * bin_s)
        yc.append(float(np.nanmean(sel)))
    return np.array(xc), np.array(yc)


def main():
    here = Path(__file__).resolve().parent
    root = here.parent
    ap = argparse.ArgumentParser(description="画 adcf_logger CSV 的温漂趋势图")
    ap.add_argument("-i", "--input", help="adcf_log CSV (默认最新)")
    ap.add_argument("-o", "--output", help="输出 png (默认同名 .png)")
    ap.add_argument("--bin", type=float, default=3600, help="均值桶大小秒 (默认 3600=1h)")
    ap.add_argument("--no-raw", action="store_true", help="不画原始散点")
    args = ap.parse_args()

    src = args.input or latest_log(str(root)) or latest_log(os.getcwd())
    if not src or not os.path.exists(src):
        sys.exit("找不到 adcf_log_*.csv，请用 -i 指定")
    (t_s, I_na, V_uv, R_ohm), ts0 = load(src)
    # monotonic_s 存的是 time.monotonic() 绝对值（采集开始前已累积若干秒），
    # 减去首样本归零，否则时长与 x 轴起点会偏大（例如把 24h 显示成 25.7h）。
    t_s = t_s - t_s[0]
    t_h = t_s / 3600.0
    dur = float(t_h[-1])
    bin_h = args.bin / 3600.0

    series = [
        ("电流 I", I_na * 1e-9, "A", "C0"),
        ("电压 V", V_uv * 1e-6, "V", "C1"),
        ("电阻 R", R_ohm,       "Ω", "C2"),
    ]

    fig, axes = plt.subplots(3, 1, figsize=(13, 10), sharex=True)
    fig.suptitle(f"ChipController 长时间温漂趋势    起始 {ts0}    "
                 f"时长 {dur:.1f} h    样本 {len(t_s)}", fontsize=13)

    summary = []
    for ax, (name, y, unit, color) in zip(axes, series):
        mean = float(np.nanmean(y))
        ppm = (y - mean) / mean * 1e6
        mask = np.isfinite(ppm)

        slope, inter = np.polyfit(t_h[mask], ppm[mask], 1)
        drift = slope * dur
        rms = float(np.nanstd(ppm))

        xc, yc = bin_mean(t_s, ppm, args.bin)
        xc_h = xc / 3600.0
        bin_pp = float(np.nanmax(yc) - np.nanmin(yc))

        if not args.no_raw:
            ax.scatter(t_h[mask], ppm[mask], s=2, alpha=0.12, c="0.7",
                       rasterized=True, label="原始(秒级)")
        ax.plot(xc_h, yc, "-o", ms=4, lw=1.6, color=color,
                label=f"均值(每{bin_h:g}h)")
        ax.plot(t_h, slope * t_h + inter, "--", color="C3", lw=1.2,
                label=f"线性拟合 {slope:+.3f} ppm/h")
        ax.axhline(0, ls=":", color="k", lw=0.8)
        ax.set_ylabel(f"{name} 偏离均值 (ppm)")
        ax.set_title(f"{name}: mean={mean:.6g} {unit}   噪声={rms:.1f} ppm rms   "
                     f"{dur:.0f}h 净漂移={drift:+.1f} ppm   "
                     f"小时均值极差={bin_pp:.1f} ppm p-p", fontsize=10)
        ax.grid(alpha=0.3)
        ax.legend(loc="upper right", fontsize=8)
        summary.append((name, mean, unit, rms, drift, bin_pp))

    axes[-1].set_xlabel("运行时间 (h)")
    fig.tight_layout(rect=[0, 0, 1, 0.97])
    out = args.output or (os.path.splitext(src)[0] + ".png")
    fig.savefig(out, dpi=150)
    print(f"saved: {out}")
    print(f"  样本 {len(t_s)}  时长 {dur:.1f} h  桶 {bin_h:g} h")
    for name, mean, unit, rms, drift, bin_pp in summary:
        print(f"  {name}: mean={mean:.6g}{unit}  噪声={rms:.1f}ppm  "
              f"{dur:.0f}h漂移={drift:+.1f}ppm  小时极差={bin_pp:.1f}ppm")


if __name__ == "__main__":
    main()
