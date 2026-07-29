#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Parse ChipController verify.txt (precision-resistor current sweep) and plot
line charts verifying current-control accuracy and resistance measurement.

Input format (per current point):
    tc current <mA>
    ThermalControl current target: <uA>, status=OK (0)
    adcf 20
    AD7190 filtered samples: ...
    adcf 1: I=<nA> V=<uV> R=<uOhm> status ...
    ...

Units: I nA, V uV, R uOhm.  ->  I mA (/1e6), V V (/1e6), R Ohm (/1e6).
"""
import re
import os
import sys
import tempfile
from pathlib import Path
import numpy as np
os.environ.setdefault("MPLCONFIGDIR", os.path.join(tempfile.gettempdir(),
                                                   "matplotlib-chipcontroller"))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

# ---- CJK font so Chinese labels render ----
for name in ("Noto Sans CJK JP", "Noto Sans CJK SC", "WenQuanYi Zen Hei", "SimHei"):
    matches = [f for f in font_manager.fontManager.ttflist if f.name == name]
    if matches:
        plt.rcParams["font.sans-serif"] = [name]
        plt.rcParams["axes.unicode_minus"] = False
        break

RE_TARGET = re.compile(r"^tc\s+current\s+([-\d.]+)\s*$")
RE_SAMPLE = re.compile(r"adcf\s+\d+:\s+I=(-?\d+)\s+nA\s+V=(-?\d+)\s+uV\s+R=(-?\d+)\s+uOhm")

REF_R = 150.007  # 精密电阻标称值 (Ohm)


def parse(path):
    rows = []                 # (target_mA, I_nA, V_uV, R_uOhm)
    target = None
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            m = RE_TARGET.match(line.strip())
            if m:
                target = float(m.group(1))
                continue
            m = RE_SAMPLE.search(line)
            if m and target is not None:
                i_na, v_uv, r_uo = map(int, m.groups())
                rows.append((target, i_na, v_uv, r_uo))
    return rows


def aggregate(rows):
    """Group by target current -> per-point mean/std for I(mA), V(V), R(Ohm)."""
    pts = {}
    for tgt, i_na, v_uv, r_uo in rows:
        pts.setdefault(tgt, []).append((i_na / 1e6, v_uv / 1e6, r_uo / 1e6))
    out = []
    for tgt in sorted(pts):
        arr = np.array(pts[tgt], dtype=float)
        out.append({
            "target_mA": tgt,
            "Imean_mA": arr[:, 0].mean(),
            "Istd_mA":  arr[:, 0].std(ddof=0),
            "Vmean_V":  arr[:, 1].mean(),
            "Vstd_V":   arr[:, 1].std(ddof=0),
            "Rmean_Ohm": arr[:, 2].mean(),
            "Rstd_Ohm":  arr[:, 2].std(ddof=0),
        })
    return out


def main():
    here = Path(__file__).resolve().parent
    src = here.parent / "verify.txt"
    if not src.exists():
        src = Path("verify.txt")
    if not src.exists():
        sys.exit("verify.txt not found")
    rows = parse(src)
    if not rows:
        sys.exit("no samples parsed")
    agg = aggregate(rows)

    tgt   = np.array([p["target_mA"]  for p in agg])
    Imean = np.array([p["Imean_mA"]   for p in agg])
    Istd  = np.array([p["Istd_mA"]    for p in agg])
    Vmean = np.array([p["Vmean_V"]    for p in agg])
    Rmean = np.array([p["Rmean_Ohm"]  for p in agg])
    Rstd  = np.array([p["Rstd_Ohm"]   for p in agg])

    Ierr_uA = (Imean - tgt) * 1000.0          # 测量-目标 (uA)
    Rerr_ppm = (Rmean - REF_R) / REF_R * 1e6  # 电阻偏差 (ppm)

    # ---- summary print ----
    print(f"points: {len(agg)}  sweep: {tgt[0]} -> {tgt[-1]} mA  REF_R={REF_R} Ohm")
    print(f"  I err: min={Ierr_uA.min():+.2f} uA  max={Ierr_uA.max():+.2f} uA"
          f"  |max|={np.abs(Ierr_uA).max():.2f} uA")
    print(f"  R mean={Rmean.mean():.4f} Ohm  min={Rmean.min():.4f}  max={Rmean.max():.4f}")
    print(f"  R vs {REF_R}: min={Rerr_ppm.min():+.0f} ppm  max={Rerr_ppm.max():+.0f} ppm"
          f"  span={(Rmean.max()-Rmean.min())*1e6:.0f} uOhm")

    # ---- figure ----
    fig, ax = plt.subplots(2, 2, figsize=(13, 9))
    fig.suptitle(f"ChipController 校准验证 (精密电阻 {REF_R} Ohm, {len(agg)} 点扫描)",
                 fontsize=14)

    # (1) 测量电流 vs 目标电流
    a = ax[0, 0]
    lim = [0, max(tgt[-1], Imean.max()) * 1.05]
    a.plot(lim, lim, "--", color="0.6", lw=1, label="理想 y=x")
    a.errorbar(tgt, Imean, yerr=Istd, fmt="-o", ms=4, lw=1.5, capsize=3,
               color="C0", ecolor="C0", elinewidth=0.8, label="测量电流 (均值±σ, n=20)")
    a.set_xlabel("目标电流 (mA)")
    a.set_ylabel("测量电流 (mA)")
    a.set_title("电流控制线性度")
    a.legend(loc="upper left")
    a.grid(alpha=0.3)

    # (2) 电阻 vs 目标电流
    a = ax[0, 1]
    a.axhline(REF_R, ls="--", color="0.6", lw=1, label=f"标称 {REF_R} Ohm")
    a.errorbar(tgt, Rmean, yerr=Rstd, fmt="-o", ms=4, lw=1.5, capsize=3,
               color="C2", ecolor="C2", elinewidth=0.8, label="测量电阻 (均值±σ)")
    a.set_xlabel("目标电流 (mA)")
    a.set_ylabel("电阻 (Ohm)")
    a.set_title("电阻测量稳定性")
    a.legend(loc="best")
    a.grid(alpha=0.3)

    # (3) 电流误差 vs 目标电流
    a = ax[1, 0]
    a.axhline(0, ls="--", color="0.6", lw=1)
    a.plot(tgt, Ierr_uA, "-o", ms=4, lw=1.5, color="C3")
    a.set_xlabel("目标电流 (mA)")
    a.set_ylabel("电流误差 测量-目标 (uA)")
    a.set_title("电流控制误差")
    a.grid(alpha=0.3)

    # (4) 电压 vs 电流 (欧姆特性, 斜率=电阻)
    a = ax[1, 1]
    a.plot(Imean, Vmean, "-o", ms=4, lw=1.5, color="C1", label="测量点")
    coef = np.polyfit(Imean, Vmean, 1)          # V per mA
    fit = np.polyval(coef, Imean)
    R_fit = coef[0] * 1000.0                     # V/mA -> V/A = Ohm
    a.plot(Imean, fit, "--", color="C0", lw=1.2,
           label=f"线性拟合  R={R_fit:.4f} Ohm")
    a.set_xlabel("测量电流 (mA)")
    a.set_ylabel("电压 (V)")
    a.set_title("V-I 欧姆特性")
    a.legend(loc="upper left")
    a.grid(alpha=0.3)

    fig.tight_layout(rect=[0, 0, 1, 0.96])
    out = here.parent / "verify_chart.png"
    fig.savefig(out, dpi=150)
    print(f"saved: {out}")

    # CSV for record
    csv = here.parent / "verify_summary.csv"
    with open(csv, "w", encoding="utf-8") as fh:
        fh.write("target_mA,I_meas_mA,I_err_uA,V_meas_V,R_meas_Ohm,R_err_ppm\n")
        for p, e, rp in zip(agg, Ierr_uA, Rerr_ppm):
            fh.write(f"{p['target_mA']:.2f},{p['Imean_mA']:.4f},{e:.2f},"
                     f"{p['Vmean_V']:.6f},{p['Rmean_Ohm']:.4f},{rp:.0f}\n")
    print(f"saved: {csv}")


if __name__ == "__main__":
    main()
