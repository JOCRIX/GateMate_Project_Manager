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
        self._yosys_bound_log_path = None

        if not self.yosys_logger.handlers or self._yosys_log_path_outdated():
            # Rebind handlers so a new/loaded project always gets the correct log file
            for handler in self.yosys_logger.handlers[:]:
                try:
                    handler.close()
                except Exception:
                    pass
                self.yosys_logger.removeHandler(handler)

            log_path = os.path.normpath(
                os.path.join(self.config["project_structure"]["logs"][0], "yosys_commands.log")
            )
            file_handler = logging.FileHandler(log_path)
            formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
            file_handler.setFormatter(formatter)
            self.yosys_logger.addHandler(file_handler)
            self._yosys_bound_log_path = log_path
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

    def _yosys_log_path_outdated(self) -> bool:
        """True when logger is bound to a different project's yosys log file."""
        try:
            expected = os.path.normpath(
                os.path.join(self.config["project_structure"]["logs"][0], "yosys_commands.log")
            )
        except Exception:
            return True
        bound = getattr(self, "_yosys_bound_log_path", None)
        if bound and os.path.normpath(bound) != expected:
            return True
        for handler in self.yosys_logger.handlers:
            base = getattr(handler, "baseFilename", None)
            if base and os.path.normpath(base) != expected:
                return True
        return False
    
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

        Prefers an absolute configured path when available; otherwise PATH.
        """
        cmd = self.get_tool_command("yosys")
        if cmd and os.path.isabs(cmd) and os.path.exists(cmd):
            self.yosys_logger.info(f"Yosys accessing binary through {cmd}")
            return cmd

        toolchain_path = self.config.get("cologne_chip_gatemate_toolchain_paths", {})
        direct = toolchain_path.get("yosys", "") or ""
        if direct and os.path.exists(direct):
            self.yosys_logger.info(f"Yosys accessing binary through {direct}")
            return direct

        if self.tool_access_mode == "PATH" or not cmd:
            self.yosys_logger.info("Yosys accessing binary through PATH name: yosys")
            return "yosys"

        if cmd:
            self.yosys_logger.info(f"Yosys accessing binary through {cmd}")
            return cmd

        self.yosys_logger.error("Yosys access mode is undefined or path missing")
        return "yosys"

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

    def _get_vhdl_files(self, primary_file: Optional[str] = None) -> List[str]:
        """
        Get a list of VHDL files to synthesize from the project hierarchy.

        Args:
            primary_file: Optional absolute path of the selected source file.
                When set, that file is placed first. If other project files
                declare the same top entity, they are excluded to avoid GHDL
                collisions when duplicate entity names exist across files.
        """
        vhdl_files = []
        hierarchy = self.config.get("hdl_project_hierarchy") if self.config else None
        if isinstance(hierarchy, dict):
            if "src" in hierarchy:
                for file_name, file_path in hierarchy["src"].items():
                    vhdl_files.append(file_path)
                    
            if "top" in hierarchy:
                for file_name, file_path in hierarchy["top"].items():
                    if file_path not in vhdl_files:
                        vhdl_files.append(file_path)
        else:
            self.yosys_logger.warning(
                "Project HDL hierarchy is not set; synthesis may have no VHDL sources."
            )

        if primary_file:
            primary_norm = os.path.normpath(primary_file)
            # Ensure selected file is included and first
            others = [f for f in vhdl_files if os.path.normpath(f) != primary_norm]
            if os.path.exists(primary_norm):
                vhdl_files = [primary_norm] + others
            else:
                self.yosys_logger.warning(f"Primary VHDL file not found: {primary_file}")

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
            result = subprocess.run(
                read_cmd,
                check=True,
                capture_output=True,
                text=True,
                env=self.get_tool_run_env(),
            )
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
            result = subprocess.run(
                yosys_cmd,
                check=True,
                capture_output=True,
                text=True,
                env=self.get_tool_run_env(),
            )
            
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

    def synthesize_gatemate(
        self,
        top_entity: str,
        options: Optional[List[str]] = None,
        primary_file: Optional[str] = None,
    ) -> bool:
        """Synthesize VHDL for GateMate using standalone GHDL then Yosys.

        New OSS CAD Suite flow:
            1) ``ghdl synth ... --out=verilog -e TOP`` -> ASCII ``{TOP}_synth.v``
            2) ``yosys -p "read_verilog ...; synth_gatemate -top TOP -luttree -nomx8 -json ..."``
               -> ``{TOP}_synth.json``

        Args:
            top_entity: Top-level VHDL entity name
            options: Extra Yosys CLI options
            primary_file: Optional selected VHDL source path (helps with duplicate entities)
        """
        os.makedirs(self.synth_dir, exist_ok=True)
        netlist_dir = self.config["project_structure"]["impl"]["netlist"][0]
        os.makedirs(netlist_dir, exist_ok=True)

        vhdl_files = self._get_vhdl_files(primary_file=primary_file)
        if not vhdl_files:
            self.yosys_logger.error("No VHDL files found for synthesis")
            return False

        # When a primary file is selected, prefer synthesizing that file alone if
        # other files declare the same entity name (avoids GHDL collisions).
        if primary_file and os.path.exists(primary_file):
            try:
                import re
                with open(primary_file, "r", encoding="utf-8", errors="replace") as f:
                    primary_content = f.read()
                primary_entities = {
                    m.lower()
                    for m in re.findall(r"entity\s+(\w+)\s+is", primary_content, re.IGNORECASE)
                }
                filtered = [primary_file]
                for path in vhdl_files:
                    if os.path.normpath(path) == os.path.normpath(primary_file):
                        continue
                    try:
                        with open(path, "r", encoding="utf-8", errors="replace") as f:
                            content = f.read()
                        entities = {
                            m.lower()
                            for m in re.findall(r"entity\s+(\w+)\s+is", content, re.IGNORECASE)
                        }
                        if primary_entities.intersection(entities):
                            self.yosys_logger.warning(
                                f"Excluding {os.path.basename(path)} due to duplicate entity name(s) "
                                f"with selected file {os.path.basename(primary_file)}"
                            )
                            continue
                    except Exception:
                        pass
                    filtered.append(path)
                vhdl_files = filtered
            except Exception as e:
                self.yosys_logger.debug(f"Could not filter duplicate entities: {e}")

        verilog_path = os.path.join(self.synth_dir, f"{top_entity}_synth.v")
        json_path = os.path.join(self.synth_dir, f"{top_entity}_synth.json")
        netlist_path = os.path.join(netlist_dir, f"{top_entity}.v")

        ghdl_cmd = self.get_tool_command("ghdl")
        if not ghdl_cmd:
            self.yosys_logger.error("GHDL tool command is not available")
            return False

        # Map YosysCommands VHDL std / ieee settings to GHDL CLI flags
        std_map = {
            "--std=08": "08",
            "--std=93": "93",
            "--std=93c": "93c",
            "08": "08",
            "93": "93",
            "93c": "93c",
        }
        std_flag = std_map.get(self.vhdl_std, "08")
        ieee_flag = None
        if self.ieee_lib and "synopsys" in str(self.ieee_lib):
            ieee_flag = "synopsys"
        elif self.ieee_lib and "mentor" in str(self.ieee_lib):
            ieee_flag = "mentor"

        # Stage 1: standalone GHDL VHDL -> ASCII Verilog
        ghdl_args = [
            ghdl_cmd,
            "synth",
            f"--std={std_flag}",
            "-fexplicit",
        ]
        if ieee_flag:
            ghdl_args.append("-fsynopsys")
        ghdl_args.append("--out=verilog")
        ghdl_args.extend(vhdl_files)
        ghdl_args.extend(["-e", top_entity])

        self.yosys_logger.info("=" * 60)
        self.yosys_logger.info("STAGE 1: GHDL VHDL -> Verilog (ASCII)")
        self.yosys_logger.info(f"GHDL command: {' '.join(ghdl_args)}")
        self.yosys_logger.info(f"Output: {verilog_path}")

        try:
            result = subprocess.run(
                ghdl_args,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=self.get_tool_run_env(),
            )
            # Verilog is on stdout — do not dump the whole netlist into the log
            if result.stderr:
                for line in result.stderr.splitlines():
                    if line.strip():
                        level = self.yosys_logger.warning
                        if "is not bound" in line.lower():
                            level = self.yosys_logger.info
                        level(f"GHDL: {line}")

            if result.returncode != 0:
                self.yosys_logger.error(f"GHDL synth failed with exit code {result.returncode}")
                if result.stdout:
                    self.yosys_logger.error(result.stdout[-2000:])
                return False

            verilog_text = result.stdout if result.stdout is not None else ""
            if not verilog_text.strip():
                self.yosys_logger.error("GHDL produced empty Verilog output")
                return False

            with open(verilog_path, "w", encoding="ascii", errors="replace", newline="\n") as f:
                f.write(verilog_text)
                if not verilog_text.endswith("\n"):
                    f.write("\n")

            self.yosys_logger.info(f"Wrote ASCII Verilog: {verilog_path} ({len(verilog_text)} chars)")
        except Exception as e:
            self.yosys_logger.error(f"GHDL synth invocation failed: {e}")
            return False

        # Stage 2: Yosys GateMate synthesis -> JSON
        # Cologne Chip recommended recipe always includes -luttree -nomx8.
        if not self.yosys_access:
            self.yosys_logger.error("Yosys tool command is not available")
            return False

        def _ys_quote(path: str) -> str:
            # Yosys -p scripts treat spaces specially; quote all absolute paths.
            return f'"{path}"' if path else path

        yosys_script = (
            f"read_verilog {_ys_quote(verilog_path)}; "
            f"synth_gatemate -top {top_entity} -luttree -nomx8 -json {_ys_quote(json_path)}; "
            f"write_verilog -noattr {_ys_quote(netlist_path)}"
        )
        yosys_cmd = [self.yosys_access, "-p", yosys_script]
        if options:
            yosys_cmd.extend(options)

        self.yosys_logger.info("=" * 60)
        self.yosys_logger.info("STAGE 2: Yosys synth_gatemate -> JSON (-luttree -nomx8)")
        self.yosys_logger.info(f"Yosys command: {' '.join(yosys_cmd)}")
        self.yosys_logger.info(f"JSON output: {json_path}")

        try:
            result = subprocess.run(
                yosys_cmd,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=self.get_tool_run_env(),
            )
            if result.stdout:
                self.yosys_logger.info("=== YOSYS GATEMATE SYNTHESIS OUTPUT ===")
                for line in result.stdout.splitlines():
                    if line.strip():
                        self.yosys_logger.info(f"YOSYS: {line}")
                self.yosys_logger.info("=== END YOSYS GATEMATE OUTPUT ===")
            if result.stderr:
                for line in result.stderr.splitlines():
                    if line.strip():
                        self.yosys_logger.warning(f"YOSYS STDERR: {line}")

            if result.returncode != 0:
                self.yosys_logger.error(f"Yosys GateMate synthesis failed with exit code {result.returncode}")
                return False

            if not os.path.exists(json_path):
                self.yosys_logger.error(f"Expected JSON netlist was not created: {json_path}")
                return False

            self.yosys_logger.info(f"Successfully synthesized {top_entity} for GateMate")
            self.yosys_logger.info(f"Generated Verilog: {verilog_path}")
            self.yosys_logger.info(f"Generated JSON: {json_path}")
            if os.path.exists(netlist_path):
                self.yosys_logger.info(f"Generated tech-mapped netlist: {netlist_path}")
            return True
        except Exception as e:
            self.yosys_logger.error(f"Yosys GateMate synthesis invocation failed: {e}")
            return False

    def build_gatemate_command_preview(
        self,
        top_entity: str,
        primary_file: Optional[str] = None,
    ) -> Dict[str, str]:
        """Build the exact GHDL + Yosys commands used by ``synthesize_gatemate``.

        Returns a dict with ``ghdl``, ``yosys``, and ``combined`` preview strings.
        Paths reflect the current project ``synth`` / ``impl/netlist`` directories.
        """
        vhdl_files = self._get_vhdl_files(primary_file=primary_file)
        verilog_path = os.path.join(self.synth_dir, f"{top_entity}_synth.v")
        json_path = os.path.join(self.synth_dir, f"{top_entity}_synth.json")
        netlist_dir = self.config["project_structure"]["impl"]["netlist"][0]
        netlist_path = os.path.join(netlist_dir, f"{top_entity}.v")

        ghdl_cmd = self.get_tool_command("ghdl") or "ghdl"
        std_map = {
            "--std=08": "08",
            "--std=93": "93",
            "--std=93c": "93c",
            "08": "08",
            "93": "93",
            "93c": "93c",
        }
        std_flag = std_map.get(self.vhdl_std, "08")
        ghdl_parts = [ghdl_cmd, "synth", f"--std={std_flag}", "-fexplicit"]
        if self.ieee_lib and "synopsys" in str(self.ieee_lib):
            ghdl_parts.append("-fsynopsys")
        ghdl_parts.append("--out=verilog")
        ghdl_parts.extend(vhdl_files or ["<vhdl_sources...>"])
        ghdl_parts.extend(["-e", top_entity])
        # stdout is redirected to the Verilog file by the wrapper
        ghdl_line = " ".join(ghdl_parts) + f"  >  {verilog_path}"

        yosys_bin = self.yosys_access or "yosys"

        def _ys_quote(path: str) -> str:
            return f'"{path}"' if path else path

        yosys_script = (
            f"read_verilog {_ys_quote(verilog_path)}; "
            f"synth_gatemate -top {top_entity} -luttree -nomx8 -json {_ys_quote(json_path)}; "
            f"write_verilog -noattr {_ys_quote(netlist_path)}"
        )
        yosys_line = f'{yosys_bin} -p "{yosys_script}"'

        combined = (
            "# GateMate synthesis (Cologne Chip recipe)\n"
            "# Stage 1 — standalone GHDL (not a Yosys plugin)\n"
            f"{ghdl_line}\n\n"
            "# Stage 2 — Yosys synth_gatemate with -luttree -nomx8\n"
            f"{yosys_line}\n"
        )
        return {"ghdl": ghdl_line, "yosys": yosys_line, "combined": combined}

    def get_available_synthesized_designs(self) -> List[str]:
        """Find designs with a GateMate JSON netlist for place and route.

        Only ``*_synth.json`` counts — a lone ``*_synth.v`` from the GHDL stage
        is not sufficient for nextpnr-himbaechel.
        """
        designs = []
        try:
            if os.path.exists(self.synth_dir):
                self.yosys_logger.info(f"Scanning for synthesized designs in {self.synth_dir}")
                
                for file in os.listdir(self.synth_dir):
                    if file.endswith('_synth.json'):
                        design_name = file.replace('_synth.json', '')
                        designs.append(design_name)
                        self.yosys_logger.info(f"Found synthesized design: {design_name} (JSON)")
                            
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