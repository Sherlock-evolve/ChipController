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


def write_command(fd, command):
    os.write(fd, (command + "\r\n").encode("ascii"))


def drain(fd, timeout_sec=0.2):
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        readable, _, _ = select.select([fd], [], [], 0.02)
        if not readable:
            continue
        try:
            os.read(fd, 4096)
        except BlockingIOError:
            pass


def is_csv_line(line):
    if line == CSV_HEADER:
        return True

    fields = line.split(",")
    return len(fields) == 8 and fields[0].isdigit() and fields[1].isdigit()


def main():
    args = parse_args()
    fd = os.open(args.port, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
    old_attrs = termios.tcgetattr(fd)
    mode = "a" if args.append else "w"
    deadline = None if args.duration_sec <= 0.0 else time.monotonic() + args.duration_sec
    buffer = ""

    try:
        configure_serial(fd, args.baud)
        drain(fd)
        write_command(fd, "adcstream stop")
        time.sleep(0.1)
        drain(fd)
        write_command(fd, "adcstream start %d" % args.period_ms)

        sys.stderr.write("logging %s at %d baud to %s\n" % (args.port, args.baud, args.output))
        sys.stderr.write("press Ctrl-C to stop\n")
        sys.stderr.flush()

        output_dir = os.path.dirname(os.path.abspath(args.output))
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)

        with open(args.output, mode, encoding="ascii", newline="") as output:
            while True:
                if deadline is not None and time.monotonic() >= deadline:
                    break

                readable, _, _ = select.select([fd], [], [], 0.2)
                if not readable:
                    continue

                try:
                    chunk = os.read(fd, 4096)
                except BlockingIOError:
                    continue

                text = chunk.decode("ascii", errors="ignore")
                for char in text:
                    if char in "\r\n":
                        line = buffer.strip()
                        buffer = ""
                        if is_csv_line(line):
                            output.write(line + "\n")
                            output.flush()
                    else:
                        buffer += char
    except KeyboardInterrupt:
        pass
    finally:
        try:
            write_command(fd, "adcstream stop")
            time.sleep(0.1)
        finally:
            termios.tcsetattr(fd, termios.TCSANOW, old_attrs)
            os.close(fd)


if __name__ == "__main__":
    main()
