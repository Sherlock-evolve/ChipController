#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ChipController 板级温漂专用采集脚本。

每隔 N 秒（默认 1s）向 ChipController 的 Type-C 调试串口发送 `adcf 1`，
解析返回的一阶低通滤波 ADC 读数（I / V / R + 两个 AD7190 状态字节），
连同单调时钟和单次采样耗时追加写入 temp_drift_*.csv，便于分析板子
长时间运行下的电流、电压和电阻漂移。

输出专供 tools/plot_temp_drift.py 使用，不包含 TCR 温度换算。需要生成
与 Qt 上位机兼容、包含 chip_temp_C 的简易采集日志时，请使用
tools/adcf_logger.py。

默认串口: /dev/ttyUSB0, 115200 8N1（固件 Type-C 调试口标准配置）。
仅依赖 Python3 标准库（termios），无需 pyserial。

固件返回行格式（Core/Src/main.c: App_PrintAdcFilteredSamples）：
    AD7190 filtered samples: count=1 alpha=250 mpermil
    adcf 1: I=<nA> nA V=<uV> uV R=<uOhm> uOhm status current=0xXX voltage=0xXX

用法示例:
    python3 tools/temp_drift_test.py
    python3 tools/temp_drift_test.py -p /dev/ttyUSB0 -o temp_drift.csv -i 2.0
    # 恒流条件下测电流漂移（先发一条 tc current 5）：
    python3 tools/temp_drift_test.py --init "tc current 5"
    # 测零点漂移：
    python3 tools/temp_drift_test.py --init zero

绘图:
    python3 tools/plot_temp_drift.py

Ctrl-C 干净退出，并在 stderr 打印一段汇总统计（min/max/mean/首末漂移）。
"""

import argparse
import csv
import os
import re
import select
import signal
import sys
import termios
import time
from datetime import datetime

DEFAULT_PORT = "/dev/ttyUSB0"
DEFAULT_BAUD = 115200
DEFAULT_INTERVAL = 1.0
READ_TIMEOUT = 0.8

BAUD_CONSTS = {
    9600: termios.B9600,
    19200: termios.B19200,
    38400: termios.B38400,
    57600: termios.B57600,
    115200: termios.B115200,
    230400: termios.B230400,
    460800: termios.B460800,
}

# 匹配: adcf 1: I=123 nA V=456 uV R=789 uOhm status current=0x08 voltage=0x08
LINE_RE = re.compile(
    r"adcf\s+\d+:\s+I=(-?\d+)\s+nA\s+V=(-?\d+)\s+uV\s+R=(-?\d+)\s+uOhm"
    r"\s+status\s+current=0x([0-9A-Fa-f]+)\s+voltage=0x([0-9A-Fa-f]+)"
)

# VMIN/VTIME 在 termios.cc 数组里的下标
_VMIN = termios.VMIN
_VTIME = termios.VTIME


class Serial:
    """基于 os.open + termios 的极简串口封装，零第三方依赖。"""

    def __init__(self, port, baud):
        try:
            self.fd = os.open(port, os.O_RDWR | os.O_NOCTTY)
        except PermissionError:
            sys.exit(f"无权限打开 {port}。请把用户加入 dialout 组 "
                     f"(sudo usermod -aG dialout $USER) 后重新登录，或用 sudo 运行。")
        except FileNotFoundError:
            sys.exit(f"串口 {port} 不存在。请确认设备已连接 (ls /dev/ttyUSB*)。")

        iflag, oflag, cflag, lflag, _ispeed, _ospeed, cc = termios.tcgetattr(self.fd)
        cc = list(cc)

        iflag = 0                       # 关闭输入处理（无 ICRNL/IXON 等）
        oflag = 0                       # 关闭输出处理
        lflag = 0                       # raw 模式：无回显、非规范
        cflag |= termios.CREAD | termios.CLOCAL
        cflag &= ~termios.CSIZE
        cflag |= termios.CS8            # 8 数据位
        cflag &= ~termios.PARENB        # 无校验
        cflag &= ~termios.CSTOPB        # 1 停止位

        bconst = BAUD_CONSTS.get(baud, termios.B115200)
        cc[_VMIN] = 0                   # 配合 select：read 永不阻塞
        cc[_VTIME] = 0

        termios.tcsetattr(self.fd, termios.TCSANOW,
                          [iflag, oflag, cflag, lflag, bconst, bconst, cc])
        self.port = port
        self.fd_ok = True

    def flush(self):
        """清空输入/输出缓冲，避免回显与历史响应堆积导致解析错位。"""
        termios.tcflush(self.fd, termios.TCIOFLUSH)

    def write(self, data: bytes):
        os.write(self.fd, data)

    def read_until(self, regex, timeout):
        """读到匹配 regex 的行就返回 Match；超时返回 None。"""
        buf = b""
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            r, _, _ = select.select([self.fd], [], [], min(0.1, remaining))
            if not r:
                continue
            try:
                chunk = os.read(self.fd, 4096)
            except OSError:
                return None
            if not chunk:
                return None
            buf += chunk
            for line in buf.decode("ascii", "replace").splitlines():
                m = regex.search(line)
                if m:
                    return m

    def drain(self, timeout=0.5):
        """启动期丢弃回显/响应，不解析。"""
        self.read_until(re.compile(r"$^"), timeout)

    def close(self):
        if self.fd_ok:
            try:
                os.close(self.fd)
            except OSError:
                pass
            self.fd_ok = False


def summary(name, vals):
    if not vals:
        return
    print(f"{name:>9}: min={min(vals):.5g}  max={max(vals):.5g}  "
          f"mean={sum(vals)/len(vals):.5g}  last={vals[-1]:.5g}  "
          f"span={max(vals)-min(vals):.5g}", file=sys.stderr)


def run(args):
    ser = Serial(args.port, args.baud)
    out_path = args.output or os.path.join(
        os.getcwd(), "temp_drift_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".csv")

    # 启动前置命令（设置测试条件，如恒流 / 归零）
    for cmd in args.init:
        ser.flush()
        ser.write((cmd + "\n").encode("ascii"))
        time.sleep(0.3)
        ser.drain(0.5)

    cols = ["timestamp", "monotonic_s", "cycle_ms",
            "I_nA", "V_uV", "R_uOhm",
            "I_A", "V_mV", "R_Ohm",
            "status_current", "status_voltage", "note"]
    f = open(out_path, "w", newline="", encoding="utf-8")
    writer = csv.writer(f)
    writer.writerow(cols)
    f.flush()

    read_timeout = min(READ_TIMEOUT, args.interval * 0.8)

    running = {"on": True}

    def stop(_signum, _frame):
        running["on"] = False

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    I_list, V_list, R_list, t_list = [], [], [], []
    n_ok = 0
    n_fail = 0
    print(f"开始采集 -> {out_path}  (Ctrl-C 结束)", file=sys.stderr)
    print(f"串口 {args.port} @ {args.baud}, 间隔 {args.interval}s, 单次读超时 {read_timeout:.2f}s",
          file=sys.stderr)

    next_t = time.monotonic()
    try:
        while running["on"]:
            t_send = time.monotonic()
            next_t += args.interval
            if next_t - t_send < 0:           # 单次耗时超过间隔，重置基准避免持续滞后
                next_t = t_send + args.interval

            ser.flush()
            ser.write(b"adcf 1\n")
            ts_iso = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            m = ser.read_until(LINE_RE, read_timeout)
            cycle_ms = int((time.monotonic() - t_send) * 1000)

            if m:
                i_na, v_uv, r_uohm, cur_st, vol_st = (int(m.group(1)), int(m.group(2)),
                                                      int(m.group(3)), m.group(4), m.group(5))
                row = [ts_iso, f"{t_send:.3f}", cycle_ms,
                       i_na, v_uv, r_uohm,
                       f"{i_na*1e-9:.6f}", f"{v_uv*1e-3:.4f}",
                       f"{r_uohm*1e-6:.4f}" if r_uohm else "",
                       "0x" + cur_st.upper(), "0x" + vol_st.upper(), ""]
                I_list.append(i_na)
                V_list.append(v_uv)
                if r_uohm:
                    R_list.append(r_uohm * 1e-6)
                t_list.append(t_send)
                n_ok += 1
                if not args.quiet:
                    print(f"\r[{ts_iso}] I={i_na:>8} nA  V={v_uv:>8} uV  "
                          f"R={r_uohm*1e-6:>9.4f} Ohm  (ok={n_ok} miss={n_fail})   ",
                          end="", file=sys.stderr, flush=True)
            else:
                row = [ts_iso, f"{t_send:.3f}", cycle_ms,
                       "", "", "", "", "", "", "", "", "timeout/no-match"]
                n_fail += 1
                if not args.quiet:
                    print(f"\r[{ts_iso}] (no response)  (ok={n_ok} miss={n_fail})   ",
                          end="", file=sys.stderr, flush=True)

            writer.writerow(row)
            f.flush()

            sleep_s = next_t - time.monotonic()
            if sleep_s > 0:
                time.sleep(sleep_s)
    finally:
        f.close()
        ser.close()
        if not args.quiet:
            print("", file=sys.stderr)

    print("\n=== 采集结束 ===", file=sys.stderr)
    print(f"文件: {out_path}", file=sys.stderr)
    print(f"成功 {n_ok} 条, 失败/超时 {n_fail} 条", file=sys.stderr)
    if n_ok >= 1:
        summary("I (nA)", I_list)
        summary("V (uV)", V_list)
        if R_list:
            summary("R (Ohm)", R_list)
    if n_ok >= 2:
        dur = t_list[-1] - t_list[0]
        print(f"首末漂移 (持续 {dur:.0f}s): "
              f"delta I={I_list[-1]-I_list[0]:+d} nA  "
              f"delta V={V_list[-1]-V_list[0]:+d} uV", file=sys.stderr)


def main():
    p = argparse.ArgumentParser(
        description="ChipController 板级温漂专用采集 (adcf 1 -> temp_drift_*.csv)")
    p.add_argument("-p", "--port", default=DEFAULT_PORT, help=f"串口设备 (默认 {DEFAULT_PORT})")
    p.add_argument("-b", "--baud", type=int, default=DEFAULT_BAUD, help="波特率 (默认 115200)")
    p.add_argument("-i", "--interval", type=float, default=DEFAULT_INTERVAL,
                   help="采样间隔秒 (默认 1.0)")
    p.add_argument("-o", "--output", help="CSV 输出路径 (默认 temp_drift_<时间>.csv)")
    p.add_argument("--init", action="append", default=[], metavar="CMD",
                   help="启动后先发送的命令,可重复,如 'tc current 5' / 'zero'")
    p.add_argument("-q", "--quiet", action="store_true", help="不实时打印进度")
    args = p.parse_args()
    if args.interval <= 0:
        sys.exit("--interval 必须为正数")
    run(args)


if __name__ == "__main__":
    main()
