"""ZI-0001 STM32 FPGA loader for Zector Instruments Logic 1.0 GateMate boards.

Uploads a GateMate .bit file to the FPGA via the on-board STM32 loader over serial.
Bundled with GateMate Project Manager; based on the standalone ZI FPGA Loader app.
"""
import argparse
import logging
import sys
import time
from pathlib import Path
from typing import Callable, Optional

import serial

VERSION = "1.0.0"

SUPPORTED_BOARDS = [
    ("ZI-0001-0001", "Logic 1"),
]


class BoardsAction(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        print("Supported boards:\n")
        for model, name in SUPPORTED_BOARDS:
            print(f"  {model:<15} {name}")
        parser.exit()


def normalize_comport(comport: str) -> str:
    comport = comport.strip().upper()
    if comport.startswith("COM"):
        return comport
    return f"COM{comport}"


def read_required_line(ser: serial.Serial, what: str) -> bytes:
    line = ser.readline()
    if not line:
        raise TimeoutError(f"Timed out waiting for {what}")
    return line


def load_bitstream(
    port: str,
    bitstream_path: Path,
    chunk_size: int = 64,
    timeout: float = 3.0,
    log_fn: Optional[Callable[[str], None]] = None,
) -> None:
    """Upload a bitstream file to the ZI-0001 FPGA loader over serial."""
    def emit(message: str) -> None:
        if log_fn:
            log_fn(message)
        else:
            print(message)

    if not bitstream_path.exists():
        raise FileNotFoundError(bitstream_path)

    data = bitstream_path.read_bytes()

    emit(f"Bitstream path: {bitstream_path}")
    emit(f"Modified: {time.ctime(bitstream_path.stat().st_mtime)}")
    emit(f"Size: {len(data)} bytes")
    emit(f"COM port: {port}")
    emit(f"Chunk size: {chunk_size}")

    with serial.Serial(port, timeout=timeout) as ser:
        time.sleep(1.0)
        ser.reset_input_buffer()
        ser.reset_output_buffer()

        cmd = f"LOAD {len(data)}\r\n".encode()
        emit(f"TX: {repr(cmd)}")

        ser.write(cmd)
        ser.flush()

        reply = read_required_line(ser, "READY")
        emit(f"RX: {repr(reply)}")

        if reply.startswith(b"ACK "):
            raise RuntimeError(
                "STM32 appears to already be in LOAD/binary mode. "
                "Wait for timeout or reset the MCU."
            )

        if reply != b"READY\r\n":
            raise RuntimeError(f"STM32 did not return READY. Got {reply!r}")

        emit("Sending bitstream...")

        sent = 0
        for i in range(0, len(data), chunk_size):
            chunk = data[i:i + chunk_size]
            ser.write(chunk)
            ser.flush()

            expected = i + len(chunk)
            ack = read_required_line(ser, f"ACK {expected}")
            expected_ack = f"ACK {expected}\r\n".encode()

            if ack != expected_ack:
                raise RuntimeError(f"Bad ACK. Expected {expected_ack!r}, got {ack!r}")

            sent += len(chunk)
            if (sent % 4096) == 0 or sent == len(data):
                percent = (sent * 100.0) / len(data)
                emit(f"Sent {sent} / {len(data)} bytes ({percent:.1f}%)")

        emit("Bitstream sent. Waiting for STM32 result...")

        while True:
            line = ser.readline()
            if not line:
                break
            emit(f"RX: {line.decode(errors='replace').rstrip()}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Upload a GateMate FPGA bitstream to the ZI-0001 STM32 FPGA loader."
    )

    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {VERSION}",
    )

    parser.add_argument(
        "bitstream",
        type=Path,
        help="Path to .bit file",
    )

    parser.add_argument(
        "--comport",
        required=True,
        help="COM port number or name, for example 6 or COM6",
    )

    parser.add_argument(
        "--chunk-size",
        type=int,
        default=64,
        help="Upload chunk size in bytes. Default: 64",
    )

    parser.add_argument(
        "--timeout",
        type=float,
        default=3.0,
        help="Serial read timeout in seconds. Default: 3.0",
    )

    parser.add_argument(
        "--boards",
        nargs=0,
        action=BoardsAction,
        help="Display the supported hardware revisions and exit.",
    )

    args = parser.parse_args()
    port = normalize_comport(args.comport)

    try:
        load_bitstream(
            port=port,
            bitstream_path=args.bitstream,
            chunk_size=args.chunk_size,
            timeout=args.timeout,
        )
    except Exception as e:
        print("ERROR:", e, file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
