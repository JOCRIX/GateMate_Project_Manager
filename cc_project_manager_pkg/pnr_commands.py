"""Handles Cologne Chip Place and Route (P&R) related commands and operations.

This module provides a manager class for Cologne Chip P&R operations, including place and route,
bitstream generation, timing analysis, and post-implementation netlist generation for VHDL designs.
"""
import os
import yaml
import logging
import subprocess
from .toolchain_manager import ToolChainManager
from typing import List, Optional, Dict, Union, Tuple
from datetime import datetime
import glob
import shutil

class PnRCommands(ToolChainManager):
    """Provides methods to work with Cologne Chip Place and Route tool.
    
    This class encapsulates the functionality needed to interact with the Cologne Chip P&R tool,
    providing methods for placing, routing, bitstream generation, timing analysis, and post-implementation
    netlist generation for GateMate FPGA designs.
    
    The class supports multiple implementation strategies, each optimized for different goals:
    
    1. speed - Optimize for maximum clock frequency and performance
       Best for: High-performance designs where timing is critical
    
    2. area - Optimize for minimal resource usage 
       Best for: Designs with tight area constraints or to fit in smaller FPGAs
    
    3. balanced - Standard optimization balancing area and speed (default)
       Best for: General-purpose designs with no extreme constraints
    
    4. power - Optimize for minimal power consumption
       Best for: Battery-powered or low-power applications
       
    5. congestion - Optimize for routing congestion relief
       Best for: Dense designs with routing challenges
       
    6. custom - User-defined strategy with custom parameters
       Best for: Advanced users who need precise control over implementation
    """

    # P&R implementation strategies
    IMPLEMENTATION_STRATEGIES = {
        "speed": {
            "effort": "high",
            "place_effort": "high", 
            "route_effort": "high",
            "timing_driven": True,
            "congestion_driven": False
        },
        "area": {
            "effort": "medium",
            "place_effort": "medium",
            "route_effort": "medium", 
            "timing_driven": False,
            "congestion_driven": True
        },
        "balanced": {
            "effort": "medium",
            "place_effort": "medium",
            "route_effort": "medium",
            "timing_driven": True,
            "congestion_driven": True
        },
        "power": {
            "effort": "medium",
            "place_effort": "low",
            "route_effort": "medium",
            "timing_driven": False,
            "congestion_driven": False
        },
        "congestion": {
            "effort": "high",
            "place_effort": "high",
            "route_effort": "high", 
            "timing_driven": False,
            "congestion_driven": True
        },
        "custom": {
            "effort": "medium",
            "place_effort": "medium",
            "route_effort": "medium",
            "timing_driven": True,
            "congestion_driven": True
        }
    }
    
    # Available device families for GateMate
    DEVICE_FAMILIES = {
        "gatemate": "gatemate",  # Default GateMate FPGA family
        "a1": "gatemate_a1",     # GateMate A1 family (if specific targeting needed)
    }
    
    # Available output formats for netlists
    NETLIST_FORMATS = {
        "vhdl": ".vhd",
        "verilog": ".v", 
        "json": ".json",
        "blif": ".blif"
    }

    def __init__(self, strategy: str = "balanced", device_family: str = "gatemate"):
        """
        Initialize the P&R command utility with default options.
        
        Creates a PnRCommands instance that manages Cologne Chip P&R operations for GateMate FPGA designs.
        The instance will use the project configuration to determine paths for inputs and outputs,
        and will apply the specified implementation strategy when processing designs.
        
        The default implementation strategy is "balanced", which provides a good compromise between
        area efficiency and performance for most designs. Other strategies include:
        
        - "speed": Focuses on maximizing design performance and clock frequency
        - "area": Focuses on minimizing resource usage at the expense of speed
        - "power": Focuses on minimizing power consumption
        - "congestion": Focuses on routing congestion relief for dense designs
        - "custom": Allows user-defined parameters for advanced control
        
        Note that implementation with different strategies will take varying amounts of time to
        complete, with "balanced" being a good compromise, while "speed" and "congestion" 
        strategies may take longer but produce better results for their respective goals.
        
        Args:
            strategy: Implementation strategy to use. Options are:
                     "speed" - optimize for maximum clock frequency
                     "area" - optimize for minimal resource usage
                     "balanced" - balance area and speed (default)
                     "power" - optimize for minimal power consumption
                     "congestion" - optimize for routing congestion relief
                     "custom" - user-defined strategy with custom parameters
            device_family: Target device family ("gatemate", "a1"). Default is "gatemate".
        
        Example:
            ```python
            # Create a PnRCommands instance with the default balanced strategy
            pnr = PnRCommands()
            
            # Create a PnRCommands instance with speed optimization
            pnr_fast = PnRCommands(strategy="speed")
            
            # Create a PnRCommands instance with area optimization
            pnr_small = PnRCommands(strategy="area")
            
            # Create a PnRCommands instance for power optimization
            pnr_power = PnRCommands(strategy="power")
            ```
        """
        super().__init__()

        self.pnr_logger = logging.getLogger("PnRCommands")
        self.pnr_logger.setLevel(logging.DEBUG)
        self.pnr_logger.propagate = False  # Prevent propagation to root logger

        if not self.pnr_logger.handlers:
            # Get log file path
            log_path = os.path.normpath(os.path.join(self.config["project_structure"]["logs"][0], "pnr_commands.log"))
            file_handler = logging.FileHandler(log_path)
            formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
            file_handler.setFormatter(formatter)
            self.pnr_logger.addHandler(file_handler)
            # Add pnr_commands.log to project configuration
            self._add_pnr_log()

        if strategy not in self.IMPLEMENTATION_STRATEGIES:
            self.pnr_logger.warning(f"Unknown implementation strategy \"{strategy}\", defaulting to balanced")
            self.strategy = "balanced"
        else:
            self.strategy = strategy
            
        # Set device family
        if device_family not in self.DEVICE_FAMILIES:
            self.pnr_logger.warning(f"Unknown device family \"{device_family}\", defaulting to gatemate")
            self.device_family = self.DEVICE_FAMILIES["gatemate"]
        else:
            self.device_family = self.DEVICE_FAMILIES[device_family]

        # Get the build directory path for intermediate files
        if isinstance(self.config["project_structure"]["build"], list) and self.config["project_structure"]["build"]:
            self.work_dir = self.config["project_structure"]["build"][0]
        else:
            self.work_dir = self.config["project_structure"]["build"]
            
        # Get the synth directory path for synthesis inputs
        if isinstance(self.config["project_structure"]["synth"], list) and self.config["project_structure"]["synth"]:
            self.synth_dir = self.config["project_structure"]["synth"][0]
        else:
            self.synth_dir = self.config["project_structure"]["synth"]
            
        # Get implementation output directories
        self.impl_dir = self.config["project_structure"]["impl"]
        self.bitstream_dir = self.impl_dir["bitstream"][0]
        self.netlist_dir = self.impl_dir["netlist"][0] 
        self.timing_dir = self.impl_dir["timing"][0]
        self.impl_logs_dir = self.impl_dir["logs"][0]
        
        # Ensure all impl directories exist
        os.makedirs(self.bitstream_dir, exist_ok=True)
        os.makedirs(self.netlist_dir, exist_ok=True)
        os.makedirs(self.timing_dir, exist_ok=True)
        os.makedirs(self.impl_logs_dir, exist_ok=True)
        
        # Get constraints directory
        if isinstance(self.config["project_structure"]["constraints"], list) and self.config["project_structure"]["constraints"]:
            self.constraints_dir = self.config["project_structure"]["constraints"][0]
        else:
            self.constraints_dir = self.config["project_structure"]["constraints"]
        
        # Ensure constraints directory exists
        os.makedirs(self.constraints_dir, exist_ok=True)
            
        # Get individual p_r preference, fallback to global preference for backward compatibility
        tool_prefs = self.config.get("cologne_chip_gatemate_tool_preferences", {})
        if "p_r" in tool_prefs:
            self.tool_access_mode = tool_prefs["p_r"]
        else:
            self.tool_access_mode = self.config.get("cologne_chip_gatemate_toolchain_preference", "PATH")
        self.pnr_access = self._get_pnr_access()
        # ToolChainManager instantiation report
        self._report_instantiation()

    def _report_instantiation(self):
        """Log the current PnRCommands configuration settings."""
        tcm_settings = f"""
        New PnRCommands Instantiation Settings:
        IMPLEMENTATION_STRATEGY: {self.strategy}
        DEVICE_FAMILY:           {self.device_family}
        WORK_DIRECTORY:          {self.work_dir}
        SYNTH_DIRECTORY:         {self.synth_dir}
        BITSTREAM_DIRECTORY:     {self.bitstream_dir}
        NETLIST_DIRECTORY:       {self.netlist_dir}
        TIMING_DIRECTORY:        {self.timing_dir}
        IMPL_LOGS_DIRECTORY:     {self.impl_logs_dir}
        TOOL_CHAIN_PREFERENCE:   {self.tool_access_mode}
        TOOL_CHAIN_ACCESS:       {self.pnr_access}
        """
        self.pnr_logger.info(tcm_settings)

    def _get_pnr_access(self) -> str:
        """
        Determine how to access the P&R binary based on the configured toolchain mode.

        Returns:
            str: Path or command used to invoke P&R tool.
        """
        pnr_access = ""
        if self.tool_access_mode == "PATH":
            pnr_access = "p_r"  # Access through PATH
            self.pnr_logger.info(f"P&R is accessing binary through {pnr_access}")
        elif self.tool_access_mode == "DIRECT":
            toolchain_path = self.config.get("cologne_chip_gatemate_toolchain_paths", {})
            pnr_access = toolchain_path.get("p_r", "")
            self.pnr_logger.info(f"P&R is accessing binary directly through {pnr_access}")
        elif self.tool_access_mode == "UNDEFINED":
            self.pnr_logger.error(f"P&R access mode is undefined. There is a problem in toolchain manager.")
        else:
            # Fallback for any unexpected values - default to PATH access
            self.pnr_logger.warning(f"Unexpected tool access mode '{self.tool_access_mode}', defaulting to PATH access")
            pnr_access = "p_r"

        return pnr_access

    def _add_pnr_log(self):
        """Add the pnr_commands.log to the project configuration file"""
        log_path = os.path.normpath(os.path.join(self.config["project_structure"]["logs"][0], "pnr_commands.log"))

        if "logs" not in self.config:
            self.config["logs"] = {}

        if "pnr_commands" not in self.config["logs"]:
            self.config["logs"]["pnr_commands"] = {}

        if "pnr_commands.log" not in self.config["logs"]["pnr_commands"]:
            self.config["logs"]["pnr_commands"]["pnr_commands.log"] = log_path
            self.pnr_logger.info(f"PnR log file path added to project configuration: {log_path}")

            try:
                config_path = self._find_config_path()
                with open(config_path, "w") as config_file:
                    yaml.safe_dump(self.config, config_file)
                    self.pnr_logger.info(f"Project configuration updated with PnR log path")
            except Exception as e:
                self.pnr_logger.error(f"Failed to update project configuration with PnR log path: {e}")
    
    def get_default_constraint_file_path(self) -> str:
        """
        Get the default constraint file path for the project.
        
        The default constraint file is named <project_name>.ccf and located
        in the constraints directory.
        
        Returns:
            str: Path to the default constraint file
        """
        project_name = self.config.get("project_name", "project")
        return os.path.join(self.constraints_dir, f"{project_name}.ccf")
    
    def create_default_constraint_file(self, overwrite: bool = False) -> bool:
        """
        Create a default constraint file for the project.
        
        Creates a template .ccf file with common pin assignments and IO constraints
        for GateMate FPGA projects. The file includes comprehensive comments explaining
        the constraint syntax and available options.
        
        Args:
            overwrite: Whether to overwrite existing constraint file
            
        Returns:
            bool: True if constraint file was created successfully, False otherwise
        """
        constraint_file_path = self.get_default_constraint_file_path()
        project_name = self.config.get("project_name", "project")
        
        # Check if file already exists
        if os.path.exists(constraint_file_path) and not overwrite:
            self.pnr_logger.info(f"Constraint file already exists: {constraint_file_path}")
            return True
        
        # Create default constraint file content
        constraint_content = f"""## {project_name}.ccf
#
# Date: {datetime.now().strftime('%Y-%m-%d')}
# Project: {project_name}
# Generated by: Cologne Chip Project Manager
#
# Syntax:
# NET "<pin-name>" Loc = "<pin-location>" | <opt.-constraints>;
#
# Backward compatible legacy syntax:
# <pin-direction> "<pin-name>" Loc = "<pin-location>" | <opt.-constraints>;
#
# Additional constraints can be appended using the pipe symbol.
# Files are read line by line. Text after the hash symbol is ignored.
#
# Available legacy pin directions:
#
# Pin_in
#   defines an input pin
# Pin_out
#   defines an output pin
# Pin_triout
#   defines a tristate output pin
# Pin_inout
#   defines a bidirectional pin
#
# Available pin constraints:
#
# SCHMITT_TRIGGER={{true,false}}
#   enables or disables schmitt trigger (hysteresis) option
# PULLUP={{true,false}}
#   enables or disables I/O pullup resistor of nominal 50kOhm
# PULLDOWN={{true,false}}
#   enables or disables I/O pulldown resistor of nominal 50kOhm
# KEEPER={{true,false}}
#   enables or disables I/O keeper option
# SLEW={{slow,fast}}
#   sets slew rate to slow or fast
# DRIVE={{3,6,9,12}}
#   sets output drive strength to 3mA..12mA
# DELAY_OBF={{0..15}}
#   adds an additional delay of n * nominal 50ps to output signal
# DELAY_IBF={{0..15}}
#   adds an additional delay of n * nominal 50ps to input signal
# FF_IBF={{true,false}}
#   enables or disables placing of FF in input buffer, if possible
# FF_OBF={{true,false}}
#   enables or disables placing of FF in output buffer, if possible
# LVDS_BOOST={{true,false}}
#   enables increased LVDS output current of 6.4mA (default: 3.2mA)
# LVDS_RTERM={{true,false}}
#   enables on-chip LVDS termination resistor of nominal 100Ohm, in input mode only
#
# Global IO constraints can be set with the default_GPIO statement. It can be
# overwritten by individual settings for specific GPIOs, e.g.:
#   default_GPIO | DRIVE=3; # sets all output strengths to 3mA, unless overwritten
#

# ============================================================================
# COMMON PIN ASSIGNMENTS (TEMPLATE)
# ============================================================================
# Uncomment and modify the pin assignments below according to your design
# For GateMate A1 FPGA pin locations, refer to the GateMate documentation

# Clock pins
# Net   "clk"  Loc = "IO_SB_A8" | SCHMITT_TRIGGER=true;

# Reset pins  
# Net   "rst"  Loc = "IO_EB_B0";

# LED outputs
# Net   "led[0]"  Loc = "IO_EB_B1";
# Net   "led[1]"  Loc = "IO_EB_B2";
# Net   "led[2]"  Loc = "IO_EB_B3";
# Net   "led[3]"  Loc = "IO_EB_B4";

# Button inputs
# Net   "btn[0]"  Loc = "IO_EB_A0" | PULLUP=true;
# Net   "btn[1]"  Loc = "IO_EB_A1" | PULLUP=true;

# UART pins
# Net   "uart_tx"  Loc = "IO_WB_A0";
# Net   "uart_rx"  Loc = "IO_WB_A1" | PULLUP=true;

# SPI pins
# Net   "spi_sck"   Loc = "IO_NB_A0";
# Net   "spi_mosi"  Loc = "IO_NB_A1";
# Net   "spi_miso"  Loc = "IO_NB_A2" | PULLUP=true;
# Net   "spi_cs"    Loc = "IO_NB_A3";

# ============================================================================
# PROJECT-SPECIFIC PIN ASSIGNMENTS
# ============================================================================
# Add your project-specific pin assignments below:

"""
        
        try:
            with open(constraint_file_path, 'w') as f:
                f.write(constraint_content)
            
            self.pnr_logger.info(f"Created default constraint file: {constraint_file_path}")
            print(f"Created constraint file: {os.path.basename(constraint_file_path)}")
            return True
            
        except Exception as e:
            self.pnr_logger.error(f"Failed to create constraint file {constraint_file_path}: {e}")
            print(f"❌ Failed to create constraint file: {e}")
            return False
    
    def check_constraint_file_exists(self, constraint_file: Optional[str] = None) -> bool:
        """
        Check if a constraint file exists.
        
        Args:
            constraint_file: Path to constraint file. If None, checks default constraint file
            
        Returns:
            bool: True if constraint file exists, False otherwise
        """
        if constraint_file is None:
            constraint_file = self.get_default_constraint_file_path()
        
        return os.path.exists(constraint_file)
    
    def list_available_constraint_files(self) -> List[str]:
        """
        List all available constraint files in the constraints directory.
        
        Returns:
            List[str]: List of constraint file names (with .ccf extension)
        """
        try:
            if not os.path.exists(self.constraints_dir):
                return []
            
            ccf_files = [f for f in os.listdir(self.constraints_dir) if f.endswith('.ccf')]
            return sorted(ccf_files)
            
        except Exception as e:
            self.pnr_logger.error(f"Error listing constraint files: {e}")
            return []
    
    def get_constraint_file_path(self, constraint_file_name: str) -> str:
        """
        Get the full path to a constraint file.
        
        Args:
            constraint_file_name: Name of the constraint file (can be with or without .ccf extension)
            
        Returns:
            str: Full path to the constraint file
        """
        if not constraint_file_name.endswith('.ccf'):
            constraint_file_name += '.ccf'
        
        return os.path.join(self.constraints_dir, constraint_file_name)

    def has_active_constraints(self, constraint_file_path: str) -> bool:
        """
        Check if a constraint file has active (uncommented) pin assignments.
        
        Args:
            constraint_file_path: Full path to the constraint file
            
        Returns:
            bool: True if the file has active pin assignments, False otherwise
        """
        try:
            if not os.path.exists(constraint_file_path):
                return False
                
            with open(constraint_file_path, 'r', encoding='utf-8', errors='ignore') as f:
                for line in f:
                    line = line.strip()
                    # Skip empty lines and comments
                    if not line or line.startswith('#'):
                        continue
                    # Check for active pin assignments (Net or Pin_ directives)
                    if (line.lower().startswith('net ') or 
                        line.lower().startswith('pin_in ') or 
                        line.lower().startswith('pin_out ') or 
                        line.lower().startswith('pin_triout ') or 
                        line.lower().startswith('pin_inout ')):
                        return True
            return False
            
        except Exception as e:
            self.pnr_logger.debug(f"Error checking constraint file {constraint_file_path}: {e}")
            return False

    def place_and_route(self, design_name: str, netlist_file: Optional[str] = None, 
                       constraint_file: Optional[str] = None, 
                       options: Optional[List[str]] = None) -> bool:
        """
        Run place and route on a synthesized design using Cologne Chip P&R tool.
        
        This function performs the place and route operation on a previously synthesized design,
        taking a netlist (typically JSON format from Yosys) and producing a placed and routed design
        ready for bitstream generation.
        
        The P&R command syntax used is:
        
            p_r [OPTIONS] -i NETLIST_FILE -o OUTPUT_FILE --part DEVICE
        
        Where:
        - NETLIST_FILE is the input synthesized netlist (JSON format preferred)
        - OUTPUT_FILE is the output placed and routed design file
        - DEVICE is the target GateMate device
        - [OPTIONS] include implementation strategy and other parameters
        
        Args:
            design_name: Name of the design (used for output file naming)
            netlist_file: Path to input netlist file. If None, looks for {design_name}_synth.json in synth directory
            constraint_file: Path to constraint file (optional)
            options: Additional command-line options for P&R as a list of strings
                
        Common Cologne Chip P&R options include:
            `-i FILE`:             Input netlist file (JSON, BLIF)
            `-o FILE`:             Output file for placed and routed design
            `--part DEVICE`:       Target device (e.g., GATEMATE_A1)
            `--seed SEED`:         Random seed for reproducible results
            `--timing-report`:     Generate timing report
            `--effort LEVEL`:      Implementation effort (low, medium, high)
            `--place-effort LEVEL`: Placement effort level
            `--route-effort LEVEL`: Routing effort level
            `--timing-driven`:     Enable timing-driven implementation
            `--congestion-driven`: Enable congestion-driven implementation
            
        Returns:
            bool: True if place and route successful, False otherwise
            
        Example:
            ```python
            pnr = PnRCommands()
            # Basic place and route with default settings
            pnr.place_and_route("counter")
            
            # Place and route with specific netlist and constraints
            pnr.place_and_route("counter", 
                               netlist_file="counter_synth.json",
                               constraint_file="counter.ccf")
            
            # Place and route with additional options
            pnr.place_and_route("counter", options=["--seed", "42", "--timing-report"])
            ```
        """
        # Determine input netlist file
        if netlist_file is None:
            # Try JSON first (preferred), then Verilog as fallback
            json_file = os.path.join(self.synth_dir, f"{design_name}_synth.json")
            verilog_file = os.path.join(self.synth_dir, f"{design_name}_synth.v")
            
            if os.path.exists(json_file):
                netlist_file = json_file
                self.pnr_logger.info(f"Using JSON netlist: {netlist_file}")
            elif os.path.exists(verilog_file):
                netlist_file = verilog_file
                self.pnr_logger.info(f"Using Verilog netlist: {netlist_file}")
            else:
                self.pnr_logger.error("❌ SYNTHESIS NETLIST REQUIRED FOR PLACE & ROUTE")
                self.pnr_logger.error(f"❌ No synthesized netlist found for design '{design_name}'")
                self.pnr_logger.error("❌ Place and Route requires a synthesized netlist as input.")
                self.pnr_logger.error("")
                self.pnr_logger.error("🔍 SEARCHED FOR:")
                self.pnr_logger.error(f"   JSON netlist: {json_file}")
                self.pnr_logger.error(f"   Verilog netlist: {verilog_file}")
                self.pnr_logger.error("")
                self.pnr_logger.error("🔧 SOLUTIONS:")
                self.pnr_logger.error("   1. Run Synthesis first to generate the netlist")
                self.pnr_logger.error("   2. Check that Synthesis completed successfully")
                self.pnr_logger.error("   3. Verify the design name matches your project")
                self.pnr_logger.error("   4. Check that synthesis output files are in the synth directory")
                self.pnr_logger.error("")
                return False
        
        if not os.path.exists(netlist_file):
            self.pnr_logger.error(f"❌ Input netlist file not found: {netlist_file}")
            self.pnr_logger.error("❌ SYNTHESIS NETLIST REQUIRED FOR PLACE & ROUTE")
            self.pnr_logger.error("❌ The specified netlist file could not be found.")
            self.pnr_logger.error("")
            self.pnr_logger.error("🔧 SOLUTIONS:")
            self.pnr_logger.error("   1. Run Synthesis first to generate the netlist")
            self.pnr_logger.error("   2. Check that Synthesis completed successfully")
            self.pnr_logger.error("   3. Verify the netlist file path is correct")
            self.pnr_logger.error(f"   4. Expected file: {netlist_file}")
            self.pnr_logger.error("")
            return False

        # Output file in build directory (P&R tool generates many files in same location)
        output_file = os.path.join(self.work_dir, f"{design_name}_impl.cfg")
        
        # Build P&R command
        pnr_cmd = [self.pnr_access]
        
        # Add strategy-specific options
        strategy_opts = self.IMPLEMENTATION_STRATEGIES[self.strategy]
        
        pnr_cmd.extend(["-i", netlist_file])
        pnr_cmd.extend(["-o", output_file])
        # Note: GateMate P&R tool may not use --part option, device is typically auto-detected
        
        # Note: Power-specific options like --pwr_red and --fpga_mode are available
        # but not automatically applied as they don't provide detailed power analysis output
        
        # Add basic options (simplified for compatibility)
        # Note: Using minimal options to ensure compatibility with different P&R tool versions
        # Advanced options can be added via the options parameter if needed
            
        # Add constraint file if provided, or use default if available
        constraint_file_used = None
        if constraint_file:
            if os.path.exists(constraint_file):
                pnr_cmd.extend(["-ccf", constraint_file])
                constraint_file_used = constraint_file
                self.pnr_logger.info(f"Using specified constraint file: {constraint_file}")
            else:
                self.pnr_logger.error(f"ERROR: Specified constraint file not found: {constraint_file}")
                self.pnr_logger.error(f"ERROR: Please check that the constraint file exists and the path is correct")
                return False
        else:
            # Auto-detection: Intelligently select the best constraint file
            default_constraint_file = self.get_default_constraint_file_path()
            available_constraints = self.list_available_constraint_files()
            
            constraint_file_to_use = None
            constraint_file_reason = ""
            
            # First, check if default constraint file exists and has active constraints
            if os.path.exists(default_constraint_file) and self.has_active_constraints(default_constraint_file):
                constraint_file_to_use = default_constraint_file
                constraint_file_reason = "default constraint file with active pin assignments"
            elif available_constraints:
                # Look for the first constraint file with active pin assignments
                for constraint_name in available_constraints:
                    constraint_path = self.get_constraint_file_path(constraint_name)
                    if self.has_active_constraints(constraint_path):
                        constraint_file_to_use = constraint_path
                        constraint_file_reason = f"first available constraint file with active pin assignments ({constraint_name})"
                        break
                
                # If no constraint file has active assignments, use the first available as fallback
                if not constraint_file_to_use and available_constraints:
                    constraint_file_to_use = self.get_constraint_file_path(available_constraints[0])
                    constraint_file_reason = f"first available constraint file (template only - {available_constraints[0]})"
            
            if constraint_file_to_use:
                pnr_cmd.extend(["-ccf", constraint_file_to_use])
                constraint_file_used = constraint_file_to_use
                self.pnr_logger.info(f"Auto-detected constraint file: {constraint_file_to_use}")
                self.pnr_logger.info(f"Selected {constraint_file_reason}")
                
                # Warn if using a template-only file
                if "template only" in constraint_file_reason:
                    self.pnr_logger.warning("WARNING: Selected constraint file appears to be a template with no active pin assignments")
                    self.pnr_logger.warning("WARNING: This may cause P&R to fail. Consider adding actual pin constraints.")
            else:
                # No constraint file available - this is often required for P&R
                self.pnr_logger.error("ERROR: CONSTRAINT FILE REQUIRED")
                self.pnr_logger.error("ERROR: No constraint file was specified and no constraint files were found.")
                self.pnr_logger.error("ERROR: Place and Route operations typically require constraint files to:")
                self.pnr_logger.error("   - Define pin assignments for I/O signals")
                self.pnr_logger.error("   - Specify timing constraints")
                self.pnr_logger.error("   - Set placement and routing preferences")
                self.pnr_logger.error("")
                self.pnr_logger.error("SOLUTIONS:")
                self.pnr_logger.error("   1. Create a constraint file (.ccf) in the constraints directory")
                self.pnr_logger.error("   2. Use the 'Create Default Constraint File' option")
                self.pnr_logger.error("   3. Import an existing constraint file")
                self.pnr_logger.error(f"   4. Default constraint file location: {default_constraint_file}")
                self.pnr_logger.error("")
                self.pnr_logger.error("Constraint file should be placed in: " + os.path.dirname(default_constraint_file))
                return False
                
        # Add any additional options
        if options:
            pnr_cmd.extend(options)
            
        self.pnr_logger.info(f"Running place and route for {design_name}")
        self.pnr_logger.debug(f"P&R Command: {' '.join(pnr_cmd)}")
        
        # Additional debug information
        self.pnr_logger.info(f"Input netlist: {netlist_file}")
        self.pnr_logger.info(f"Output file: {output_file}")
        self.pnr_logger.info(f"Working directory: {self.work_dir}")
        self.pnr_logger.info(f"PnR access command: '{self.pnr_access}'")
        
        try:
            # Run without check=True first to get more detailed error information
            result = subprocess.run(pnr_cmd, capture_output=True, text=True, timeout=300)
            
            self.pnr_logger.info(f"P&R process completed with return code: {result.returncode}")
            
            if result.stdout:
                self.pnr_logger.info(f"P&R STDOUT: {result.stdout}")
            if result.stderr:
                self.pnr_logger.info(f"P&R STDERR: {result.stderr}")
                
            if result.returncode == 0:
                self.pnr_logger.info(f"Successfully completed place and route for {design_name}")
                self.pnr_logger.info(f"Generated implementation file: {output_file}")
                
                self._organize_pnr_output_files(design_name)
                return True
            else:
                self.pnr_logger.error(f"Place and route failed for {design_name} with return code {result.returncode}")
                return False
                
        except subprocess.TimeoutExpired as e:
            self.pnr_logger.error(f"Place and route timed out for {design_name}: {e}")
            return False
        except FileNotFoundError as e:
            self.pnr_logger.error(f"P&R tool not found: {e}")
            self.pnr_logger.error(f"Attempted to run: {self.pnr_access}")
            return False
        except Exception as e:
            self.pnr_logger.error(f"Unexpected error during place and route for {design_name}: {e}")
            self.pnr_logger.error(f"Exception type: {type(e).__name__}")
            import traceback
            self.pnr_logger.error(f"Traceback: {traceback.format_exc()}")
            return False

    def _organize_pnr_output_files(self, design_name: str) -> None:
        """
        Organize P&R output files into their proper directories.
        
        The P&R tool generates all files in the same directory as the main output file.
        This method moves them to the appropriate project directories:
        - Bitstream files (.bit) -> bitstream directory
        - Timing files (.sdf) -> timing directory  
        - Post-implementation netlists (.v) -> netlist directory
        - Reports and other files stay in build directory
        """
        # Define file patterns and their target directories
        file_mappings = [
            (f"{design_name}_impl*.bit", self.bitstream_dir, "bitstream files"),
            (f"{design_name}_impl*.sdf", self.timing_dir, "timing files"),
            (f"{design_name}_impl*.v", self.netlist_dir, "post-implementation netlists"),
        ]
        
        # Also check for the main implementation file with _00 suffix and create a consistent name
        impl_file_pattern = os.path.join(self.work_dir, f"{design_name}_impl_*.cfg")
        impl_files = glob.glob(impl_file_pattern)
        if impl_files:
            # Use the first (and typically only) implementation file found
            source_impl_file = impl_files[0]
            target_impl_file = os.path.join(self.work_dir, f"{design_name}_impl.cfg")
            
            # Create a consistent name for subsequent operations
            if source_impl_file != target_impl_file:
                try:
                    shutil.copy2(source_impl_file, target_impl_file)
                    self.pnr_logger.info(f"Created consistent implementation file: {os.path.basename(target_impl_file)}")
                except Exception as e:
                    self.pnr_logger.warning(f"Failed to create consistent implementation file: {e}")
        
        for pattern, target_dir, file_type in file_mappings:
            # Find files matching the pattern in the build directory
            search_pattern = os.path.join(self.work_dir, pattern)
            matching_files = glob.glob(search_pattern)
            
            if matching_files:
                # Ensure target directory exists
                os.makedirs(target_dir, exist_ok=True)
                
                for file_path in matching_files:
                    filename = os.path.basename(file_path)
                    target_path = os.path.join(target_dir, filename)
                    
                    try:
                        shutil.move(file_path, target_path)
                        self.pnr_logger.info(f"Moved {file_type}: {filename} -> {os.path.relpath(target_dir)}")
                    except Exception as e:
                        self.pnr_logger.warning(f"Failed to move {filename}: {e}")
                        
        self.pnr_logger.info(f"Organized P&R output files for {design_name}")

    def generate_bitstream(self, design_name: str, impl_file: Optional[str] = None,
                          options: Optional[List[str]] = None) -> bool:
        """
        Generate bitstream file from a placed and routed design.
        
        This function takes a placed and routed design and generates the final bitstream
        file that can be programmed to the GateMate FPGA.
        
        The bitstream generation command syntax used is:
        
            p_r [OPTIONS] --bitstream -i IMPL_FILE -o BITSTREAM_FILE
        
        Args:
            design_name: Name of the design (used for output file naming)
            impl_file: Path to implementation file. If None, looks for {design_name}_impl.ccf in impl logs directory
            options: Additional command-line options for bitstream generation
                
        Returns:
            bool: True if bitstream generation successful, False otherwise
            
        Example:
            ```python
            pnr = PnRCommands()
            # Generate bitstream after place and route
            pnr.generate_bitstream("counter")
            ```
        """
        # Determine input implementation file
        if impl_file is None:
            impl_file = os.path.join(self.work_dir, f"{design_name}_impl.cfg")
        
        if not os.path.exists(impl_file):
            self.pnr_logger.error(f"❌ Implementation file not found: {impl_file}")
            self.pnr_logger.error("❌ IMPLEMENTATION FILE REQUIRED FOR BITSTREAM GENERATION")
            self.pnr_logger.error("❌ Bitstream generation requires a completed place and route implementation.")
            self.pnr_logger.error("")
            self.pnr_logger.error("🔧 SOLUTIONS:")
            self.pnr_logger.error("   1. Run Place & Route first to generate the implementation file")
            self.pnr_logger.error("   2. Check that Place & Route completed successfully")
            self.pnr_logger.error(f"   3. Expected implementation file: {impl_file}")
            self.pnr_logger.error("")
            return False

        # Output bitstream file
        bitstream_file = os.path.join(self.bitstream_dir, f"{design_name}.bit")
        
        # Build bitstream generation command
        pnr_cmd = [self.pnr_access]
        pnr_cmd.extend(["--bitstream"])
        pnr_cmd.extend(["-i", impl_file])
        pnr_cmd.extend(["-o", bitstream_file])
        
        # Add any additional options
        if options:
            pnr_cmd.extend(options)
            
        self.pnr_logger.info(f"Generating bitstream for {design_name}")
        self.pnr_logger.debug(f"P&R Command: {' '.join(pnr_cmd)}")
        
        try:
            result = subprocess.run(pnr_cmd, check=True, capture_output=True, text=True)
            if result.stdout:
                self.pnr_logger.info(f"Bitstream generation output: {result.stdout}")
            self.pnr_logger.info(f"Successfully generated bitstream for {design_name}")
            self.pnr_logger.info(f"Generated bitstream file: {bitstream_file}")
            return True
        except subprocess.CalledProcessError as e:
            self.pnr_logger.error(f"Bitstream generation failed for {design_name}: {e}")
            self.pnr_logger.error(f"STDERR: {e.stderr}")
            return False

    def timing_analysis(self, design_name: str, impl_file: Optional[str] = None,
                       options: Optional[List[str]] = None) -> bool:
        """
        Perform timing analysis on a placed and routed design.
        
        This function analyzes the timing characteristics of the implemented design,
        generating timing reports and SDF files for post-implementation simulation.
        
        Args:
            design_name: Name of the design (used for output file naming)
            impl_file: Path to implementation file. If None, looks for {design_name}_impl.ccf in impl logs directory
            options: Additional command-line options for timing analysis
                
        Returns:
            bool: True if timing analysis successful, False otherwise
            
        Example:
            ```python
            pnr = PnRCommands()
            # Run timing analysis after place and route
            pnr.timing_analysis("counter")
            ```
        """
        # Determine input implementation file
        if impl_file is None:
            impl_file = os.path.join(self.work_dir, f"{design_name}_impl.cfg")
        
        if not os.path.exists(impl_file):
            self.pnr_logger.error(f"Implementation file not found: {impl_file}")
            return False

        # Output timing files
        timing_report = os.path.join(self.timing_dir, f"{design_name}_timing.rpt")
        sdf_file = os.path.join(self.timing_dir, f"{design_name}.sdf")
        
        # Build timing analysis command
        pnr_cmd = [self.pnr_access]
        pnr_cmd.extend(["--timing-analysis"])
        pnr_cmd.extend(["-i", impl_file])
        pnr_cmd.extend(["--timing-report", timing_report])
        pnr_cmd.extend(["--sdf", sdf_file])
        
        # Add any additional options
        if options:
            pnr_cmd.extend(options)
            
        self.pnr_logger.info(f"Running timing analysis for {design_name}")
        self.pnr_logger.debug(f"P&R Command: {' '.join(pnr_cmd)}")
        
        try:
            result = subprocess.run(pnr_cmd, check=True, capture_output=True, text=True)
            if result.stdout:
                self.pnr_logger.info(f"Timing analysis output: {result.stdout}")
            self.pnr_logger.info(f"Successfully completed timing analysis for {design_name}")
            self.pnr_logger.info(f"Generated timing report: {timing_report}")
            self.pnr_logger.info(f"Generated SDF file: {sdf_file}")
            return True
        except subprocess.CalledProcessError as e:
            self.pnr_logger.error(f"Timing analysis failed for {design_name}: {e}")
            self.pnr_logger.error(f"STDERR: {e.stderr}")
            return False

    def generate_post_impl_netlist(self, design_name: str, impl_file: Optional[str] = None,
                                  netlist_format: str = "vhdl", 
                                  options: Optional[List[str]] = None) -> bool:
        """
        Generate post-implementation netlist for simulation.
        
        This function creates a netlist from the placed and routed design that includes
        implementation-specific information like delays and routing. This netlist can be
        used for post-implementation simulation to verify the design behavior with
        realistic timing.
        
        Args:
            design_name: Name of the design (used for output file naming)
            impl_file: Path to implementation file. If None, looks for {design_name}_impl.ccf in impl logs directory
            netlist_format: Output format ("vhdl", "verilog", "json", "blif")
            options: Additional command-line options for netlist generation
                
        Returns:
            bool: True if netlist generation successful, False otherwise
            
        Example:
            ```python
            pnr = PnRCommands()
            # Generate VHDL post-implementation netlist
            pnr.generate_post_impl_netlist("counter", netlist_format="vhdl")
            
            # Generate Verilog netlist
            pnr.generate_post_impl_netlist("counter", netlist_format="verilog")
            ```
        """
        # Determine input implementation file
        if impl_file is None:
            impl_file = os.path.join(self.work_dir, f"{design_name}_impl.cfg")
        
        if not os.path.exists(impl_file):
            self.pnr_logger.error(f"Implementation file not found: {impl_file}")
            return False

        # Validate netlist format
        if netlist_format not in self.NETLIST_FORMATS:
            self.pnr_logger.error(f"Unsupported netlist format: {netlist_format}")
            return False

        # Output netlist file
        file_ext = self.NETLIST_FORMATS[netlist_format]
        netlist_file = os.path.join(self.netlist_dir, f"{design_name}_impl{file_ext}")
        
        # Build netlist generation command
        pnr_cmd = [self.pnr_access]
        pnr_cmd.extend(["--write-netlist"])
        pnr_cmd.extend(["-i", impl_file])
        pnr_cmd.extend(["-o", netlist_file])
        pnr_cmd.extend(["--format", netlist_format])
        
        # Add any additional options
        if options:
            pnr_cmd.extend(options)
            
        self.pnr_logger.info(f"Generating {netlist_format.upper()} post-implementation netlist for {design_name}")
        self.pnr_logger.debug(f"P&R Command: {' '.join(pnr_cmd)}")
        
        try:
            result = subprocess.run(pnr_cmd, check=True, capture_output=True, text=True)
            if result.stdout:
                self.pnr_logger.info(f"Netlist generation output: {result.stdout}")
            self.pnr_logger.info(f"Successfully generated {netlist_format.upper()} netlist for {design_name}")
            self.pnr_logger.info(f"Generated netlist file: {netlist_file}")
            return True
        except subprocess.CalledProcessError as e:
            self.pnr_logger.error(f"Post-implementation netlist generation failed for {design_name}: {e}")
            self.pnr_logger.error(f"STDERR: {e.stderr}")
            return False

    def full_implementation_flow(self, design_name: str, netlist_file: Optional[str] = None,
                                constraint_file: Optional[str] = None,
                                generate_bitstream: bool = True,
                                run_timing_analysis: bool = True,
                                generate_sim_netlist: bool = True,
                                sim_netlist_format: str = "vhdl",
                                options: Optional[List[str]] = None) -> bool:
        """
        Run the complete implementation flow from netlist to bitstream.
        
        This function performs the complete implementation flow including:
        1. Place and route
        2. Bitstream generation (optional)
        3. Timing analysis (optional)
        4. Post-implementation netlist generation (optional)
        
        Args:
            design_name: Name of the design
            netlist_file: Path to input netlist file (optional)
            constraint_file: Path to constraint file (optional)
            generate_bitstream: Whether to generate bitstream file
            run_timing_analysis: Whether to run timing analysis
            generate_sim_netlist: Whether to generate post-implementation netlist
            sim_netlist_format: Format for simulation netlist ("vhdl", "verilog", "json", "blif")
            options: Additional command-line options for P&R
                
        Returns:
            bool: True if all selected steps completed successfully, False otherwise
            
        Example:
            ```python
            pnr = PnRCommands(strategy="speed")
            # Run complete flow with all outputs
            pnr.full_implementation_flow("counter", 
                                        generate_bitstream=True,
                                        run_timing_analysis=True,
                                        generate_sim_netlist=True)
            ```
        """
        self.pnr_logger.info(f"Starting full implementation flow for {design_name}")
        
        # Step 1: Place and route
        if not self.place_and_route(design_name, netlist_file, constraint_file, options):
            self.pnr_logger.error(f"Place and route failed for {design_name}")
            return False
        
        # Step 2: Bitstream generation (optional)
        if generate_bitstream:
            if not self.generate_bitstream(design_name):
                self.pnr_logger.error(f"Bitstream generation failed for {design_name}")
                return False
        
        # Step 3: Timing analysis (optional)
        if run_timing_analysis:
            if not self.timing_analysis(design_name):
                self.pnr_logger.error(f"Timing analysis failed for {design_name}")
                return False
        
        # Step 4: Post-implementation netlist (optional)
        if generate_sim_netlist:
            if not self.generate_post_impl_netlist(design_name, netlist_format=sim_netlist_format):
                self.pnr_logger.error(f"Post-implementation netlist generation failed for {design_name}")
                return False
        
        self.pnr_logger.info(f"Successfully completed full implementation flow for {design_name}")
        return True

    def get_implementation_status(self, design_name: str) -> Dict[str, bool]:
        """
        Check the implementation status of a design by looking for output files.
        
        Args:
            design_name: Name of the design to check
            
        Returns:
            Dict with status of each implementation step
            
        Example:
            ```python
            pnr = PnRCommands()
            status = pnr.get_implementation_status("counter")
            if status["placed"]:
                print("Design has been placed and routed")
            ```
        """
        status = {
            "placed": False,
            "routed": False, 
            "timing_analyzed": False,
            "bitstream_generated": False,
            "post_impl_netlist": False
        }
        
        # Check for implementation file (indicates place and route completed)
        # Look for both _impl.cfg and _impl_00.cfg patterns
        impl_file_patterns = [
            os.path.join(self.work_dir, f"{design_name}_impl.cfg"),
            os.path.join(self.work_dir, f"{design_name}_impl_00.cfg")
        ]
        
        for impl_file in impl_file_patterns:
            if os.path.exists(impl_file):
                status["placed"] = True
                status["routed"] = True  # P&R tool does both in one step
                break
        
        # Check for timing files (with _00 suffix pattern)
        timing_patterns = [
            os.path.join(self.timing_dir, f"{design_name}_timing.rpt"),
            os.path.join(self.timing_dir, f"{design_name}.sdf"),
            os.path.join(self.timing_dir, f"{design_name}_impl_00.sdf")
        ]
        
        for timing_file in timing_patterns:
            if os.path.exists(timing_file):
                status["timing_analyzed"] = True
                break
        
        # Check for bitstream file (with _00 suffix pattern)
        bitstream_patterns = [
            os.path.join(self.bitstream_dir, f"{design_name}.bit"),
            os.path.join(self.bitstream_dir, f"{design_name}_impl_00.cfg.bit")
        ]
        
        for bitstream_file in bitstream_patterns:
            if os.path.exists(bitstream_file):
                status["bitstream_generated"] = True
                break
        
        # Check for post-implementation netlists (with _00 suffix pattern)
        for fmt, ext in self.NETLIST_FORMATS.items():
            netlist_patterns = [
                os.path.join(self.netlist_dir, f"{design_name}_impl{ext}"),
                os.path.join(self.netlist_dir, f"{design_name}_impl_00{ext}")
            ]
            
            for netlist_file in netlist_patterns:
                if os.path.exists(netlist_file):
                    status["post_impl_netlist"] = True
                    break
            
            if status["post_impl_netlist"]:
                break
        
        return status

    def clean_implementation_files(self, design_name: str) -> bool:
        """
        Clean implementation files for a design.
        
        This removes all generated implementation files to allow for a fresh implementation run.
        
        Args:
            design_name: Name of the design to clean
            
        Returns:
            bool: True if cleaning successful, False otherwise
        """
        files_to_clean = []
        
        # Implementation file
        impl_file = os.path.join(self.impl_logs_dir, f"{design_name}_impl.ccf")
        if os.path.exists(impl_file):
            files_to_clean.append(impl_file)
        
        # Bitstream file
        bitstream_file = os.path.join(self.bitstream_dir, f"{design_name}.bit")
        if os.path.exists(bitstream_file):
            files_to_clean.append(bitstream_file)
        
        # Timing files
        timing_report = os.path.join(self.timing_dir, f"{design_name}_timing.rpt")
        sdf_file = os.path.join(self.timing_dir, f"{design_name}.sdf")
        if os.path.exists(timing_report):
            files_to_clean.append(timing_report)
        if os.path.exists(sdf_file):
            files_to_clean.append(sdf_file)
        
        # Post-implementation netlists
        for fmt, ext in self.NETLIST_FORMATS.items():
            netlist_file = os.path.join(self.netlist_dir, f"{design_name}_impl{ext}")
            if os.path.exists(netlist_file):
                files_to_clean.append(netlist_file)
        
        # Remove files
        cleaned_count = 0
        for file_path in files_to_clean:
            try:
                os.remove(file_path)
                cleaned_count += 1
                self.pnr_logger.info(f"Removed: {file_path}")
            except Exception as e:
                self.pnr_logger.error(f"Failed to remove {file_path}: {e}")
        
        self.pnr_logger.info(f"Cleaned {cleaned_count}/{len(files_to_clean)} implementation files for {design_name}")
        return cleaned_count == len(files_to_clean)

    def get_available_placed_designs(self) -> List[str]:
        """Find available placed and routed designs that can be used for bitstream generation.
        
        Scans the build directory for implementation files (CFG format)
        and returns a list of design names that have been successfully placed and routed.
        
        Returns:
            List[str]: List of design names that have implementation files
        """
        designs = []
        try:
            if os.path.exists(self.work_dir):
                self.pnr_logger.info(f"Scanning for placed designs in {self.work_dir}")
                
                # Look for implementation CFG files (both _impl.cfg and _impl_00.cfg patterns)
                for file in os.listdir(self.work_dir):
                    if file.endswith('_impl.cfg') or file.endswith('_impl_00.cfg'):
                        # Extract design name from different patterns
                        if file.endswith('_impl_00.cfg'):
                            design_name = file.replace('_impl_00.cfg', '')
                        else:
                            design_name = file.replace('_impl.cfg', '')
                        
                        if design_name not in designs:  # Avoid duplicates
                            designs.append(design_name)
                            self.pnr_logger.info(f"Found placed design: {design_name}")
                        
                self.pnr_logger.info(f"Found {len(designs)} placed designs: {designs}")
            else:
                self.pnr_logger.warning(f"Build directory not found: {self.work_dir}")
                
        except Exception as e:
            self.pnr_logger.error(f"Error scanning for placed designs: {e}")
            
        return sorted(designs)

# Example usage function for documentation
def example_usage():
    """Example of how to use the PnRCommands class for GateMate implementation."""
    # Initialize P&R commands with strategy
    pnr = PnRCommands(strategy="balanced")
    
    design_name = "counter"
    
    # Check current implementation status
    status = pnr.get_implementation_status(design_name)
    print(f"Implementation status: {status}")
    
    # Run individual steps
    if pnr.place_and_route(design_name):
        print("Place and route completed")
        
        if pnr.generate_bitstream(design_name):
            print("Bitstream generated")
            
        if pnr.timing_analysis(design_name):
            print("Timing analysis completed")
            
        if pnr.generate_post_impl_netlist(design_name, netlist_format="vhdl"):
            print("Post-implementation VHDL netlist generated")
    
    # Alternative: Run complete flow in one call
    pnr_speed = PnRCommands(strategy="speed")
    success = pnr_speed.full_implementation_flow(
        design_name=design_name,
        generate_bitstream=True,
        run_timing_analysis=True,
        generate_sim_netlist=True,
        sim_netlist_format="vhdl"
    )
    
    if success:
        print("Complete implementation flow successful")
    else:
        print("Implementation flow failed")

if __name__ == "__main__":
    example_usage() 