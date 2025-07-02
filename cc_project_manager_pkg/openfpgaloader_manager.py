"""Handles openFPGALoader related commands and operations.

This module provides a manager class for openFPGALoader operations, including programming
FPGAs, reading device information, and managing bitstream loading for GateMate devices.
"""
import os
import yaml
import logging
import subprocess
from .toolchain_manager import ToolChainManager
from typing import List, Optional, Dict, Union, Tuple
from datetime import datetime
import glob

class OpenFPGALoaderManager(ToolChainManager):
    """Provides methods to work with openFPGALoader tool.
    
    This class encapsulates the functionality needed to interact with openFPGALoader,
    providing methods for programming FPGAs, device detection, bitstream loading,
    and configuration management for GateMate FPGA devices.
    
    The class supports multiple programming modes and device interfaces:
    
    1. JTAG - Standard JTAG interface programming
       Best for: Development and debugging with JTAG adapters
    
    2. SPI - Serial Peripheral Interface programming  
       Best for: Direct SPI flash programming
    
    3. Cable detection - Automatic cable and device detection
       Best for: Automatic setup and device identification
    
    openFPGALoader is a universal utility for programming FPGAs that supports
    many FPGA families including GateMate devices from Cologne Chip.
    """

    # Supported programming interfaces
    PROGRAMMING_INTERFACES = {
        "jtag": "JTAG interface programming",
        "spi": "SPI flash programming", 
        "auto": "Automatic interface detection"
    }
    
    # Supported GateMate devices
    SUPPORTED_DEVICES = {
        "gatemate": "GateMate FPGA (auto-detect)",
        "gatemate_a1": "GateMate A1 FPGA",
        "gatemate_evb": "GateMate Evaluation Board"
    }
    
    # Common programming modes
    PROGRAMMING_MODES = {
        "sram": "Program SRAM (volatile, lost on power cycle)",
        "flash": "Program flash memory (non-volatile, persistent)",
        "verify": "Verify programmed bitstream",
        "detect": "Detect connected devices and cables"
    }

    def __init__(self, interface: str = "auto", device: str = "gatemate", board_identifier: Optional[str] = None):
        """
        Initialize OpenFPGALoaderManager with interface, device, and board configuration.
        
        This manager handles openFPGALoader operations for programming GateMate FPGAs
        with various board configurations and programming modes.
        
        Args:
            interface: Programming interface - "jtag", "spi", or "auto"
            device: Target FPGA device type (e.g., "gatemate")  
            board_identifier: Board identifier for openFPGALoader (e.g., "olimex_gatemateevb")
        
        The class supports multiple interfaces and devices:
        - Interfaces: JTAG (standard debugging), SPI (direct flash), Auto (detection)
        - Devices: GateMate FPGAs and compatible devices
        - Boards: Both standard and custom board configurations
        """
        # Initialize parent class with project loading
        super().__init__()
        
        self.loader_logger = logging.getLogger("OpenFPGALoaderManager")
        self.loader_logger.setLevel(logging.DEBUG)
        self.loader_logger.propagate = False  # Prevent propagation to root logger

        # Remove existing handlers to prevent cross-project logging issues
        for handler in self.loader_logger.handlers[:]:
            self.loader_logger.removeHandler(handler)

        # Get log file path
        log_path = os.path.normpath(os.path.join(self.config["project_structure"]["logs"][0], "openfpgaloader.log"))
        file_handler = logging.FileHandler(log_path)
        formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
        file_handler.setFormatter(formatter)
        self.loader_logger.addHandler(file_handler)
        
        # Add openfpgaloader.log to project configuration
        self._add_loader_log()

        # Set interface
        if interface not in self.PROGRAMMING_INTERFACES:
            self.loader_logger.warning(f"Unknown interface \"{interface}\", defaulting to auto")
            self.interface = "auto"
        else:
            self.interface = interface
            
        # Set device
        if device not in self.SUPPORTED_DEVICES:
            self.loader_logger.warning(f"Unknown device \"{device}\", defaulting to gatemate")
            self.device = "gatemate"
        else:
            self.device = device
        
        # Set board identifier
        self.board_identifier = board_identifier

        # Get the bitstream directory path
        self.impl_dir = self.config["project_structure"]["impl"]
        self.bitstream_dir = self.impl_dir["bitstream"][0]
        
        # Ensure bitstream directory exists
        os.makedirs(self.bitstream_dir, exist_ok=True)
            
        # Get individual openfpgaloader preference, fallback to global preference for backward compatibility
        tool_prefs = self.config.get("cologne_chip_gatemate_tool_preferences", {})
        if "openfpgaloader" in tool_prefs:
            self.tool_access_mode = tool_prefs["openfpgaloader"]
        else:
            self.tool_access_mode = self.config.get("cologne_chip_gatemate_toolchain_preference", "PATH")
        self.loader_access = self._get_loader_access()
        
        # Load custom board configuration if using a custom board
        self.custom_board_config = self._load_custom_board_config()
        
        # ToolChainManager instantiation report
        self._report_instantiation()

    def _report_instantiation(self):
        """Log the current OpenFPGALoaderManager configuration settings."""
        tcm_settings = f"""
        New OpenFPGALoaderManager Instantiation Settings:
        PROGRAMMING_INTERFACE:   {self.interface}
        TARGET_DEVICE:           {self.device}
        BOARD_IDENTIFIER:        {self.board_identifier or 'None (using device)'}
        BITSTREAM_DIRECTORY:     {self.bitstream_dir}
        TOOL_CHAIN_PREFERENCE:   {self.tool_access_mode}
        TOOL_CHAIN_ACCESS:       {self.loader_access}
        """
        self.loader_logger.info(tcm_settings)

    def _get_loader_access(self) -> str:
        """
        Determine how to access the openFPGALoader binary based on the configured toolchain mode.

        Returns:
            str: Path or command used to invoke openFPGALoader tool.
        """
        loader_access = ""
        if self.tool_access_mode == "PATH":
            loader_access = "openFPGALoader.exe"  # Use correct binary name with .exe extension
            self.loader_logger.info(f"openFPGALoader is accessing binary through PATH: {loader_access}")
        elif self.tool_access_mode == "DIRECT":
            toolchain_path = self.config.get("cologne_chip_gatemate_toolchain_paths", {})
            loader_access = toolchain_path.get("openfpgaloader", "")
            self.loader_logger.info(f"openFPGALoader is accessing binary directly through {loader_access}")
            if not loader_access:
                self.loader_logger.warning("Direct path for openFPGALoader is empty, falling back to PATH")
                loader_access = "openFPGALoader.exe"
            elif not os.path.exists(loader_access):
                self.loader_logger.warning(f"Direct path for openFPGALoader does not exist: {loader_access}, falling back to PATH")
                loader_access = "openFPGALoader.exe"
        elif self.tool_access_mode == "UNDEFINED":
            self.loader_logger.error(f"openFPGALoader access mode is undefined. There is a problem in toolchain manager.")
            self.loader_logger.info("Falling back to PATH access")
            loader_access = "openFPGALoader.exe"
        else:
            # Fallback for any unexpected values - default to PATH access
            self.loader_logger.warning(f"Unexpected tool access mode '{self.tool_access_mode}', defaulting to PATH access")
            loader_access = "openFPGALoader.exe"

        self.loader_logger.debug(f"Final loader access command: {loader_access}")
        return loader_access

    def _load_custom_board_config(self) -> Optional[Dict]:
        """
        Load custom board configuration if the device is a custom board.
        
        Returns:
            Dict with custom board configuration or None if not a custom board
        """
        try:
            from .boards_manager import BoardsManager
            boards_manager = BoardsManager()
            
            # Get board details for the current device
            board_details = boards_manager.get_board_details(self.device)
            if board_details and board_details.get('custom_board', False):
                self.loader_logger.info(f"Using custom board configuration for {self.device}")
                return board_details
            
            return None
            
        except Exception as e:
            self.loader_logger.debug(f"Could not load custom board config: {e}")
            return None
    
    def _build_base_command(self, operation_type: str = "program", additional_options: Optional[List[str]] = None) -> List[str]:
        """
        Build base command for openFPGALoader operations with custom board support.
        
        Args:
            operation_type: Type of operation ("program", "detect", "verify", etc.)
            additional_options: Additional command-line options
            
        Returns:
            List of command components
        """
        cmd = [self.loader_access]
        
        # Add additional options early in the command
        if additional_options:
            cmd.extend(additional_options)
        
        # Handle custom boards differently
        if self.custom_board_config:
            # Use cable-based approach for custom boards
            cable_type = self.custom_board_config.get('cable_type', 'cmsisdap')
            cmd.extend(["-c", cable_type])
            
            # Add USB device selection parameters
            usb_config = self.custom_board_config.get('usb_device_selection', {})
            
            if usb_config.get('vid') and usb_config.get('pid'):
                cmd.extend(["--vid", usb_config['vid']])
                cmd.extend(["--pid", usb_config['pid']])
                self.loader_logger.debug(f"Using USB VID:PID {usb_config['vid']}:{usb_config['pid']}")
            
            if usb_config.get('cable_index'):
                cmd.extend(["--cable-index", str(usb_config['cable_index'])])
                self.loader_logger.debug(f"Using cable index {usb_config['cable_index']}")
            
            if usb_config.get('bus') and usb_config.get('device'):
                cmd.extend(["--busdev-num", f"{usb_config['bus']}:{usb_config['device']}"])
                self.loader_logger.debug(f"Using bus:device {usb_config['bus']}:{usb_config['device']}")
            
            if usb_config.get('ftdi_serial'):
                cmd.extend(["--ftdi-serial", usb_config['ftdi_serial']])
                self.loader_logger.debug(f"Using FTDI serial {usb_config['ftdi_serial']}")
            
            if usb_config.get('ftdi_channel'):
                cmd.extend(["--ftdi-channel", str(usb_config['ftdi_channel'])])
                self.loader_logger.debug(f"Using FTDI channel {usb_config['ftdi_channel']}")
            
            # Add custom parameters
            if 'pin_mapping' in self.custom_board_config:
                cmd.extend(["--pins", self.custom_board_config['pin_mapping']])
            
            if 'jtag_frequency' in self.custom_board_config:
                cmd.extend(["--freq", str(self.custom_board_config['jtag_frequency'])])
            
            if 'fpga_part' in self.custom_board_config:
                cmd.extend(["--fpga-part", self.custom_board_config['fpga_part']])
                
            self.loader_logger.debug(f"Using custom board cable configuration: {cable_type}")
        else:
            # Use standard board-based approach
            board_to_use = self.board_identifier or self.device
            cmd.extend(["-b", board_to_use])
            
            # Add interface specification if not auto
            if self.interface != "auto":
                cmd.extend(["--cable", self.interface])
        
        return cmd

    def scan_usb_devices(self) -> List[Dict[str, str]]:
        """
        Scan for connected USB devices that can be used with openFPGALoader.
        
        Returns:
            List of dictionaries containing device information
        """
        devices = []
        
        try:
            # Run USB scan command
            scan_cmd = [self.loader_access, "--scan-usb"]
            self.loader_logger.debug(f"USB scan command: {' '.join(scan_cmd)}")
            
            result = subprocess.run(scan_cmd, capture_output=True, text=True, timeout=30)
            
            if result.returncode == 0 and result.stdout:
                # Parse the output to extract device information
                devices = self._parse_usb_scan_output(result.stdout)
                self.loader_logger.info(f"Found {len(devices)} USB devices")
            else:
                self.loader_logger.warning(f"USB scan failed or returned no devices")
                if result.stderr:
                    self.loader_logger.debug(f"USB scan stderr: {result.stderr}")
                    
        except subprocess.TimeoutExpired:
            self.loader_logger.error("USB scan timed out")
        except Exception as e:
            self.loader_logger.error(f"USB scan failed: {e}")
        
        return devices
    
    def _parse_usb_scan_output(self, output: str) -> List[Dict[str, str]]:
        """
        Parse openFPGALoader --scan-usb output to extract device information.
        
        Args:
            output: Raw output from --scan-usb command
            
        Returns:
            List of device dictionaries with parsed information
        """
        devices = []
        
        try:
            lines = output.strip().split('\n')
            
            for line in lines:
                line = line.strip()
                if not line or line.startswith('#') or line.startswith('USB'):
                    continue
                    
                # Try to parse different formats of USB device listings
                device_info = {}
                
                # Look for VID:PID pattern
                if 'vid:' in line.lower() and 'pid:' in line.lower():
                    # Extract VID and PID
                    import re
                    vid_match = re.search(r'vid:\s*([0-9a-fA-F]+)', line, re.IGNORECASE)
                    pid_match = re.search(r'pid:\s*([0-9a-fA-F]+)', line, re.IGNORECASE)
                    
                    if vid_match and pid_match:
                        device_info['vid'] = vid_match.group(1)
                        device_info['pid'] = pid_match.group(1)
                
                # Look for bus:device pattern
                bus_dev_match = re.search(r'bus:\s*(\d+)\s*dev:\s*(\d+)', line, re.IGNORECASE)
                if bus_dev_match:
                    device_info['bus'] = bus_dev_match.group(1)
                    device_info['device'] = bus_dev_match.group(2)
                
                # Look for serial number
                if 'serial' in line.lower():
                    serial_match = re.search(r'serial:\s*([^\s]+)', line, re.IGNORECASE)
                    if serial_match:
                        device_info['serial'] = serial_match.group(1)
                
                # Try to identify the device type/name
                if 'cmsis' in line.lower():
                    device_info['type'] = 'cmsisdap'
                    device_info['name'] = 'CMSIS-DAP'
                elif 'ftdi' in line.lower() or 'ft232' in line.lower() or 'ft231' in line.lower():
                    device_info['type'] = 'ftdi'
                    if 'ft232' in line.lower():
                        device_info['name'] = 'FTDI FT232'
                    elif 'ft231' in line.lower():
                        device_info['name'] = 'FTDI FT231'
                    else:
                        device_info['name'] = 'FTDI Device'
                elif 'jlink' in line.lower():
                    device_info['type'] = 'jlink'
                    device_info['name'] = 'Segger J-Link'
                elif 'digilent' in line.lower():
                    device_info['type'] = 'digilent'
                    device_info['name'] = 'Digilent'
                else:
                    device_info['type'] = 'unknown'
                    device_info['name'] = 'Unknown Device'
                
                # Add raw line for reference
                device_info['raw'] = line
                
                # Only add if we found at least VID/PID or bus/device
                if device_info.get('vid') or device_info.get('bus'):
                    devices.append(device_info)
                    
        except Exception as e:
            self.loader_logger.error(f"Error parsing USB scan output: {e}")
        
        return devices

    def _add_loader_log(self):
        """Add openFPGALoader log file to project configuration."""
        try:
            if "logs" not in self.config:
                self.config["logs"] = {}
            
            if "openfpgaloader" not in self.config["logs"]:
                self.config["logs"]["openfpgaloader"] = {}
            
            log_path = os.path.normpath(os.path.join(self.config["project_structure"]["logs"][0], "openfpgaloader.log"))
            self.config["logs"]["openfpgaloader"]["openfpgaloader.log"] = log_path
            
            # Write updated config
            with open(self.config_path, "w") as config_file:
                yaml.safe_dump(self.config, config_file)
                
        except Exception as e:
            self.loader_logger.error(f"Failed to add openFPGALoader log to project configuration: {e}")

    def detect_devices(self) -> bool:
        """
        Detect connected FPGA devices and programming cables.
        
        This function scans for available programming interfaces and connected
        FPGA devices, providing information about what hardware is available
        for programming operations.
        
        For GateMate FPGAs, this uses the command:
        openFPGALoader --detect -b <board>
        
        Returns:
            bool: True if detection successful, False otherwise
            
        Example:
            ```python
            loader = OpenFPGALoaderManager()
            if loader.detect_devices():
                print("Devices detected successfully")
            ```
        """
        self.loader_logger.info("Detecting connected FPGA devices and cables...")
        
        # Build detection command using the base command builder
        detect_cmd = self._build_base_command("detect", ["--detect"])
        
        self.loader_logger.debug(f"Detection command: {' '.join(detect_cmd)}")
        
        try:
            result = subprocess.run(detect_cmd, check=True, capture_output=True, text=True, timeout=30)
            if result.stdout:
                self.loader_logger.info(f"Device detection output:\n{result.stdout}")
            if result.stderr:
                self.loader_logger.info(f"Device detection stderr:\n{result.stderr}")
            
            self.loader_logger.info("Device detection completed successfully")
            return True
            
        except subprocess.TimeoutExpired:
            self.loader_logger.error("Device detection timed out (30 seconds)")
            return False
        except subprocess.CalledProcessError as e:
            self.loader_logger.error(f"Device detection failed: {e}")
            if e.stdout:
                self.loader_logger.error(f"STDOUT: {e.stdout}")
            if e.stderr:
                self.loader_logger.error(f"STDERR: {e.stderr}")
            return False

    def program_sram(self, bitstream_file: Optional[str] = None, design_name: Optional[str] = None,
                     options: Optional[List[str]] = None) -> bool:
        """
        Program FPGA SRAM with a bitstream file (volatile programming).
        
        SRAM programming loads the bitstream directly into the FPGA's configuration
        memory. This is volatile - the configuration is lost when power is removed.
        This mode is ideal for development and testing.
        
        For GateMate FPGAs, this uses the command:
        openFPGALoader -b <board> <bitstream.cdf>
        
        Args:
            bitstream_file: Path to bitstream file. If None, looks for design_name.cdf in bitstream directory
            design_name: Name of the design (used to find bitstream file if bitstream_file is None)
            options: Additional command-line options for openFPGALoader
                
        Common openFPGALoader options include:
            `--cable CABLE`:       Specify programming cable
            `--freq FREQUENCY`:    Set programming frequency
            `--verbose`:           Enable verbose output
            `--reset`:             Reset device before programming
            
        Returns:
            bool: True if programming successful, False otherwise
            
        Example:
            ```python
            loader = OpenFPGALoaderManager()
            # Program with specific bitstream file
            loader.program_sram("counter.cdf")
            
            # Program using design name (looks for counter.cdf)
            loader.program_sram(design_name="counter")
            
            # Program with additional options
            loader.program_sram("counter.cdf", options=["--verbose", "--reset"])
            ```
        """
        # Determine bitstream file
        if bitstream_file is None:
            if design_name is None:
                self.loader_logger.error("Either bitstream_file or design_name must be provided")
                return False
            # Look for .cdf files first (GateMate format), then .bit files
            cdf_file = os.path.join(self.bitstream_dir, f"{design_name}.cdf")
            bit_file = os.path.join(self.bitstream_dir, f"{design_name}.bit")
            if os.path.exists(cdf_file):
                bitstream_file = cdf_file
            elif os.path.exists(bit_file):
                bitstream_file = bit_file
            else:
                self.loader_logger.error(f"No bitstream file found for design '{design_name}' (.cdf or .bit)")
                return False
        
        if not os.path.exists(bitstream_file):
            self.loader_logger.error(f"Bitstream file not found: {bitstream_file}")
            return False

        self.loader_logger.info(f"Programming FPGA SRAM with bitstream: {bitstream_file}")
        
        # Build base command with SRAM programming flag
        base_options = ["-m"]  # or --write-sram
        if options:
            base_options.extend(options)
        
        program_cmd = self._build_base_command("program", base_options)
        
        # Add bitstream file (must be last)
        program_cmd.append(bitstream_file)
            
        self.loader_logger.debug(f"SRAM programming command: {' '.join(program_cmd)}")
        
        try:
            # Use real-time output capture for progress tracking
            result = self._run_with_progress_capture(program_cmd, timeout=60, operation="SRAM Programming")
            
            if result:
                self.loader_logger.info(f"Successfully programmed FPGA SRAM with {bitstream_file}")
                return True
            else:
                self.loader_logger.error(f"SRAM programming failed")
                return False
            
        except subprocess.TimeoutExpired:
            self.loader_logger.error("SRAM programming timed out (60 seconds)")
            return False
        except Exception as e:
            self.loader_logger.error(f"SRAM programming failed: {e}")
            return False

    def program_flash(self, bitstream_file: Optional[str] = None, design_name: Optional[str] = None,
                      options: Optional[List[str]] = None) -> bool:
        """
        Program FPGA flash memory with a bitstream file (non-volatile programming).
        
        Flash programming writes the bitstream to non-volatile flash memory.
        The configuration persists through power cycles and the FPGA will
        automatically configure itself on power-up. This mode is used for
        production deployment.
        
        For GateMate FPGAs, this uses the command:
        openFPGALoader -f -b <board> <bitstream.cdf>
        
        Args:
            bitstream_file: Path to bitstream file. If None, looks for design_name.cdf in bitstream directory
            design_name: Name of the design (used to find bitstream file if bitstream_file is None)
            options: Additional command-line options for openFPGALoader
                
        Returns:
            bool: True if programming successful, False otherwise
            
        Example:
            ```python
            loader = OpenFPGALoaderManager()
            # Program flash with specific bitstream file
            loader.program_flash("counter.cdf")
            
            # Program flash using design name
            loader.program_flash(design_name="counter")
            ```
        """
        # Determine bitstream file
        if bitstream_file is None:
            if design_name is None:
                self.loader_logger.error("Either bitstream_file or design_name must be provided")
                return False
            # Look for .cdf files first (GateMate format), then .bit files
            cdf_file = os.path.join(self.bitstream_dir, f"{design_name}.cdf")
            bit_file = os.path.join(self.bitstream_dir, f"{design_name}.bit")
            if os.path.exists(cdf_file):
                bitstream_file = cdf_file
            elif os.path.exists(bit_file):
                bitstream_file = bit_file
            else:
                self.loader_logger.error(f"No bitstream file found for design '{design_name}' (.cdf or .bit)")
                return False
        
        if not os.path.exists(bitstream_file):
            self.loader_logger.error(f"Bitstream file not found: {bitstream_file}")
            return False

        self.loader_logger.info(f"Programming FPGA flash with bitstream: {bitstream_file}")
        
        # Build base command with flash programming flag
        base_options = ["-f"]  # or --write-flash
        if options:
            base_options.extend(options)
        
        program_cmd = self._build_base_command("program", base_options)
        
        # Add bitstream file (must be last)
        program_cmd.append(bitstream_file)
            
        self.loader_logger.debug(f"Flash programming command: {' '.join(program_cmd)}")
        
        try:
            # Use real-time output capture for progress tracking
            result = self._run_with_progress_capture(program_cmd, timeout=120, operation="Flash Programming")
            
            if result:
                self.loader_logger.info(f"Successfully programmed FPGA flash with {bitstream_file}")
                return True
            else:
                self.loader_logger.error(f"Flash programming failed")
                return False
            
        except subprocess.TimeoutExpired:
            self.loader_logger.error("Flash programming timed out (120 seconds)")
            return False
        except Exception as e:
            self.loader_logger.error(f"Flash programming failed: {e}")
            return False

    def verify_bitstream(self, bitstream_file: Optional[str] = None, design_name: Optional[str] = None,
                         options: Optional[List[str]] = None) -> bool:
        """
        Verify that the programmed bitstream matches the source file.
        
        This function reads back the configuration from the FPGA and compares
        it with the source bitstream file to ensure programming was successful.
        
        For GateMate FPGAs, this uses the command:
        openFPGALoader --verify -b <board> <bitstream.cdf>
        
        Args:
            bitstream_file: Path to bitstream file. If None, looks for design_name.cdf in bitstream directory
            design_name: Name of the design (used to find bitstream file if bitstream_file is None)
            options: Additional command-line options for openFPGALoader
                
        Returns:
            bool: True if verification successful, False otherwise
            
        Example:
            ```python
            loader = OpenFPGALoaderManager()
            # Verify programmed bitstream
            if loader.verify_bitstream("counter.cdf"):
                print("Bitstream verification passed")
            ```
        """
        # Determine bitstream file
        if bitstream_file is None:
            if design_name is None:
                self.loader_logger.error("Either bitstream_file or design_name must be provided")
                return False
            # Look for .cdf files first (GateMate format), then .bit files
            cdf_file = os.path.join(self.bitstream_dir, f"{design_name}.cdf")
            bit_file = os.path.join(self.bitstream_dir, f"{design_name}.bit")
            if os.path.exists(cdf_file):
                bitstream_file = cdf_file
            elif os.path.exists(bit_file):
                bitstream_file = bit_file
            else:
                self.loader_logger.error(f"No bitstream file found for design '{design_name}' (.cdf or .bit)")
                return False
        
        if not os.path.exists(bitstream_file):
            self.loader_logger.error(f"Bitstream file not found: {bitstream_file}")
            return False

        self.loader_logger.info(f"Verifying FPGA bitstream: {bitstream_file}")
        
        # Build base command with verification flag
        base_options = ["--verify"]
        if options:
            base_options.extend(options)
        
        verify_cmd = self._build_base_command("verify", base_options)
        
        # Add bitstream file (must be last)
        verify_cmd.append(bitstream_file)
            
        self.loader_logger.debug(f"Verification command: {' '.join(verify_cmd)}")
        
        try:
            # Use real-time output capture for progress tracking
            result = self._run_with_progress_capture(verify_cmd, timeout=60, operation="Verification")
            
            if result:
                self.loader_logger.info(f"Successfully verified bitstream {bitstream_file}")
                return True
            else:
                self.loader_logger.error(f"Bitstream verification failed")
                return False
            
        except subprocess.TimeoutExpired:
            self.loader_logger.error("Bitstream verification timed out (60 seconds)")
            return False
        except Exception as e:
            self.loader_logger.error(f"Bitstream verification failed: {e}")
            return False

    def get_device_info(self, options: Optional[List[str]] = None) -> bool:
        """
        Get information about connected FPGA devices.
        
        This function queries connected devices for detailed information
        including device ID, manufacturer, and other relevant details.
        
        Args:
            options: Additional command-line options for openFPGALoader
                
        Returns:
            bool: True if device info retrieval successful, False otherwise
            
        Example:
            ```python
            loader = OpenFPGALoaderManager()
            loader.get_device_info()
            ```
        """
        self.loader_logger.info("Getting FPGA device information...")
        
        # Build info command
        info_cmd = [self.loader_access, "--read-register", "0"]  # Read a register to get device info
        
        # Add device specification if not auto
        if self.device != "gatemate":
            info_cmd.extend(["--board", self.device])
        
        # Add interface specification if not auto
        if self.interface != "auto":
            info_cmd.extend(["--cable", self.interface])
        
        # Add any additional options
        if options:
            info_cmd.extend(options)
            
        self.loader_logger.debug(f"Device info command: {' '.join(info_cmd)}")
        
        try:
            result = subprocess.run(info_cmd, check=True, capture_output=True, text=True)
            if result.stdout:
                self.loader_logger.info(f"Device info output:\n{result.stdout}")
            if result.stderr:
                self.loader_logger.info(f"Device info stderr:\n{result.stderr}")
            
            self.loader_logger.info("Successfully retrieved device information")
            return True
            
        except subprocess.CalledProcessError as e:
            self.loader_logger.error(f"Device info retrieval failed: {e}")
            if e.stdout:
                self.loader_logger.error(f"STDOUT: {e.stdout}")
            if e.stderr:
                self.loader_logger.error(f"STDERR: {e.stderr}")
            return False

    def reset_device(self, options: Optional[List[str]] = None) -> bool:
        """
        Reset the connected FPGA device.
        
        This function sends a reset command to the FPGA, which can be useful
        for clearing the current configuration or preparing for new programming.
        
        Args:
            options: Additional command-line options for openFPGALoader
                
        Returns:
            bool: True if reset successful, False otherwise
            
        Example:
            ```python
            loader = OpenFPGALoaderManager()
            loader.reset_device()
            ```
        """
        self.loader_logger.info("Resetting FPGA device...")
        
        # Build reset command
        reset_cmd = [self.loader_access, "--reset"]
        
        # Add device specification if not auto
        if self.device != "gatemate":
            reset_cmd.extend(["--board", self.device])
        
        # Add interface specification if not auto
        if self.interface != "auto":
            reset_cmd.extend(["--cable", self.interface])
        
        # Add any additional options
        if options:
            reset_cmd.extend(options)
            
        self.loader_logger.debug(f"Reset command: {' '.join(reset_cmd)}")
        
        try:
            result = subprocess.run(reset_cmd, check=True, capture_output=True, text=True)
            if result.stdout:
                self.loader_logger.info(f"Reset output:\n{result.stdout}")
            if result.stderr:
                self.loader_logger.info(f"Reset stderr:\n{result.stderr}")
            
            self.loader_logger.info("Successfully reset FPGA device")
            return True
            
        except subprocess.CalledProcessError as e:
            self.loader_logger.error(f"Device reset failed: {e}")
            if e.stdout:
                self.loader_logger.error(f"STDOUT: {e.stdout}")
            if e.stderr:
                self.loader_logger.error(f"STDERR: {e.stderr}")
            return False

    def list_supported_devices(self) -> bool:
        """
        List all devices supported by openFPGALoader.
        
        This function queries openFPGALoader for a list of all supported
        FPGA devices and programming interfaces.
        
        Returns:
            bool: True if listing successful, False otherwise
            
        Example:
            ```python
            loader = OpenFPGALoaderManager()
            loader.list_supported_devices()
            ```
        """
        self.loader_logger.info("Listing supported devices...")
        
        # Build list command
        list_cmd = [self.loader_access, "--list-boards"]
        
        self.loader_logger.debug(f"List devices command: {' '.join(list_cmd)}")
        
        try:
            result = subprocess.run(list_cmd, check=True, capture_output=True, text=True)
            if result.stdout:
                self.loader_logger.info(f"Supported devices:\n{result.stdout}")
            if result.stderr:
                self.loader_logger.info(f"List stderr:\n{result.stderr}")
            
            self.loader_logger.info("Successfully listed supported devices")
            return True
            
        except subprocess.CalledProcessError as e:
            self.loader_logger.error(f"Device listing failed: {e}")
            if e.stdout:
                self.loader_logger.error(f"STDOUT: {e.stdout}")
            if e.stderr:
                self.loader_logger.error(f"STDERR: {e.stderr}")
            return False

    def get_bitstream_files(self) -> List[str]:
        """
        Get a list of available bitstream files in the bitstream directory.
        
        Returns:
            List[str]: List of bitstream file paths
            
        Example:
            ```python
            loader = OpenFPGALoaderManager()
            bitstreams = loader.get_bitstream_files()
            for bitstream in bitstreams:
                print(f"Found bitstream: {bitstream}")
            ```
        """
        bitstream_files = []
        
        # Look for common bitstream file extensions
        extensions = ["*.bit", "*.bin", "*.cfg"]
        
        for ext in extensions:
            pattern = os.path.join(self.bitstream_dir, ext)
            bitstream_files.extend(glob.glob(pattern))
        
        self.loader_logger.info(f"Found {len(bitstream_files)} bitstream files in {self.bitstream_dir}")
        for bf in bitstream_files:
            self.loader_logger.debug(f"  {bf}")
        
        return bitstream_files

    def get_tool_version(self) -> str:
        """
        Get openFPGALoader version information.
        
        Returns:
            str: Version information string
            
        Example:
            ```python
            loader = OpenFPGALoaderManager()
            version = loader.get_tool_version()
            print(f"openFPGALoader version: {version}")
            ```
        """
        self.loader_logger.info("Getting openFPGALoader version...")
        
        # Build version command - openFPGALoader uses --Version (capital V)
        version_cmd = [self.loader_access, "--Version"]
        
        self.loader_logger.debug(f"Version command: {' '.join(version_cmd)}")
        
        try:
            result = subprocess.run(version_cmd, check=True, capture_output=True, text=True)
            version_info = result.stdout.strip() if result.stdout else "Version information not available"
            
            if result.stderr:
                self.loader_logger.debug(f"Version stderr:\n{result.stderr}")
            
            self.loader_logger.info(f"openFPGALoader version: {version_info}")
            return version_info
            
        except subprocess.CalledProcessError as e:
            error_msg = f"Failed to get version: {e}"
            self.loader_logger.error(error_msg)
            if e.stdout:
                self.loader_logger.error(f"STDOUT: {e.stdout}")
            if e.stderr:
                self.loader_logger.error(f"STDERR: {e.stderr}")
            return error_msg
        except FileNotFoundError:
            error_msg = f"openFPGALoader not found: {self.loader_access}"
            self.loader_logger.error(error_msg)
            return error_msg

    def _run_with_progress_capture(self, cmd: List[str], timeout: int = 60, operation: str = "Operation") -> bool:
        """
        Run openFPGALoader command with real-time progress capture.
        
        This method captures output in real-time and can be used to provide
        progress feedback to the GUI during programming operations.
        
        Args:
            cmd: Command list to execute
            timeout: Timeout in seconds
            operation: Operation name for logging
            
        Returns:
            bool: True if command successful, False otherwise
        """
        import threading
        import queue
        import time
        
        self.loader_logger.debug(f"{operation} command: {' '.join(cmd)}")
        
        try:
            # Create process with real-time output capture
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,  # Combine stderr with stdout
                text=True,
                bufsize=1,  # Line buffered
                universal_newlines=True
            )
            
            # Queue to collect output lines
            output_queue = queue.Queue()
            
            def read_output():
                """Read output lines and put them in queue."""
                try:
                    for line in iter(process.stdout.readline, ''):
                        if line:
                            output_queue.put(line.rstrip())
                    process.stdout.close()
                except Exception as e:
                    self.loader_logger.debug(f"Error reading output: {e}")
            
            # Start output reading thread
            output_thread = threading.Thread(target=read_output)
            output_thread.daemon = True
            output_thread.start()
            
            # Monitor process and collect output
            start_time = time.time()
            all_output = []
            
            while process.poll() is None:
                # Check for timeout
                if time.time() - start_time > timeout:
                    process.terminate()
                    process.wait(timeout=5)
                    raise subprocess.TimeoutExpired(cmd, timeout)
                
                # Collect any available output
                try:
                    while True:
                        line = output_queue.get_nowait()
                        all_output.append(line)
                        self.loader_logger.info(f"{operation}: {line}")
                        
                        # Look for progress indicators and log them
                        if any(indicator in line.lower() for indicator in 
                               ['%', 'programming', 'erasing', 'writing', 'verifying', 'done']):
                            self.loader_logger.info(f"Progress: {line}")
                            
                except queue.Empty:
                    pass
                
                # Small delay to prevent busy waiting
                time.sleep(0.1)
            
            # Collect any remaining output
            try:
                while True:
                    line = output_queue.get_nowait()
                    all_output.append(line)
                    self.loader_logger.info(f"{operation}: {line}")
            except queue.Empty:
                pass
            
            # Wait for output thread to finish
            output_thread.join(timeout=2)
            
            # Check return code
            return_code = process.returncode
            
            if return_code == 0:
                self.loader_logger.info(f"{operation} completed successfully")
                return True
            else:
                self.loader_logger.error(f"{operation} failed with return code {return_code}")
                if all_output:
                    self.loader_logger.error(f"Full output:\n" + "\n".join(all_output))
                return False
                
        except subprocess.TimeoutExpired:
            self.loader_logger.error(f"{operation} timed out after {timeout} seconds")
            return False
        except Exception as e:
            self.loader_logger.error(f"{operation} failed: {e}")
            return False