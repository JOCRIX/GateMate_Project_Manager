"""OSS CAD Suite GateMate place-and-route and bitstream packing.

Replaces the legacy Cologne Chip proprietary ``p_r`` flow with:

1. ``nextpnr-himbaechel`` for place-and-route (JSON + CCF -> ``*_impl.txt``)
2. ``gmpack`` for bitstream packing (``*_impl.txt`` -> ``.bit``)

Typical command sequence::

    nextpnr-himbaechel --device=CCGM1A1 --json <design>_synth.json \\
        -o ccf=<constraints>.ccf -o out=<design>_impl.txt \\
        --router router2 -o fpga_mode=speed -o time_mode=worst

    gmpack <design>_impl.txt <design>.bit
"""
import json
import os
import queue
import re
import shutil
import threading
import time
import yaml
import logging
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed, CancelledError
from types import SimpleNamespace
from typing import Any, List, Optional, Dict, Tuple, Callable

from .toolchain_manager import ToolChainManager


# Fallback command names when no configured path is available (resolved via PATH).
_FALLBACK_NEXTPNR = "nextpnr-himbaechel"
_FALLBACK_GMPACK = "gmpack"

# Opinionated defaults for GateMate nextpnr-himbaechel (Cologne Chip guidance).
DEFAULT_PNR_SETTINGS: Dict[str, Any] = {
    "preset": "Development",
    "device": "CCGM1A1",
    "fpga_mode": "speed",
    "time_mode": "worst",
    "sdc_path": "",
    "fallback_frequency_mhz": 100.0,
    "use_fallback_frequency": True,
    "allow_timing_failure": False,
    "placer": "heap",
    "seed_mode": "fixed",  # fixed | multi
    "fixed_seed": 1,
    "iterations": 20,
    "first_seed": 1,
    "parallel_jobs": 1,
    "selection": "best_worst_slack",  # best_worst_slack | best_fmax | lowest_wirelength
    "stop_when_timing_met": False,
    "router": "router2",
    "generate_report": True,
    "keep_log": True,
    "generate_sdf": False,
    "generate_placed_svg": False,
    "generate_routed_svg": False,
    "open_gui": False,
    "clock_strategy": "auto",  # auto | mirror | full | clk1
    "no_cpe_cp": False,
    "no_bridges": False,
    "force_die": False,
    "heap_alpha": "",
    "heap_beta": "",
    "heap_critexp": "",
    "heap_timingweight": "",
    "timing_driven_ripup": False,
    "router2_alt_weights": False,
    "detailed_timing_report": False,
    "verbose": False,
    "debug": False,
    "generate_bitstream": True,
    "run_timing_analysis": False,
    "generate_sim_netlist": False,
}


class NextPnRCommands(ToolChainManager):
    """Place-and-route and bitstream generation via nextpnr-himbaechel and gmpack.

    This manager mirrors the structure of the legacy ``PnRCommands`` class but
    invokes the OSS CAD Suite GateMate tools exclusively. It never calls the
    proprietary ``p_r`` binary.
    """

    # nextpnr Himbaechel options keyed by high-level strategy name
    IMPLEMENTATION_STRATEGIES = {
        "speed": {
            "fpga_mode": "speed",
            "time_mode": "worst",
            "router": "router2",
        },
        "area": {
            "fpga_mode": "economy",
            "time_mode": "worst",
            "router": "router2",
        },
        "balanced": {
            "fpga_mode": "speed",
            "time_mode": "worst",
            "router": "router2",
        },
    }

    # Kept for GUI status scanning (legacy PnRCommands compatibility).
    # nextpnr/gmpack primarily produce ``*_impl.txt`` + ``.bit``; optional
    # post-impl netlists may appear under these extensions when exported.
    NETLIST_FORMATS = {
        "vhdl": ".vhd",
        "verilog": ".v",
        "json": ".json",
        "blif": ".blif",
    }

    def __init__(self, strategy: str = "balanced", device: str = "CCGM1A1"):
        """
        Initialize nextpnr / gmpack command helpers for a GateMate project.

        Args:
            strategy: Implementation strategy ("balanced", "speed", "area").
            device: Target GateMate device string (default ``CCGM1A1``).
        """
        super().__init__()

        self.nextpnr_logger = logging.getLogger("NextPnRCommands")
        self.nextpnr_logger.setLevel(logging.DEBUG)
        self.nextpnr_logger.propagate = False
        self._nextpnr_bound_log_path = None

        expected_log = os.path.normpath(
            os.path.join(self.config["project_structure"]["logs"][0], "nextpnr_commands.log")
        )
        handlers_outdated = False
        for handler in self.nextpnr_logger.handlers:
            base = getattr(handler, "baseFilename", None)
            if base and os.path.normpath(base) != expected_log:
                handlers_outdated = True
                break

        if not self.nextpnr_logger.handlers or handlers_outdated:
            for handler in self.nextpnr_logger.handlers[:]:
                try:
                    handler.close()
                except Exception:
                    pass
                self.nextpnr_logger.removeHandler(handler)

            file_handler = logging.FileHandler(expected_log)
            formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
            file_handler.setFormatter(formatter)
            self.nextpnr_logger.addHandler(file_handler)
            self._nextpnr_bound_log_path = expected_log
            self._add_nextpnr_log()

        if strategy not in self.IMPLEMENTATION_STRATEGIES:
            self.nextpnr_logger.warning(
                f'Unknown implementation strategy "{strategy}", defaulting to balanced'
            )
            self.strategy = "balanced"
        else:
            self.strategy = strategy

        self.device = device or "CCGM1A1"

        # Project directories
        if isinstance(self.config["project_structure"]["build"], list) and self.config["project_structure"]["build"]:
            self.work_dir = self.config["project_structure"]["build"][0]
        else:
            self.work_dir = self.config["project_structure"]["build"]

        if isinstance(self.config["project_structure"]["synth"], list) and self.config["project_structure"]["synth"]:
            self.synth_dir = self.config["project_structure"]["synth"][0]
        else:
            self.synth_dir = self.config["project_structure"]["synth"]

        self.impl_dir = self.config["project_structure"]["impl"]
        self.bitstream_dir = self.impl_dir["bitstream"][0]
        self.netlist_dir = self.impl_dir["netlist"][0]
        self.timing_dir = self.impl_dir["timing"][0]
        self.impl_logs_dir = self.impl_dir["logs"][0]

        os.makedirs(self.work_dir, exist_ok=True)
        os.makedirs(self.bitstream_dir, exist_ok=True)
        os.makedirs(self.netlist_dir, exist_ok=True)
        os.makedirs(self.timing_dir, exist_ok=True)
        os.makedirs(self.impl_logs_dir, exist_ok=True)

        if isinstance(self.config["project_structure"]["constraints"], list) and self.config["project_structure"]["constraints"]:
            self.constraints_dir = self.config["project_structure"]["constraints"][0]
        else:
            self.constraints_dir = self.config["project_structure"]["constraints"]
        os.makedirs(self.constraints_dir, exist_ok=True)

        self.nextpnr_cmd = self._resolve_tool_command("nextpnr_himbaechel", _FALLBACK_NEXTPNR)
        self.gmpack_cmd = self._resolve_tool_command("gmpack", _FALLBACK_GMPACK)

        self.last_error: Optional[str] = None
        self.last_return_code: Optional[int] = None
        self.last_command: Optional[List[str]] = None
        self.last_seed_results: List[Dict[str, Any]] = []
        # Seed whose implementation was promoted to ``{design}_impl.txt`` / .bit
        self.last_bitstream_seed: Optional[int] = None
        self.progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None
        self._state_lock = threading.Lock()

        self._report_instantiation()

    # Compatibility alias used by older GUI helpers
    @property
    def pnr_logger(self):
        return self.nextpnr_logger

    def set_progress_callback(self, callback: Optional[Callable[[Dict[str, Any]], None]]) -> None:
        """Optional callback for multi-seed / live P&R progress events (GUI)."""
        self.progress_callback = callback

    def _notify_progress(self, info: Dict[str, Any]) -> None:
        cb = self.progress_callback
        if not cb:
            return
        try:
            cb(info)
        except Exception as e:
            self.nextpnr_logger.debug(f"progress_callback failed: {e}")

    def get_default_pnr_settings(self) -> Dict[str, Any]:
        """Return a fresh copy of recommended GateMate P&R defaults."""
        settings = dict(DEFAULT_PNR_SETTINGS)
        settings["device"] = self.device or settings["device"]
        return settings

    def load_pnr_settings(self) -> Dict[str, Any]:
        """Load persisted per-project P&R settings, merged over defaults."""
        settings = self.get_default_pnr_settings()
        stored = self.config.get("nextpnr_place_and_route_settings") or {}
        if isinstance(stored, dict):
            settings.update(stored)
        return settings

    def save_pnr_settings(self, settings: Dict[str, Any]) -> bool:
        """Persist P&R settings into the project configuration."""
        try:
            to_store = dict(settings or {})
            # Do not persist ephemeral design/constraint selection here
            for key in ("design_name", "constraint_file", "strategy"):
                to_store.pop(key, None)
            self.config["nextpnr_place_and_route_settings"] = to_store
            config_path = self._find_config_path()
            with open(config_path, "w") as config_file:
                yaml.safe_dump(self.config, config_file)
            return True
        except Exception as e:
            self.nextpnr_logger.error(f"Failed to save P&R settings: {e}")
            return False

    def merge_pnr_settings(self, overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Merge defaults, persisted settings, and call-site overrides."""
        settings = self.load_pnr_settings()
        if overrides:
            settings.update(overrides)
        return settings

    def _resolve_tool_command(self, tool_name: str, fallback_cmd: str) -> str:
        """Resolve a tool via get_tool_command, config, or a PATH command name."""
        cmd = ""
        try:
            cmd = self.get_tool_command(tool_name) or ""
        except Exception as e:
            self.nextpnr_logger.debug(f"get_tool_command({tool_name}) failed: {e}")

        if cmd:
            # Absolute configured path that exists, or a PATH-style command name
            if os.path.isabs(cmd):
                if os.path.exists(cmd):
                    return cmd
                self.nextpnr_logger.warning(
                    f"{tool_name} path from get_tool_command does not exist: {cmd}"
                )
            else:
                return cmd

        tool_paths = self.config.get("cologne_chip_gatemate_toolchain_paths", {})
        configured = tool_paths.get(tool_name, "")
        if configured and os.path.exists(configured):
            return configured

        self.nextpnr_logger.info(
            f"Using PATH command for {tool_name}: {fallback_cmd}"
        )
        return fallback_cmd

    def _report_instantiation(self) -> None:
        """Log the current NextPnRCommands configuration settings."""
        settings = f"""
        New NextPnRCommands Instantiation Settings:
        IMPLEMENTATION_STRATEGY: {self.strategy}
        DEVICE:                  {self.device}
        WORK_DIRECTORY:          {self.work_dir}
        SYNTH_DIRECTORY:         {self.synth_dir}
        BITSTREAM_DIRECTORY:     {self.bitstream_dir}
        NETLIST_DIRECTORY:       {self.netlist_dir}
        TIMING_DIRECTORY:        {self.timing_dir}
        IMPL_LOGS_DIRECTORY:     {self.impl_logs_dir}
        CONSTRAINTS_DIRECTORY:   {self.constraints_dir}
        NEXTPNR_COMMAND:         {self.nextpnr_cmd}
        GMPACK_COMMAND:          {self.gmpack_cmd}
        """
        self.nextpnr_logger.info(settings)

    def _add_nextpnr_log(self) -> None:
        """Register nextpnr_commands.log under logs.nextpnr_commands in project config."""
        log_path = os.path.normpath(
            os.path.join(self.config["project_structure"]["logs"][0], "nextpnr_commands.log")
        )

        if "logs" not in self.config:
            self.config["logs"] = {}

        if "nextpnr_commands" not in self.config["logs"]:
            self.config["logs"]["nextpnr_commands"] = {}

        if "nextpnr_commands.log" not in self.config["logs"]["nextpnr_commands"]:
            self.config["logs"]["nextpnr_commands"]["nextpnr_commands.log"] = log_path
            self.nextpnr_logger.info(
                f"NextPnR log file path added to project configuration: {log_path}"
            )
            try:
                config_path = self._find_config_path()
                with open(config_path, "w") as config_file:
                    yaml.safe_dump(self.config, config_file)
                self.nextpnr_logger.info(
                    "Project configuration updated with NextPnR log path"
                )
            except Exception as e:
                self.nextpnr_logger.error(
                    f"Failed to update project configuration with NextPnR log path: {e}"
                )

    @staticmethod
    def _ensure_ascii_path(path: str) -> str:
        """Normalize a path and require ASCII-only characters for tool compatibility."""
        normalized = os.path.normpath(path)
        try:
            normalized.encode("ascii")
        except UnicodeEncodeError as exc:
            raise ValueError(
                f"Path contains non-ASCII characters which are not supported by "
                f"nextpnr/gmpack on this flow: {normalized}"
            ) from exc
        return normalized

    # ------------------------------------------------------------------
    # Constraint helpers (adapted from PnRCommands; no template generation)
    # ------------------------------------------------------------------

    def get_default_constraint_file_path(self) -> str:
        """Return the default ``<project_name>.ccf`` path in the constraints directory."""
        project_name = self.config.get("project_name", "project")
        return os.path.join(self.constraints_dir, f"{project_name}.ccf")

    def list_available_constraint_files(self) -> List[str]:
        """List ``.ccf`` files in the constraints directory."""
        try:
            if not os.path.exists(self.constraints_dir):
                return []
            ccf_files = [f for f in os.listdir(self.constraints_dir) if f.endswith(".ccf")]
            return sorted(ccf_files)
        except Exception as e:
            self.nextpnr_logger.error(f"Error listing constraint files: {e}")
            return []

    def get_constraint_file_path(self, constraint_file_name: str) -> str:
        """Resolve a constraint file name to a full path under constraints_dir."""
        if not constraint_file_name.endswith(".ccf"):
            constraint_file_name += ".ccf"
        return os.path.join(self.constraints_dir, constraint_file_name)

    def has_active_constraints(self, constraint_file_path: str) -> bool:
        """Return True if the CCF has uncommented pin / Loc assignments."""
        try:
            if not os.path.exists(constraint_file_path):
                return False

            with open(constraint_file_path, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "#" in line:
                        line = line.split("#", 1)[0].strip()
                        if not line:
                            continue
                    line_lower = line.lower()
                    if (
                        line_lower.startswith("net ")
                        or line_lower.startswith("pin_in ")
                        or line_lower.startswith("pin_out ")
                        or line_lower.startswith("pin_triout ")
                        or line_lower.startswith("pin_inout ")
                        or " loc = " in line_lower
                    ):
                        return True
            return False
        except Exception as e:
            self.nextpnr_logger.debug(f"Error checking constraint file {constraint_file_path}: {e}")
            return False

    def resolve_constraint_file(
        self,
        constraint_file: Optional[str] = None,
        design_name: Optional[str] = None,
    ) -> Tuple[Optional[str], str, bool]:
        """
        Resolve which constraint file to use for place-and-route.

        Priority when no explicit file is provided:
        1. Design-specific ``{design_name}.ccf`` with active pin assignments
        2. Default project constraint file with active pin assignments
        3. First available constraint file with active pin assignments
        4. Design-specific / first available file even if template-only

        Returns:
            ``(file_path or None, selection_reason, is_template_only)``
        """
        if constraint_file:
            if os.path.exists(constraint_file):
                is_template = not self.has_active_constraints(constraint_file)
                return (
                    constraint_file,
                    f"specified constraint file ({os.path.basename(constraint_file)})",
                    is_template,
                )
            return None, f"specified constraint file not found ({constraint_file})", False

        default_constraint_file = self.get_default_constraint_file_path()
        available_constraints = self.list_available_constraint_files()

        design_constraint_file = None
        if design_name:
            design_constraint_file = self.get_constraint_file_path(design_name)

        if (
            design_constraint_file
            and os.path.exists(design_constraint_file)
            and self.has_active_constraints(design_constraint_file)
        ):
            return (
                design_constraint_file,
                f"design-specific constraint file with active pin assignments ({design_name}.ccf)",
                False,
            )

        if os.path.exists(default_constraint_file) and self.has_active_constraints(default_constraint_file):
            return (
                default_constraint_file,
                f"default constraint file with active pin assignments ({os.path.basename(default_constraint_file)})",
                False,
            )

        for constraint_name in available_constraints:
            constraint_path = self.get_constraint_file_path(constraint_name)
            if os.path.exists(constraint_path) and self.has_active_constraints(constraint_path):
                return (
                    constraint_path,
                    f"first available constraint file with active pin assignments ({constraint_name})",
                    False,
                )

        if design_constraint_file and os.path.exists(design_constraint_file):
            return (
                design_constraint_file,
                f"design-specific constraint file (template only - {design_name}.ccf)",
                True,
            )

        if available_constraints:
            constraint_path = self.get_constraint_file_path(available_constraints[0])
            return (
                constraint_path,
                f"first available constraint file (template only - {available_constraints[0]})",
                True,
            )

        return None, "no constraint files found", False

    def validate_constraint_file_for_pnr(
        self,
        constraint_file: Optional[str] = None,
        design_name: Optional[str] = None,
    ) -> Tuple[bool, Optional[str]]:
        """
        Validate that a usable, non-empty constraint file is available for nextpnr.

        Args:
            constraint_file: Selected name/path, ``\"default\"``, ``\"none\"``, or None
            design_name: Design name for design-specific ``.ccf`` preference

        Returns:
            ``(is_valid, error_message or None)``
        """
        try:
            if constraint_file == "none":
                return False, (
                    "❌ CONSTRAINT FILE REQUIRED\n\n"
                    "nextpnr-himbaechel place-and-route requires a .ccf constraint file "
                    "with active pin assignments.\n"
                    "Select or create a constraint file before continuing."
                )

            constraint_file_path = None
            constraint_source = ""

            if constraint_file and constraint_file not in ("default", "none"):
                if os.path.isabs(constraint_file):
                    constraint_file_path = constraint_file
                else:
                    constraint_file_path = os.path.join(self.constraints_dir, constraint_file)
                constraint_source = (
                    f"selected constraint file: {os.path.basename(constraint_file_path)}"
                )
            else:
                if design_name:
                    design_constraint_file = self.get_constraint_file_path(design_name)
                    if os.path.exists(design_constraint_file):
                        if not self.has_active_constraints(design_constraint_file):
                            error_msg = (
                                f"❌ CONSTRAINT FILE IS EMPTY OR ALL COMMENTED OUT\n\n"
                                f"The design-specific constraint file {design_name}.ccf exists but "
                                f"contains no active pin assignments:\n"
                                f"File: {design_constraint_file}\n\n"
                                f"Place and Route for '{design_name}' requires active pin constraints "
                                f"in {design_name}.ccf.\n\n"
                                f"SOLUTIONS:\n"
                                f"1. Edit {design_name}.ccf and add pin assignments for this design\n"
                                f"2. Uncomment existing pin assignments in the file\n"
                                f"3. Select a different constraint file from the dropdown"
                            )
                            return False, error_msg

                constraint_file_path, constraint_source, is_template = self.resolve_constraint_file(
                    design_name=design_name
                )
                if constraint_file_path and is_template:
                    constraint_source = constraint_source.replace(" (template only", "")

            if not constraint_file_path:
                return False, (
                    "❌ CONSTRAINT FILE REQUIRED\n\n"
                    "No constraint file was found for nextpnr-himbaechel place-and-route.\n"
                    "Create or select a .ccf file with active pin assignments "
                    f"in:\n{self.constraints_dir}"
                )

            if not os.path.exists(constraint_file_path):
                error_msg = (
                    f"❌ CONSTRAINT FILE NOT FOUND\n\n"
                    f"The {constraint_source} was not found:\n"
                    f"Expected: {constraint_file_path}\n\n"
                    f"SOLUTIONS:\n"
                    f"1. Check that the constraint file exists\n"
                    f"2. Create a constraint file with pin assignments\n"
                    f"3. Select a different constraint file"
                )
                return False, error_msg

            if not self.has_active_constraints(constraint_file_path):
                error_msg = (
                    f"❌ CONSTRAINT FILE IS EMPTY OR ALL COMMENTED OUT\n\n"
                    f"The {constraint_source} exists but contains no active pin assignments:\n"
                    f"File: {constraint_file_path}\n\n"
                    f"nextpnr-himbaechel requires active pin constraints to succeed.\n"
                    f"The file either:\n"
                    f"• Contains only comments (lines starting with #)\n"
                    f"• Contains only empty lines\n"
                    f"• Has no Net, Pin_in, Pin_out, Pin_triout, or Pin_inout assignments\n\n"
                    f"SOLUTIONS:\n"
                    f"1. Edit the constraint file and add pin assignments\n"
                    f"2. Uncomment existing pin assignments in the file\n"
                    f"3. Select a different constraint file with active constraints"
                )
                return False, error_msg

            return True, None

        except Exception as e:
            self.nextpnr_logger.error(f"Error validating constraint file: {e}")
            return False, f"Constraint validation error: {e}"

    def _emit_live(self, message: str, level: int = logging.INFO) -> None:
        """Log to the nextpnr file logger and the root logger (GUI output window)."""
        text = (message or "").rstrip()
        if not text:
            return
        self.nextpnr_logger.log(level, text)
        # nextpnr_logger has propagate=False; root logger feeds the GUI LogHandler
        logging.log(level, text)

    @staticmethod
    def _classify_tool_line(line: str) -> int:
        """Map a nextpnr/gmpack console line to a logging level.

        Prefer nextpnr's own severity prefixes (``Info:`` / ``Warning:`` / ``ERROR:``).
        Do **not** treat substrings like ``fout error 0.000%`` as ERROR.
        """
        # Strip optional live-stream prefixes such as "[seed 2] "
        stripped = re.sub(r"^\[(?:seed\s+\d+|gmpack)\]\s*", "", (line or "").strip(), flags=re.IGNORECASE)
        if not stripped:
            return logging.INFO

        # nextpnr / general tool prefixes (case-insensitive)
        m = re.match(r"^(INFO|WARNING|WARN|ERROR|FATAL|CRITICAL)\s*:\s*", stripped, re.IGNORECASE)
        if m:
            tag = m.group(1).upper()
            if tag in ("ERROR", "FATAL", "CRITICAL"):
                return logging.ERROR
            if tag in ("WARNING", "WARN"):
                return logging.WARNING
            return logging.INFO

        upper = stripped.upper()
        # Explicit severity words only when they are not measurement jargon
        if re.search(r"\bFATAL\b", upper):
            return logging.ERROR
        # "fout error 0.12%" / "frequency error" are informational PLL messages
        if re.search(r"\bFOUT\s+ERROR\b", upper) or re.search(r"\bERROR\s+[\d.]+%", upper):
            return logging.INFO
        if re.search(r"(^|\s)ERROR(\s|:|$)", upper) and "FOUT" not in upper:
            return logging.ERROR
        if re.search(r"(^|\s)WARNING(\s|:|$)", upper):
            return logging.WARNING
        return logging.INFO

    def seed_svg_paths(self, design_name: str, seed: int) -> Dict[str, str]:
        """Return expected placed/routed SVG paths for a seed."""
        seed_tag = f"{int(seed):03d}"
        return {
            "placed": os.path.join(
                self.timing_dir, f"{design_name}_seed_{seed_tag}_placed.svg"
            ),
            "routed": os.path.join(
                self.timing_dir, f"{design_name}_seed_{seed_tag}_routed.svg"
            ),
        }

    def cleanup_seed_artifacts(self, design_name: str) -> int:
        """Remove previous multi-seed SVGs/reports/impls for ``design_name``.

        Avoids showing stale placement/routing previews from an earlier run.
        Returns the number of files removed.
        """
        removed = 0
        patterns = [
            (self.timing_dir, f"{design_name}_seed_*_placed.svg"),
            (self.timing_dir, f"{design_name}_seed_*_routed.svg"),
            (self.timing_dir, f"{design_name}_report_seed_*.json"),
            (self.timing_dir, f"{design_name}_seed_*.sdf"),
            (self.work_dir, f"{design_name}_impl_seed_*.txt"),
        ]
        import glob as _glob

        for directory, pattern in patterns:
            if not directory or not os.path.isdir(directory):
                continue
            for path in _glob.glob(os.path.join(directory, pattern)):
                try:
                    os.remove(path)
                    removed += 1
                    self.nextpnr_logger.info(f"Removed previous seed artifact: {path}")
                except Exception as e:
                    self.nextpnr_logger.debug(f"Could not remove {path}: {e}")
        return removed

    def _run_tool_streaming(
        self,
        cmd: List[str],
        *,
        tool_label: str,
        timeout: int = 600,
        line_prefix: str = "",
    ) -> SimpleNamespace:
        """Run a tool and stream stdout/stderr line-by-line to the GUI/log.

        Returns a SimpleNamespace with ``returncode``, ``stdout``, ``stderr``
        compatible with ``_format_tool_error``.
        """
        self._emit_live(f"▶ {tool_label}: {' '.join(cmd)}")

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=self.get_tool_run_env(),
        )

        output_queue: queue.Queue = queue.Queue()
        all_output: List[str] = []

        def _reader() -> None:
            try:
                assert process.stdout is not None
                for line in iter(process.stdout.readline, ""):
                    if line:
                        output_queue.put(line.rstrip("\r\n"))
                process.stdout.close()
            except Exception as e:
                output_queue.put(f"[{tool_label} reader error: {e}]")
            finally:
                output_queue.put(None)

        reader = threading.Thread(target=_reader, daemon=True)
        reader.start()

        start = time.time()
        timed_out = False
        reader_done = False

        while not reader_done:
            try:
                line = output_queue.get(timeout=0.25)
            except queue.Empty:
                if timeout and (time.time() - start) > timeout:
                    timed_out = True
                    try:
                        process.kill()
                    except Exception:
                        pass
                    self._emit_live(
                        f"{tool_label} timed out after {timeout}s — killing process",
                        logging.ERROR,
                    )
                    break
                continue

            if line is None:
                reader_done = True
                break

            all_output.append(line)
            prefix = f"{line_prefix} " if line_prefix else ""
            level = self._classify_tool_line(line)
            self._emit_live(f"{prefix}{line}", level)

            if timeout and (time.time() - start) > timeout:
                timed_out = True
                try:
                    process.kill()
                except Exception:
                    pass
                self._emit_live(
                    f"{tool_label} timed out after {timeout}s — killing process",
                    logging.ERROR,
                )
                break

        reader.join(timeout=5)
        try:
            returncode = process.wait(timeout=5)
        except Exception:
            returncode = process.returncode if process.returncode is not None else -1

        if timed_out:
            raise subprocess.TimeoutExpired(cmd, timeout, output="\n".join(all_output))

        combined = "\n".join(all_output)
        self._emit_live(f"■ {tool_label} finished (exit {returncode})")
        return SimpleNamespace(returncode=returncode, stdout=combined, stderr="")

    def _format_tool_error(self, result: Any, tool_label: str) -> str:
        """Build a concise error summary from captured tool output."""
        parts = []
        for text in (getattr(result, "stdout", None), getattr(result, "stderr", None)):
            if text and text.strip():
                parts.append(text.strip())
        combined = "\n".join(parts).strip()
        if not combined:
            return f"{tool_label} exited with code {result.returncode} (no output captured)."

        interesting = []
        for line in combined.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            upper = stripped.upper()
            if (
                "ERROR" in upper
                or "FATAL" in upper
                or "FAIL" in upper
                or stripped.startswith("WARNING")
                or "does not match" in stripped.lower()
            ):
                if stripped not in interesting:
                    interesting.append(stripped)

        if interesting:
            interesting.append(f"Exit code: {result.returncode}")
            return "\n".join(interesting)

        non_empty = [line.strip() for line in combined.splitlines() if line.strip()]
        fallback = non_empty[-5:] if len(non_empty) > 5 else non_empty
        fallback.append(f"Exit code: {result.returncode}")
        return "\n".join(fallback)

    def build_user_failure_message(
        self,
        design_name: str,
        operation: str = "Place and route",
        constraint_file: Optional[str] = None,
    ) -> str:
        """Build a concise error message suitable for the GUI output window."""
        lines = [f"❌ {operation} failed for {design_name}"]

        if self.last_error:
            lines.append("")
            lines.append(self.last_error)
        elif constraint_file:
            lines.append(f"Constraint file: {os.path.basename(constraint_file)}")

        lines.append("")
        lines.append("See View Implementation Logs for full details.")
        return "\n".join(lines)

    def get_last_error(self) -> Optional[str]:
        """Return the most recent nextpnr/gmpack error details, if any."""
        return self.last_error

    # ------------------------------------------------------------------
    # Core flow
    # ------------------------------------------------------------------

    def build_nextpnr_command(
        self,
        *,
        design_name: str,
        netlist_file: str,
        constraint_file: str,
        output_file: str,
        settings: Dict[str, Any],
        seed: Optional[int] = None,
        report_file: Optional[str] = None,
    ) -> List[str]:
        """Build the nextpnr-himbaechel argv list for the given settings."""
        device = settings.get("device") or self.device or "CCGM1A1"
        placer = (settings.get("placer") or "heap").lower()
        router = (settings.get("router") or "router2").lower()
        fpga_mode = (settings.get("fpga_mode") or "speed").lower()
        time_mode = (settings.get("time_mode") or "worst").lower()

        if seed is None:
            seed = int(settings.get("fixed_seed", 1) or 1)

        cmd = [
            self.nextpnr_cmd,
            f"--device={device}",
            "--json",
            netlist_file,
            "-o",
            f"ccf={constraint_file}",
            "-o",
            f"out={output_file}",
            "--placer",
            placer,
            "--router",
            router,
            "--seed",
            str(seed),
            "-o",
            f"fpga_mode={fpga_mode}",
            "-o",
            f"time_mode={time_mode}",
        ]

        sdc_path = (settings.get("sdc_path") or "").strip()
        if sdc_path and os.path.exists(sdc_path):
            cmd.extend(["--sdc", sdc_path])
        elif settings.get("use_fallback_frequency", True):
            try:
                freq = float(settings.get("fallback_frequency_mhz", 0) or 0)
            except (TypeError, ValueError):
                freq = 0.0
            if freq > 0:
                cmd.extend(["--freq", str(freq)])

        if settings.get("allow_timing_failure"):
            cmd.append("--timing-allow-fail")

        if settings.get("generate_report", True):
            if not report_file:
                report_file = os.path.join(self.timing_dir, f"{design_name}_report.json")
            cmd.extend(["--report", report_file])

        if settings.get("generate_sdf"):
            cmd.extend(["--sdf", os.path.join(self.timing_dir, f"{design_name}_seed_{int(seed):03d}.sdf")])
        if settings.get("generate_placed_svg"):
            cmd.extend([
                "--placed-svg",
                os.path.join(self.timing_dir, f"{design_name}_seed_{int(seed):03d}_placed.svg"),
            ])
        if settings.get("generate_routed_svg"):
            cmd.extend([
                "--routed-svg",
                os.path.join(self.timing_dir, f"{design_name}_seed_{int(seed):03d}_routed.svg"),
            ])
        if settings.get("open_gui"):
            cmd.append("--gui")

        strategy = (settings.get("clock_strategy") or "auto").lower()
        if strategy and strategy != "auto":
            cmd.extend(["-o", f"strategy={strategy}"])
        if settings.get("no_cpe_cp"):
            cmd.extend(["-o", "no-cpe-cp=true"])
        if settings.get("no_bridges"):
            cmd.extend(["-o", "no-bridges=true"])
        if settings.get("force_die") and str(device).upper() == "CCGM1A2":
            cmd.extend(["-o", "force_die=true"])

        for opt_name, key in (
            ("--placer-heap-alpha", "heap_alpha"),
            ("--placer-heap-beta", "heap_beta"),
            ("--placer-heap-critexp", "heap_critexp"),
            ("--placer-heap-timingweight", "heap_timingweight"),
        ):
            val = settings.get(key)
            if val not in (None, "", "default"):
                cmd.extend([opt_name, str(val)])

        if settings.get("timing_driven_ripup"):
            cmd.append("--tmg-ripup")
        if settings.get("router2_alt_weights"):
            cmd.append("--router2-alt-weights")
        if settings.get("detailed_timing_report"):
            cmd.append("--detailed-timing-report")
        if settings.get("verbose"):
            cmd.append("--verbose")
        if settings.get("debug"):
            cmd.append("--debug")

        return cmd

    def format_command_preview(self, cmd: List[str]) -> str:
        """Pretty-print a command for GUI / PowerShell copy-paste."""
        if not cmd:
            return ""
        # Quote paths that contain spaces
        parts = []
        for part in cmd:
            if " " in part and not (part.startswith('"') and part.endswith('"')):
                parts.append(f'"{part}"')
            else:
                parts.append(part)
        return " ".join(parts)

    @staticmethod
    def parse_report_metrics(report_path: str) -> Dict[str, Any]:
        """Parse nextpnr ``--report`` JSON into timing / utilization metrics.

        Handles common shapes (nested ``fmax`` maps, slack / WNS fields, util).
        Missing fields remain None.
        """
        metrics: Dict[str, Any] = {
            "worst_slack": None,
            "fmax": None,
            "fmax_by_clock": {},
            "wirelength": None,
            "utilization": {},
            "summary_lines": [],
            "raw": None,
        }
        if not report_path or not os.path.exists(report_path):
            return metrics

        try:
            with open(report_path, "r", encoding="utf-8", errors="replace") as f:
                data = json.load(f)
        except Exception:
            return metrics

        metrics["raw"] = data
        summary: List[str] = []

        # --- fmax ---
        fmax_section = data.get("fmax")
        fmax_by_clock: Dict[str, float] = {}
        if isinstance(fmax_section, dict):
            for clk, info in fmax_section.items():
                if isinstance(info, dict):
                    val = info.get("achieved", info.get("fmax", info.get("actual")))
                    if isinstance(val, (int, float)):
                        fmax_by_clock[str(clk)] = float(val)
                        constraint = info.get("constraint", info.get("target"))
                        if isinstance(constraint, (int, float)):
                            summary.append(
                                f"Fmax[{clk}]={float(val):.3f} MHz (constraint {float(constraint):.3f})"
                            )
                        else:
                            summary.append(f"Fmax[{clk}]={float(val):.3f} MHz")
                elif isinstance(info, (int, float)):
                    fmax_by_clock[str(clk)] = float(info)
                    summary.append(f"Fmax[{clk}]={float(info):.3f} MHz")
        elif isinstance(fmax_section, (int, float)):
            fmax_by_clock["design"] = float(fmax_section)

        metrics["fmax_by_clock"] = fmax_by_clock
        if fmax_by_clock:
            # Limiting (worst) clock domain Fmax
            metrics["fmax"] = min(fmax_by_clock.values())

        # --- walk for slack / wirelength fallbacks ---
        def _walk(obj, path=""):
            found = []
            if isinstance(obj, dict):
                for k, v in obj.items():
                    key = str(k).lower()
                    found.extend(_walk(v, f"{path}.{key}" if path else key))
                    if isinstance(v, (int, float)):
                        found.append((key, float(v), path))
            elif isinstance(obj, list):
                for i, item in enumerate(obj):
                    found.extend(_walk(item, f"{path}[{i}]"))
            return found

        leaves = _walk(data)

        def _pick(predicates):
            for key, value, path in leaves:
                for pred in predicates:
                    if pred(key, path):
                        return value
            return None

        if metrics["worst_slack"] is None:
            metrics["worst_slack"] = _pick(
                [
                    lambda k, p: "worst" in k and "slack" in k,
                    lambda k, p: k in ("wns", "worst_negative_slack"),
                    lambda k, p: k == "slack" and ("worst" in p or "critical" in p),
                ]
            )
        if metrics["fmax"] is None:
            metrics["fmax"] = _pick(
                [
                    lambda k, p: k in ("fmax", "max_frequency", "maxfreq", "achieved"),
                    lambda k, p: "fmax" in k,
                ]
            )
        metrics["wirelength"] = _pick(
            [
                lambda k, p: "wirelength" in k or k in ("wirelen", "wl"),
            ]
        )

        # Utilization block if present
        util = data.get("utilization") or data.get("utilisation") or data.get("util")
        if isinstance(util, dict):
            metrics["utilization"] = util
            # Prefer resources that are actually used, then fill with the rest
            util_items = list(util.items())

            def _used_count(item):
                info = item[1]
                if isinstance(info, dict):
                    used = info.get("used", info.get("count"))
                    try:
                        return int(used or 0)
                    except (TypeError, ValueError):
                        return 0
                return 0

            util_items.sort(key=_used_count, reverse=True)
            for res, info in util_items[:16]:
                if isinstance(info, dict):
                    used = info.get("used", info.get("count"))
                    avail = info.get("available", info.get("total"))
                    if used is not None and avail is not None:
                        summary.append(f"Util[{res}]={used}/{avail}")
                    elif used is not None:
                        summary.append(f"Util[{res}]={used}")
                elif isinstance(info, (int, float)):
                    summary.append(f"Util[{res}]={info}")

        if metrics["worst_slack"] is not None:
            summary.insert(0, f"Worst slack={metrics['worst_slack']} ns")
        if metrics["fmax"] is not None and not fmax_by_clock:
            summary.insert(0 if metrics["worst_slack"] is None else 1, f"Fmax={metrics['fmax']} MHz")
        if metrics["wirelength"] is not None:
            summary.append(f"Wirelength={metrics['wirelength']}")

        # GateMate/himbaechel reports often have empty timing for tiny / unconstrained nets
        crit = data.get("critical_paths")
        fmax_empty = isinstance(fmax_section, dict) and not fmax_section
        if metrics["worst_slack"] is None and metrics["fmax"] is None and (
            fmax_empty or crit == [] or crit is None
        ):
            summary.insert(
                0,
                "No Fmax/slack in report (fmax empty / no critical paths) - utilization only",
            )

        metrics["summary_lines"] = summary
        return metrics

    def _score_seed_result(self, result: Dict[str, Any], selection: str) -> Tuple[float, float, float]:
        """Return a sortable score tuple (higher is better for primary metric)."""
        worst_slack = result.get("worst_slack")
        fmax = result.get("fmax")
        wirelength = result.get("wirelength")
        ok = 1.0 if result.get("success") else 0.0

        # Missing metrics sort below present ones
        slack_score = float(worst_slack) if worst_slack is not None else -1e9
        fmax_score = float(fmax) if fmax is not None else -1e9
        # Lower wirelength is better -> invert
        wl_score = -float(wirelength) if wirelength is not None else -1e9

        selection = (selection or "best_worst_slack").lower()
        if selection in ("best_fmax", "best_max_freq", "fmax"):
            return (ok, fmax_score, slack_score)
        if selection in ("lowest_wirelength", "wirelength", "lowest_wire_length"):
            return (ok, wl_score, slack_score)
        # Default: best worst-case timing / slack
        return (ok, slack_score, fmax_score)

    def _timing_met(self, result: Dict[str, Any]) -> bool:
        """Heuristic: positive worst slack means timing met when slack is known."""
        slack = result.get("worst_slack")
        if slack is None:
            return bool(result.get("success"))
        return float(slack) >= 0.0

    def place_and_route(
        self,
        design_name: str,
        netlist_file: Optional[str] = None,
        constraint_file: Optional[str] = None,
        options: Optional[List[str]] = None,
        settings: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Run nextpnr-himbaechel place-and-route on a synthesized GateMate JSON netlist.

        Prefers ``{synth}/{design_name}_synth.json``. Writes
        ``{build}/{design_name}_impl.txt``. Requires a non-empty ``.ccf`` constraint file.

        When ``settings['seed_mode'] == 'multi'``, runs a multi-seed search and keeps
        the best implementation as ``{design}_impl.txt``.

        Returns:
            True on success, False on failure (see ``last_error``).
        """
        self.last_error = None
        self.last_return_code = None
        self.last_command = None
        self.last_seed_results = []
        self.last_bitstream_seed = None

        pnr_settings = self.merge_pnr_settings(settings)
        if pnr_settings.get("device"):
            self.device = str(pnr_settings["device"])

        if (pnr_settings.get("seed_mode") or "fixed").lower() == "multi":
            return self._place_and_route_multi_seed(
                design_name=design_name,
                netlist_file=netlist_file,
                constraint_file=constraint_file,
                options=options,
                settings=pnr_settings,
            )

        return self._place_and_route_single(
            design_name=design_name,
            netlist_file=netlist_file,
            constraint_file=constraint_file,
            options=options,
            settings=pnr_settings,
            seed=int(pnr_settings.get("fixed_seed", 1) or 1),
            output_file=None,
            report_file=None,
            copy_as_canonical=True,
        )

    def _resolve_pnr_inputs(
        self,
        design_name: str,
        netlist_file: Optional[str],
        constraint_file: Optional[str],
    ) -> Tuple[Optional[str], Optional[str]]:
        """Resolve JSON netlist and CCF paths; set last_error on failure."""
        if netlist_file is None:
            json_file = os.path.join(self.synth_dir, f"{design_name}_synth.json")
            if os.path.exists(json_file):
                netlist_file = json_file
                self.nextpnr_logger.info(f"Using JSON netlist: {netlist_file}")
            else:
                # Help diagnose partial synthesis (GHDL .v without Yosys JSON)
                synth_listing = []
                try:
                    if os.path.isdir(self.synth_dir):
                        synth_listing = sorted(os.listdir(self.synth_dir))
                except Exception:
                    pass
                v_only = os.path.join(self.synth_dir, f"{design_name}_synth.v")
                hint = ""
                if os.path.exists(v_only):
                    hint = (
                        f" Found {design_name}_synth.v but not the JSON netlist — "
                        "re-run GateMate synthesis so Yosys writes *_synth.json "
                        "(synth_gatemate -luttree -nomx8)."
                    )
                elif synth_listing:
                    hint = f" Synth directory contents: {', '.join(synth_listing[:20])}."
                self.last_error = (
                    f"Synthesis JSON netlist not found for '{design_name}'. "
                    f"Expected: {json_file}.{hint} Run synthesis first."
                )
                self.nextpnr_logger.error("❌ SYNTHESIS NETLIST REQUIRED FOR PLACE & ROUTE")
                self.nextpnr_logger.error(f"❌ No synthesized JSON found for design '{design_name}'")
                self.nextpnr_logger.error(f"   Expected: {json_file}")
                if hint:
                    self.nextpnr_logger.error(f"   {hint.strip()}")
                return None, None

        if not os.path.exists(netlist_file):
            self.last_error = f"Input netlist file not found: {netlist_file}"
            self.nextpnr_logger.error(f"❌ {self.last_error}")
            return None, None

        try:
            netlist_file = self._ensure_ascii_path(netlist_file)
        except ValueError as e:
            self.last_error = str(e)
            self.nextpnr_logger.error(self.last_error)
            return None, None

        constraint_file_used = None
        if constraint_file:
            if os.path.exists(constraint_file):
                constraint_file_used = constraint_file
                self.nextpnr_logger.info(f"Using specified constraint file: {constraint_file}")
            else:
                self.last_error = f"Specified constraint file not found: {constraint_file}"
                self.nextpnr_logger.error(f"ERROR: {self.last_error}")
                return None, None
        else:
            constraint_file_to_use, constraint_file_reason, is_template = self.resolve_constraint_file(
                design_name=design_name
            )
            if constraint_file_to_use:
                constraint_file_used = constraint_file_to_use
                self.nextpnr_logger.info(f"Auto-detected constraint file: {constraint_file_to_use}")
                self.nextpnr_logger.info(f"Selected {constraint_file_reason}")
                if is_template:
                    self.last_error = (
                        "Selected constraint file has no active pin assignments "
                        f"({os.path.basename(constraint_file_to_use)})"
                    )
                    self.nextpnr_logger.error(f"ERROR: {self.last_error}")
                    return None, None
            else:
                default_constraint_file = self.get_default_constraint_file_path()
                self.last_error = (
                    "CONSTRAINT FILE REQUIRED: No constraint file was specified and "
                    "no constraint files were found."
                )
                self.nextpnr_logger.error("ERROR: CONSTRAINT FILE REQUIRED")
                self.nextpnr_logger.error(
                    f"ERROR: Default constraint file location: {default_constraint_file}"
                )
                return None, None

        if not self.has_active_constraints(constraint_file_used):
            self.last_error = (
                "CONSTRAINT FILE IS EMPTY OR ALL COMMENTED OUT: "
                f"{constraint_file_used}"
            )
            self.nextpnr_logger.error(f"ERROR: {self.last_error}")
            return None, None

        try:
            constraint_file_used = self._ensure_ascii_path(constraint_file_used)
        except ValueError as e:
            self.last_error = str(e)
            self.nextpnr_logger.error(self.last_error)
            return None, None

        return netlist_file, constraint_file_used

    def _place_and_route_single(
        self,
        *,
        design_name: str,
        netlist_file: Optional[str],
        constraint_file: Optional[str],
        options: Optional[List[str]],
        settings: Dict[str, Any],
        seed: int,
        output_file: Optional[str],
        report_file: Optional[str],
        copy_as_canonical: bool,
        job_meta: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Run one nextpnr seed. On success, optionally copy to ``{design}_impl.txt``.

        ``job_meta`` (optional) receives ``return_code``, ``error``, and ``command`` so
        parallel workers do not race on ``self.last_*``.
        """
        def _meta(**kwargs: Any) -> None:
            if job_meta is not None:
                job_meta.update(kwargs)

        resolved = self._resolve_pnr_inputs(design_name, netlist_file, constraint_file)
        if not resolved[0] or not resolved[1]:
            _meta(return_code=self.last_return_code, error=self.last_error, command=None)
            return False
        netlist_file, constraint_file_used = resolved

        if output_file is None:
            output_file = os.path.join(self.work_dir, f"{design_name}_impl.txt")
        try:
            output_file = self._ensure_ascii_path(output_file)
        except ValueError as e:
            with self._state_lock:
                self.last_error = str(e)
            _meta(return_code=None, error=str(e), command=None)
            self.nextpnr_logger.error(str(e))
            return False

        if report_file is None and settings.get("generate_report", True):
            report_file = os.path.join(self.timing_dir, f"{design_name}_report.json")

        nextpnr_cmd = self.build_nextpnr_command(
            design_name=design_name,
            netlist_file=netlist_file,
            constraint_file=constraint_file_used,
            output_file=output_file,
            settings=settings,
            seed=seed,
            report_file=report_file,
        )
        if options:
            nextpnr_cmd.extend(options)

        preview = self.format_command_preview(nextpnr_cmd)
        with self._state_lock:
            self.last_command = list(nextpnr_cmd)
        _meta(command=preview)
        self.nextpnr_logger.info(f"Running nextpnr-himbaechel place and route for {design_name}")
        self.nextpnr_logger.info(f"Command preview: {preview}")
        self.nextpnr_logger.debug(f"nextpnr Command: {' '.join(nextpnr_cmd)}")
        self.nextpnr_logger.info(f"Input netlist: {netlist_file}")
        self.nextpnr_logger.info(f"Constraint file: {constraint_file_used}")
        self.nextpnr_logger.info(f"Output file: {output_file}")
        self.nextpnr_logger.info(f"Device: {settings.get('device', self.device)}")
        self.nextpnr_logger.info(
            f"Modes: fpga_mode={settings.get('fpga_mode')} time_mode={settings.get('time_mode')} "
            f"placer={settings.get('placer')} router={settings.get('router')} seed={seed}"
        )

        sdc = (settings.get("sdc_path") or "").strip()
        if not sdc and not (
            settings.get("use_fallback_frequency", True)
            and float(settings.get("fallback_frequency_mhz") or 0) > 0
        ):
            self.nextpnr_logger.warning(
                "No timing constraint file or target frequency is specified. "
                "P&R may complete, but meaningful timing closure cannot be verified."
            )

        try:
            line_prefix = f"[seed {seed}]"
            result = self._run_tool_streaming(
                nextpnr_cmd,
                tool_label="nextpnr-himbaechel",
                timeout=600,
                line_prefix=line_prefix,
            )

            with self._state_lock:
                self.last_return_code = result.returncode
            _meta(return_code=result.returncode)
            self.nextpnr_logger.info(
                f"nextpnr process completed with return code: {result.returncode}"
            )
            if result.stdout:
                self.nextpnr_logger.debug(f"nextpnr full transcript ({len(result.stdout)} chars)")

            metrics = self.parse_report_metrics(report_file) if report_file else {}
            seed_result = {
                "seed": seed,
                "success": result.returncode == 0 and os.path.exists(output_file),
                "return_code": result.returncode,
                "impl_path": output_file,
                "report_path": report_file,
                "worst_slack": metrics.get("worst_slack"),
                "fmax": metrics.get("fmax"),
                "wirelength": metrics.get("wirelength"),
                "command": preview,
            }
            with self._state_lock:
                self.last_seed_results = [seed_result]

            if result.returncode == 0:
                if not os.path.exists(output_file):
                    err = (
                        f"nextpnr reported success but output file was not created: {output_file}"
                    )
                    with self._state_lock:
                        self.last_error = err
                    _meta(error=err)
                    self.nextpnr_logger.error(err)
                    return False

                if copy_as_canonical:
                    canonical = os.path.join(self.work_dir, f"{design_name}_impl.txt")
                    if os.path.normpath(output_file) != os.path.normpath(canonical):
                        shutil.copy2(output_file, canonical)
                        self.nextpnr_logger.info(f"Copied best/canonical impl to {canonical}")
                    with self._state_lock:
                        self.last_bitstream_seed = int(seed)
                    self._emit_live(
                        f"Bitstream source seed: {seed} "
                        f"(implementation → {os.path.basename(canonical)})"
                    )

                with self._state_lock:
                    self.last_error = None
                _meta(error=None)
                self.nextpnr_logger.info(
                    f"Successfully completed place and route for {design_name}"
                )
                self.nextpnr_logger.info(f"Generated implementation file: {output_file}")
                return True

            err = self._format_tool_error(result, "nextpnr-himbaechel")
            with self._state_lock:
                self.last_error = err
            _meta(error=err)
            self.nextpnr_logger.error(
                f"Place and route failed for {design_name} with return code {result.returncode}"
            )
            self.nextpnr_logger.error(f"nextpnr error summary:\n{err}")
            return False

        except subprocess.TimeoutExpired as e:
            err = f"nextpnr-himbaechel timed out after 600 seconds: {e}"
            with self._state_lock:
                self.last_error = err
            _meta(error=err, return_code=-1)
            self.nextpnr_logger.error(f"Place and route timed out for {design_name}: {e}")
            return False
        except FileNotFoundError as e:
            err = f"nextpnr-himbaechel not found: {self.nextpnr_cmd}"
            with self._state_lock:
                self.last_error = err
            _meta(error=err, return_code=-1)
            self.nextpnr_logger.error(f"nextpnr tool not found: {e}")
            self.nextpnr_logger.error(f"Attempted to run: {self.nextpnr_cmd}")
            return False
        except Exception as e:
            err = str(e)
            with self._state_lock:
                self.last_error = err
            _meta(error=err, return_code=-1)
            self.nextpnr_logger.error(
                f"Unexpected error during place and route for {design_name}: {e}"
            )
            import traceback
            self.nextpnr_logger.error(f"Traceback: {traceback.format_exc()}")
            return False

    def _run_one_seed_job(
        self,
        *,
        design_name: str,
        netlist_file: str,
        constraint_file: str,
        settings: Dict[str, Any],
        seed: int,
        options: Optional[List[str]],
    ) -> Dict[str, Any]:
        """Execute a single multi-seed iteration (safe for ThreadPoolExecutor)."""
        seed_tag = f"{seed:03d}"
        output_file = os.path.join(self.work_dir, f"{design_name}_impl_seed_{seed_tag}.txt")
        report_file = os.path.join(self.timing_dir, f"{design_name}_report_seed_{seed_tag}.json")
        job_meta: Dict[str, Any] = {}

        ok = self._place_and_route_single(
            design_name=design_name,
            netlist_file=netlist_file,
            constraint_file=constraint_file,
            options=options,
            settings=settings,
            seed=seed,
            output_file=output_file,
            report_file=report_file,
            copy_as_canonical=False,
            job_meta=job_meta,
        )
        metrics = self.parse_report_metrics(report_file)
        svg_paths = self.seed_svg_paths(design_name, seed)
        return {
            "seed": seed,
            "success": ok,
            "return_code": job_meta.get("return_code"),
            "impl_path": output_file,
            "report_path": report_file if os.path.exists(report_file) else None,
            "placed_svg": svg_paths["placed"] if os.path.exists(svg_paths["placed"]) else None,
            "routed_svg": svg_paths["routed"] if os.path.exists(svg_paths["routed"]) else None,
            "worst_slack": metrics.get("worst_slack"),
            "fmax": metrics.get("fmax"),
            "fmax_by_clock": metrics.get("fmax_by_clock") or {},
            "wirelength": metrics.get("wirelength"),
            "summary_lines": metrics.get("summary_lines") or [],
            "command": job_meta.get("command") or "",
            "error": None if ok else job_meta.get("error"),
        }

    def _place_and_route_multi_seed(
        self,
        *,
        design_name: str,
        netlist_file: Optional[str],
        constraint_file: Optional[str],
        options: Optional[List[str]],
        settings: Dict[str, Any],
    ) -> bool:
        """Run multiple seeds, keep the best implementation as ``{design}_impl.txt``."""
        resolved = self._resolve_pnr_inputs(design_name, netlist_file, constraint_file)
        if not resolved[0] or not resolved[1]:
            return False
        netlist_file, constraint_file_used = resolved

        try:
            iterations = max(1, int(settings.get("iterations", 20) or 20))
            first_seed = int(settings.get("first_seed", 1) or 1)
            parallel_jobs = max(1, int(settings.get("parallel_jobs", 1) or 1))
        except (TypeError, ValueError):
            iterations, first_seed, parallel_jobs = 20, 1, 1

        # Always emit placed+routed SVG and report JSON for the progress UI
        run_settings = dict(settings)
        run_settings["generate_placed_svg"] = True
        run_settings["generate_routed_svg"] = True
        run_settings["generate_report"] = True
        run_settings["detailed_timing_report"] = True

        # Drop stale previews/reports from a previous multi-seed run of this design
        removed = self.cleanup_seed_artifacts(design_name)
        if removed:
            self._emit_live(
                f"Cleared {removed} previous seed artifact(s) for {design_name}"
            )

        seeds = list(range(first_seed, first_seed + iterations))
        selection = run_settings.get("selection") or "best_worst_slack"
        stop_when_met = bool(run_settings.get("stop_when_timing_met"))

        self._emit_live(
            f"=== Multi-seed P&R for {design_name}: "
            f"{len(seeds)} iterations, seeds {seeds[0]}..{seeds[-1]}, "
            f"selection={selection}, parallel_jobs={parallel_jobs} ==="
        )
        if parallel_jobs > 1:
            self._emit_live(
                f"Launching up to {parallel_jobs} concurrent nextpnr workers "
                "(progress window shows the current best seed)"
            )

        self._notify_progress(
            {
                "event": "multi_seed_start",
                "design": design_name,
                "total": len(seeds),
                "first_seed": first_seed,
                "selection": selection,
                "parallel_jobs": parallel_jobs,
                "show_best": parallel_jobs > 1,
            }
        )

        results: List[Dict[str, Any]] = []
        results_lock = threading.Lock()
        completed_count = 0

        def _consume(result: Dict[str, Any], index: int, *, show_best: bool) -> bool:
            results.append(result)
            status = "PASS" if result.get("success") else "FAIL"
            self._emit_live(
                f"=== Seed {result['seed']} result [{index}/{len(seeds)}]: "
                f"{status} worst_slack={result.get('worst_slack')} "
                f"fmax={result.get('fmax')} ==="
            )
            best_so_far = None
            successful_so_far = [
                r for r in results
                if r.get("success") and r.get("impl_path") and os.path.exists(r["impl_path"])
            ]
            if successful_so_far:
                best_so_far = max(
                    successful_so_far, key=lambda r: self._score_seed_result(r, selection)
                )

            # Parallel mode: preview/timing panels show the current best.
            # Sequential mode: show the seed that just finished (unchanged).
            display = best_so_far if (show_best and best_so_far) else result

            self._notify_progress(
                {
                    "event": "seed_done",
                    "design": design_name,
                    "seed": result.get("seed"),
                    "display_seed": display.get("seed"),
                    "index": index,
                    "total": len(seeds),
                    "status": status,
                    "show_best": show_best,
                    "parallel_jobs": parallel_jobs,
                    "worst_slack": display.get("worst_slack"),
                    "fmax": display.get("fmax"),
                    "fmax_by_clock": display.get("fmax_by_clock") or {},
                    "wirelength": display.get("wirelength"),
                    "summary_lines": display.get("summary_lines") or [],
                    "report_path": display.get("report_path"),
                    "placed_svg": display.get("placed_svg"),
                    "routed_svg": display.get("routed_svg"),
                    "best_seed": best_so_far.get("seed") if best_so_far else None,
                    "best_worst_slack": best_so_far.get("worst_slack") if best_so_far else None,
                    "best_fmax": best_so_far.get("fmax") if best_so_far else None,
                    "result": result,
                    "results": list(results),
                }
            )
            return stop_when_met and result.get("success") and self._timing_met(result)

        if parallel_jobs <= 1:
            for index, seed in enumerate(seeds, start=1):
                self._emit_live(
                    f"=== Starting seed {seed} ({index}/{len(seeds)}) ==="
                )
                self._notify_progress(
                    {
                        "event": "seed_start",
                        "design": design_name,
                        "seed": seed,
                        "index": index,
                        "total": len(seeds),
                        "show_best": False,
                        "parallel_jobs": 1,
                    }
                )
                result = self._run_one_seed_job(
                    design_name=design_name,
                    netlist_file=netlist_file,
                    constraint_file=constraint_file_used,
                    settings=run_settings,
                    seed=seed,
                    options=options,
                )
                if _consume(result, index, show_best=False):
                    self._emit_live(
                        f"Stopping multi-seed early: timing met at seed {seed}"
                    )
                    break
        else:
            stop_flag = threading.Event()
            self._notify_progress(
                {
                    "event": "seed_start",
                    "design": design_name,
                    "seed": seeds[0],
                    "index": 0,
                    "total": len(seeds),
                    "show_best": True,
                    "parallel_jobs": parallel_jobs,
                    "active_workers": min(parallel_jobs, len(seeds)),
                }
            )

            with ThreadPoolExecutor(max_workers=parallel_jobs) as pool:
                futures = {
                    pool.submit(
                        self._run_one_seed_job,
                        design_name=design_name,
                        netlist_file=netlist_file,
                        constraint_file=constraint_file_used,
                        settings=run_settings,
                        seed=seed,
                        options=options,
                    ): seed
                    for seed in seeds
                }
                for fut in as_completed(futures):
                    seed = futures[fut]
                    try:
                        result = fut.result()
                    except CancelledError:
                        continue
                    except Exception as e:
                        result = {
                            "seed": seed,
                            "success": False,
                            "return_code": -1,
                            "impl_path": None,
                            "report_path": None,
                            "placed_svg": None,
                            "routed_svg": None,
                            "worst_slack": None,
                            "fmax": None,
                            "fmax_by_clock": {},
                            "wirelength": None,
                            "summary_lines": [],
                            "command": "",
                            "error": str(e),
                        }

                    with results_lock:
                        completed_count += 1
                        index = completed_count
                        should_stop = _consume(result, index, show_best=True)

                    if should_stop and not stop_flag.is_set():
                        stop_flag.set()
                        self._emit_live(
                            f"Stopping multi-seed early: timing met at seed {seed} "
                            "(canceling queued workers; in-flight jobs may still finish)"
                        )
                        for pending in futures:
                            pending.cancel()

        self.last_seed_results = sorted(results, key=lambda r: r.get("seed", 0))
        successful = [r for r in results if r.get("success") and r.get("impl_path") and os.path.exists(r["impl_path"])]
        if not successful:
            self.last_error = (
                self.last_error
                or f"Multi-seed place and route failed for {design_name}: no successful seed"
            )
            self.nextpnr_logger.error(self.last_error)
            self._notify_progress(
                {
                    "event": "multi_seed_done",
                    "design": design_name,
                    "success": False,
                    "error": self.last_error,
                    "results": list(self.last_seed_results),
                }
            )
            return False

        best = max(successful, key=lambda r: self._score_seed_result(r, selection))
        for r in self.last_seed_results:
            r["is_best"] = r.get("seed") == best.get("seed")

        canonical = os.path.join(self.work_dir, f"{design_name}_impl.txt")
        try:
            shutil.copy2(best["impl_path"], canonical)
        except Exception as e:
            self.last_error = f"Failed to copy best implementation to {canonical}: {e}"
            self.nextpnr_logger.error(self.last_error)
            self._notify_progress(
                {
                    "event": "multi_seed_done",
                    "design": design_name,
                    "success": False,
                    "error": self.last_error,
                    "results": list(self.last_seed_results),
                }
            )
            return False

        self.last_bitstream_seed = int(best["seed"])

        if best.get("report_path") and os.path.exists(best["report_path"]):
            try:
                shutil.copy2(
                    best["report_path"],
                    os.path.join(self.timing_dir, f"{design_name}_report.json"),
                )
            except Exception as e:
                self.nextpnr_logger.warning(f"Could not copy best report: {e}")

        self.last_error = None
        self.last_return_code = 0
        self._emit_live(
            f"=== Multi-seed P&R selected seed {best['seed']} as best "
            f"(worst_slack={best.get('worst_slack')}, fmax={best.get('fmax')}) ==="
        )
        self._emit_live(f"Canonical implementation: {canonical}")
        self._emit_live(
            f"Bitstream will be generated from seed {best['seed']} only "
            f"({os.path.basename(canonical)} → {design_name}.bit)"
        )
        self._notify_progress(
            {
                "event": "multi_seed_done",
                "design": design_name,
                "success": True,
                "best_seed": best.get("seed"),
                "best_worst_slack": best.get("worst_slack"),
                "best_fmax": best.get("fmax"),
                "report_path": best.get("report_path"),
                "placed_svg": best.get("placed_svg"),
                "routed_svg": best.get("routed_svg"),
                "canonical_impl": canonical,
                "results": list(self.last_seed_results),
            }
        )
        return True

    def generate_bitstream(
        self,
        design_name: str,
        impl_file: Optional[str] = None,
        options: Optional[List[str]] = None,
    ) -> bool:
        """
        Pack a nextpnr implementation text file into a ``.bit`` bitstream with gmpack.

        Default implementation input: ``{build}/{design_name}_impl.txt``
        Output: ``{bitstream_dir}/{design_name}.bit``

        Returns:
            True on success, False on failure (see ``last_error``).
        """
        self.last_error = None
        self.last_return_code = None

        if impl_file is None:
            impl_file = os.path.join(self.work_dir, f"{design_name}_impl.txt")

        if not os.path.exists(impl_file):
            self.last_error = (
                f"Implementation file not found: {impl_file}. "
                "Run place and route first."
            )
            self.nextpnr_logger.error(f"❌ {self.last_error}")
            self.nextpnr_logger.error("🔧 SOLUTIONS:")
            self.nextpnr_logger.error("   1. Run Place & Route first to generate the implementation file")
            self.nextpnr_logger.error("   2. Check that Place & Route completed successfully")
            return False

        bitstream_file = os.path.join(self.bitstream_dir, f"{design_name}.bit")
        os.makedirs(self.bitstream_dir, exist_ok=True)

        try:
            impl_file = self._ensure_ascii_path(impl_file)
            bitstream_file = self._ensure_ascii_path(bitstream_file)
        except ValueError as e:
            self.last_error = str(e)
            self.nextpnr_logger.error(self.last_error)
            return False

        gmpack_cmd = [self.gmpack_cmd, impl_file, bitstream_file]
        if options:
            gmpack_cmd.extend(options)

        self.last_command = list(gmpack_cmd)
        seed_note = ""
        if self.last_bitstream_seed is not None:
            seed_note = f" (from P&R seed {self.last_bitstream_seed})"
            self._emit_live(
                f"Packing bitstream from seed {self.last_bitstream_seed}: "
                f"{os.path.basename(impl_file)} → {os.path.basename(bitstream_file)}"
            )
        self.nextpnr_logger.info(
            f"Generating bitstream for {design_name} with gmpack{seed_note}"
        )
        self.nextpnr_logger.debug(f"gmpack Command: {' '.join(gmpack_cmd)}")
        self.nextpnr_logger.info(f"Input implementation: {impl_file}")
        self.nextpnr_logger.info(f"Output bitstream: {bitstream_file}")

        try:
            result = self._run_tool_streaming(
                gmpack_cmd,
                tool_label="gmpack",
                timeout=300,
                line_prefix="[gmpack]",
            )

            self.nextpnr_logger.info(
                f"gmpack process completed with return code: {result.returncode}"
            )

            if result.returncode == 0:
                if not os.path.exists(bitstream_file):
                    self.last_error = (
                        f"gmpack reported success but bitstream was not created: {bitstream_file}"
                    )
                    self.nextpnr_logger.error(self.last_error)
                    return False
                self.last_error = None
                self.last_return_code = None
                self.nextpnr_logger.info(f"Successfully generated bitstream for {design_name}")
                self.nextpnr_logger.info(f"Generated bitstream file: {bitstream_file}")
                if self.last_bitstream_seed is not None:
                    self._emit_live(
                        f"Bitstream ready: {os.path.basename(bitstream_file)} "
                        f"was packed from seed {self.last_bitstream_seed}"
                    )
                return True

            self.last_return_code = result.returncode
            self.last_error = self._format_tool_error(result, "gmpack")
            self.nextpnr_logger.error(
                f"Bitstream generation failed for {design_name} with return code {result.returncode}"
            )
            self.nextpnr_logger.error(f"gmpack error summary:\n{self.last_error}")
            return False

        except subprocess.TimeoutExpired as e:
            self.last_error = f"gmpack timed out after 300 seconds: {e}"
            self.nextpnr_logger.error(f"Bitstream generation timed out for {design_name}: {e}")
            return False
        except FileNotFoundError as e:
            self.last_error = f"gmpack not found: {self.gmpack_cmd}"
            self.nextpnr_logger.error(f"gmpack tool not found: {e}")
            self.nextpnr_logger.error(f"Attempted to run: {self.gmpack_cmd}")
            return False
        except Exception as e:
            self.last_error = str(e)
            self.nextpnr_logger.error(
                f"Unexpected error during bitstream generation for {design_name}: {e}"
            )
            import traceback
            self.nextpnr_logger.error(f"Traceback: {traceback.format_exc()}")
            return False

    def full_implementation_flow(
        self,
        design_name: str,
        constraint_file: Optional[str] = None,
        options: Optional[List[str]] = None,
        settings: Optional[Dict[str, Any]] = None,
        generate_bitstream: bool = True,
        run_timing_analysis: bool = False,
        generate_sim_netlist: bool = False,
        sim_netlist_format: str = "vhdl",
    ) -> bool:
        """
        Run place-and-route then optionally pack bitstream for ``design_name``.

        Extra kwargs (``run_timing_analysis``, ``generate_sim_netlist``, ...) are
        accepted for GUI compatibility; timing/netlist steps remain stubs for now.
        """
        del sim_netlist_format
        self.nextpnr_logger.info(f"Starting full nextpnr/gmpack implementation flow for {design_name}")

        pnr_settings = self.merge_pnr_settings(settings)
        if generate_bitstream is not None:
            pnr_settings["generate_bitstream"] = generate_bitstream

        if not self.place_and_route(
            design_name,
            constraint_file=constraint_file,
            options=options,
            settings=pnr_settings,
        ):
            self.nextpnr_logger.error(f"Place and route failed for {design_name}")
            return False

        if run_timing_analysis:
            self.nextpnr_logger.info(
                "Timing analysis requested: results are included in nextpnr logs/reports "
                "(dedicated post-P&R timing step is not yet automated)."
            )
        if generate_sim_netlist:
            self.nextpnr_logger.warning(
                "Post-implementation netlist generation is not supported with gmpack yet; skipping."
            )

        if pnr_settings.get("generate_bitstream", True):
            if not self.generate_bitstream(design_name):
                self.nextpnr_logger.error(f"Bitstream generation failed for {design_name}")
                return False

        self.nextpnr_logger.info(
            f"Successfully completed full implementation flow for {design_name}"
        )
        return True

    def get_analysis_artifacts(self, design_name: str) -> Dict[str, Any]:
        """Locate nextpnr analysis outputs for ``design_name`` after Place & Route.

        Prefers the canonical best-seed copies (``{design}_report.json``, etc.),
        then falls back to per-seed artifacts and optional SDF / SVG files.
        """
        artifacts: Dict[str, Any] = {
            "report_json": None,
            "seed_reports": [],
            "sdf_files": [],
            "placed_svg": None,
            "routed_svg": None,
            "impl_txt": None,
            "log_file": None,
        }
        if not design_name:
            return artifacts

        impl = os.path.join(self.work_dir, f"{design_name}_impl.txt")
        if os.path.isfile(impl):
            artifacts["impl_txt"] = impl

        log_file = os.path.join(self.impl_logs_dir, "nextpnr_commands.log")
        if os.path.isfile(log_file):
            artifacts["log_file"] = log_file

        canonical_report = os.path.join(self.timing_dir, f"{design_name}_report.json")
        if os.path.isfile(canonical_report):
            artifacts["report_json"] = canonical_report

        seed_reports: List[str] = []
        placed_candidates: List[str] = []
        routed_candidates: List[str] = []
        sdf_files: List[str] = []

        search_dirs = [self.timing_dir, self.work_dir]
        for directory in search_dirs:
            if not directory or not os.path.isdir(directory):
                continue
            try:
                for name in os.listdir(directory):
                    path = os.path.join(directory, name)
                    if not os.path.isfile(path):
                        continue
                    if name.startswith(f"{design_name}_report_seed_") and name.endswith(".json"):
                        seed_reports.append(path)
                    elif name.startswith(f"{design_name}_seed_") and name.endswith("_placed.svg"):
                        placed_candidates.append(path)
                    elif name.startswith(f"{design_name}_seed_") and name.endswith("_routed.svg"):
                        routed_candidates.append(path)
                    elif name.startswith(design_name) and name.endswith(".sdf"):
                        sdf_files.append(path)
                    elif name == f"{design_name}_placed.svg":
                        placed_candidates.append(path)
                    elif name == f"{design_name}_routed.svg":
                        routed_candidates.append(path)
            except OSError:
                continue

        seed_reports.sort()
        artifacts["seed_reports"] = seed_reports
        if not artifacts["report_json"] and seed_reports:
            # Prefer last seed report if canonical missing (multi-seed without copy)
            artifacts["report_json"] = seed_reports[-1]

        # Prefer SVG matching last_bitstream_seed when known
        def _pick_svg(candidates: List[str], kind: str) -> Optional[str]:
            if not candidates:
                return None
            seed = self.last_bitstream_seed
            if seed is not None:
                tag = f"{int(seed):03d}"
                for path in candidates:
                    if f"_seed_{tag}_{kind}.svg" in os.path.basename(path):
                        return path
            return sorted(candidates)[-1]

        artifacts["placed_svg"] = _pick_svg(placed_candidates, "placed")
        artifacts["routed_svg"] = _pick_svg(routed_candidates, "routed")
        artifacts["sdf_files"] = sorted(sdf_files)
        return artifacts

    def get_implementation_status(self, design_name: str) -> Dict[str, bool]:
        """Check whether nextpnr / gmpack outputs exist for a design."""
        impl_file = os.path.join(self.work_dir, f"{design_name}_impl.txt")
        bitstream_file = os.path.join(self.bitstream_dir, f"{design_name}.bit")
        placed = os.path.exists(impl_file)
        artifacts = self.get_analysis_artifacts(design_name)
        has_report = bool(artifacts.get("report_json"))
        has_sdf = bool(artifacts.get("sdf_files"))
        has_svg = bool(artifacts.get("placed_svg") or artifacts.get("routed_svg"))
        return {
            "placed": placed,
            "routed": placed,
            "bitstream_generated": os.path.exists(bitstream_file),
            "timing_analyzed": has_report or has_sdf,
            "has_report": has_report,
            "has_placement_graphics": has_svg,
        }

    def get_available_placed_designs(self) -> List[str]:
        """Return design names that have a ``*_impl.txt`` file in the build directory."""
        designs = []
        try:
            if not os.path.exists(self.work_dir):
                self.nextpnr_logger.warning(f"Build directory not found: {self.work_dir}")
                return []

            for file in os.listdir(self.work_dir):
                if file.endswith("_impl.txt"):
                    design_name = file[: -len("_impl.txt")]
                    if design_name and design_name not in designs:
                        designs.append(design_name)
                        self.nextpnr_logger.info(f"Found placed design: {design_name}")
        except Exception as e:
            self.nextpnr_logger.error(f"Error scanning for placed designs: {e}")

        return sorted(designs)

    def timing_analysis(self, design_name: str, options: Optional[List[str]] = None) -> bool:
        """Timing analysis is produced during nextpnr place-and-route.

        Dedicated post-P&R timing extraction is not yet automated. Timing
        messages are available in ``nextpnr_commands.log`` and optionally via
        nextpnr ``--sdf`` / ``--report`` (future work).
        """
        del options
        self.last_error = (
            "Dedicated timing analysis is not yet implemented for nextpnr-himbaechel. "
            "Review timing messages in the nextpnr log from Place & Route, "
            f"or inspect {design_name}_impl.txt."
        )
        self.nextpnr_logger.warning(self.last_error)
        return False

    def generate_post_impl_netlist(
        self,
        design_name: str,
        netlist_format: str = "verilog",
        options: Optional[List[str]] = None,
    ) -> bool:
        """Post-implementation netlist export is not part of the gmpack flow yet."""
        del netlist_format, options
        self.last_error = (
            "Post-implementation netlist generation is not supported with the "
            f"gmpack bitstream flow yet (design={design_name})."
        )
        self.nextpnr_logger.warning(self.last_error)
        return False
