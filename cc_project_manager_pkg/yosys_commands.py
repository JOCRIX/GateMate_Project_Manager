"""Handles Yosys synthesizer related commands and operations.

This module provides a manager class for Yosys operations, including reading design files, 
synthesizing VHDL code, and generating netlists.
"""
import os
import yaml
import logging
import subprocess
from .toolchain_manager import ToolChainManager
from typing import List, Optional, Dict, Union, Tuple

class YosysCommands(ToolChainManager):
    """Provides methods to work with Yosys synthesizer.
    
    This class encapsulates the functionality needed to interact with Yosys,
    providing methods for reading, synthesizing VHDL designs and generating netlists.
    
    The class supports multiple synthesis strategies, each optimized for different goals:
    
    1. area - Optimize for minimal resource usage (LUTs, logic gates)
       Commands: synth -top {top} -flatten; abc -lut 4 -dress; opt_clean; opt -full; clean
       Best for: Designs with tight area constraints or large designs that need to fit in smaller FPGAs
    
    2. speed - Optimize for maximum performance/frequency
       Commands: synth -top {top} -flatten; abc -fast; opt; clean
       Best for: High-performance designs where timing is critical
    
    3. balanced - Standard optimization balancing area and speed
       Commands: synth -top {top} -flatten; abc; opt; clean
       Best for: General-purpose designs with no extreme constraints
    
    4. quality - More thorough optimization for better results
       Commands: synth -top {top} -flatten; opt -full; abc; opt -full; clean
       Best for: Production designs where synthesis time is less important than results
    
    5. timing - Advanced timing-driven optimization
       Commands: synth -top {top} -flatten; abc -lut 4; opt_clean; abc -lut 4 -dff -D 0.1; opt -full; clean
       Best for: Designs with critical timing requirements and complex timing paths
       
    6. extreme - Maximum optimization for performance-critical designs
       Commands: synth -top {top} -flatten; opt -full; abc -lut 4; opt -full -fine; abc -lut 4 -dff -D 0.01; opt -full -fine; clean
       Best for: Designs requiring the highest possible performance regardless of synthesis time
       Note: This strategy uses -full -fine optimizations and can be significantly slower
    """

    # Yosys config options
    SYNTHESIS_STRATEGIES = {
        "area": ["synth -top {top} -flatten", "abc -lut 4 -dress", "opt_clean", "opt -full", "clean"],
        "speed": ["synth -top {top} -flatten", "abc -fast", "opt", "clean"],
        "balanced": ["synth -top {top} -flatten", "abc", "opt", "clean"],
        "quality": ["synth -top {top} -flatten", "opt -full", "abc", "opt -full", "clean"],
        "timing": ["synth -top {top} -flatten", "abc -lut 4", "opt_clean", "abc -lut 4 -dff -D 0.1", "opt -full", "clean"],
        "extreme": ["synth -top {top} -flatten", "opt -full", "abc -lut 4", "opt -full -fine", "abc -lut 4 -dff -D 0.01", "opt -full -fine", "clean"]
    }
    
    # Available VHDL standards
    VHDL_STANDARDS = {
        "VHDL-1993": "--std=93",   # VHDL-1993
        "VHDL-1993c": "--std=93c", # VHDL-1993 with relaxed restrictions, partially supported in Yosys + GHDL
        "VHDL-2008": "--std=08",   # VHDL-2008 (most commonly used)
    }
    
    # Available IEEE library implementations
    IEEE_LIBS = {
        "synopsys": "--ieee=synopsys", # Most compatible with synthesis tools. Use this one unless there is a really good reason
        "mentor": "--ieee=mentor",     # Alternative implementation
        "none": "--ieee=none"          # No IEEE libraries (minimal)
    }

    def __init__(self, strategy: str = "balanced", vhdl_std: str = "VHDL-2008", ieee_lib: str = "synopsys"):
        """
        Initialize the Yosys command utility with default options.
        
        Creates a YosysCommands instance that manages Yosys synthesis operations for VHDL designs.
        The instance will use the project configuration to determine paths for inputs and outputs,
        and will apply the specified synthesis strategy when processing designs.
        
        The default synthesis strategy is "balanced", which provides a good compromise between
        area efficiency and performance for most designs. Other strategies include:
        
        - "area": Focuses on minimizing resource usage at the expense of speed
        - "speed": Focuses on maximizing design performance at the expense of area
        - "quality": Performs more thorough optimizations for better overall results
        - "timing": Uses timing-driven optimization techniques for critical paths
        - "extreme": Applies maximum optimizations for the highest performance possible
        
        Note that synthesis with different strategies will take varying amounts of time to
        complete, with "balanced" and "speed" being the fastest, while "quality" and "timing"
        may take considerably longer but produce better results for complex designs. The
        "extreme" strategy will typically take the longest but may achieve the best
        results for performance-critical designs.
        
        Args:
            strategy: Synthesis strategy to use. Options are:
                     "area" - optimize for minimal resource usage
                     "speed" - optimize for maximum clock frequency
                     "balanced" - balance area and speed (default)
                     "quality" - more thorough optimizations for better results
                     "timing" - advanced timing-driven optimization
                     "extreme" - maximum optimization for highest performance
            vhdl_std: VHDL standard to use ("VHDL-1993", "VHDL-1993c", "VHDL-2008"). Default is VHDL-2008.
                     VHDL-1993c is only partially supported by Yosys + GHDL.
            ieee_lib: IEEE library implementation ('synopsys', 'mentor', 'none'). Default is "synopsys".
                     The synopsys library is generally most compatible with synthesis tools.
        
        Example:
            ```python
            # Create a YosysCommands instance with the default balanced strategy
            yosys = YosysCommands()
            
            # Create a YosysCommands instance with speed optimization
            yosys_fast = YosysCommands(strategy="speed")
            
            # Create a YosysCommands instance with area optimization
            yosys_small = YosysCommands(strategy="area")
            
            # Create a YosysCommands instance with extreme optimization
            yosys_max = YosysCommands(strategy="extreme")
            
            # Create a YosysCommands instance using VHDL-1993
            yosys_93 = YosysCommands(vhdl_std="VHDL-1993")
            
            # Create a YosysCommands instance using a specific IEEE library
            yosys_mentor = YosysCommands(ieee_lib="mentor")
            ```
        """
        super().__init__()

        self.yosys_logger = logging.getLogger("YosysCommands")
        self.yosys_logger.setLevel(logging.DEBUG)
        self.yosys_logger.propagate = False  # Prevent propagation to root logger

        if not self.yosys_logger.handlers:
            # Get log file path
            log_path = os.path.normpath(os.path.join(self.config["project_structure"]["logs"][0], "yosys_commands.log"))
            file_handler = logging.FileHandler(log_path)
            formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
            file_handler.setFormatter(formatter)
            self.yosys_logger.addHandler(file_handler)
            # Add yosys_commands.log to project configuration
            self._add_yosys_log()

        # Load custom synthesis strategies from file (preserves built-in strategies)
        self._load_custom_synthesis_strategies()
        
        if strategy not in self.SYNTHESIS_STRATEGIES:
            self.yosys_logger.warning(f"Unknown synthesis strategy \"{strategy}\", defaulting to balanced")
            self.strategy = "balanced"
        else:
            self.strategy = strategy
            
        # Set VHDL standard
        if vhdl_std not in self.VHDL_STANDARDS:
            self.yosys_logger.warning(f"Unknown VHDL Standard \"{vhdl_std}\", defaulting to VHDL-2008")
            self.vhdl_std = self.VHDL_STANDARDS["VHDL-2008"]
        else:
            self.vhdl_std = self.VHDL_STANDARDS[vhdl_std]
            
        # Set IEEE library
        if ieee_lib not in self.IEEE_LIBS:
            self.yosys_logger.warning(f"Unknown IEEE library \"{ieee_lib}\", defaulting to synopsys")
            self.ieee_lib = self.IEEE_LIBS["synopsys"]
        else:
            self.ieee_lib = self.IEEE_LIBS[ieee_lib]

        # Get the build directory path
        if isinstance(self.config["project_structure"]["build"], list) and self.config["project_structure"]["build"]:
            self.work_dir = self.config["project_structure"]["build"][0]
        else:
            self.work_dir = self.config["project_structure"]["build"]
            
        # Get the synth directory path for outputs
        if isinstance(self.config["project_structure"]["synth"], list) and self.config["project_structure"]["synth"]:
            self.synth_dir = self.config["project_structure"]["synth"][0]
        else:
            self.synth_dir = self.config["project_structure"]["synth"]
            
        # Get individual yosys preference, fallback to global preference for backward compatibility
        tool_prefs = self.config.get("cologne_chip_gatemate_tool_preferences", {})
        if "yosys" in tool_prefs:
            self.tool_access_mode = tool_prefs["yosys"]
        else:
            self.tool_access_mode = self.config.get("cologne_chip_gatemate_toolchain_preference", "PATH")
        self.yosys_access = self._get_yosys_access()
        
        # Create synthesis options file
        self._create_synthesis_options_file()
        
        # ToolChainManager instantiation report
        self._report_instantiation()
    
    def _load_custom_synthesis_strategies(self):
        """Load custom synthesis strategies from synthesis_options.yml file.
        
        This method loads ONLY custom synthesis strategies (marked with custom: true) 
        from the synthesis_options.yml file and adds them to the existing built-in 
        SYNTHESIS_STRATEGIES dictionary. Built-in strategies are always preserved.
        """
        try:
            # Get synthesis options file path
            setup_files = self.config.get("setup_files_initial", {})
            if "synthesis_options_file" in setup_files:
                synthesis_options_path = setup_files["synthesis_options_file"][0]
            else:
                # Fallback to config directory
                config_dir = self.config.get("project_structure", {}).get("config", [])
                if isinstance(config_dir, list) and config_dir:
                    synthesis_options_path = os.path.join(config_dir[0], "synthesis_options.yml")
                else:
                    synthesis_options_path = os.path.join(config_dir, "synthesis_options.yml")
            
            # Load synthesis options
            if os.path.exists(synthesis_options_path):
                import yaml
                with open(synthesis_options_path, 'r') as f:
                    synthesis_options = yaml.safe_load(f)
                
                if synthesis_options and 'synthesis_strategies' in synthesis_options:
                    custom_strategies_loaded = 0
                    # Only add custom strategies, preserve built-in ones
                    for strategy_name, strategy_config in synthesis_options['synthesis_strategies'].items():
                        if 'yosys_commands' in strategy_config and strategy_config.get('custom', False):
                            # Only load strategies marked as custom
                            self.SYNTHESIS_STRATEGIES[strategy_name] = strategy_config['yosys_commands']
                            self.yosys_logger.info(f"Loaded custom synthesis strategy: {strategy_name}")
                            custom_strategies_loaded += 1
                    
                    if custom_strategies_loaded > 0:
                        self.yosys_logger.info(f"Loaded {custom_strategies_loaded} custom synthesis strategies from {synthesis_options_path}")
                    else:
                        self.yosys_logger.debug(f"No custom synthesis strategies found in {synthesis_options_path}")
                
                self.yosys_logger.debug(f"Total synthesis strategies available: {len(self.SYNTHESIS_STRATEGIES)}")
            else:
                self.yosys_logger.debug(f"Synthesis options file not found at {synthesis_options_path}, using built-in strategies only")
                
        except Exception as e:
            self.yosys_logger.error(f"Error loading custom synthesis strategies: {e}, using built-in strategies only")

    def _report_instantiation(self):
        """Log the current YosysCommands configuration settings."""
        tcm_settings = f"""
        New YosysCommands Instantiation Settings:
        SYNTHESIS_STRATEGY:     {self.strategy}
        VHDL_STANDARD:          {self.vhdl_std}
        IEEE_LIBRARY:           {self.ieee_lib}
        WORK_DIRECTORY:         {self.work_dir}
        SYNTH_DIRECTORY:        {self.synth_dir}
        TOOL CHAIN PREFERENCE:  {self.tool_access_mode}
        TOOL CHAIN ACCESS:      {self.yosys_access}
        """
        self.yosys_logger.info(tcm_settings)

    def _get_yosys_access(self) -> str:
        """
        Determine how to access the Yosys binary based on the configured toolchain mode.

        Returns:
            str: Path or command used to invoke Yosys.
        """
        # Get yosys access mode
        yosys_access = ""
        if self.tool_access_mode == "PATH":  # Yosys should be accessed through PATH
            yosys_access = "yosys"  # Accesses the yosys binary through PATH
            self.yosys_logger.info(f"Yosys is accessing binary through {yosys_access}")
        elif self.tool_access_mode == "DIRECT":  # Yosys should be accessed directly
            toolchain_path = self.config.get("cologne_chip_gatemate_toolchain_paths", {})
            yosys_access = toolchain_path.get("yosys", "")
            self.yosys_logger.info(f"Yosys is accessing binary directly through {yosys_access}")
        elif self.tool_access_mode == "UNDEFINED":
            self.yosys_logger.error(f"Yosys access mode is undefined. There is a problem in toolchain manager.")
        else:
            # Fallback for any unexpected values - default to PATH access
            self.yosys_logger.warning(f"Unexpected tool access mode '{self.tool_access_mode}', defaulting to PATH access")
            yosys_access = "yosys"

        return yosys_access

    def _add_yosys_log(self):
        """Add Yosys commands log file path to the project configuration.
        
        This function adds the 'yosys_commands.log' file to the project configuration
        under the 'logs' section, following the structure:
        
        logs:
          yosys_commands:
            yosys_commands.log: /path/to/yosys_commands.log
            
        If the 'yosys_commands' entry already exists, the operation is skipped.
        
        Returns:
            bool: True if the log was added successfully or already exists, False if an error occurred.
        """
        # Check if key exists
        existing_keys = self.config["logs"].keys()
        if "yosys_commands" in existing_keys:  # yosys_commands already added. Skip.
            self.yosys_logger.warning("yosys_commands.log has already been added to the project configuration file. Skipping.")
            return True
        self.yosys_logger.info("Adding yosys_commands.log to the project configuration file.")
        # get logs dir path
        log_path = self.config["project_structure"].get("logs")[0]
        # get yosys log path
        yosys_cmd_log_path = os.path.join(log_path, "yosys_commands.log")
        self.yosys_logger.info(f"Attempting to add yosys_commands.log at {yosys_cmd_log_path} to project configuration file.")
        # Add yosys log to project config.
        self.config["logs"]["yosys_commands"] = {"yosys_commands.log": yosys_cmd_log_path}
        try:
            with open(self.config_path, "w") as config_file:
                yaml.safe_dump(self.config, config_file)
                self.yosys_logger.info(f"Project configuration file updating with yosys_commands.log at {yosys_cmd_log_path}")
                return True
        except Exception as e:
            self.yosys_logger.error(f"An error occured adding yosys_commands.log to project configuration file: {e}")
            return False

    def _create_synthesis_options_file(self):
        """Create synthesis_options.yml file with default synthesis options.
        
        This method creates a comprehensive synthesis options file in the config directory
        that defines default synthesis options, strategy descriptions, VHDL standards,
        and IEEE library compatibility information.
        
        The file is only created if it doesn't already exist to avoid overwriting
        user customizations.
        
        Returns:
            bool: True if file was created or already exists, False if an error occurred.
        """
        try:
            # Get config directory path
            if isinstance(self.config["project_structure"]["config"], list) and self.config["project_structure"]["config"]:
                config_dir = self.config["project_structure"]["config"][0]
            else:
                config_dir = self.config["project_structure"]["config"]
            
            synthesis_options_path = os.path.join(config_dir, "synthesis_options.yml")
            
            # Check if file already exists
            if os.path.exists(synthesis_options_path):
                self.yosys_logger.info(f"Synthesis options file already exists at {synthesis_options_path}. Skipping creation.")
                return True
            
            self.yosys_logger.info(f"Creating synthesis options file at {synthesis_options_path}")
            
            # Define synthesis options content
            synthesis_options_content = {
                'synthesis_defaults': {
                    'strategy': 'balanced',
                    'vhdl_standard': 'VHDL-2008',
                    'ieee_library': 'synopsys'
                },
                'synthesis_strategies': {
                    'area': {
                        'description': 'Optimize for minimal resource usage (LUTs, logic gates)',
                        'recommended_for': 'Designs with tight area constraints or to fit in smaller FPGAs',
                        'yosys_commands': ['synth -top {top} -flatten', 'abc -lut 4 -dress', 'opt_clean', 'opt -full', 'clean']
                    },
                    'speed': {
                        'description': 'Optimize for maximum performance/frequency',
                        'recommended_for': 'High-performance designs where timing is critical',
                        'yosys_commands': ['synth -top {top} -flatten', 'abc -fast', 'opt', 'clean']
                    },
                    'balanced': {
                        'description': 'Standard optimization balancing area and speed',
                        'recommended_for': 'General-purpose designs with no extreme constraints',
                        'default': True,
                        'yosys_commands': ['synth -top {top} -flatten', 'abc', 'opt', 'clean']
                    },
                    'quality': {
                        'description': 'More thorough optimization for better results',
                        'recommended_for': 'Production designs where synthesis time is less important than results',
                        'yosys_commands': ['synth -top {top} -flatten', 'opt -full', 'abc', 'opt -full', 'clean']
                    },
                    'timing': {
                        'description': 'Advanced timing-driven optimization',
                        'recommended_for': 'Designs with critical timing requirements and complex timing paths',
                        'yosys_commands': ['synth -top {top} -flatten', 'abc -lut 4', 'opt_clean', 'abc -lut 4 -dff -D 0.1', 'opt -full', 'clean']
                    },
                    'extreme': {
                        'description': 'Maximum optimization for performance-critical designs',
                        'recommended_for': 'Designs requiring the highest possible performance regardless of synthesis time',
                        'note': 'This strategy uses -full -fine optimizations and can be significantly slower',
                        'yosys_commands': ['synth -top {top} -flatten', 'opt -full', 'abc -lut 4', 'opt -full -fine', 'abc -lut 4 -dff -D 0.01', 'opt -full -fine', 'clean']
                    }
                },
                'vhdl_standards': {
                    'VHDL-1993': {
                        'description': 'VHDL-1993 standard (older, limited features)',
                        'compatibility': 'high',
                        'recommended': False,
                        'yosys_flag': '--std=93'
                    },
                    'VHDL-1993c': {
                        'description': 'VHDL-1993 with relaxed restrictions (partial support)',
                        'compatibility': 'medium',
                        'recommended': False,
                        'note': 'Only partially supported by Yosys + GHDL',
                        'yosys_flag': '--std=93c'
                    },
                    'VHDL-2008': {
                        'description': 'VHDL-2008 standard (most commonly used, recommended)',
                        'compatibility': 'high',
                        'recommended': True,
                        'default': True,
                        'yosys_flag': '--std=08'
                    }
                },
                'ieee_libraries': {
                    'synopsys': {
                        'description': 'Most compatible with synthesis tools (recommended)',
                        'compatibility': 'high',
                        'recommended': True,
                        'default': True,
                        'yosys_flag': '--ieee=synopsys'
                    },
                    'mentor': {
                        'description': 'Alternative implementation (Mentor Graphics)',
                        'compatibility': 'medium',
                        'recommended': False,
                        'yosys_flag': '--ieee=mentor'
                    },
                    'none': {
                        'description': 'No IEEE libraries (minimal, use with caution)',
                        'compatibility': 'low',
                        'recommended': False,
                        'note': 'May cause synthesis issues with standard VHDL designs',
                        'yosys_flag': '--ieee=none'
                    }
                },
                'config_info': {
                    'version': '1.0',
                    'description': 'Default synthesis options for Cologne Chip GateMate toolchain',
                    'maintained_by': 'yosys_commands',
                    'auto_generated': True
                }
            }
            
            # Write the synthesis options file
            import yaml
            with open(synthesis_options_path, 'w') as f:
                # Add header comment
                f.write("# Default Synthesis Options Configuration\n")
                f.write("# This file defines the default synthesis options for the Cologne Chip Project Manager\n")
                f.write("# Auto-generated by yosys_commands.py during instantiation\n")
                f.write("# These settings will be used as fallback values when no custom configuration is set\n\n")
                
                # Write YAML content
                yaml.safe_dump(synthesis_options_content, f, default_flow_style=False, sort_keys=False)
            
            self.yosys_logger.info(f"Successfully created synthesis options file at {synthesis_options_path}")
            
            # Add synthesis options file reference to project configuration
            self._add_synthesis_options_to_config(synthesis_options_path)
            
            return True
            
        except Exception as e:
            self.yosys_logger.error(f"Failed to create synthesis options file: {e}")
            return False

    def _add_synthesis_options_to_config(self, synthesis_options_path: str):
        """Add synthesis options file path to project configuration.
        
        Args:
            synthesis_options_path: Path to the synthesis options file
            
        Returns:
            bool: True if added successfully, False otherwise
        """
        try:
            # Check if synthesis_options_file already exists in setup_files_initial
            setup_files = self.config.get("setup_files_initial", {})
            if "synthesis_options_file" in setup_files:
                self.yosys_logger.info("synthesis_options_file already exists in project configuration. Skipping.")
                return True
            
            self.yosys_logger.info("Adding synthesis_options_file to project configuration.")
            
            # Get config directory for second element
            if isinstance(self.config["project_structure"]["config"], list) and self.config["project_structure"]["config"]:
                config_dir = self.config["project_structure"]["config"][0]
            else:
                config_dir = self.config["project_structure"]["config"]
            
            # Add synthesis options file to project config
            if "setup_files_initial" not in self.config:
                self.config["setup_files_initial"] = {}
            
            self.config["setup_files_initial"]["synthesis_options_file"] = [
                synthesis_options_path,
                config_dir
            ]
            
            # Write back to config file
            with open(self.config_path, "w") as config_file:
                yaml.safe_dump(self.config, config_file)
                
            self.yosys_logger.info(f"Successfully added synthesis_options_file to project configuration: {synthesis_options_path}")
            return True
            
        except Exception as e:
            self.yosys_logger.error(f"Failed to add synthesis_options_file to project configuration: {e}")
            return False

    def _get_vhdl_files(self) -> List[str]:
        """
        Get a list of VHDL files to synthesize from the project hierarchy.
        
        This internal method retrieves the VHDL file paths from the project 
        hierarchy configuration. It collects files from the 'src' section and
        optionally includes files from the 'top' section if they're not already
        in the list.
        
        The method relies on a properly configured HDL project hierarchy in the
        project configuration file. If the hierarchy doesn't exist, it will return
        an empty list.
        
        The collected files include all source files needed for synthesis, but
        typically exclude testbench files which are usually not synthesizable.
        
        Returns:
            List[str]: List of absolute paths to VHDL files for synthesis
            
        Note:
            This is an internal helper method used by the synthesis methods and
            is not typically called directly by users.
        """
        vhdl_files = []
        if self.check_hierarchy():
            # Include source files
            if "src" in self.config["hdl_project_hierarchy"]:
                for file_name, file_path in self.config["hdl_project_hierarchy"]["src"].items():
                    vhdl_files.append(file_path)
                    
            # Include top level file if it's different from src files
            if "top" in self.config["hdl_project_hierarchy"]:
                for file_name, file_path in self.config["hdl_project_hierarchy"]["top"].items():
                    if file_path not in vhdl_files:
                        vhdl_files.append(file_path)
                        
        return vhdl_files

    def analyze_and_elaborate_vhdl(self, vhdl_files: List[str], top_entity: str) -> bool:
        """
        Analyze and elaborate VHDL files into Yosys using the GHDL plugin.
        
        This function uses the Yosys GHDL plugin to perform both analysis and elaboration
        of VHDL source files in a single operation:
        
        1. Analysis: Parses and checks the VHDL source files for syntax and semantics
        2. Elaboration: Creates the design hierarchy with the specified top entity
        
        The processed design is imported into the Yosys environment for synthesis,
        converted to the internal Yosys Intermediate Language (IL) format.
        
        The command syntax used is:
        
            yosys -p "ghdl --std=08 --ieee=synopsys VHDL_FILES -e TOP_ENTITY"
        
        Where:
        - VHDL_FILES are space-separated paths to the input VHDL files
        - TOP_ENTITY is the name of the top-level entity to elaborate
        
        Common GHDL plugin options include:
            `--std=STD`:         VHDL standard to use (93, 93c, 08)
            `--ieee=MODE`:       IEEE library mode (synopsys, mentor, none)
            `-e ENTITY`:         Top entity name to elaborate
            `--work=NAME`:       Set the work library name
            `--no-formal`:       Disable formal verification features
            `--no-ieee`:         Disable IEEE library
            
        Args:
            vhdl_files: List of VHDL file paths to analyze
            top_entity: Name of the top-level entity to elaborate
            
        Returns:
            bool: True if successful, False otherwise
            
        Example:
            ```python
            yosys = YosysCommands()
            vhdl_files = ["counter.vhd", "counter_pkg.vhd"]
            yosys.analyze_and_elaborate_vhdl(vhdl_files, "counter")
            ```
        """
        if not vhdl_files:
            self.yosys_logger.error("No VHDL files provided for synthesis")
            return False
            
        # Create the command with all files
        # Check if any files have spaces - if so, we'll use a script file approach
        files_with_spaces = any(" " in file for file in vhdl_files)
        
        if files_with_spaces:
            # For paths with spaces, use script file approach with proper quoting
            vhdl_files_str = " ".join(f'"{file}"' for file in vhdl_files)
            ghdl_command = f"ghdl {self.vhdl_std} {self.ieee_lib} {vhdl_files_str} -e {top_entity}"
            
            self.yosys_logger.info("File paths contain spaces, using temporary script file for GHDL command")
            import tempfile
            with tempfile.NamedTemporaryFile(mode='w', suffix='.ys', delete=False) as script_file:
                script_file.write(ghdl_command)
                script_file_path = script_file.name
            
            read_cmd = [self.yosys_access, "-s", script_file_path]
        else:
            # For paths without spaces, use the normal approach
            vhdl_files_str = " ".join(vhdl_files)
            read_cmd = [self.yosys_access, "-p", 
                        f"ghdl {self.vhdl_std} {self.ieee_lib} {vhdl_files_str} -e {top_entity}"]
        
        self.yosys_logger.info(f"Analyzing and elaborating VHDL files with GHDL plugin")
        self.yosys_logger.debug(f"Command: {' '.join(read_cmd)}")
        
        try:
            result = subprocess.run(read_cmd, check=True, capture_output=True, text=True)
            self.yosys_logger.info(f"Successfully analyzed and elaborated VHDL files")
            if result.stdout:
                self.yosys_logger.debug(f"Yosys output: {result.stdout}")
            return True
        except subprocess.CalledProcessError as e:
            self.yosys_logger.error(f"Failed to analyze and elaborate VHDL files: {e}")
            self.yosys_logger.error(f"STDERR: {e.stderr}")
            return False
        finally:
            # Clean up script file if it was created
            if files_with_spaces and 'script_file_path' in locals():
                try:
                    os.unlink(script_file_path)
                except:
                    pass

    def synthesize(self, top_entity: str, options: Optional[List[str]] = None) -> bool:
        """
        Synthesize a VHDL design using Yosys.
        
        This function analyzes and elaborates VHDL files and runs Yosys to synthesize the design 
        according to the selected strategy. The synthesis process converts the VHDL design into 
        a gate-level netlist, optimized for the chosen strategy (area, speed, balanced, quality, 
        timing, or extreme).
        
        The Yosys command syntax used is:
        
            yosys -p "ghdl --std=08 --ieee=synopsys VHDL_FILES -e TOP_ENTITY; 
                     synth -top TOP_ENTITY -flatten;
                     [STRATEGY_SPECIFIC_COMMANDS];
                     write_verilog -noattr OUTPUT_VERILOG;
                     write_json OUTPUT_JSON" [USER_OPTIONS]
        
        Where:
        - VHDL_FILES are the input design files
        - TOP_ENTITY is the name of the top-level entity to synthesize
        - STRATEGY_SPECIFIC_COMMANDS are commands based on the selected strategy
        - OUTPUT_VERILOG/OUTPUT_JSON are the output file paths
        - USER_OPTIONS are additional command-line options provided via the options parameter
        
        Args:
            top_entity: Name of the top-level entity to synthesize
            options: Additional command-line options for Yosys as a list of strings. These are 
                     appended to the command and are independent of the synthesis strategy.
            
        Common Yosys synthesis commands and options:
            `synth -top TOP`: Main synthesis command for generic technology
            `-flatten`: Flatten the design hierarchy
            `abc`: Technology mapping using ABC tool (default balanced mode)
            `abc -fast`: Faster but less optimal mapping
            `abc -g AND,OR`: Optimize for AND/OR gates (area strategy)
            `opt`: Basic optimizations
            `opt -full`: More extensive optimizations
            `opt_clean`: Removes unused cells and wires
            `clean`: Remove unused elements from design
            `abc -lut 4`: Map to 4-input LUTs (for FPGA targets)
            `abc -lut 4 -dff -D 0.1`: Advanced timing-driven mapping
            
        Returns:
            bool: True if synthesis successful, False otherwise
            
        Example:
            ```python
            yosys = YosysCommands()
            # Basic synthesis with default settings (balanced strategy)
            yosys.synthesize("counter")
            
            # Synthesis optimized for speed
            yosys = YosysCommands(strategy="speed")
            yosys.synthesize("counter")
            
            # Synthesis with additional Yosys command-line options
            yosys.synthesize("counter", options=["-q", "-l", "synthesis.log"])
            
            # Combining strategy and custom options
            yosys = YosysCommands(strategy="area")
            yosys.synthesize("counter", options=["-v", "-T"]) # Verbose with timing info
            ```
        """
        # Ensure the synth directory exists
        os.makedirs(self.synth_dir, exist_ok=True)
            
        # Get list of VHDL files to synthesize
        vhdl_files = self._get_vhdl_files()
        if not vhdl_files:
            self.yosys_logger.error("No VHDL files found for synthesis")
            return False
            
        # Format file paths as space-separated string with single quotes for paths with spaces
        vhdl_files_str = " ".join(f"'{file}'" if " " in file else file for file in vhdl_files)
        
        # Output file paths
        verilog_path = os.path.join(self.synth_dir, f"{top_entity}_synth.v")
        json_path = os.path.join(self.synth_dir, f"{top_entity}_synth.json")
        
        # Build the complete Yosys command script with all steps
        commands = [
            f"ghdl {self.vhdl_std} {self.ieee_lib} {vhdl_files_str} -e {top_entity};",
            f"synth -top {top_entity} -flatten;",
        ]
        
        # Add optimization commands based on strategy
        # The first command in each strategy array is synth, which we've already added above,
        # so we skip it and only add the remaining commands
        commands.extend([cmd.format(top=top_entity) + ";" for cmd in self.SYNTHESIS_STRATEGIES[self.strategy][1:]])
        
        # Add output commands
        commands.extend([
            f"write_verilog -noattr {verilog_path};",
            f"write_json {json_path};"
        ])
        
        # Construct the full command
        yosys_cmd = [self.yosys_access, "-p", " ".join(commands)]
        
        if options:
            yosys_cmd.extend(options)
            
        self.yosys_logger.info(f"Running synthesis for {top_entity}")
        self.yosys_logger.debug(f"Yosys command: {' '.join(yosys_cmd)}")
        
        try:
            result = subprocess.run(yosys_cmd, check=True, capture_output=True, text=True)
            
            # Log detailed Yosys output for synthesis log viewing
            if result.stdout:
                self.yosys_logger.info("=== YOSYS SYNTHESIS OUTPUT ===")
                # Log each line of stdout separately for better formatting
                for line in result.stdout.strip().split('\n'):
                    if line.strip():
                        self.yosys_logger.info(f"YOSYS: {line}")
                self.yosys_logger.info("=== END YOSYS OUTPUT ===")
            
            if result.stderr:
                self.yosys_logger.warning("=== YOSYS STDERR ===")
                for line in result.stderr.strip().split('\n'):
                    if line.strip():
                        self.yosys_logger.warning(f"YOSYS STDERR: {line}")
                self.yosys_logger.warning("=== END YOSYS STDERR ===")
            
            self.yosys_logger.info(f"Successfully synthesized {top_entity}")
            self.yosys_logger.info(f"Generated Verilog output: {verilog_path}")
            self.yosys_logger.info(f"Generated JSON output: {json_path}")
            return True
        except subprocess.CalledProcessError as e:
            self.yosys_logger.error(f"Synthesis failed: {e}")
            self.yosys_logger.error(f"Command that failed: {' '.join(yosys_cmd)}")
            if e.stdout:
                self.yosys_logger.error("=== YOSYS STDOUT (FAILED) ===")
                for line in e.stdout.strip().split('\n'):
                    if line.strip():
                        self.yosys_logger.error(f"YOSYS STDOUT: {line}")
                self.yosys_logger.error("=== END YOSYS STDOUT ===")
            if e.stderr:
                self.yosys_logger.error("=== YOSYS STDERR (FAILED) ===")
                for line in e.stderr.strip().split('\n'):
                    if line.strip():
                        self.yosys_logger.error(f"YOSYS STDERR: {line}")
                self.yosys_logger.error("=== END YOSYS STDERR ===")
            return False

    def synthesize_gatemate(self, top_entity: str, options: Optional[List[str]] = None) -> bool:
        """
        Synthesize a VHDL design for the GateMate FPGA using Yosys.
        
        This function analyzes and elaborates VHDL files and runs Yosys with GateMate-specific synthesis 
        commands to create a netlist optimized specifically for the Cologne Chip GateMate FPGA.
        It uses the synth_gatemate command which is specially designed for GateMate FPGAs and
        provides better results than generic synthesis for this target.
        
        The Yosys command syntax used is:
        
            yosys -p "ghdl --std=08 --ieee=synopsys VHDL_FILES -e TOP_ENTITY;
                     synth_gatemate -top TOP_ENTITY -vlog OUTPUT_VERILOG;
                     write_verilog -noattr NETLIST_PATH" [USER_OPTIONS]
                     
        Where: 
        - VHDL_FILES are the input design files
        - TOP_ENTITY is the name of the top-level entity to synthesize
        - OUTPUT_VERILOG is the path to the output Verilog file
        - NETLIST_PATH is the path to the technology-mapped netlist file
        - USER_OPTIONS are additional command-line options provided via the options parameter
        
        Args:
            top_entity: Name of the top-level entity to synthesize
            options: Additional command-line options for Yosys as a list of strings. These are 
                     appended to the command and are independent of the synthesis strategy.
            
        Common synth_gatemate options include:
            `-top TOP`: Specify the top module
            `-vlog FILE`: Write Verilog netlist to file
            `-run <from_step>:<to_step>`: Run only selected parts of the flow
            `-nodffe`: Do not use flip-flops with enable
            `-nobram`: Do not use block RAMs, use logic instead
            `-nomx8`: Do not use MX8 cells, use logic instead
            `-nolutram`: Do not use LUT RAMs, use logic instead
            `-nobram-ports`: Expose individual BRAM ports
            `-noalu`: Do not use ALU cells, use logic instead
            `-no-rw-check`: Skip read/write port checking for RAMs
            
        Returns:
            bool: True if synthesis successful, False otherwise
            
        Example:
            ```python
            yosys = YosysCommands()
            # Basic GateMate-specific synthesis with default settings (balanced strategy)
            yosys.synthesize_gatemate("counter")
            
            # GateMate-specific synthesis optimized for area
            yosys = YosysCommands(strategy="area")
            yosys.synthesize_gatemate("counter")
            
            # GateMate synthesis with additional Yosys command-line options
            yosys.synthesize_gatemate("counter", options=["-q", "-l", "gatemate_synth.log"])
            
            # Combining strategy and custom options
            yosys = YosysCommands(strategy="timing")
            yosys.synthesize_gatemate("counter", options=["-v", "-T"]) # Verbose with timing info
            ```
        """
        # Ensure the synth directory exists
        os.makedirs(self.synth_dir, exist_ok=True)
        
        # Ensure the netlist directory exists
        netlist_dir = self.config["project_structure"]["impl"]["netlist"][0]
        os.makedirs(netlist_dir, exist_ok=True)
            
        # Get list of VHDL files to synthesize
        vhdl_files = self._get_vhdl_files()
        if not vhdl_files:
            self.yosys_logger.error("No VHDL files found for synthesis")
            return False
            
        # Check if any files have spaces - if so, we'll use temporary directory approach
        files_with_spaces = any(" " in file for file in vhdl_files)
        temp_dir_to_cleanup = None
        
        # Import shutil for file operations if needed
        if files_with_spaces:
            import shutil
        

        if files_with_spaces:
            # For paths with spaces, copy files to temporary directory without spaces
            # This completely avoids all quoting/escaping issues
            self.yosys_logger.info("Files with spaces detected - copying to temporary directory")
            import tempfile
            import shutil
            
            # Create a temporary directory without spaces
            temp_dir = tempfile.mkdtemp(prefix="yosys_temp_")
            self.yosys_logger.info(f"Created temporary directory: {temp_dir}")
            
            # Copy VHDL files to temp directory and track mappings
            vhdl_files_temp = []
            file_mappings = []
            
            for file in vhdl_files:
                if os.path.exists(file):
                    # Get just the filename
                    filename = os.path.basename(file)
                    temp_file_path = os.path.join(temp_dir, filename)
                    
                    # Copy the file
                    shutil.copy2(file, temp_file_path)
                    vhdl_files_temp.append(temp_file_path)
                    file_mappings.append((file, temp_file_path))
                    self.yosys_logger.info(f"Copied: {file} -> {temp_file_path}")
                else:
                    self.yosys_logger.error(f"Source file not found: {file}")
                    return False
            
            vhdl_files_str = " ".join(vhdl_files_temp)
            self.yosys_logger.info(f"Using temporary VHDL files: {vhdl_files_str}")
            
            # Store temp_dir for cleanup later
            temp_dir_to_cleanup = temp_dir
        else:
            # For paths without spaces, use the normal approach
            vhdl_files_str = " ".join(vhdl_files)
            temp_dir_to_cleanup = None
        
        # Output file paths
        verilog_path = os.path.join(self.synth_dir, f"{top_entity}_synth.v")
        netlist_path = os.path.join(netlist_dir, f"{top_entity}.v")
        
        # Handle output paths - use temp directory if input files have spaces
        if files_with_spaces:
            # Use temporary directory for output files too
            verilog_filename = f"{top_entity}_synth.v"
            netlist_filename = f"{top_entity}.v"
            
            verilog_path_temp = os.path.join(temp_dir, verilog_filename)
            netlist_path_temp = os.path.join(temp_dir, netlist_filename)
            
            verilog_path_final = verilog_path_temp
            netlist_path_final = netlist_path_temp
            
            self.yosys_logger.info(f"Temporary verilog output: {verilog_path_final}")
            self.yosys_logger.info(f"Temporary netlist output: {netlist_path_final}")
        else:
            verilog_path_final = verilog_path
            netlist_path_final = netlist_path
        
        # Build the complete Yosys command script with all steps
        # For GateMate, we use the synth_gatemate command which is a specialized
        # synthesis command for GateMate FPGAs, followed by strategy-specific optimizations
        commands = [
            f"ghdl {self.vhdl_std} {self.ieee_lib} {vhdl_files_str} -e {top_entity};",
            f"synth_gatemate -top {top_entity} -vlog {verilog_path_final};",
        ]
        
        # Add strategy-specific optimization commands after GateMate synthesis
        # Skip the first command (synth) since we use synth_gatemate instead
        strategy_commands = [cmd.format(top=top_entity) + ";" for cmd in self.SYNTHESIS_STRATEGIES[self.strategy][1:]]
        commands.extend(strategy_commands)
        
        # Add final output command
        commands.append(f"write_verilog -noattr {netlist_path_final};")
        
        # Log the strategy being applied
        self.yosys_logger.info(f"Applying '{self.strategy}' strategy optimizations after GateMate synthesis")
        self.yosys_logger.debug(f"Strategy commands: {strategy_commands}")
        
        # Construct the full command
        yosys_cmd = [self.yosys_access, "-p", " ".join(commands)]
        
        # Debug: Check if yosys executable exists and is accessible
        self.yosys_logger.debug(f"Yosys executable path: {repr(self.yosys_access)}")
        if os.path.sep in self.yosys_access:  # Full path
            if not os.path.exists(self.yosys_access):
                self.yosys_logger.error(f"Yosys executable not found at: {self.yosys_access}")
            elif not os.access(self.yosys_access, os.X_OK):
                self.yosys_logger.error(f"Yosys executable not executable: {self.yosys_access}")
        else:  # PATH-based executable
            import shutil
            if not shutil.which(self.yosys_access):
                self.yosys_logger.error(f"Yosys executable '{self.yosys_access}' not found in PATH")
        
        if options:
            yosys_cmd.extend(options)
            
        self.yosys_logger.info(f"Running GateMate synthesis for {top_entity}")
        self.yosys_logger.debug(f"Yosys command: {' '.join(yosys_cmd)}")
        
        # Debug: Log the exact command components
        self.yosys_logger.debug(f"Command components:")
        for i, component in enumerate(yosys_cmd):
            self.yosys_logger.debug(f"  [{i}]: {repr(component)}")
        
        # Debug: Check command length
        full_cmd_str = ' '.join(yosys_cmd)
        self.yosys_logger.debug(f"Full command length: {len(full_cmd_str)} characters")
        if len(full_cmd_str) > 8191:
            self.yosys_logger.warning(f"Command line is very long ({len(full_cmd_str)} chars), may exceed Windows limit")
        
        # Use script file if command line is too long OR if there are spaces in file paths
        use_script_file = len(full_cmd_str) > 8000 or files_with_spaces
        script_cmd = None
        
        try:
            
            if use_script_file:
                if files_with_spaces:
                    self.yosys_logger.info("File paths contain spaces, using temporary script file to avoid quoting issues")
                else:
                    self.yosys_logger.info("Command line too long, using temporary script file")
                    
                import tempfile
                with tempfile.NamedTemporaryFile(mode='w', suffix='.ys', delete=False) as script_file:
                    script_content = " ".join(commands)
                    script_file.write(script_content)
                    script_file_path = script_file.name
                    
                    # Debug: Log the script content for troubleshooting
                    self.yosys_logger.debug(f"Script file content: {script_content}")
                    if files_with_spaces:
                        self.yosys_logger.info(f"Files with spaces detected: {[f for f in vhdl_files if ' ' in f]}")
                        self.yosys_logger.info(f"VHDL files string: {vhdl_files_str}")
                        self.yosys_logger.info(f"Verilog output: {verilog_path_final}")
                        self.yosys_logger.info(f"Netlist output: {netlist_path_final}")
                
                try:
                    # Run yosys with script file
                    script_cmd = [self.yosys_access, "-s", script_file_path]
                    if options:
                        script_cmd.extend(options)
                    self.yosys_logger.debug(f"Using script file: {script_file_path}")
                    self.yosys_logger.debug(f"Script command: {' '.join(script_cmd)}")
                    self.yosys_logger.debug(f"Script content: {' '.join(commands)}")
                    result = subprocess.run(script_cmd, check=True, capture_output=True, text=True)
                finally:
                    # Clean up temporary file
                    try:
                        os.unlink(script_file_path)
                    except:
                        pass
            else:
                result = subprocess.run(yosys_cmd, check=True, capture_output=True, text=True)
            
            # Log detailed Yosys output for synthesis log viewing
            if result.stdout:
                self.yosys_logger.info("=== YOSYS GATEMATE SYNTHESIS OUTPUT ===")
                # Log each line of stdout separately for better formatting
                for line in result.stdout.strip().split('\n'):
                    if line.strip():
                        self.yosys_logger.info(f"YOSYS: {line}")
                self.yosys_logger.info("=== END YOSYS GATEMATE OUTPUT ===")
            
            if result.stderr:
                self.yosys_logger.warning("=== YOSYS GATEMATE STDERR ===")
                for line in result.stderr.strip().split('\n'):
                    if line.strip():
                        self.yosys_logger.warning(f"YOSYS STDERR: {line}")
                self.yosys_logger.warning("=== END YOSYS GATEMATE STDERR ===")
            
            self.yosys_logger.info(f"Successfully synthesized {top_entity} for GateMate")
            
            # If we used temporary files, copy outputs back to original locations
            if files_with_spaces and temp_dir_to_cleanup:
                try:
                    # Copy output files back to original locations
                    if os.path.exists(verilog_path_final):
                        shutil.copy2(verilog_path_final, verilog_path)
                        self.yosys_logger.info(f"Copied verilog output: {verilog_path_final} -> {verilog_path}")
                    
                    if os.path.exists(netlist_path_final):
                        shutil.copy2(netlist_path_final, netlist_path)
                        self.yosys_logger.info(f"Copied netlist output: {netlist_path_final} -> {netlist_path}")
                    
                    # Clean up temporary directory
                    shutil.rmtree(temp_dir_to_cleanup)
                    self.yosys_logger.info(f"Cleaned up temporary directory: {temp_dir_to_cleanup}")
                    
                except Exception as e:
                    self.yosys_logger.warning(f"Error during cleanup: {e}")
            
            self.yosys_logger.info(f"Generated Verilog output: {verilog_path}")
            self.yosys_logger.info(f"Generated netlist: {netlist_path}")
            return True
        except subprocess.CalledProcessError as e:
            self.yosys_logger.error(f"GateMate synthesis failed: {e}")
            if use_script_file:
                self.yosys_logger.error(f"Script command that failed: {' '.join(script_cmd)}")
                self.yosys_logger.error(f"Script content that failed: {' '.join(commands)}")
            else:
                self.yosys_logger.error(f"Command that failed: {' '.join(yosys_cmd)}")
            
            # Check for common path-related issues
            path_issue_detected = False
            if e.stderr:
                stderr_text = e.stderr.lower()
                if "unexpected extension for file" in stderr_text or "cannot find entity" in stderr_text:
                    # Check if any VHDL files have spaces in their paths
                    files_with_spaces = [f for f in vhdl_files if " " in f]
                    if files_with_spaces:
                        path_issue_detected = True
                        self.yosys_logger.error("❌ PATH WITH SPACES DETECTED")
                        self.yosys_logger.error("❌ Synthesis failed due to file paths containing spaces.")
                        self.yosys_logger.error("❌ GHDL/Yosys has issues with file paths that contain spaces.")
                        self.yosys_logger.error("")
                        self.yosys_logger.error("🔍 PROBLEMATIC FILES:")
                        for file_path in files_with_spaces:
                            self.yosys_logger.error(f"   • {file_path}")
                        self.yosys_logger.error("")
                        self.yosys_logger.error("🔧 SOLUTIONS:")
                        self.yosys_logger.error("   1. Move your project to a path without spaces")
                        self.yosys_logger.error("      Example: C:\\Projects\\MyProject instead of C:\\My Projects\\MyProject")
                        self.yosys_logger.error("   2. Rename directories to remove spaces")
                        self.yosys_logger.error("      Example: 'New folder' → 'NewFolder' or 'New_folder'")
                        self.yosys_logger.error("   3. Use underscores or hyphens instead of spaces")
                        self.yosys_logger.error("   4. Avoid placing projects in Desktop or Documents folders with spaces")
                        self.yosys_logger.error("")
                        self.yosys_logger.error("📁 RECOMMENDED PROJECT LOCATIONS:")
                        self.yosys_logger.error("   • C:\\Projects\\")
                        self.yosys_logger.error("   • C:\\FPGA_Projects\\")
                        self.yosys_logger.error("   • C:\\Development\\")
                        self.yosys_logger.error("   • D:\\Projects\\ (if you have a D: drive)")
            
            if e.stdout:
                self.yosys_logger.error("=== YOSYS GATEMATE STDOUT (FAILED) ===")
                for line in e.stdout.strip().split('\n'):
                    if line.strip():
                        self.yosys_logger.error(f"YOSYS STDOUT: {line}")
                self.yosys_logger.error("=== END YOSYS GATEMATE STDOUT ===")
            if e.stderr:
                self.yosys_logger.error("=== YOSYS GATEMATE STDERR (FAILED) ===")
                for line in e.stderr.strip().split('\n'):
                    if line.strip():
                        self.yosys_logger.error(f"YOSYS STDERR: {line}")
                self.yosys_logger.error("=== END YOSYS GATEMATE STDERR ===")
                
            if not path_issue_detected:
                self.yosys_logger.error("")
                self.yosys_logger.error("🔧 COMMON SYNTHESIS ISSUES:")
                self.yosys_logger.error("   • Check that all VHDL files exist and are readable")
                self.yosys_logger.error("   • Verify the top entity name matches the entity in your VHDL file")
                self.yosys_logger.error("   • Ensure VHDL syntax is correct")
                self.yosys_logger.error("   • Check that GHDL and Yosys are properly installed")
                self.yosys_logger.error("   • Avoid file paths with spaces or special characters")
            
            # Clean up temporary directory if it was created
            if files_with_spaces and temp_dir_to_cleanup:
                try:
                    shutil.rmtree(temp_dir_to_cleanup)
                    self.yosys_logger.info(f"Cleaned up temporary directory after error: {temp_dir_to_cleanup}")
                except Exception as cleanup_error:
                    self.yosys_logger.warning(f"Error during error cleanup: {cleanup_error}")
            
            return False

    def parse_entity_name_from_vhdl(self, vhdl_file_path):
        """
        Parse and return the first entity name found in a VHDL file.
        
        This function reads a VHDL file and extracts the entity name
        by looking for the 'entity' keyword followed by an identifier.
        
        This is a utility method that can be used to automatically determine
        the top entity name from a VHDL file, which is useful when automating
        the synthesis process without having to manually specify entity names.
        
        The function performs a simple text-based search and does not perform
        full VHDL parsing - it looks for lines that start with "entity " and
        extracts the following word as the entity name. This approach works
        for most standard VHDL files but may not handle all edge cases or
        complex formatting.
        
        Args:
            vhdl_file_path (str): Path to the VHDL file to parse
            
        Returns:
            str or None: The entity name if found, None otherwise
            
        Example:
            ```python
            yosys = YosysCommands()
            entity_name = yosys.parse_entity_name_from_vhdl("counter.vhd")
            if entity_name:
                print(f"Found entity: {entity_name}")
                yosys.synthesize(entity_name)
            else:
                print("No entity found in the file")
            ```
        """
        self.yosys_logger.info(f"Parsing entity name from VHDL file: {vhdl_file_path}")
        
        if not os.path.exists(vhdl_file_path):
            self.yosys_logger.error(f"VHDL file not found: {vhdl_file_path}")
            return None
        
        try:
            self.yosys_logger.debug(f"Opening VHDL file for parsing: {vhdl_file_path}")
            with open(vhdl_file_path, 'r', encoding='utf-8') as f:
                line_number = 0
                for line in f:
                    line_number += 1
                    line = line.strip()
                    if line.lower().startswith('entity '):
                        parts = line.split()
                        if len(parts) >= 2:
                            entity_name = parts[1]
                            self.yosys_logger.info(f"Found entity '{entity_name}' at line {line_number}")
                            return entity_name
            
            self.yosys_logger.warning(f"No entity declaration found in file: {vhdl_file_path}")
            return None
        except Exception as e:
            self.yosys_logger.error(f"Error parsing entity name from {vhdl_file_path}: {e}")
            return None

    def check_hierarchy(self) -> bool:
        """
        Check if the HDL hierarchy exists in the project configuration.
        
        This method verifies that the project configuration contains the necessary
        'hdl_project_hierarchy' section, which defines the structure of HDL files
        in the project. This hierarchy is required for automatic collection of
        source files during synthesis.
        
        The HDL hierarchy in the project configuration typically looks like:
        
        ```yaml
        hdl_project_hierarchy:
          src:
            StateMachineTest.vhd: /path/to/StateMachineTest.vhd
          top:
            top_entity.vhd: /path/to/top_entity.vhd
          tb:
            test_bench.vhd: /path/to/test_bench.vhd
        ```
        
        This method logs an error and returns False if the hierarchy is not defined,
        allowing calling methods to handle the error condition appropriately.
        
        Returns:
            bool: True if the hierarchy exists, False otherwise
            
        Example:
            ```python
            yosys = YosysCommands()
            if yosys.check_hierarchy():
                # Proceed with synthesis
                yosys.synthesize("my_entity")
            else:
                # Handle missing hierarchy
                print("Please set up the HDL project hierarchy first")
            ```
        """
        if "hdl_project_hierarchy" not in self.config:
            self.yosys_logger.error("The project's HDL hierarchy has not been set. Check set_hierarchy settings.")
            print("The project's HDL hierarchy has not been set. Check set_hierarchy settings.")
            return False
        return True

    def get_available_synthesized_designs(self) -> List[str]:
        """Find available synthesized designs that can be used for place and route.
        
        Scans the synthesis output directory for synthesized netlist files (JSON and Verilog)
        and returns a list of design names that have been successfully synthesized.
        
        Returns:
            List[str]: List of design names (without extensions) that have synthesized netlists
        """
        designs = []
        try:
            if os.path.exists(self.synth_dir):
                self.yosys_logger.info(f"Scanning for synthesized designs in {self.synth_dir}")
                
                # Look for synthesized JSON files (preferred by P&R)
                for file in os.listdir(self.synth_dir):
                    if file.endswith('_synth.json'):
                        design_name = file.replace('_synth.json', '')
                        designs.append(design_name)
                        self.yosys_logger.info(f"Found synthesized design: {design_name} (JSON)")
                        
                # Also look for synthesized Verilog files as backup
                for file in os.listdir(self.synth_dir):
                    if file.endswith('_synth.v'):
                        design_name = file.replace('_synth.v', '')
                        if design_name not in designs:  # Avoid duplicates
                            designs.append(design_name)
                            self.yosys_logger.info(f"Found synthesized design: {design_name} (Verilog)")
                            
                self.yosys_logger.info(f"Found {len(designs)} synthesized designs: {designs}")
            else:
                self.yosys_logger.warning(f"Synthesis directory not found: {self.synth_dir}")
                
        except Exception as e:
            self.yosys_logger.error(f"Error scanning for synthesized designs: {e}")
            
        return sorted(designs)

if __name__ == "__main__":
    yosys = YosysCommands()
    # Get a top entity from the config if available
    top_entity = None
    if yosys.check_hierarchy() and "top" in yosys.config["hdl_project_hierarchy"]:
        top_files = yosys.config["hdl_project_hierarchy"]["top"]
        if top_files:
            first_top_file = list(top_files.keys())[0]
            # Parse entity name from file
            vhdl_file_path = top_files[first_top_file]
            top_entity = yosys.parse_entity_name_from_vhdl(vhdl_file_path)
    
    if top_entity:
        print(f"Top entity detected: {top_entity}")
        print(f"You can now synthesize this entity with:")
        print(f"1. Standard synthesis:  yosys.synthesize('{top_entity}')")
        print(f"2. GateMate synthesis: yosys.synthesize_gatemate('{top_entity}')")
    else:
        print("No top entity found in project hierarchy. Please set up the hierarchy first.") 