import os
import shutil
import yaml
import logging
import subprocess
from typing import Any, Dict, List, Optional, Tuple
from .hierarchy_manager import HierarchyManager


class ToolChainManager(HierarchyManager):
    """Controls what the GateMate toolchain is doing"""
    
    # GateMate toolchain binaries (OSS CAD Suite + standalone GHDL).
    # Legacy proprietary p_r is no longer part of the supported flow.
    __tool_chain = {
        "ghdl": "ghdl.exe",
        "yosys": "yosys.exe",
        "nextpnr_himbaechel": "nextpnr-himbaechel.exe",
        "gmpack": "gmpack.exe",
        "openfpgaloader": "openFPGALoader.exe",  # optional; ZI loader preferred for Zector boards
    }

    # Empty placeholders for config keys. Absolute paths come only from user
    # Configuration / project YAML / PATH — never hardcode install locations.
    DEFAULT_TOOL_PATHS = {
        "ghdl": "",
        "yosys": "",
        "nextpnr_himbaechel": "",
        "gmpack": "",
        "openfpgaloader": "",
    }

    # Core tools required for synthesis + implementation
    REQUIRED_TOOLS = ("ghdl", "yosys", "nextpnr_himbaechel", "gmpack")
    

    def __init__(self):
        super().__init__(None)
        #self.project_path = os.path.dirname(__file__) 
        #self.log_file = os.path.join(os.path.dirname(__file__),"logs", "project_manager.log") #join path of directory and project_manager.log
        #logging.basicConfig(filename=self.log_file, level=logging.DEBUG,
        #           format="%(asctime)s - %(levelname)s - %(message)s")
        self.set_config_path_structure()

    def check_toolchain(self) -> bool:
        """
            Check if the tools are available and set individual tool preferences.
            Each tool can be configured independently to use PATH or DIRECT access.

        Returns:
            bool: True if at least one tool is available, False if all tools fail.
        """
        STATUS_OK = "OK"
        STATUS_FAIL = "FAIL"
        
        # Initialize individual tool preferences if they don't exist
        self.initialize_individual_tool_preferences()
        
        tool_results = {}
        
        # Check each tool individually
        for tool_name in self.__tool_chain:
            tool_results[tool_name] = {
                "PATH": STATUS_FAIL,
                "DIRECT": STATUS_FAIL,
                "available": False
            }
            
            # Check via PATH
            if self.check_tool_version_path(tool_name):
                tool_results[tool_name]["PATH"] = STATUS_OK
                logging.info(f"{tool_name} is available through PATH")
            else:
                logging.warning(f"{tool_name} is not available through PATH")
            
            # Check via direct paths
            if self.check_tool_version_direct(tool_name):
                tool_results[tool_name]["DIRECT"] = STATUS_OK
                logging.info(f"{tool_name} is available through direct path")
            else:
                logging.warning(f"{tool_name} is not available through direct path")
            
            # Set individual tool preference based on availability
            path_available = tool_results[tool_name]["PATH"] == STATUS_OK
            direct_available = tool_results[tool_name]["DIRECT"] == STATUS_OK
            
            if path_available and direct_available:
                # Both available - keep current preference or default to PATH
                current_pref = self.get_tool_preference(tool_name)
                if current_pref not in ["PATH", "DIRECT"]:
                    self.set_tool_preference(tool_name, "PATH")
                    logging.info(f"{tool_name}: Both PATH and DIRECT available, set to PATH")
                else:
                    logging.info(f"{tool_name}: Both PATH and DIRECT available, keeping current preference: {current_pref}")
                tool_results[tool_name]["available"] = True
            elif path_available:
                self.set_tool_preference(tool_name, "PATH")
                logging.info(f"{tool_name}: Only PATH available, set to PATH")
                tool_results[tool_name]["available"] = True
            elif direct_available:
                self.set_tool_preference(tool_name, "DIRECT")
                logging.info(f"{tool_name}: Only DIRECT available, set to DIRECT")
                tool_results[tool_name]["available"] = True
            else:
                self.set_tool_preference(tool_name, "UNDEFINED")
                logging.error(f"{tool_name}: Neither PATH nor DIRECT available, set to UNDEFINED")
                tool_results[tool_name]["available"] = False

        # Check how many tools are available
        available_tools = sum(1 for tool in tool_results.values() if tool["available"])
        total_tools = len(self.__tool_chain)
        
        logging.info(f"Toolchain check complete: {available_tools}/{total_tools} tools available")
        
        if available_tools == 0:
            logging.error("No GateMate tools are available. Check tool installations and configuration.")
            print("No GateMate tools are available. Check tool installations and configuration.")
            return False
        elif available_tools < total_tools:
            logging.warning(f"Some GateMate tools are not available ({available_tools}/{total_tools}). Available tools can still be used.")
            print(f"Some GateMate tools are not available ({available_tools}/{total_tools}). Available tools can still be used.")
        else:
            logging.info("All GateMate tools are available and configured.")
            print("All GateMate tools are available and configured.")

        # New flow uses standalone GHDL synth (no Yosys GHDL plugin required).
        # Still report plugin status as informational if both tools are present.
        if (tool_results.get("yosys", {}).get("available", False) and
                tool_results.get("ghdl", {}).get("available", False)):
            if self.check_ghdl_yosys_link():
                logging.info("Yosys GHDL plugin is available (optional; new flow uses standalone GHDL)")
            else:
                logging.info("Yosys GHDL plugin not detected (OK for new standalone GHDL -> Yosys flow)")

        missing_required = [
            name for name in self.REQUIRED_TOOLS
            if not tool_results.get(name, {}).get("available", False)
        ]
        if missing_required:
            logging.error(
                "Required GateMate tools missing: " + ", ".join(missing_required)
            )
            print("Required GateMate tools missing: " + ", ".join(missing_required))
            return False

        return True

    def initialize_individual_tool_preferences(self):
        """Initialize individual tool preferences if they don't exist."""
        if "cologne_chip_gatemate_tool_preferences" not in self.config:
            self.config["cologne_chip_gatemate_tool_preferences"] = {}
        
        # Ensure all tools have a preference entry
        for tool_name in self.__tool_chain:
            if tool_name not in self.config["cologne_chip_gatemate_tool_preferences"]:
                self.config["cologne_chip_gatemate_tool_preferences"][tool_name] = "PATH"
        
        # Also initialize GTKWave preference — DIRECT when a path is already known
        gtk_path = (self.config.get("gtkwave_tool_path") or {}).get("gtkwave", "")
        if "gtkwave" not in self.config["cologne_chip_gatemate_tool_preferences"]:
            self.config["cologne_chip_gatemate_tool_preferences"]["gtkwave"] = (
                "DIRECT" if gtk_path and os.path.isfile(gtk_path) else "PATH"
            )
        elif gtk_path and os.path.isfile(gtk_path):
            # Prefer DIRECT whenever an absolute gtkwave path is configured
            self.config["cologne_chip_gatemate_tool_preferences"]["gtkwave"] = "DIRECT"
            self.config["gtkwave_preference"] = "DIRECT"

        # Prefer DIRECT when a user-configured absolute path exists and PATH fails
        paths = self.config.setdefault("cologne_chip_gatemate_toolchain_paths", {})
        for tool_name in self.__tool_chain:
            current = paths.get(tool_name, "")
            if current and os.path.exists(current):
                pref = self.config["cologne_chip_gatemate_tool_preferences"].get(tool_name, "PATH")
                if pref in ("PATH", "UNDEFINED") and not self.check_tool_version_path(tool_name):
                    self.config["cologne_chip_gatemate_tool_preferences"][tool_name] = "DIRECT"
        
        # Save configuration
        self.update_config()

    def get_tool_preference(self, tool_name: str) -> str:
        """
        Get the access preference for a specific tool.
        
        Args:
            tool_name (str): Name of the tool (ghdl, yosys, p_r, openfpgaloader, gtkwave)
            
        Returns:
            str: Tool preference ("PATH", "DIRECT", or "UNDEFINED")
        """
        # Special handling for GTKWave (uses different config system)
        if tool_name == "gtkwave":
            tool_prefs = self.config.get("cologne_chip_gatemate_tool_preferences", {})
            return tool_prefs.get(tool_name, "PATH")
        
        if tool_name not in self.__tool_chain:
            logging.error(f"Unknown tool: {tool_name}")
            return "UNDEFINED"
        
        tool_prefs = self.config.get("cologne_chip_gatemate_tool_preferences", {})
        return tool_prefs.get(tool_name, "PATH")

    def set_tool_preference(self, tool_name: str, preference: str) -> bool:
        """
        Set the access preference for a specific tool.
        
        Args:
            tool_name (str): Name of the tool (ghdl, yosys, p_r, openfpgaloader, gtkwave)
            preference (str): Tool preference ("PATH", "DIRECT", or "UNDEFINED")
            
        Returns:
            bool: True if successfully set, False otherwise
        """
        supported_preferences = ("PATH", "DIRECT", "UNDEFINED")
        if preference.upper() not in supported_preferences:
            logging.error(f"Invalid preference {preference} for {tool_name}. Must be one of: {supported_preferences}")
            return False
        
        # Special handling for GTKWave (uses different config system)
        if tool_name == "gtkwave":
            # Ensure the preferences structure exists
            if "cologne_chip_gatemate_tool_preferences" not in self.config:
                self.config["cologne_chip_gatemate_tool_preferences"] = {}
            
            new_pref = preference.upper()
            old_pref = self.config["cologne_chip_gatemate_tool_preferences"].get(tool_name)
            self.config["cologne_chip_gatemate_tool_preferences"][tool_name] = new_pref
            if old_pref != new_pref:
                logging.info(f"Set {tool_name} preference to {new_pref}")
            else:
                logging.debug(f"{tool_name} preference already {new_pref}")
            
            # Save configuration
            return self.update_config()
        
        if tool_name not in self.__tool_chain:
            logging.error(f"Unknown tool: {tool_name}")
            return False
        
        # Ensure the preferences structure exists
        if "cologne_chip_gatemate_tool_preferences" not in self.config:
            self.config["cologne_chip_gatemate_tool_preferences"] = {}
        
        new_pref = preference.upper()
        old_pref = self.config["cologne_chip_gatemate_tool_preferences"].get(tool_name)
        self.config["cologne_chip_gatemate_tool_preferences"][tool_name] = new_pref
        if old_pref != new_pref:
            logging.info(f"Set {tool_name} preference to {new_pref}")
        else:
            logging.debug(f"{tool_name} preference already {new_pref}")
        
        # Save configuration
        return self.update_config()

    def get_oss_cad_suite_root(self) -> str:
        """Return the OSS CAD Suite root directory if it can be determined.

        Resolution order (no hardcoded install locations):
        1. ``YOSYSHQ_ROOT`` environment variable
        2. Parent of ``bin/`` from a configured tool absolute path
           (yosys / nextpnr / gmpack / openfpgaloader / gtkwave)
        3. Directory containing ``environment.bat`` near a configured tool
        4. Parent of ``bin/`` from a tool found on PATH via ``shutil.which``
        """
        env_root = os.environ.get("YOSYSHQ_ROOT", "").strip().rstrip("\\/")
        if env_root and os.path.isdir(env_root):
            if os.path.isfile(os.path.join(env_root, "environment.bat")) or os.path.isdir(
                os.path.join(env_root, "bin")
            ):
                return env_root

        def _root_from_tool_path(tool_path: str) -> str:
            if not tool_path:
                return ""
            norm = os.path.abspath(os.path.normpath(tool_path))
            if not os.path.exists(norm):
                return ""
            # .../bin/tool.exe
            parent = os.path.dirname(norm)
            if os.path.basename(parent).lower() == "bin":
                root = os.path.dirname(parent)
                if os.path.isdir(os.path.join(root, "lib")) or os.path.isfile(
                    os.path.join(root, "environment.bat")
                ):
                    return root
            # Walk parents looking for environment.bat (suite root marker)
            cur = parent if os.path.isdir(norm) else parent
            for _ in range(6):
                if os.path.isfile(os.path.join(cur, "environment.bat")):
                    return cur
                nxt = os.path.dirname(cur)
                if nxt == cur:
                    break
                cur = nxt
            return ""

        paths = self.config.get("cologne_chip_gatemate_toolchain_paths", {}) or {}
        for tool in (
            "yosys",
            "nextpnr_himbaechel",
            "gmpack",
            "openfpgaloader",
            "ghdl",
        ):
            root = _root_from_tool_path(paths.get(tool, "") or "")
            if root:
                return root

        # GTKWave lives under gtkwave_tool_path (separate config key)
        gtk = (self.config.get("gtkwave_tool_path") or {}).get("gtkwave", "") or ""
        root = _root_from_tool_path(gtk)
        if root:
            return root

        # Auto-Setup machine defaults
        try:
            from .toolchain_autosetup import get_global_toolchain_defaults, load_global_settings
            defaults = get_global_toolchain_defaults()
            for key in ("yosys", "gtkwave", "gmpack", "nextpnr_himbaechel", "openfpgaloader"):
                root = _root_from_tool_path(defaults.get(key, "") or "")
                if root:
                    return root
            block = load_global_settings().get("toolchain_autosetup") or {}
            for key in ("yosyshq_root", "install_root"):
                candidate = (block.get(key) or "").strip().rstrip("\\/")
                if candidate and os.path.isdir(candidate):
                    # install_root may be parent of oss-cad-suite/
                    if os.path.isfile(os.path.join(candidate, "environment.bat")):
                        return candidate
                    nested = os.path.join(candidate, "oss-cad-suite")
                    if os.path.isfile(os.path.join(nested, "environment.bat")):
                        return nested
        except Exception:
            pass

        for exe_name in (
            "yosys",
            "yosys.exe",
            "nextpnr-himbaechel",
            "nextpnr-himbaechel.exe",
            "gmpack",
            "gmpack.exe",
            "gtkwave",
            "gtkwave.exe",
        ):
            found = shutil.which(exe_name)
            if found:
                root = _root_from_tool_path(found)
                if root:
                    return root

        return ""

    def get_tool_run_env(self) -> dict:
        """Build an environment that can execute OSS CAD Suite binaries.

        Mirrors ``environment.bat`` / ``environment.ps1`` from the suite:
        ``bin`` + ``lib`` on PATH, plus GTK/GDK/SSL/Qt vars. Required for
        ``gtkwave.exe`` on Windows (YosysHQ: use environment.bat; there are
        no Windows wrappers).
        """
        env = os.environ.copy()
        root = self.get_oss_cad_suite_root()
        if not root:
            return env
        return self.apply_oss_cad_env(env, root)

    @staticmethod
    def apply_oss_cad_env(env: dict, root: str) -> dict:
        """Apply OSS CAD Suite environment variables onto ``env`` (in-place + return)."""
        root = os.path.abspath(root)
        # environment.bat uses YOSYSHQ_ROOT with a trailing separator
        yroot = root if root.endswith(("\\", "/")) else root + os.sep
        bin_dir = os.path.join(root, "bin")
        lib_dir = os.path.join(root, "lib")

        prefix_parts = []
        if os.path.isdir(bin_dir):
            prefix_parts.append(bin_dir)
        if os.path.isdir(lib_dir):
            prefix_parts.append(lib_dir)
        if prefix_parts:
            prefix = os.pathsep.join(prefix_parts)
            current = env.get("PATH", "")
            if not current.lower().startswith(prefix.lower()):
                env["PATH"] = prefix + os.pathsep + current

        env["YOSYSHQ_ROOT"] = yroot
        cert = os.path.join(root, "etc", "cacert.pem")
        if os.path.isfile(cert):
            env["SSL_CERT_FILE"] = cert
        py = os.path.join(root, "lib", "python3.exe")
        if os.path.isfile(py):
            env["PYTHON_EXECUTABLE"] = py

        # Suite builds ship qt5 plugins (see environment.ps1); fall back to qt6
        qt5 = os.path.join(root, "lib", "qt5", "plugins")
        qt6 = os.path.join(root, "lib", "qt6", "plugins")
        if os.path.isdir(qt5):
            env["QT_PLUGIN_PATH"] = qt5
        elif os.path.isdir(qt6):
            env["QT_PLUGIN_PATH"] = qt6
        env["QT_LOGGING_RULES"] = "*=false"

        env["GTK_EXE_PREFIX"] = yroot
        env["GTK_DATA_PREFIX"] = yroot
        pixbuf_dir = os.path.join(root, "lib", "gdk-pixbuf-2.0", "2.10.0", "loaders")
        pixbuf_cache = os.path.join(
            root, "lib", "gdk-pixbuf-2.0", "2.10.0", "loaders.cache"
        )
        if os.path.isdir(pixbuf_dir):
            env["GDK_PIXBUF_MODULEDIR"] = pixbuf_dir
        if os.path.isfile(pixbuf_cache) or os.path.isdir(os.path.dirname(pixbuf_cache)):
            env["GDK_PIXBUF_MODULE_FILE"] = pixbuf_cache

        soj = os.path.join(root, "share", "openFPGALoader")
        if os.path.isdir(soj):
            env["OPENFPGALOADER_SOJ_DIR"] = soj
        return env

    def run_in_oss_cad_env(
        self,
        args: List[str],
        *,
        timeout: int = 30,
        cwd: Optional[str] = None,
    ) -> subprocess.CompletedProcess:
        """Run a command with the OSS CAD environment active.

        On Windows this prefers ``call environment.bat && ...`` (the supported
        YosysHQ method). Falls back to applying the same env vars in-process.
        """
        root = self.get_oss_cad_suite_root()
        if not root:
            return subprocess.run(
                args,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                cwd=cwd,
            )

        if os.name == "nt":
            bat = os.path.join(root, "environment.bat")
            if os.path.isfile(bat):
                # Quote each arg for cmd.exe
                def _q(a: str) -> str:
                    if not a:
                        return '""'
                    if any(ch in a for ch in ' \t"&<>|^()'):
                        return '"' + a.replace('"', '\\"') + '"'
                    return a

                cmdline = "call {} && {}".format(_q(bat), " ".join(_q(a) for a in args))
                return subprocess.run(
                    cmdline,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=timeout,
                    cwd=cwd or root,
                    shell=True,
                )

        env = self.apply_oss_cad_env(os.environ.copy(), root)
        return subprocess.run(
            args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            cwd=cwd or os.path.join(root, "bin"),
            env=env,
        )

    def _tool_version_args(self, tool_name: str) -> List[str]:
        """Return CLI args used to probe a tool's version / availability."""
        if tool_name == "openfpgaloader":
            return ["--Version"]
        if tool_name == "gmpack":
            # gmpack does not support --version; --help prints the banner + usage
            return ["--help"]
        return ["--version"]

    def _extract_version_string(self, tool_name: str, stdout: str, stderr: str) -> str:
        """Parse a short human-readable version string from tool output."""
        text = "\n".join([stdout or "", stderr or ""]).strip()
        if not text:
            return ""

        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        if not lines:
            return ""

        if tool_name == "gmpack":
            for ln in lines:
                if "version" in ln.lower() and ("gatemate" in ln.lower() or "peppercorn" in ln.lower() or ln.lower().startswith("open source")):
                    return ln
            return lines[0][:120]

        if tool_name == "nextpnr_himbaechel":
            # e.g. "nextpnr-himbaechel" -- Next Generation Place and Route (Version nextpnr-0.11-...)
            for ln in lines:
                if "version" in ln.lower() or "nextpnr" in ln.lower():
                    return ln[:160]
            return lines[0][:160]

        if tool_name == "yosys":
            for ln in lines:
                if ln.lower().startswith("yosys"):
                    return ln[:160]
            return lines[0][:160]

        if tool_name == "ghdl":
            for ln in lines:
                if ln.lower().startswith("ghdl"):
                    return ln[:160]
            return lines[0][:160]

        return lines[0][:160]

    def _probe_tool_command(self, command: str, tool_name: str) -> Tuple[bool, str]:
        """Run a version/help probe. Returns (ok, version_string)."""
        if not command:
            return False, ""

        args = [command] + self._tool_version_args(tool_name)
        try:
            result = subprocess.run(
                args,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=self.get_tool_run_env(),
                timeout=20,
            )
        except FileNotFoundError:
            return False, ""
        except subprocess.TimeoutExpired:
            logging.debug(f"{tool_name} probe timed out: {args}")
            return False, ""
        except Exception as e:
            logging.debug(f"{tool_name} probe failed: {e}")
            return False, ""

        combined = (result.stdout or "") + (result.stderr or "")
        version = self._extract_version_string(tool_name, result.stdout or "", result.stderr or "")

        if tool_name == "gmpack":
            # --help / unknown option still prints the version banner; treat as available
            ok = (
                "gatemate" in combined.lower()
                or "peppercorn" in combined.lower()
                or "bitstream packer" in combined.lower()
                or "gmpack" in combined.lower()
                or result.returncode == 0
            )
            return ok, version

        # nextpnr prints version on stderr with exit 0; accept either stream
        if result.returncode == 0:
            return True, version

        # Some tools write useful version info even on non-zero (rare)
        if version and ("version" in version.lower() or tool_name.split("_")[0] in version.lower()):
            return True, version

        return False, ""

    def get_tool_version_string(self, tool_name: str, prefer: Optional[str] = None) -> str:
        """Return version string for a tool using PATH or DIRECT preference."""
        if tool_name not in self.__tool_chain:
            return ""

        preference = (prefer or self.get_tool_preference(tool_name) or "PATH").upper()
        candidates = []
        if preference == "DIRECT":
            tool_paths = self.config.get("cologne_chip_gatemate_toolchain_paths", {})
            direct = tool_paths.get(tool_name, "") or ""
            if direct:
                candidates.append(direct)
            candidates.append(self.__tool_chain[tool_name])
        else:
            candidates.append(self.__tool_chain[tool_name])
            tool_paths = self.config.get("cologne_chip_gatemate_toolchain_paths", {})
            direct = tool_paths.get(tool_name, "") or ""
            if direct:
                candidates.append(direct)

        seen = set()
        for cmd in candidates:
            if not cmd or cmd in seen:
                continue
            seen.add(cmd)
            ok, version = self._probe_tool_command(cmd, tool_name)
            if ok and version:
                return version
            if ok:
                return "Available"
        return ""

    def check_tool_version_path(self, tool_name: str) -> bool:
        """Check if a specific tool is available through PATH (with OSS CAD Suite env)."""
        if tool_name not in self.__tool_chain:
            return False
        ok, _ = self._probe_tool_command(self.__tool_chain[tool_name], tool_name)
        return ok

    def check_tool_version_direct(self, tool_name: str) -> bool:
        """Check if a specific tool is available through direct path (with OSS CAD Suite env)."""
        if tool_name not in self.__tool_chain:
            return False
        
        tool_paths = self.config.get("cologne_chip_gatemate_toolchain_paths", {})
        tool_path = tool_paths.get(tool_name, "") or ""
        
        if not tool_path or not os.path.exists(tool_path):
            return False

        ok, _ = self._probe_tool_command(tool_path, tool_name)
        return ok

    def get_tool_command(self, tool_name: str) -> str:
        """
        Get the command to execute a specific tool based on its preference.
        
        Args:
            tool_name (str): Name of the tool
            
        Returns:
            str: Command to execute the tool, or empty string if not available
        """
        if tool_name not in self.__tool_chain:
            logging.error(f"Unknown tool: {tool_name}")
            return ""
        
        preference = self.get_tool_preference(tool_name)
        
        tool_paths = self.config.get("cologne_chip_gatemate_toolchain_paths", {})
        configured = tool_paths.get(tool_name, "") or ""

        if preference == "DIRECT":
            if configured and os.path.exists(configured):
                return configured
            logging.warning(
                f"{tool_name} preference is DIRECT but path not found, falling back to PATH"
            )
            return self.__tool_chain[tool_name]
        elif preference == "PATH":
            # Prefer configured absolute path when PATH binary is not yet activated
            return self.__tool_chain[tool_name]
        else:
            if configured and os.path.exists(configured):
                return configured
            logging.warning(f"{tool_name} preference is {preference}, tool may not be available")
            return ""

    def check_toolchain_path(self) -> bool:
        """check if the colognechip gatemate toolchain is available through the PATH environment variable"""

        #Check if GHDL has been added to PATH
        logging.info("Checking if the GateMate toolchain is available through Windows PATH")

        tool_status = {}

        try:
            for tool in self.__tool_chain:
                logging.info(f"Checking if {tool} is available through windows PATH")
                status = self.check_tool_version(tool)
                tool_status[tool] = status
                if tool_status[tool]:
                    #print(f"{tool} returns OK.")
                    logging.info(f"{tool} returns OK through PATH.")
                else:
                    #print(f"{tool} returns FAIL.")
                    logging.error(f"{tool} returns FAIL through PATH.")
        except Exception as e:
            #print(f"An error occured when verifying the tool chain: {e}")
            logging.error(f"An error occured when verifying the tool chain: {e}")
        if all(tool_status.values()): #all() returns true if all values are truthy
            #print("CologneChip GateMate A1 toolchain reports OK through PATH.")
            logging.info("CologneChip GateMate A1 toolchain reports OK through PATH.")
            return True
        else:
            #print("A tool in CologneChip GateMate A1 toolchain failed through PATH.")
            logging.error("A tool in CologneChip GateMate A1 toolchain failed through PATH.")
            return False
    
    def check_toolchain_direct(self, override_exit : bool = False) -> bool:
        """check the direct file paths for access to the GateMate toolchain binaries
        use add_tool_path() to set tool paths in the configuration file.
        
        return 1 if ok
        """
         #Check if tool chain is available at the direct path
        logging.info("Checking if the GateMate toolchain binaries are available at the specified tool path in the configuration file.")

        for tool in self.__tool_chain:
            try:
                tool_path = self.config.get("cologne_chip_gatemate_toolchain_paths", {}).get(tool, "")
                if not os.path.exists(tool_path): #Check if the path exists
                    if not override_exit:
                        logging.error(f"{tool} is unavailable at {tool_path}. Reconfigure GateMate tool chain. Exit.")
                        #return False
                    else:
                        logging.error(f"{tool} is unavailable at {tool_path}. Reconfigure GateMate tool chain. override_exit is set, continuing.")
                ok, _ = self._probe_tool_command(tool_path, tool)
                if not ok:
                    logging.error(f"Invalid response from {tool} at {tool_path}. Reconfigure GateMate tool chain. Exit.")
                    return False
                logging.info(f"GateMate tool {tool} is confirmed working at {tool_path}")

            except Exception as e:
                logging.error(f"Checking {tool} at {tool_path} resulted in errors. {e}")
                return False
        
        logging.info("GateMate direct tool path check complete. All tools are available and OK.")
        return True
    
    def update_config(self) -> bool:
        """Update the configuration file with current config data."""
        try:
            if not self.config_path:
                # Expected before Create/Load Project — keep in-memory only
                logging.debug(
                    "No project configuration open; skipping save (in-memory only)."
                )
                return False
            with open(self.config_path, "w") as config_file:
                yaml.safe_dump(self.config, config_file)
            return True
        except Exception as e:
            logging.error(f"Failed to update configuration file: {e}")
            return False

    def set_toolchain_preference(self, preference: str = "PATH") -> bool:
        """
        Legacy method for backward compatibility. Sets all tools to the same preference.
        
        Args:
            preference (str): Toolchain access preference ("PATH", "DIRECT", "UNDEFINED")
            
        Returns:
            bool: True if successful, False otherwise
        """
        new_preference = preference.upper()
        supported_preferences = ("PATH", "DIRECT", "UNDEFINED")
        if new_preference not in supported_preferences:
            logging.error(f"Invalid preference {preference}. Must be one of: {supported_preferences}")
            return False
        
        # Set all tools to the same preference
        success = True
        for tool_name in self.__tool_chain:
            if not self.set_tool_preference(tool_name, new_preference):
                success = False
        
        logging.info(f"Set all tools to preference: {new_preference}")
        return success

    def check_ghdl_yosys_link(self) -> bool:
        """Verify the GateMate synthesis toolchain pieces used by this app.

        The OSS CAD Suite Yosys build does **not** ship a Yosys ``ghdl`` plugin.
        The supported flow is:

        1. Standalone GHDL (``ghdl synth ... --out=verilog``)
        2. OSS CAD Yosys ``synth_gatemate`` (with ``-luttree -nomx8``)

        This check therefore confirms GHDL is callable and that Yosys exposes
        ``synth_gatemate``, not that ``yosys -p "help ghdl"`` succeeds.
        """
        logging.info("Verifying GateMate synthesis flow: standalone GHDL + Yosys synth_gatemate.")

        ghdl_cmd = self.get_tool_command("ghdl")
        if not ghdl_cmd:
            logging.error("GHDL is not available - GateMate synthesis flow cannot run")
            return False

        ok_ghdl, ghdl_ver = self._probe_tool_command(ghdl_cmd, "ghdl")
        if not ok_ghdl:
            # Fall back to PATH / DIRECT probes
            if not (self.check_tool_version_path("ghdl") or self.check_tool_version_direct("ghdl")):
                logging.error("GHDL probe failed - GateMate synthesis flow cannot run")
                return False
        else:
            logging.info(f"Standalone GHDL OK: {ghdl_ver or ghdl_cmd}")

        yosys_access = self.get_tool_command("yosys")
        if not yosys_access:
            logging.error("Yosys is not available - cannot check synth_gatemate")
            return False

        try:
            result = subprocess.run(
                [yosys_access, "-p", "help synth_gatemate"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=self.get_tool_run_env(),
                timeout=30,
            )
        except Exception as e:
            logging.error(f"Failed to query Yosys for synth_gatemate: {e}")
            return False

        combined = f"{result.stdout or ''}\n{result.stderr or ''}"
        logging.info(f"Querying Yosys for synth_gatemate with: \"{yosys_access} -p 'help synth_gatemate'\"")
        if result.stdout:
            logging.info(f"Yosys STDOUT:\n{result.stdout}")
        if result.stderr:
            logging.info(f"Yosys STDERR:\n{result.stderr}")

        # Accept either help text for the pass or the typical option list
        keywords = (
            "synth_gatemate",
            "luttree",
            "nomx8",
            "gatemate",
            "-top",
            "-json",
        )
        if any(word.lower() in combined.lower() for word in keywords) and "no such command" not in combined.lower():
            logging.info("Yosys synth_gatemate is available (GateMate synthesis flow OK).")
            return True

        logging.warning(
            "Yosys does not appear to provide synth_gatemate. "
            "Install/use OSS CAD Suite Yosys for GateMate."
        )
        return False

    def check_gatemate_synth_flow_status(self) -> Dict[str, Any]:
        """Return a structured status for the Advanced Checks UI."""
        status: Dict[str, Any] = {
            "ok": False,
            "ghdl_ok": False,
            "yosys_ok": False,
            "message": "",
            "detail": "",
        }
        try:
            ghdl_cmd = self.get_tool_command("ghdl") or ""
            status["ghdl_ok"] = bool(
                ghdl_cmd and (self.check_tool_version_path("ghdl") or self.check_tool_version_direct("ghdl"))
            )
            yosys_cmd = self.get_tool_command("yosys") or ""
            yosys_probe_ok = False
            if yosys_cmd:
                result = subprocess.run(
                    [yosys_cmd, "-p", "help synth_gatemate"],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    env=self.get_tool_run_env(),
                    timeout=30,
                )
                combined = f"{result.stdout or ''}\n{result.stderr or ''}"
                yosys_probe_ok = (
                    "synth_gatemate" in combined.lower()
                    and "no such command" not in combined.lower()
                )
            status["yosys_ok"] = yosys_probe_ok
            status["ok"] = status["ghdl_ok"] and status["yosys_ok"]
            if status["ok"]:
                status["message"] = "GateMate synth flow: ✅ GHDL + Yosys synth_gatemate ready"
                status["detail"] = (
                    "Uses standalone GHDL (VHDL→Verilog) then OSS CAD Yosys "
                    "synth_gatemate -luttree -nomx8 (no Yosys ghdl plugin required)."
                )
            elif not status["ghdl_ok"] and not status["yosys_ok"]:
                status["message"] = "GateMate synth flow: ❌ GHDL and Yosys synth_gatemate unavailable"
            elif not status["ghdl_ok"]:
                status["message"] = "GateMate synth flow: ⚠️ GHDL missing (Yosys synth_gatemate OK)"
            else:
                status["message"] = "GateMate synth flow: ⚠️ Yosys synth_gatemate missing (GHDL OK)"
            return status
        except Exception as e:
            status["message"] = f"GateMate synth flow: ❌ Check failed ({e})"
            return status


    def add_tool_path(self, tool_name : str = None,  path : str = None) -> bool:
        """Adds a toolpath to the project configuration file
        tool_name must be in __tool_chain

        Syntax:
            path must be an absolute path to the tool executable.
            In YAML, backslashes must be escaped (e.g. "C:\\\\tools\\\\bin\\\\ghdl.exe").
        
        """
        #Verifying tool_name
        if tool_name not in self.__tool_chain:
            logging.error(f"{tool_name} is not listed in {self.__tool_chain}. The new tool is unsupported by toolchain manager. Exit")
            print(f"{tool_name} is not listed in {self.__tool_chain}. The new tool is unsupported by toolchain manager. Exit")
            return
        resolved_path = os.path.normpath(path.lower().strip()) #get absolute path and normalize to OS, remove case and strip whitespaces
        logging.info(f"Verifying toolpath for {tool_name} at {resolved_path}")

        #Checking if toolname matches tool binary name
        if not path.endswith(self.__tool_chain[tool_name]):
              logging.error(f"Mismatch between tool_name and tool binary name. Exit")
              return

        #Check if the path exists
        if not os.path.exists(resolved_path):
            logging.info(f"Toolpath does not exist for {tool_name} at {resolved_path}. Exit")
            return

        logging.info(f"Attempting to add {tool_name} to local config at {resolved_path}")
        # Append the new tool path to the tool path structure in the configuration file
        #check that the structure is A-ok
        if "cologne_chip_gatemate_toolchain_paths" not in self.config: 
            self.config["cologne_chip_gatemate_toolchain_paths"] = {}
            logging.warning("cologne_chip_gatemate_toolchain_paths didn't exist. Remaking it.")
        #initialize src if it doesnt exist
        if tool_name not in self.config["cologne_chip_gatemate_toolchain_paths"]:
            self.config["cologne_chip_gatemate_toolchain_paths"][tool_name] = ""
            logging.warning(f"{tool_name} didnt exist in cologne_chip_gatemate_toolchain_paths. Remaking it.")

        #add the new source as key value pair
        self.config["cologne_chip_gatemate_toolchain_paths"][tool_name] = resolved_path
        self.update_config()
        logging.info(f"Added {tool_name} at {resolved_path} to local config.")
        #logging.info(f"{tool_name} path set to {resolved_path}")
        return True

    def set_config_path_structure(self):
        """creates the path structure in the project configuration file"""

        # Seed empty keys from one-time Auto-Setup machine defaults when present.
        global_defaults = {}
        try:
            from .toolchain_autosetup import get_global_toolchain_defaults
            global_defaults = get_global_toolchain_defaults()
        except Exception:
            global_defaults = {}

        tool_path_structure = {
            tool: (
                global_defaults.get(tool)
                or self.DEFAULT_TOOL_PATHS.get(tool, "")
            )
            for tool in self.__tool_chain
        }

        if "cologne_chip_gatemate_toolchain_paths" in self.config:
            # Migrate older projects: ensure new keys exist; fill empties from Auto-Setup
            paths = self.config["cologne_chip_gatemate_toolchain_paths"]
            updated = False
            for tool, default_path in tool_path_structure.items():
                if tool not in paths:
                    paths[tool] = default_path
                    updated = True
                elif not paths.get(tool) and global_defaults.get(tool):
                    paths[tool] = global_defaults[tool]
                    updated = True
            if updated:
                logging.info("Updated toolchain path structure with Auto-Setup / OSS CAD defaults")
                self.update_config()
            return

        self.config["cologne_chip_gatemate_toolchain_paths"] = tool_path_structure

        if not self.config_path:
            # No project yet — seed in-memory defaults without alarming the user
            logging.debug(
                "Seeded toolchain path structure in memory (no project open yet)."
            )
            return

        try:
            logging.info(
                "Creating toolchain path structure in the project configuration file."
            )
            logging.info(
                f"Adding tool chain path structure {tool_path_structure} to local config"
            )
            with open(self.config_path, "w") as config_file:
                yaml.safe_dump(self.config, config_file)
        except Exception as e:
            logging.error(f"Failed to append tool_path_structure to the configuration file: {e}")

    def check_tool_version(self, tool_name: str = None) -> bool:
        """Checks if tool is available and logs the version using individual tool preference.
        
        Args:
            tool_name (str): The name of the tool. "ghdl", "yosys", "p_r", "openfpgaloader"
        Returns:
            bool: Returns True if OK, False otherwise.       
        """
        if tool_name not in self.__tool_chain:
            logging.error(f"Unsupported tool in tool check: {tool_name}, valid tools are {self.__tool_chain}")
            return False
        
        # Get the appropriate command based on individual tool preference
        tool_command = self.get_tool_command(tool_name)
        
        if not tool_command:
            logging.error(f"Tool command not available for {tool_name}")
            return False
        
        try:
            ok, version = self._probe_tool_command(tool_command, tool_name)
            if ok:
                logging.info(f"{tool_name} version check successful:\n{version}")
                return True
            preference = self.get_tool_preference(tool_name)
            if preference == "DIRECT":
                logging.error(f"Error: '{tool_name}' failed at direct path: {tool_command}")
            else:
                logging.error(f"Error: '{tool_command}' failed in PATH.")
            return False
        except FileNotFoundError:
            preference = self.get_tool_preference(tool_name)
            if preference == "DIRECT":
                logging.error(f"Error: '{tool_name}' not found at direct path: {tool_command}")
            else:
                logging.error(f"Error: '{tool_command}' not found in PATH.")
            return False


if __name__ == "__main__":
    """Manual smoke test: configure tools via Configuration / PATH, then check."""
    tcm = ToolChainManager()
    tcm.check_toolchain()
