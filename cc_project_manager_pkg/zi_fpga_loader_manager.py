"""Manager for Zector Instruments ZI-0001 STM32 FPGA loader operations."""
import os
import logging
from pathlib import Path
from typing import List, Optional

from .toolchain_manager import ToolChainManager
from .zi_fpga_loader import load_bitstream, normalize_comport, VERSION


class ZiFPGALoaderManager(ToolChainManager):
    """Program GateMate FPGAs on ZI-0001 boards via the bundled serial FPGA loader."""

    def __init__(self, board_identifier: Optional[str] = None):
        super().__init__()

        self.loader_logger = logging.getLogger("ZiFPGALoaderManager")
        self.loader_logger.setLevel(logging.DEBUG)
        self.loader_logger.propagate = False

        for handler in self.loader_logger.handlers[:]:
            self.loader_logger.removeHandler(handler)

        log_path = os.path.normpath(
            os.path.join(self.config["project_structure"]["logs"][0], "zi_fpga_loader.log")
        )
        file_handler = logging.FileHandler(log_path)
        formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
        file_handler.setFormatter(formatter)
        self.loader_logger.addHandler(file_handler)

        self.board_identifier = board_identifier
        self.board_config = self._load_board_config()
        self.last_error: Optional[str] = None

        self.impl_dir = self.config["project_structure"]["impl"]
        self.bitstream_dir = self.impl_dir["bitstream"][0]
        os.makedirs(self.bitstream_dir, exist_ok=True)

        self.loader_logger.info(
            f"ZiFPGALoaderManager initialized for board: {board_identifier or 'none'}"
        )

    def _load_board_config(self) -> dict:
        try:
            from .boards_manager import BoardsManager

            if not self.board_identifier:
                return {}
            boards_manager = BoardsManager()
            return boards_manager.get_board_details(self.board_identifier) or {}
        except Exception as e:
            self.loader_logger.debug(f"Could not load board config: {e}")
            return {}

    def get_programming_tool_name(self) -> str:
        return "ZI FPGA Loader"

    def get_com_port(self) -> str:
        return self.board_config.get("com_port", "COM6")

    def get_chunk_size(self) -> int:
        return int(self.board_config.get("chunk_size", 64))

    def get_serial_timeout(self) -> float:
        return float(self.board_config.get("serial_timeout", 3.0))

    def _log_loader_message(self, message: str, level: int = logging.INFO) -> None:
        """Log to file and GUI output (root logger)."""
        self.loader_logger.log(level, message)
        logging.getLogger().log(level, message)
        for handler in self.loader_logger.handlers:
            handler.flush()

    def is_available(self) -> bool:
        try:
            import serial  # noqa: F401
            return True
        except ImportError:
            return False

    def detect_devices(self) -> bool:
        """Test whether the configured COM port is accessible."""
        if not self.is_available():
            self.last_error = "pyserial is not installed"
            self.loader_logger.error(self.last_error)
            return False

        port = normalize_comport(self.get_com_port())
        self.loader_logger.info(f"Testing serial connection on {port}")

        try:
            import serial

            with serial.Serial(port, timeout=1.0) as ser:
                self.loader_logger.info(f"Serial port {port} opened successfully")
                return True
        except Exception as e:
            self.last_error = f"Could not open {port}: {e}"
            self.loader_logger.error(self.last_error)
            return False

    def list_serial_ports(self) -> List[str]:
        try:
            from serial.tools import list_ports

            return [port.device for port in list_ports.comports()]
        except Exception as e:
            self.loader_logger.error(f"Could not list serial ports: {e}")
            return []

    def _resolve_bitstream_file(
        self,
        bitstream_file: Optional[str],
        design_name: Optional[str],
    ) -> Optional[str]:
        if bitstream_file:
            return bitstream_file if os.path.exists(bitstream_file) else None

        if not design_name:
            return None

        for ext in (".bit", ".cdf"):
            candidate = os.path.join(self.bitstream_dir, f"{design_name}{ext}")
            if os.path.exists(candidate):
                return candidate
        return None

    def program_sram(
        self,
        bitstream_file: Optional[str] = None,
        design_name: Optional[str] = None,
        options: Optional[List[str]] = None,
    ) -> bool:
        """Program FPGA SRAM using the ZI-0001 STM32 serial loader."""
        del options  # Not used for serial loader

        resolved = self._resolve_bitstream_file(bitstream_file, design_name)
        if not resolved:
            self.last_error = "Bitstream file not found (.bit or .cdf)"
            self.loader_logger.error(self.last_error)
            return False

        if not resolved.lower().endswith(".bit"):
            self.last_error = (
                f"ZI FPGA Loader requires a .bit file, got: {os.path.basename(resolved)}"
            )
            self.loader_logger.error(self.last_error)
            return False

        if not self.is_available():
            self.last_error = "pyserial is not installed"
            self.loader_logger.error(self.last_error)
            return False

        port = normalize_comport(self.get_com_port())
        self._log_loader_message(
            f"Programming SRAM via ZI FPGA Loader v{VERSION}: {resolved} -> {port}"
        )

        def log_fn(message: str) -> None:
            self._log_loader_message(message)

        try:
            load_bitstream(
                port=port,
                bitstream_path=Path(resolved),
                chunk_size=self.get_chunk_size(),
                timeout=self.get_serial_timeout(),
                log_fn=log_fn,
            )
            self.last_error = None
            self._log_loader_message(f"Successfully programmed SRAM with {resolved}")
            return True
        except Exception as e:
            self.last_error = str(e)
            self._log_loader_message(f"SRAM programming failed: {e}", logging.ERROR)
            return False

    def program_flash(self, *args, **kwargs) -> bool:
        self.last_error = "Flash programming is not supported by the ZI FPGA Loader"
        self.loader_logger.error(self.last_error)
        return False

    def verify_bitstream(self, *args, **kwargs) -> bool:
        self.last_error = "Bitstream verification is not supported by the ZI FPGA Loader"
        self.loader_logger.error(self.last_error)
        return False
