"""Handles GHDL 5.0.1 related commands and operations.

This module provides a manager class for GHDL 5.0.1 operations, including analyzing, 
elaborating, and running simulations for VHDL files.
"""
import os
import yaml
import logging
import subprocess
from .toolchain_manager import ToolChainManager
from typing import List, Optional, Dict, Union, Tuple
import re

class GHDLCommands(ToolChainManager):
    """Provides methods to work with GHDL 5.0.1 for VHDL simulation.
    
    This class encapsulates the functionality needed to interact with GHDL 5.0.1,
    providing methods for analyzing, elaborating, and running VHDL simulations.
    """

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

    def __init__(self, vhdl_std: str = "VHDL-2008", ieee_lib : str = "synopsys", work_lib_name: Optional[str] = "work"):
        """
        Initialize the GHDL command utility with default options.
        
        Args:
            vhdl_std: VHDL standard to use ("VHDL-1993", "VHDL-1993c", "VHDL-2008"). Default is VHDL-2008. VHDL-1993c is only partially supported by Yosys + GHDL
            ieee_lib: IEEE library implementation ('synopsys', 'mentor', 'none'). Default is "synopsis"
            work_lib_name: Name of the work library. Default is "work"
        """
        super().__init__()

        self.ghdl_logger = logging.getLogger("GHDLCommands")
        self.ghdl_logger.setLevel(logging.DEBUG)
        self.ghdl_logger.propagate = False  # Prevent propagation to root logger

        # Always ensure we have the correct log file handler for this project
        # Remove any existing handlers to prevent cross-project logging issues
        for handler in self.ghdl_logger.handlers[:]:
            self.ghdl_logger.removeHandler(handler)
            handler.close()
        
        # Get log file path for current project
        log_path = os.path.normpath(os.path.join(self.config["project_structure"]["logs"][0], "ghdl_commands.log"))
        file_handler = logging.FileHandler(log_path)
        formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
        file_handler.setFormatter(formatter)
        self.ghdl_logger.addHandler(file_handler)
        
        # Add ghdl_commands.log to project configuration
        self._add_ghdl_log()

        if vhdl_std not in self.VHDL_STANDARDS:
            self.ghdl_logger.warning(f"Unknown VHDL Standard \"{vhdl_std}\", defaulting to VHDL-2008")
            return
        if ieee_lib not in self.IEEE_LIBS:
            self.ghdl_logger.error(f"The specified ieee_lib {ieee_lib} is not supported by GHDLCommands.")
            return
        self.vhdl_std = self.VHDL_STANDARDS[vhdl_std]
        self.ieee_lib = self.IEEE_LIBS[ieee_lib]
        self.work_lib_name = work_lib_name
        # Get the build directory path
        if isinstance(self.config["project_structure"]["build"], list) and self.config["project_structure"]["build"]:
            self.work_dir = self.config["project_structure"]["build"][0]
        else:
            self.work_dir = self.config["project_structure"]["build"]
        # Get individual ghdl preference, fallback to global preference for backward compatibility
        tool_prefs = self.config.get("cologne_chip_gatemate_tool_preferences", {})
        if "ghdl" in tool_prefs:
            self.tool_access_mode = tool_prefs["ghdl"]
        else:
            self.tool_access_mode = self.config.get("cologne_chip_gatemate_toolchain_preference", "PATH")
        self.ghdl_access = self._get_ghdl_access()
        #ToolChainManager instantiation report
        self._report_instantiation()
    
    def _report_instantiation(self):
        """Log the current ToolChainManager configuration settings."""
        tcm_settings = f"""
        New ToolChainManager Instantiation Settings:
        VHDL_STANDARD:          {self.vhdl_std}
        IEEE_LIBRARY:           {self.ieee_lib}
        WORK_LIB_NAME:          {self.work_lib_name}
        WORK_DIRECTORY:         {self.work_dir}
        TOOL CHAIN PREFERENCE:  {self.tool_access_mode}
        TOOL CHAIN ACCESS:      {self.ghdl_access}
        """
        self.ghdl_logger.info(tcm_settings)

    def _get_ghdl_access(self) -> str:
        """
        Determine how to access the GHDL binary based on the configured toolchain mode.

        Returns:
            str: Path or command used to invoke GHDL.
        """
        #Get ghdl access mode
        ghdl_access = ""
        if self.tool_access_mode == "PATH": #GHDL should be accessed through PATH
            ghdl_access = "ghdl" #Accesses the ghdl binary through PATH
            self.ghdl_logger.info(f"GHDL Analysis is accessing GHDL binary through {ghdl_access}")
        elif self.tool_access_mode == "DIRECT": #GHDL should be accessed directly
            toolchain_path = self.config.get("cologne_chip_gatemate_toolchain_paths", {})
            ghdl_access = toolchain_path.get("ghdl", "")
            self.ghdl_logger.info(f"GHDL Analysis is accessing GHDL directly through {ghdl_access}")
        elif self.tool_access_mode == "UNDEFINED":
            self.ghdl_logger.error(f"GHDL access mode is undefined. There is a problem in toolchain manager.")
        else:
            # Fallback for any unexpected values - default to PATH access
            self.ghdl_logger.warning(f"Unexpected tool access mode '{self.tool_access_mode}', defaulting to PATH access")
            ghdl_access = "ghdl"

        return ghdl_access


    def _add_ghdl_log(self):
        """Add GHDL commands log file path to the project configuration.
        
        This function adds the 'ghdl_commands.log' file to the project configuration
        under the 'logs' section, following the structure:
        
        logs:
          ghdl_commands:
            ghdl_commands.log: /path/to/ghdl_commands.log
            
        If the 'ghdl_commands' entry already exists, the operation is skipped.
        
        Returns:
            bool: True if the log was added successfully or already exists, False if an error occurred.
        """
        #Check if key exists
        existing_keys = self.config["logs"].keys()
        if "ghdl_commands" in existing_keys: #ghdl_commands already added. Skip.
            self.ghdl_logger.warning("ghdl_commands.log has already been added to the project configuration file. Skipping.")
            return True
        self.ghdl_logger.info("Adding ghdl_commands.log to the project configuration file.")
        #get logs dir path
        log_path = self.config["project_structure"].get("logs")[0]
        #get ghdl log path
        ghdl_cmd_log_path = os.path.join(log_path, "ghdl_commands.log")
        self.ghdl_logger.info(f"Attempting to add ghdl_commands.log at {ghdl_cmd_log_path} to project configuration file.")
        #Add ghdl log to project config.
        self.config["logs"]["ghdl_commands"] = {"ghdl_commands.log": ghdl_cmd_log_path}
        try:
            with open(self.config_path, "w") as config_file:
                yaml.safe_dump(self.config, config_file)
                self.ghdl_logger.info(f"Project configuration file updating with ghdl_commands.log at {ghdl_cmd_log_path}")
                return True
        except Exception as e:
            self.ghdl_logger.error(f"An error occured adding ghdl_commands.log to project configuration file: {e}")
            return False




    def analyze(self, vhdl_file : str, options: Optional[List[str]] = None) -> bool:
        """
        Analyze a VHDL file with GHDL 5.0.1.
        
        This performs syntax and semantic analysis of the VHDL file and compiles it
        into the work library. The GHDL command syntax used is:

        Analyzed entites can be found in the work library file:
        {self.work_dir}\\work-obj08.cf
        
            ghdl analyze [OPTIONS] VHDL_FILE
        
        Where [OPTIONS] includes both standard and additional options.
        
        Args:
            vhdl_file: Path to the VHDL file to analyze
            options: Additional command-line options for GHDL analysis as a list of strings.
                
        Commonly used GHDL 5.0.1 analyze options include:
            `--work=LIBRARY`:      Set working library name (default: work)
            `--workdir=DIR`:       Set directory for working library
            `--std=STD`:           VHDL standard to use (93, 93c, 08)
            `--ieee=MODE`:         IEEE library mode (synopsys, mentor, none)
            `-P<DIR>`:             Add directory to library search path
            `--vital-checks`:      Enable VITAL checking
            `--no-vital-checks`:   Disable VITAL checking
            `-fexplicit`:          Give priority to explicitly declared operators
            `-frelaxed-rules`:     Relax some LRM rules
            `-fpsl`:               Parse PSL in comments
            `-C/--mb-comments`:    Allow multi-byte characters in comments
            `--syn-binding`:       Use synthesis default binding rule
            `-Wall`:               Enable all warnings
            `-v`:                  Verbose mode, show compilation stages
                
        Returns:
            bool: True if analysis successful, False otherwise
            
        Example:
            ```python
            ghdl = GHDLCommands()
            # Basic analysis with default options set in the constructor
            ghdl.analyze("counter.vhd")
            # Analysis with additional options
            ghdl.analyze("counter.vhd", ["-v", "-Wall"])
            # The command actually executed might look like:
            # ghdl analyze --std=08 --ieee=synopsys --workdir=/path/to/build --work=work -v -Wall counter.vhd
            ```
        """
        # Build GHDL analysis command
        ghdl_cmd = [self.ghdl_access, "analyze"]
        
        # Add standard VHDL version
        ghdl_cmd.append(self.vhdl_std)
        
        # Add IEEE library mode
        ghdl_cmd.append(self.ieee_lib)
        
        # Add work directory
        ghdl_cmd.append(f"--workdir={self.work_dir}")
        
        # Add work name if specified
        if self.work_lib_name:
            ghdl_cmd.append(f"--work={self.work_lib_name}")
            
        # Add any other specified options
        if options:
            ghdl_cmd.extend(options)
            
        # Add the VHDL file to analyze
        ghdl_cmd.append(vhdl_file)
        
        self.ghdl_logger.info(f"Analyzing VHDL file: {vhdl_file}")
        self.ghdl_logger.debug(f"GHDL Command: {' '.join(ghdl_cmd)}")

        try:
            result = subprocess.run(ghdl_cmd, check=True, capture_output=True, text=True)
            self.ghdl_logger.info(f"Successfully analyzed {vhdl_file}")
            if result.stdout:
                self.ghdl_logger.info(f"GHDL CMD: {result.stdout}")
            return True
        except subprocess.CalledProcessError as e:
            self.ghdl_logger.error(f"GHDL analysis failed for {vhdl_file}: {e}")
            self.ghdl_logger.error(f"STDERR: {e.stderr}")
            return False

    def elaborate(self, top_entity : str, options : Optional[List[str]] = None)-> bool:
        """
        Elaborate a VHDL design with GHDL 5.0.1.
        
        This performs elaboration of a previously analyzed design unit. Elaboration is the process
        of creating an executable design hierarchy by binding component instances to entities
        according to VHDL rules. The GHDL command syntax used is:
        
            ghdl elaborate [OPTIONS] TOP_ENTITY
        
        Where TOP_ENTITY is the name of the top-level entity to elaborate, and [OPTIONS] includes
        both standard and additional options. Top entity is often a testbench, or just the highest level design entity.
        
        Args:
            top_entity: Name of the top entity (primary unit) to elaborate
            options: Additional command-line options for GHDL elaboration as a list of strings
                
        Commonly used GHDL 5.0.1 elaborate options include:
            `--work=LIBRARY`:      Set working library name (default: work)
            `--workdir=DIR`:       Set directory for working library
            `--std=STD`:           VHDL standard to use (93, 93c, 08)
            `--ieee=MODE`:         IEEE library mode (synopsys, mentor, none)
            `-P<DIR>`:             Add directory to library search path
            `-v`:                  Verbose mode
            `-l`:                  List entities/architectures after elaboration
            `--syn-binding`:       Use synthesis default binding rule
            `--no-vital-checks`:   Disable VITAL checking
            `--psl-report=FILE`:   Write PSL report to FILE
                
        Returns:
            bool: True if elaboration successful, False otherwise
            
        Example:
            ```python
            ghdl = GHDLCommands()
            # Analyze the files first
            ghdl.analyze("counter.vhd")
            # Then elaborate the top entity
            ghdl.elaborate("counter")
            # With additional options
            ghdl.elaborate("counter", ["-v"])
            ```
        """
        #Elaborate cmd
        ghdl_elab_cmd = [self.ghdl_access, "elaborate"]

        #Add VHDL standard
        ghdl_elab_cmd.append(self.vhdl_std)
        
        #Add IEEE library mode
        ghdl_elab_cmd.append(self.ieee_lib)

        #Add work library
        ghdl_elab_cmd.append(f"--work={self.work_lib_name}")

        #add work directory
        ghdl_elab_cmd.append(f"--workdir={self.work_dir}")

        #add any other options
        if options:
            ghdl_elab_cmd.extend(options)
        
        #Add top entity name
        ghdl_elab_cmd.append(top_entity)

        #Run elaborate
        self.ghdl_logger.info(f"Running GHDL elaborate on {top_entity}")
        self.ghdl_logger.debug(f"GHDL Command: {' '.join(ghdl_elab_cmd)}")
        try:
            result = subprocess.run(ghdl_elab_cmd, check=True, capture_output=True, text=True)
            self.ghdl_logger.info(f"Successfully elaborated {top_entity}")
            if result.stdout:
                self.ghdl_logger.info(f"GHDL CMD: {result.stdout}")
            return True
        except subprocess.CalledProcessError as e:
            self.ghdl_logger.error(f"GHDL elaborate failed for {top_entity}: {e}")
            self.ghdl_logger.error(f"STDERR: {e.stderr}")
            return False

    def behavioral_simulation(self, top_entity: str, options: Optional[List[str]] = None, 
                 run_options: Optional[List[str]] = None) -> bool:
        """
        Run behavioral simulation for a VHDL design with GHDL 5.0.1.
        
        This function runs the simulation after the design has been analyzed and elaborated.
        It uses the original VHDL source code without any synthesis or implementation effects.
        The simulation output is placed in the behavioral directory.
        
        The GHDL command syntax used is:
        
            ghdl run [OPTIONS] TOP_ENTITY [RUN_OPTIONS]
        
        Where TOP_ENTITY is the name of the top-level entity to simulate, [OPTIONS] are
        command options similar to those used during elaboration, and [RUN_OPTIONS] are 
        options specific to the simulation run.
        
        Args:
            top_entity: Name of the top entity (primary unit) to simulate
            options: Command-line options for GHDL run as a list of strings
            run_options: Runtime options for the simulation as a list of strings
                
        Common GHDL 5.0.1 run command options include:
            `--work=LIBRARY`:      Set working library name (default: work)
            `--workdir=DIR`:       Set directory for working library
            `--std=STD`:           VHDL standard to use (93, 93c, 08)
            `--ieee=MODE`:         IEEE library mode (synopsys, mentor, none)
            
        Common GHDL 5.0.1 runtime options include:
            `--wave=FILE`:         Write waveform data to FILE (ghw format by default)
            `--vcd=FILE`:          Write waveform data to FILE in VCD format
            `--stop-time=TIME`:    Stop the simulation after TIME (e.g., 100ns)
            `--assert-level=LEVEL`: Set the assertion level (default, note, warning, error, failure)
            `--ieee-asserts=POLICY`: Control IEEE assertions (ignore, disable, enable)
            
        Returns:
            bool: True if simulation successful, False otherwise
            
        Example:
            ```python
            ghdl = GHDLCommands()
            # Analyze the files
            ghdl.analyze("counter_tb.vhd")
            # Elaborate the testbench
            ghdl.elaborate("counter_tb")
            # Run the simulation with a VCD waveform file and a 100ns runtime
            ghdl.behavioral_simulation("counter_tb", run_options=["--vcd=counter.vcd", "--stop-time=100ns"])
            ```
        """
        # Get the behavioral directory path
        behavioral_dir = self.config["project_structure"]["sim"]["behavioral"][0]
        
        # Build GHDL run command
        ghdl_run_cmd = [self.ghdl_access, "run"]
        
        # Add standard VHDL version
        ghdl_run_cmd.append(self.vhdl_std)
        
        # Add IEEE library mode
        ghdl_run_cmd.append(self.ieee_lib)
        
        # Add work directory
        ghdl_run_cmd.append(f"--workdir={self.work_dir}")
        
        # Add work name if specified
        if self.work_lib_name:
            ghdl_run_cmd.append(f"--work={self.work_lib_name}")
            
        # Add any command options
        if options:
            ghdl_run_cmd.extend(options)
            
        # Add the top entity to simulate
        ghdl_run_cmd.append(top_entity)
        
        # Parse run_options to find and modify wave/vcd paths
        modified_run_options = []
        has_wave_option = False
        has_vcd_option = False
        
        if run_options:
            for opt in run_options:
                if opt.startswith("--wave"):
                    # Replace with full path version
                    has_wave_option = True
                    modified_run_options.append(f"--wave={os.path.join(behavioral_dir, f'{top_entity}.ghw')}")
                elif opt.startswith("--vcd"):
                    # Replace with full path version
                    has_vcd_option = True
                    modified_run_options.append(f"--vcd={os.path.join(behavioral_dir, f'{top_entity}.vcd')}")
                else:
                    # Keep other options as-is
                    modified_run_options.append(opt)
            
            # If no wave format was specified, add default VCD
            if not (has_wave_option or has_vcd_option):
                modified_run_options.append(f"--vcd={os.path.join(behavioral_dir, f'{top_entity}.vcd')}")
        else:
            # No options were provided, use default VCD output
            modified_run_options = [f"--vcd={os.path.join(behavioral_dir, f'{top_entity}.vcd')}"]
        
        # Add the modified runtime options
        ghdl_run_cmd.extend(modified_run_options)
        
        self.ghdl_logger.info(f"Running GHDL behavioral simulation for {top_entity}")
        self.ghdl_logger.debug(f"GHDL Command: {' '.join(ghdl_run_cmd)}")
        
        try:
            result = subprocess.run(ghdl_run_cmd, check=True, capture_output=True, text=True)
            self.ghdl_logger.info(f"Successfully simulated {top_entity}")
            if result.stdout:
                self.ghdl_logger.info(f"Simulation output: {result.stdout}")
            return True
        except subprocess.CalledProcessError as e:
            self.ghdl_logger.error(f"GHDL simulation failed for {top_entity}: {e}")
            self.ghdl_logger.error(f"STDERR: {e.stderr}")
            return False

    # Alias for backward compatibility
    simulate = behavioral_simulation

    def post_synthesis_simulation(self, entity_name: str, testbench_name: str = None,
                                 analyze_options: Optional[List[str]] = None,
                                 elaborate_options: Optional[List[str]] = None,
                                 run_options: Optional[List[str]] = None,
                                 simulation_time: int = None,
                                 time_prefix: str = None) -> bool:
        """
        Post-synthesis simulation using GHDL synthesis to VHDL followed by VHDL simulation.
        
        CORRECT VHDL-TO-VHDL WORKFLOW:
        1. Analyze original VHDL source
        2. Use GHDL synthesis to generate synthesized VHDL netlist
        3. Analyze synthesized VHDL 
        4. Analyze VHDL testbench (using component instantiation)
        5. Elaborate and run simulation with synthesized entity
        
        This provides true post-synthesis verification by simulating the actual
        synthesized logic while allowing users to write VHDL testbenches.
        
        Args:
            entity_name: Name of the VHDL entity to synthesize
            testbench_name: Name of the testbench (if None, will be auto-detected)
            analyze_options: Additional options for analysis (unused in this implementation)
            elaborate_options: Additional options for elaboration (unused in this implementation) 
            run_options: Additional options for simulation run (unused in this implementation)
            simulation_time: Simulation time duration (if None, uses project config or defaults)
            time_prefix: Time unit (if None, uses project config or defaults)
            
        Returns:
            bool: True if post-synthesis simulation successful, False otherwise
        """
        
        self.ghdl_logger.info(f"Starting VHDL post-synthesis simulation for entity: {entity_name}")
        
        try:
            # Helper function to build standard GHDL options
            def get_standard_options():
                return [
                    self.vhdl_std,
                    self.ieee_lib,
                    f"--workdir={self.work_dir}",
                    f"--work={self.work_lib_name}"
                ]
            
            # 1. Find the VHDL source file for the entity
            vhdl_file = self._find_entity_file(entity_name)
            if not vhdl_file:
                self.ghdl_logger.error(f"Could not find VHDL file for entity: {entity_name}")
                return False
            
            # 2. Setup output directories using project configuration paths
            synth_dir = self.config["project_structure"]["synth"][0]
            post_synth_sim_dir = self.config["project_structure"]["sim"]["post-synthesis"][0]
            os.makedirs(synth_dir, exist_ok=True)
            os.makedirs(post_synth_sim_dir, exist_ok=True)
            
            # 3. Step 1: Analyze original VHDL source
            self.ghdl_logger.info("Step 1: Analyzing original VHDL source...")
            cmd = [self.ghdl_access, "-a"] + get_standard_options() + [vhdl_file]
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.returncode != 0:
                self.ghdl_logger.error(f"Analysis of original VHDL failed: {result.stderr}")
                return False
            
            self.ghdl_logger.info("Original VHDL analysis successful")
            
            # 4. Step 2: Synthesize to VHDL netlist
            self.ghdl_logger.info("Step 2: Synthesizing to VHDL netlist...")
            synth_file = os.path.join(synth_dir, f"{entity_name}_synth_vhdl.vhd")
            cmd = [self.ghdl_access, "synth", "--out=vhdl"] + get_standard_options() + [entity_name]
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.returncode != 0:
                self.ghdl_logger.error(f"VHDL synthesis failed: {result.stderr}")
                return False
            
            # Save synthesized VHDL to file with proper encoding
            with open(synth_file, "w", encoding="utf-8") as f:
                f.write(result.stdout)
            
            self.ghdl_logger.info(f"VHDL synthesis successful - saved to: {synth_file}")
            
            # 5. Step 3: Analyze synthesized VHDL
            self.ghdl_logger.info("Step 3: Analyzing synthesized VHDL...")
            cmd = [self.ghdl_access, "-a"] + get_standard_options() + [synth_file]
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.returncode != 0:
                self.ghdl_logger.error(f"Analysis of synthesized VHDL failed: {result.stderr}")
                return False
            
            self.ghdl_logger.info("Synthesized VHDL analysis successful")
            
            # 6. Step 4: Find and analyze VHDL testbench
            if testbench_name is None:
                # Auto-detect testbench
                testbench_file = self._find_testbench_file(entity_name)
                if not testbench_file:
                    self.ghdl_logger.error(f"Could not find testbench file for entity: {entity_name}")
                    return False
                
                # Extract testbench entity name from file
                testbench_name = self._extract_testbench_entity_name(testbench_file)
                if not testbench_name:
                    self.ghdl_logger.error(f"Could not extract testbench entity name from: {testbench_file}")
                    return False
            else:
                # Find testbench file by name
                testbench_file = self._find_testbench_file_by_name(testbench_name)
                if not testbench_file:
                    self.ghdl_logger.error(f"Could not find testbench file for: {testbench_name}")
                    return False
            
            self.ghdl_logger.info(f"Step 4: Analyzing VHDL testbench: {testbench_file}")
            cmd = [self.ghdl_access, "-a"] + get_standard_options() + [testbench_file]
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.returncode != 0:
                self.ghdl_logger.error(f"Analysis of testbench failed: {result.stderr}")
                return False
            
            self.ghdl_logger.info(f"Testbench analysis successful - entity: {testbench_name}")
            
            # 7. Step 5: Elaborate testbench
            self.ghdl_logger.info("Step 5: Elaborating testbench with synthesized entity...")
            cmd = [self.ghdl_access, "-e"] + get_standard_options() + [testbench_name]
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.returncode != 0:
                self.ghdl_logger.error(f"Elaboration failed: {result.stderr}")
                return False
            
            self.ghdl_logger.info("Elaboration successful")
            
            # 8. Step 6: Run post-synthesis simulation
            self.ghdl_logger.info("Step 6: Running post-synthesis simulation with VHDL testbench...")
            vcd_file = os.path.join(post_synth_sim_dir, f"{entity_name}_vhdl_post_synth.vcd")
            
            # Get simulation time settings from config (same as behavioral simulation)
            if simulation_time is not None and time_prefix is not None:
                # Use passed parameters
                self.ghdl_logger.info(f"Using provided simulation settings: {simulation_time}{time_prefix}")
            else:
                # Fall back to config or defaults
                simulation_time = 1000  # Default
                time_prefix = "ns"      # Default
                
                try:
                    # Try to get simulation settings from project config
                    if "simulation_settings" in self.config:
                        settings = self.config["simulation_settings"]
                        simulation_time = settings.get("simulation_time", 1000)
                        time_prefix = settings.get("time_prefix", "ns")
                        self.ghdl_logger.info(f"Using simulation settings from config: {simulation_time}{time_prefix}")
                    else:
                        self.ghdl_logger.info(f"Using default simulation settings: {simulation_time}{time_prefix}")
                except Exception as e:
                    self.ghdl_logger.warning(f"Could not read simulation settings, using defaults: {e}")
            
            # Build simulation command with time limit
            cmd = [self.ghdl_access, "-r"] + get_standard_options() + [
                testbench_name, 
                f"--vcd={vcd_file}",
                f"--stop-time={simulation_time}{time_prefix}"
            ]
            
            self.ghdl_logger.info(f"Running simulation with time limit: {simulation_time}{time_prefix}")
            self.ghdl_logger.debug(f"GHDL Command: {' '.join(cmd)}")
            self.ghdl_logger.debug(f"VCD file path: {vcd_file}")
            
            # Change to project directory to ensure correct working directory
            original_cwd = os.getcwd()
            project_path = self.config.get("project_path", original_cwd)
            
            try:
                os.chdir(project_path)
                self.ghdl_logger.debug(f"Changed working directory to: {project_path}")
                
                result = subprocess.run(cmd, capture_output=True, text=True)
                
                # Verify VCD file was created
                if result.returncode == 0:
                    if os.path.exists(vcd_file):
                        file_size = os.path.getsize(vcd_file)
                        self.ghdl_logger.info(f"VCD file created successfully: {vcd_file} ({file_size} bytes)")
                    else:
                        self.ghdl_logger.warning(f"Simulation succeeded but VCD file not found at: {vcd_file}")
                        # Check if VCD file was created in working directory
                        local_vcd = f"{entity_name}_vhdl_post_synth.vcd"
                        if os.path.exists(local_vcd):
                            self.ghdl_logger.info(f"Found VCD file in working directory: {local_vcd}")
                            # Move it to the correct location
                            import shutil
                            shutil.move(local_vcd, vcd_file)
                            self.ghdl_logger.info(f"Moved VCD file to correct location: {vcd_file}")
                
            finally:
                os.chdir(original_cwd)
                self.ghdl_logger.debug(f"Restored working directory to: {original_cwd}")
            
            if result.returncode != 0:
                self.ghdl_logger.error(f"Post-synthesis simulation failed: {result.stderr}")
                return False
            
            self.ghdl_logger.info("Post-synthesis simulation successful!")
            self.ghdl_logger.info(f"VCD file: {vcd_file}")
            
            # Log simulation output
            if result.stdout.strip():
                self.ghdl_logger.info("Simulation output:")
                for line in result.stdout.strip().split('\n'):
                    self.ghdl_logger.info(f"    {line}")
            
            self.ghdl_logger.info("VHDL POST-SYNTHESIS SIMULATION COMPLETE!")
            self.ghdl_logger.info("You can now view waveforms with GTKWave")
            self.ghdl_logger.info("This tested the SYNTHESIZED logic with your VHDL testbench")
            
            return True
                
        except Exception as e:
            self.ghdl_logger.error(f"Error in VHDL post-synthesis simulation: {e}")
            return False

    def _create_verilog_testbench(self, entity_name: str, output_dir: str) -> Optional[str]:
        """Create a Verilog testbench for the synthesized entity."""
        
        try:
            # Find the original VHDL testbench to extract interface
            original_tb = self._find_testbench_file(entity_name)
            if not original_tb:
                self.ghdl_logger.warning("No VHDL testbench found, creating basic Verilog testbench")
                interface = self._get_basic_interface(entity_name)
            else:
                interface = self._extract_entity_interface(original_tb, entity_name)
            
            # Generate Verilog testbench
            verilog_tb_path = os.path.join(output_dir, f"{entity_name}_post_synth_tb.v")
            
            with open(verilog_tb_path, 'w') as f:
                f.write(self._generate_verilog_testbench_content(entity_name, interface))
            
            self.ghdl_logger.info(f"✅ Created Verilog testbench: {verilog_tb_path}")
            return verilog_tb_path
            
        except Exception as e:
            self.ghdl_logger.error(f"Error creating Verilog testbench: {e}")
            return None

    def _generate_verilog_testbench_content(self, entity_name: str, interface: Dict) -> str:
        """Generate Verilog testbench content."""
        
        lines = [
            "`timescale 1ns/1ps",
            "",
            f"module {entity_name}_post_synth_tb;",
            "",
            "    // Testbench signals"
        ]
        
        # Declare signals based on interface
        for port in interface.get('ports', []):
            port_type = "reg" if port['direction'] == 'input' else "wire"
            if port.get('width', 1) > 1:
                lines.append(f"    {port_type} [{port['width']-1}:0] {port['name']};")
            else:
                lines.append(f"    {port_type} {port['name']};")
        
        lines.extend([
            "",
            f"    // Instantiate the synthesized {entity_name}",
            f"    {entity_name} uut ("
        ])
        
        # Port connections
        port_connections = []
        for port in interface.get('ports', []):
            port_connections.append(f"        .{port['name']}({port['name']})")
        
        lines.append(",\n".join(port_connections))
        lines.extend([
            "    );",
            ""
        ])
        
        # Add clock generation if there's a clock
        clock_ports = [p for p in interface.get('ports', []) if 'clk' in p['name'].lower()]
        if clock_ports:
            clock_name = clock_ports[0]['name']
            lines.extend([
                "    // Clock generation",
                f"    always #10 {clock_name} = ~{clock_name};",
                ""
            ])
        
        # Add VCD dump and basic stimulus
        lines.extend([
            "    // VCD dump for waveform viewing",
            "    initial begin",
            f"        $dumpfile(\"{entity_name}_post_synth_tb.vcd\");",
            f"        $dumpvars(0, {entity_name}_post_synth_tb);",
            "    end",
            "",
            "    // Test stimulus",
            "    initial begin",
            f"        $display(\"=== Post-Synthesis Simulation of {entity_name} ===\");",
            ""
        ])
        
        # Initialize signals
        for port in interface.get('ports', []):
            if port['direction'] == 'input':
                init_value = "1" if 'rst' in port['name'].lower() else "0"
                lines.append(f"        {port['name']} = {init_value};")
        
        lines.extend([
            "",
            "        // Release reset if present",
            "        #100;"
        ])
        
        # Release reset
        reset_ports = [p for p in interface.get('ports', []) if 'rst' in p['name'].lower() or 'reset' in p['name'].lower()]
        if reset_ports:
            reset_name = reset_ports[0]['name']
            lines.append(f"        {reset_name} = 0;")
        
        lines.extend([
            "",
            "        // Run simulation for multiple cycles",
            "        #2000;",
            "",
            f"        $display(\"=== Post-Synthesis Simulation of {entity_name} Complete ===\");",
            "        $finish;",
            "    end",
            "",
            "endmodule"
        ])
        
        return "\n".join(lines)

    def _get_basic_interface(self, entity_name: str) -> Dict:
        """Get basic interface for common entities."""
        
        # Default interface for state machine
        if 'SM' in entity_name or 'state' in entity_name.lower():
            return {
                'ports': [
                    {'name': 'clk', 'direction': 'input', 'width': 1},
                    {'name': 'rst', 'direction': 'input', 'width': 1},
                    {'name': 'red', 'direction': 'output', 'width': 1},
                    {'name': 'yellow', 'direction': 'output', 'width': 1},
                    {'name': 'green', 'direction': 'output', 'width': 1}
                ]
            }
        
        # Default minimal interface
        return {
            'ports': [
                {'name': 'clk', 'direction': 'input', 'width': 1},
                {'name': 'rst', 'direction': 'input', 'width': 1}
            ]
        }

    def _run_verilog_simulation(self, netlist_path: str, testbench_path: str, sim_dir: str) -> bool:
        """Run Verilog simulation using available simulator."""
        
        try:
            sim_name = os.path.basename(testbench_path).replace('.v', '_sim')
            
            # Try different Verilog simulators
            simulators = [
                {'name': 'iverilog', 'compile': ['iverilog', '-o', sim_name, netlist_path, testbench_path], 'run': [f'./{sim_name}']},
                {'name': 'ghdl', 'compile': ['ghdl', 'import', '--std=08', netlist_path, testbench_path], 'run': ['ghdl', '-m', '--std=08', sim_name]},
            ]
            
            cwd = os.getcwd()
            os.chdir(sim_dir)
            
            try:
                for sim in simulators:
                    try:
                        self.ghdl_logger.info(f"Trying {sim['name']} simulator...")
                        
                        # Compile
                        self.ghdl_logger.debug(f"Compile command: {' '.join(sim['compile'])}")
                        result = subprocess.run(sim['compile'], capture_output=True, text=True)
                        
                        if result.returncode == 0:
                            self.ghdl_logger.info(f"✅ Compiled successfully with {sim['name']}")
                            
                            # Run simulation
                            self.ghdl_logger.debug(f"Run command: {' '.join(sim['run'])}")
                            result = subprocess.run(sim['run'], capture_output=True, text=True)
                            
                            if result.returncode == 0:
                                self.ghdl_logger.info(f"✅ Simulation completed with {sim['name']}")
                                if result.stdout:
                                    self.ghdl_logger.info(f"Simulation output:\n{result.stdout}")
                                return True
                            else:
                                self.ghdl_logger.warning(f"Simulation failed with {sim['name']}: {result.stderr}")
                        else:
                            self.ghdl_logger.warning(f"Compilation failed with {sim['name']}: {result.stderr}")
                            
                    except FileNotFoundError:
                        self.ghdl_logger.debug(f"{sim['name']} not available")
                        continue
                    except Exception as e:
                        self.ghdl_logger.warning(f"Error with {sim['name']}: {e}")
                        continue
                
                self.ghdl_logger.error("No suitable Verilog simulator found")
                return False
                
            finally:
                os.chdir(cwd)
                
        except Exception as e:
            self.ghdl_logger.error(f"Error running Verilog simulation: {e}")
            return False

    def _find_entity_file(self, entity_name: str) -> Optional[str]:
        """Find the VHDL file containing the specified entity."""
        
        try:
            # Get source files from config
            src_files = self.config["hdl_project_hierarchy"].get("src", {})
            project_root = self.config.get("project_path", os.getcwd())
            
            for file_name, file_path in src_files.items():
                # Handle relative paths
                if not os.path.isabs(file_path):
                    abs_file_path = os.path.join(project_root, file_path)
                else:
                    abs_file_path = file_path
                
                # Check if this file contains our entity
                if os.path.exists(abs_file_path):
                    entity_found = self.parse_entity_name_from_vhdl(abs_file_path)
                    if entity_found and entity_found.lower() == entity_name.lower():
                        return abs_file_path
            
            return None
            
        except Exception as e:
            self.ghdl_logger.error(f"Error finding entity file: {e}")
            return None

    def _find_testbench_file(self, entity_name: str) -> Optional[str]:
        """Find the VHDL testbench file for the specified entity."""
        
        try:
            # Get testbench files from config
            tb_files = self.config["hdl_project_hierarchy"].get("testbench", {})
            project_root = self.config.get("project_path", os.getcwd())
            
            for file_name, file_path in tb_files.items():
                # Handle relative paths
                if not os.path.isabs(file_path):
                    abs_file_path = os.path.join(project_root, file_path)
                else:
                    abs_file_path = file_path
                
                # Check if this file exists and might be related to our entity
                if os.path.exists(abs_file_path):
                    # Look for entity name in filename or file content
                    if entity_name.lower() in file_name.lower():
                        return abs_file_path
            
            return None
            
        except Exception as e:
            self.ghdl_logger.error(f"Error finding testbench file: {e}")
            return None

    def _extract_entity_interface(self, testbench_file: str, entity_name: str) -> Dict:
        """Extract entity interface from VHDL testbench file."""
        
        try:
            with open(testbench_file, 'r') as f:
                content = f.read()
            
            # Look for component declaration or port map
            # This is a simplified parser - for production use, consider using a proper VHDL parser
            interface = {'ports': []}
            
            # Try to find component declaration
            import re
            component_pattern = rf'component\s+{entity_name}.*?end\s+component'
            component_match = re.search(component_pattern, content, re.DOTALL | re.IGNORECASE)
            
            if component_match:
                component_text = component_match.group(0)
                # Extract port declarations
                port_pattern = r'(\w+)\s*:\s*(in|out|inout)\s+(\w+(?:\([^)]+\))?)'
                ports = re.findall(port_pattern, component_text, re.IGNORECASE)
                
                for port_name, direction, port_type in ports:
                    width = 1
                    # Check for vector types
                    if 'vector' in port_type.lower():
                        # Try to extract width from (x downto y) or (x to y)
                        width_match = re.search(r'\((\d+)\s+(?:downto|to)\s+(\d+)\)', port_type)
                        if width_match:
                            high = int(width_match.group(1))
                            low = int(width_match.group(2))
                            width = abs(high - low) + 1
                    
                    interface['ports'].append({
                        'name': port_name,
                        'direction': direction.lower(),
                        'width': width
                    })
            
            # If no component found, use basic interface
            if not interface['ports']:
                interface = self._get_basic_interface(entity_name)
            
            return interface
            
        except Exception as e:
            self.ghdl_logger.error(f"Error extracting entity interface: {e}")
            return self._get_basic_interface(entity_name)

    def post_implementation_simulation(self) -> bool: #TODO: Implement this
        """
        Run post-implementation simulation for a VHDL design with GHDL 5.0.1.
        
        This function runs the simulation after the design has been implemented.
        """

    def parse_entity_name_from_vhdl(self, vhdl_file_path):
        """Parse and return the first entity name found in a VHDL file.
        
        This function reads a VHDL file and extracts the entity name
        by looking for the 'entity' keyword followed by an identifier.
        
        Args:
            vhdl_file_path (str): Path to the VHDL file to parse
            
        Returns:
            str or None: The entity name if found, None otherwise
        """
        self.ghdl_logger.info(f"Parsing entity name from VHDL file: {vhdl_file_path}")
        
        if not os.path.exists(vhdl_file_path):
            self.ghdl_logger.error(f"VHDL file not found: {vhdl_file_path}")
            return None
        
        try:
            self.ghdl_logger.debug(f"Opening VHDL file for parsing: {vhdl_file_path}")
            with open(vhdl_file_path, 'r', encoding='utf-8') as f:
                line_number = 0
                for line in f:
                    line_number += 1
                    line = line.strip()
                    if line.lower().startswith('entity '):
                        parts = line.split()
                        if len(parts) >= 2:
                            entity_name = parts[1]
                            self.ghdl_logger.info(f"Found entity '{entity_name}' at line {line_number}")
                            return entity_name
            
            self.ghdl_logger.warning(f"No entity declaration found in file: {vhdl_file_path}")
            return None
        except Exception as e:
            self.ghdl_logger.error(f"Error parsing entity name from {vhdl_file_path}: {e}")
            return None
   

    def check_work_library(self):
        """Check the GHDL work library file for entity names and their case.
        
        This function reads and parses the GHDL work library file (work-obj08.cf)
        to extract information about analyzed entities, their names and case.
        Useful for diagnostics.
        
        Returns:
            list or None: List of entity names if found, None if file doesn't exist
        """
        build_dir = self.config["project_structure"]["build"][0]
        work_lib_file = os.path.join(build_dir, "work-obj08.cf")
        
        self.ghdl_logger.info(f"Checking GHDL work library at: {work_lib_file}")
        
        if not os.path.exists(work_lib_file):
            self.ghdl_logger.warning(f"GHDL work library file not found: {work_lib_file}")
            print(f"GHDL work library file not found: {work_lib_file}")
            return None
        
        self.ghdl_logger.info(f"Found work library file: {work_lib_file}")
        print(f"Found work library file: {work_lib_file}")
        
        try:
            with open(work_lib_file, 'r', encoding='utf-8') as f:
                content = f.read()
                self.ghdl_logger.debug("Successfully read work library file content")
                print("\nGHDL work library content:")
                print(content)
                
                # Look for entity definitions in the file
                import re
                entity_matches = re.findall(r'entity\s+(\S+)\s+at', content)
                if entity_matches:
                    self.ghdl_logger.info(f"Found {len(entity_matches)} entities in work library")
                    print("\nEntities found in work library:")
                    for entity_name in entity_matches:
                        self.ghdl_logger.info(f"Entity in work library: {entity_name}")
                        print(f"  {entity_name}")
                    return entity_matches
                else:
                    self.ghdl_logger.warning("No entities found in work library file")
                    print("No entities found in work library file")
                    return []
        except Exception as e:
            self.ghdl_logger.error(f"Error reading work library file: {e}")
            print(f"Error reading work library file: {e}")
            return None
    

    def check_hierarchy(self) -> bool:
        """Check if the HDL hierarchy exists in the project configuration.
        
        Returns:
            bool: True if the hierarchy exists, False otherwise
        """
        if "hdl_project_hierarchy" not in self.config:
            self.ghdl_logger.error("The projects HDL hierarchy has not been set. Check set_hierarchy settings. Exit")
            print("The projects HDL hierarchy has not been set. Check set_hierarchy settings. Exit")
            return False
        return True

    def analyze_elaborate_simulate(self, vhdl_files: List[str], top_entity: str, 
                               analyze_options: Optional[List[str]] = None,
                               elaborate_options: Optional[List[str]] = None,
                               run_options: Optional[List[str]] = None) -> bool:
        """
        Perform the complete VHDL workflow: analyze, elaborate, and simulate in one step.
        
        This convenience function runs all three stages of the GHDL workflow in sequence.
        It will stop and return False if any stage fails.
        
        Args:
            vhdl_files: List of VHDL file paths to analyze
            top_entity: Name of the top entity to elaborate and simulate
            analyze_options: Options for the analyze stage
            elaborate_options: Options for the elaborate stage
            run_options: Runtime options for the simulation
            
        Returns:
            bool: True if all stages completed successfully, False if any stage failed
            
        Example:
            ```python
            ghdl = GHDLCommands()
            # Run the complete workflow
            ghdl.analyze_elaborate_simulate(
                ["counter.vhd", "counter_tb.vhd"],
                "counter_tb",
                run_options=["--vcd=counter.vcd", "--stop-time=100ns"]
            )
            ```
        """
        self.ghdl_logger.info(f"Starting complete GHDL workflow for {top_entity}")
        
        # Step 1: Analyze all VHDL files
        for vhdl_file in vhdl_files:
            self.ghdl_logger.info(f"Analyzing file: {vhdl_file}")
            if not self.analyze(vhdl_file, analyze_options):
                self.ghdl_logger.error(f"Analysis failed for {vhdl_file}, aborting workflow")
                return False
        
        # Step 2: Elaborate the design
        self.ghdl_logger.info(f"Elaborating design with top entity: {top_entity}")
        if not self.elaborate(top_entity, elaborate_options):
            self.ghdl_logger.error(f"Elaboration failed for {top_entity}, aborting workflow")
            return False
        
        # Step 3: Run the simulation
        self.ghdl_logger.info(f"Running simulation with top entity: {top_entity}")
        if not self.behavioral_simulation(top_entity, elaborate_options, run_options):
            self.ghdl_logger.error(f"Simulation failed for {top_entity}")
            return False
        
        self.ghdl_logger.info(f"Complete GHDL workflow completed successfully for {top_entity}")
        return True

    def _extract_testbench_entity_name(self, testbench_file: str) -> Optional[str]:
        """Extract testbench entity name from VHDL file."""
        try:
            with open(testbench_file, 'r', encoding='utf-8') as f:
                content = f.read().lower()
                
            # Look for entity declaration pattern
            entity_match = re.search(r'entity\s+(\w+)\s+is', content)
            if entity_match:
                entity_name = entity_match.group(1)
                self.ghdl_logger.debug(f"Found testbench entity: {entity_name}")
                return entity_name
            else:
                self.ghdl_logger.warning(f"Could not find entity declaration in: {testbench_file}")
                return None
                
        except Exception as e:
            self.ghdl_logger.error(f"Error extracting testbench entity name: {e}")
            return None

    def _find_testbench_file_by_name(self, testbench_name: str) -> Optional[str]:
        """Find testbench file by entity name."""
        try:
            # Search in common locations
            search_dirs = ["src", "testbench", "tb", "."]
            
            for search_dir in search_dirs:
                if not os.path.exists(search_dir):
                    continue
                    
                for file in os.listdir(search_dir):
                    if file.endswith('.vhd') or file.endswith('.vhdl'):
                        file_path = os.path.join(search_dir, file)
                        
                        # Check if this file contains the testbench entity
                        try:
                            with open(file_path, 'r', encoding='utf-8') as f:
                                content = f.read().lower()
                                
                            if f'entity {testbench_name.lower()}' in content:
                                self.ghdl_logger.debug(f"Found testbench file: {file_path}")
                                return file_path
                                
                        except Exception:
                            continue
            
            self.ghdl_logger.warning(f"Could not find testbench file for entity: {testbench_name}")
            return None
            
        except Exception as e:
            self.ghdl_logger.error(f"Error finding testbench file: {e}")
            return None

if __name__ == "__main__":
    gman = GHDLCommands()
    #gman.analyze("C:\\Git_Projects\\CodePractice\\Python\\cc_project_manager\\src\\StateMachineTest_tb_top.vhd")
    gman.analyze(gman.config["hdl_project_hierarchy"]["src"]["StateMachineTest.vhd"])
    #gman.analyze_all()
    #gman.elaborate()
    #gman.pre_synth_simulate()

       

