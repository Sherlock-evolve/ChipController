#!/usr/bin/env python3
import argparse
import os
import select
import sys
import termios
import time


CSV_HEADER = "index,tick_ms,status,current_nA,voltage_uV,resistance_mOhm,current_adc_status,voltage_adc_status"

BAUD_RATES = {
    9600: termios.B9600,
    19200: termios.B19200,
    38400: termios.B38400,
    57600: termios.B57600,
    115200: termios.B115200,
    230400: termios.B230400,
    460800: termios.B460800,
    921600: termios.B921600,
}


def parse_args():
    parser = argparse.ArgumentParser(description="Log ChipController ADC stream output to CSV.")
    parser.add_argument("port", help="Serial port, for example /dev/ttyUSB0 or /dev/serial/by-id/...")
    parser.add_argument("output", help="CSV output path")
    parser.add_argument("--baud", type=int, default=115200, choices=sorted(BAUD_RATES))
    parser.add_argument("--period-ms", type=int, default=100, help="ADC stream period sent to firmware")
    parser.add_argument("--duration-sec", type=float, default=0.0, help="Stop after this many seconds; 0 means until Ctrl-C")
    parser.add_argument("--append", action="store_true", help="Append to the output file")
    parser.add_argument("--raw-log", help="Optional path for all raw serial lines, useful when the CSV file stays empty")
    parser.add_argument("--startup-delay-sec", type=float, default=8.0, help="Wait after opening the port before sending commands")
    parser.add_argument("--char-delay-ms", type=float, default=5.0, help="Delay between command characters")
    args = parser.parse_args()
    if args.period_ms < 50 or args.period_ms > 60000:
        parser.error("--period-ms must be between 50 and 60000")
    return args


def configure_serial(fd, baud):
    attrs = termios.tcgetattr(fd)
    attrs[0] = 0
    attrs[1] = 0
    attrs[2] |= termios.CLOCAL | termios.CREAD
    attrs[2] &= ~(termios.PARENB | termios.CSTOPB | termios.CSIZE | getattr(termios, "CRTSCTS", 0))
    attrs[2] |= termios.CS8
    attrs[3] = 0
    attrs[4] = BAUD_RATES[baud]
    attrs[5] = BAUD_RATES[baud]
    attrs[6][termios.VMIN] = 0
    attrs[6][termios.VTIME] = 1
    termios.tcsetattr(fd, termios.TCSANOW, attrs)


def write_command(fd, command, char_delay_ms):
    for byte in (command + "\r\n").encode("ascii"):
        os.write(fd, bytes([byte]))
        termios.tcdrain(fd)
        if char_delay_ms > 0.0:
            time.sleep(char_delay_ms / 1000.0)


def is_csv_line(line):
    if line == CSV_HEADER:
        return True

    fields = line.split(",")
    return len(fields) == 8 and fields[0].isdigit() and fields[1].isdigit()


def handle_line(line, output, raw_output, stats):
    if not line:
        return

    if raw_output is not None:
        raw_output.write(line + "\n")
        raw_output.flush()

    if line == CSV_HEADER:
        return

    if is_csv_line(line):
        output.write(line + "\n")
        output.flush()
        stats["csv_rows"] += 1
    else:
        stats["other_lines"] += 1


def process_serial(fd, buffer, output, raw_output, stats, timeout_sec):
    deadline = time.monotonic() + timeout_sec
    seen_start = False
    seen_sample = False

    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0.0:
            break

        readable, _, _ = select.select([fd], [], [], min(0.2, remaining))
        if not readable:
            continue

        try:
            chunk = os.read(fd, 4096)
        except BlockingIOError:
            continue

        stats["bytes"] += len(chunk)
        text = chunk.decode("ascii", errors="ignore")
        for char in text:
            if char in "\r\n":
                line = buffer.strip()
                buffer = ""
                if line.startswith("ADCSTREAM START"):
                    seen_start = True
                if is_csv_line(line) and line != CSV_HEADER:
                    seen_sample = True
                handle_line(line, output, raw_output, stats)
            else:
                buffer += char

    return buffer, seen_start, seen_sample


def main():
    args = parse_args()
    fd = os.open(args.port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    old_attrs = termios.tcgetattr(fd)
    mode = "a" if args.append else "w"
    deadline = None
    buffer = ""
    stats = {"bytes": 0, "csv_rows": 0, "other_lines": 0}

    try:
        output_dir = os.path.dirname(os.path.abspath(args.output))
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)

        raw_output = open(args.raw_log, "w", encoding="ascii", newline="") if args.raw_log else None
        try:
            with open(args.output, mode, encoding="ascii", newline="") as output:
                if not args.append or os.path.getsize(args.output) == 0:
                    output.write(CSV_HEADER + "\n")
                    output.flush()

                configure_serial(fd, args.baud)
                if args.startup_delay_sec > 0.0:
                    time.sleep(args.startup_delay_sec)

                buffer, _, _ = process_serial(fd, buffer, output, raw_output, stats, 0.5)

                started = False
                for attempt in range(1, 6):
                    write_command(fd, "adcstream stop", args.char_delay_ms)
                    buffer, _, _ = process_serial(fd, buffer, output, raw_output, stats, 0.3)
                    write_command(fd, "adcstream start %d" % args.period_ms, args.char_delay_ms)
                    buffer, seen_start, seen_sample = process_serial(fd, buffer, output, raw_output, stats, 2.0)
                    if seen_start or seen_sample:
                        started = True
                        break

                    sys.stderr.write("adcstream start not acknowledged, retry %d/5\n" % attempt)
                    sys.stderr.flush()

                if not started:
                    sys.stderr.write("warning: adcstream start was not acknowledged; logging raw input anyway\n")

                deadline = None if args.duration_sec <= 0.0 else time.monotonic() + args.duration_sec

                sys.stderr.write("logging %s at %d baud to %s\n" % (args.port, args.baud, args.output))
                sys.stderr.write("press Ctrl-C to stop\n")
                sys.stderr.flush()

                while True:
                    if deadline is not None and time.monotonic() >= deadline:
                        break

                    buffer, _, _ = process_serial(fd, buffer, output, raw_output, stats, 0.2)
        finally:
            if raw_output is not None:
                raw_output.close()
    except KeyboardInterrupt:
        pass
    finally:
        try:
            write_command(fd, "adcstream stop", args.char_delay_ms)
            time.sleep(0.1)
        finally:
            termios.tcsetattr(fd, termios.TCSANOW, old_attrs)
            os.close(fd)
            sys.stderr.write(
                "done: bytes=%d csv_rows=%d other_lines=%d\n"
                % (stats["bytes"], stats["csv_rows"], stats["other_lines"])
            )


if __name__ == "__main__":
    main()
