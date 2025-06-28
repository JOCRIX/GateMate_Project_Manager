import logging
import subprocess
import os
from .ghdl_commands import GHDLCommands
import yaml
import datetime
from typing import Optional
from .hierarchy_manager import HierarchyManager

class SimulationManager(GHDLCommands):
    """Handles anything related to simulations including GTKWave integration"""
    
    # GTKWave tool definition - similar to ToolChainManager pattern
    __gtkwave_tool = {"gtkwave": "gtkwave.exe"} if os.name == 'nt' else {"gtkwave": "gtkwave"}
    
    def __init__(self, simulation_time: int = None, time_prefix: str = None):
        """
        Initialize SimulationManager with optional override parameters.
        If no parameters provided, loads from simulation_config.yml
        """
        # Load config first to check/set toolchain preference before calling super()
        temp_hierarchy = HierarchyManager()
        self.project_config = temp_hierarchy.load_config()
        self.config_path = temp_hierarchy._find_config_path()
        
        # Ensure toolchain preference is set for GHDL functionality
        if "cologne_chip_gatemate_toolchain_preference" not in self.project_config:
            self.project_config["cologne_chip_gatemate_toolchain_preference"] = "PATH"
            # Save the updated config
            try:
                with open(self.config_path, "w") as config_file:
                    yaml.safe_dump(self.project_config, config_file)
            except Exception:
                pass  # Continue without saving if failed
        
        # Get simulation configuration settings for GHDL
        vhdl_standard = "VHDL-2008"  # Default
        ieee_library = "synopsys"    # Default
        
        # Try to load simulation configuration from project config
        if "simulation_configuration" in self.project_config:
            sim_config = self.project_config["simulation_configuration"]
            vhdl_standard = sim_config.get("vhdl_standard", "VHDL-2008")
            ieee_library = sim_config.get("ieee_library", "synopsys")
            logging.info(f"Using simulation configuration: VHDL={vhdl_standard}, IEEE={ieee_library}")
        else:
            logging.info(f"No simulation configuration found, using defaults: VHDL={vhdl_standard}, IEEE={ieee_library}")
        
        # Now call super() with the simulation configuration settings
        super().__init__(vhdl_std=vhdl_standard, ieee_lib=ieee_library)
        
        # Load simulation configuration
        self.sim_config_path = os.path.join(os.path.dirname(self.config_path), "simulation_config.yml")
        self.sim_config = self.load_simulation_config()
        
        # Set simulation parameters
        if simulation_time is not None and time_prefix is not None:
            self.simulation_time = simulation_time
            self.time_prefix = time_prefix
        else:
            # Load from configuration
            current_settings = self.sim_config.get("current_simulation_settings", {})
            self.simulation_time = current_settings.get("simulation_time", 1000)
            self.time_prefix = current_settings.get("time_prefix", "ns")
        
        # Get supported values from config
        self.supported_time_prefixes = self.sim_config.get("supported_time_prefixes", ["ns"])
        self.simulation_types = self.sim_config.get("simulation_types", ["behavioral", "post-synthesis", "post-implementation"])
        
        # Ensure project simulation structure exists
        self.set_simulation_structure()
        
        # Set up GTKWave configuration structure
        self.set_gtkwave_config_structure()

    def load_simulation_config(self) -> dict:
        """
        Load simulation configuration from simulation_config.yml
        
        Returns:
            dict: Simulation configuration or default config if file doesn't exist
        """
        try:
            if os.path.exists(self.sim_config_path):
                with open(self.sim_config_path, 'r') as f:
                    config = yaml.safe_load(f)
                    logging.info(f"Loaded simulation configuration from {self.sim_config_path}")
                    return config
            else:
                logging.warning(f"Simulation config file not found at {self.sim_config_path}. Using defaults.")
                return self._get_default_simulation_config()
        except Exception as e:
            logging.error(f"Error loading simulation configuration: {e}")
            return self._get_default_simulation_config()

    def _get_default_simulation_config(self) -> dict:
        """
        Get default simulation configuration if config file doesn't exist
        
        Returns:
            dict: Default simulation configuration
        """
        return {
            "default_simulation_settings": {
                "simulation_time": 1000,
                "time_prefix": "ns"
            },
            "current_simulation_settings": {
                "simulation_time": 1000,
                "time_prefix": "ns",
                "profile_name": "standard"
            },
            "supported_time_prefixes": ["fs", "ps", "ns", "us", "ms", "sec"],
            "simulation_types": ["behavioral", "post-synthesis", "post-implementation"],
            "simulation_time_presets": {
                "quick": {"simulation_time": 100, "time_prefix": "ns", "description": "Quick test - 100ns"},
                "standard": {"simulation_time": 1000, "time_prefix": "ns", "description": "Standard test - 1μs"},
                "extended": {"simulation_time": 10000, "time_prefix": "ns", "description": "Extended test - 10μs"}
            }
        }

    def save_simulation_config(self) -> bool:
        """
        Save current simulation configuration to file
        
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            with open(self.sim_config_path, 'w') as f:
                yaml.safe_dump(self.sim_config, f, default_flow_style=False)
                logging.info(f"Saved simulation configuration to {self.sim_config_path}")
                return True
        except Exception as e:
            logging.error(f"Error saving simulation configuration: {e}")
            return False

    def get_simulation_presets(self) -> dict:
        """
        Get available simulation time presets
        
        Returns:
            dict: Available simulation presets
        """
        return self.sim_config.get("simulation_time_presets", {})

    def get_user_simulation_profiles(self) -> dict:
        """
        Get user-defined simulation profiles
        
        Returns:
            dict: User simulation profiles
        """
        return self.sim_config.get("user_simulation_profiles", {})

    def apply_simulation_preset(self, preset_name: str) -> bool:
        """
        Apply a simulation preset or user profile
        
        Args:
            preset_name (str): Name of the preset/profile to apply
            
        Returns:
            bool: True if successful, False otherwise
        """
        # Check both built-in presets and user profiles
        all_profiles = self.list_all_simulation_profiles()
        
        if preset_name not in all_profiles:
            logging.error(f"Simulation profile '{preset_name}' not found")
            return False
        
        profile = all_profiles[preset_name]
        self.simulation_time = profile["simulation_time"]
        self.time_prefix = profile["time_prefix"]
        
        # Update current settings in config
        self.sim_config["current_simulation_settings"] = {
            "simulation_time": self.simulation_time,
            "time_prefix": self.time_prefix,
            "profile_name": preset_name
        }
        
        # Save to file
        success = self.save_simulation_config()
        if success:
            logging.info(f"Applied simulation profile '{preset_name}': {self.simulation_time}{self.time_prefix}")
        
        return success

    def create_user_simulation_profile(self, profile_name: str, simulation_time: int, 
                                     time_prefix: str, description: str = "") -> bool:
        """
        Create a new user simulation profile
        
        Args:
            profile_name (str): Name for the new profile
            simulation_time (int): Simulation time
            time_prefix (str): Time prefix (ns, us, etc.)
            description (str): Optional description
            
        Returns:
            bool: True if successful, False otherwise
        """
        if time_prefix not in self.supported_time_prefixes:
            logging.error(f"Unsupported time prefix: {time_prefix}")
            return False
        
        # Initialize user profiles if they don't exist
        if "user_simulation_profiles" not in self.sim_config:
            self.sim_config["user_simulation_profiles"] = {}
        
        # Create new profile
        self.sim_config["user_simulation_profiles"][profile_name] = {
            "simulation_time": simulation_time,
            "time_prefix": time_prefix,
            "description": description if description else f"User profile - {simulation_time}{time_prefix}"
        }
        
        success = self.save_simulation_config()
        if success:
            logging.info(f"Created user simulation profile '{profile_name}': {simulation_time}{time_prefix}")
        
        return success

    def delete_user_simulation_profile(self, profile_name: str) -> bool:
        """
        Delete a user simulation profile
        
        Args:
            profile_name (str): Name of the profile to delete
            
        Returns:
            bool: True if successful, False otherwise
        """
        user_profiles = self.sim_config.get("user_simulation_profiles", {})
        
        if profile_name not in user_profiles:
            logging.error(f"User simulation profile '{profile_name}' not found")
            return False
        
        del self.sim_config["user_simulation_profiles"][profile_name]
        
        success = self.save_simulation_config()
        if success:
            logging.info(f"Deleted user simulation profile '{profile_name}'")
        
        return success

    def create_simulation_file(self) -> bool:
        """
        Creates a simulation structure for the project configuration file
        true if OK, false if not generated or failure
        """
        #check if the file path has been set
        if self.project_config["project_structure"]["simulation"]:
            logging.info("Simulation file path has already been set. Skipping.")
            return False
        #check if the file exists
        if os.path.exists(self.project_config["project_structure"]["simulation"]):
            logging.info("Simulation file path does not exist. Creating it.")
            os.makedirs(self.project_config["project_structure"]["simulation"])

    def set_simulation_structure(self) -> bool:
        """Makes a simulation structure for the project configuration file
        true if OK, false if not generated or failure
        
        """
        
        logging.info("Checking if simulation structure has already been generated in the project configuration.")
        available_keys = list(self.project_config.keys())
        if "simulation_settings" in available_keys:
            logging.info("Simulation setting structure has already been generated. Skipping.")
            return False
        
        logging.info("Generating a structure for simulation settings in the project configuration file")

        simulation_settings = {
            "simulation_time" : self.simulation_time,
            "time_prefix" : self.time_prefix
        }

        #append simulation settings to config
        self.project_config["simulation_settings"] = simulation_settings
        
        #write to project configuration file.

        try:
            with open(self.config_path, "w") as config_file:
                yaml.safe_dump(self.project_config, config_file)
                logging.info(f"Added simulation_settings: {simulation_settings} to project configuration.")
        except Exception as e:
            logging.error(f"Adding simulation settings to project configuration generated an error: {e}")

    def set_simulation_length(self, simulation_length: int = 1000, time_prefix: str = "ns") -> bool:
        """
        Sets the length of the simulation and the prefix (default ns)
        Updates both the simulation config and project config for backward compatibility

        Args:
            simulation_length (int): Simulation time value
            time_prefix (str): Time prefix (ns, us, etc.)
            
        Returns:
            bool: True if successful, False otherwise
        """
        # Validate time prefix
        if time_prefix not in self.supported_time_prefixes:
            logging.error(f"The chosen time prefix: {time_prefix} is not supported by simulation manager. Supported prefixes are {self.supported_time_prefixes}")
            return False
        
        # Update instance variables
        self.simulation_time = simulation_length
        self.time_prefix = time_prefix
        
        # Update simulation config
        self.sim_config["current_simulation_settings"] = {
            "simulation_time": simulation_length,
            "time_prefix": time_prefix,
            "profile_name": "custom"
        }
        
        # Save simulation config
        sim_config_success = self.save_simulation_config()
        
        # Update project config for backward compatibility
        project_config_success = True
        try:
            # Check if the simulation setting structure exists in project config
            available_keys = list(self.project_config.keys())
            if "simulation_settings" not in available_keys:
                logging.warning("Simulation setting structure not found in project config. Creating it.")
                self.project_config["simulation_settings"] = {}
            
            # Update project config
            self.project_config["simulation_settings"]["time_prefix"] = time_prefix
            self.project_config["simulation_settings"]["simulation_time"] = simulation_length
            
            # Save project config
            with open(self.config_path, "w") as config:
                yaml.safe_dump(self.project_config, config)
                logging.info(f"Updated simulation settings in project configuration: {simulation_length}{time_prefix}")
                
        except Exception as e:
            logging.error(f"Error updating project configuration: {e}")
            project_config_success = False
        
        if sim_config_success:
            logging.info(f"Updated simulation settings: {simulation_length}{time_prefix}")
        
        return sim_config_success and project_config_success

    def get_simulation_length(self) -> list|bool:
        """
        Returns the current simulation settings as list object or False if fail
        Uses simulation config as primary source, falls back to project config
        
        Returns:
            list: [simulation_time, time_prefix] or False if error
        """
        logging.info("Retrieving simulation settings")
        
        try:
            # Try to get from simulation config first
            current_settings = self.sim_config.get("current_simulation_settings", {})
            if current_settings:
                simulation_time = current_settings.get("simulation_time")
                time_prefix = current_settings.get("time_prefix")
                if simulation_time is not None and time_prefix is not None:
                    return [simulation_time, time_prefix]
            
            # Fall back to project config for backward compatibility
            self.project_config = self.load_config()
            if "simulation_settings" in self.project_config:
                simulation_settings = list(self.project_config["simulation_settings"].values())
                return simulation_settings
            
            # Use defaults
            logging.warning("No simulation settings found, using defaults")
            return [1000, "ns"]
            
        except Exception as e:
            logging.error(f"An error occurred reading simulation settings: {e}")
            return False

    def get_current_simulation_profile(self) -> str:
        """
        Get the name of the currently active simulation profile
        
        Returns:
            str: Profile name or "custom" if no specific profile
        """
        current_settings = self.sim_config.get("current_simulation_settings", {})
        return current_settings.get("profile_name", "custom")

    def list_all_simulation_profiles(self) -> dict:
        """
        Get all available simulation profiles (presets + user profiles)
        
        Returns:
            dict: Combined dictionary of all available profiles
        """
        all_profiles = {}
        
        # Add presets
        presets = self.get_simulation_presets()
        for name, preset in presets.items():
            all_profiles[name] = {
                "simulation_time": preset["simulation_time"],
                "time_prefix": preset["time_prefix"],
                "description": preset.get("description", ""),
                "type": "preset"
            }
        
        # Add user profiles
        user_profiles = self.get_user_simulation_profiles()
        for name, profile in user_profiles.items():
            all_profiles[name] = {
                "simulation_time": profile["simulation_time"],
                "time_prefix": profile["time_prefix"],
                "description": profile.get("description", ""),
                "type": "user"
            }
        
        return all_profiles

    def export_simulation_profile(self, profile_name: str, export_path: str) -> bool:
        """
        Export a simulation profile to a YAML file
        
        Args:
            profile_name (str): Name of the profile to export
            export_path (str): Path where to save the exported profile
            
        Returns:
            bool: True if successful, False otherwise
        """
        all_profiles = self.list_all_simulation_profiles()
        
        if profile_name not in all_profiles:
            logging.error(f"Profile '{profile_name}' not found")
            return False
        
        try:
            profile_data = {
                "profile_name": profile_name,
                "profile_data": all_profiles[profile_name],
                "exported_from": "Cologne Chip Project Manager",
                "export_date": str(os.path.getctime(self.sim_config_path))
            }
            
            with open(export_path, 'w') as f:
                yaml.safe_dump(profile_data, f, default_flow_style=False)
            
            logging.info(f"Exported simulation profile '{profile_name}' to {export_path}")
            return True
            
        except Exception as e:
            logging.error(f"Error exporting simulation profile: {e}")
            return False

    def import_simulation_profile(self, import_path: str) -> bool:
        """
        Import a simulation profile from a YAML file
        
        Args:
            import_path (str): Path to the profile file to import
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            with open(import_path, 'r') as f:
                imported_data = yaml.safe_load(f)
            
            profile_name = imported_data.get("profile_name")
            profile_data = imported_data.get("profile_data", {})
            
            if not profile_name or not profile_data:
                logging.error("Invalid profile file format")
                return False
            
            # Extract profile information
            simulation_time = profile_data.get("simulation_time")
            time_prefix = profile_data.get("time_prefix")
            description = profile_data.get("description", f"Imported profile - {simulation_time}{time_prefix}")
            
            if simulation_time is None or time_prefix is None:
                logging.error("Profile file missing required simulation settings")
                return False
            
            # Create the profile as a user profile
            return self.create_user_simulation_profile(profile_name, simulation_time, time_prefix, description)
            
        except Exception as e:
            logging.error(f"Error importing simulation profile: {e}")
            return False

    def prepare_testbench_for_simulation(self, testbench_entity_name: str = None) -> bool:
        """
        Prepare a testbench for simulation by analyzing and elaborating all necessary files.
        
        This method performs the complete preparation workflow:
        1. Analyze all source files (dependencies)
        2. Analyze testbench files  
        3. Elaborate the specified testbench entity
        
        Args:
            testbench_entity_name (str, optional): Name of testbench entity to elaborate.
                                                 If None, uses top-level testbench from project config.
        
        Returns:
            bool: True if preparation was successful, False otherwise
        """
        logging.info("Preparing testbench for simulation...")
        
        try:
            # Check that the hierarchy exists
            if not self.check_hierarchy():
                logging.error("Project hierarchy not found. Cannot prepare simulation.")
                return False
            
            hierarchy = HierarchyManager()
            files_info = hierarchy.get_source_files_info()
            
            analyzed_files = 0
            total_files = 0
            
            # Step 1: Analyze source files first (dependencies)
            if files_info["src"]:
                logging.info("Analyzing source files...")
                print("Analyzing source files...")
                for file_name, file_path in files_info["src"].items():
                    total_files += 1
                    print(f"   Analyzing: {file_name}")
                    if self.analyze(file_path):
                        analyzed_files += 1
                        print(f"   [OK] {file_name}")
                    else:
                        print(f"   [X] {file_name} - Analysis failed")
                        logging.error(f"Failed to analyze source file: {file_path}")
            
            # Step 2: Analyze top-level files
            if files_info["top"]:
                logging.info("Analyzing top-level files...")
                print("Analyzing top-level files...")
                for file_name, file_path in files_info["top"].items():
                    total_files += 1
                    print(f"   Analyzing: {file_name}")
                    if self.analyze(file_path):
                        analyzed_files += 1
                        print(f"   [OK] {file_name}")
                    else:
                        print(f"   [X] {file_name} - Analysis failed")
                        logging.error(f"Failed to analyze top-level file: {file_path}")
            
            # Step 3: Analyze testbench files
            if files_info["testbench"]:
                logging.info("Analyzing testbench files...")
                print("Analyzing testbench files...")
                for file_name, file_path in files_info["testbench"].items():
                    total_files += 1
                    print(f"   Analyzing: {file_name}")
                    
                    # Check if file is empty or too small to be valid VHDL
                    try:
                        if os.path.getsize(file_path) < 10:  # Less than 10 bytes is probably empty/invalid
                            print(f"   [WARN] {file_name} - Skipping (file too small/empty)")
                            logging.warning(f"Skipping analysis of {file_path} - file is empty or too small")
                            continue
                    except OSError:
                        print(f"   [X] {file_name} - File not accessible")
                        logging.error(f"Cannot access file {file_path}")
                        continue
                    
                    if self.analyze(file_path):
                        analyzed_files += 1
                        print(f"   [OK] {file_name}")
                    else:
                        print(f"   [X] {file_name} - Analysis failed")
                        logging.error(f"Failed to analyze testbench file: {file_path}")
            
            # Check if all files were analyzed successfully
            if analyzed_files != total_files:
                print(f"[WARN] Warning: {total_files - analyzed_files} files failed analysis")
                logging.warning(f"Only {analyzed_files}/{total_files} files analyzed successfully")
                # Continue anyway, but user should be aware
            else:
                print(f"[OK] All {total_files} files analyzed successfully")
                logging.info(f"All {total_files} files analyzed successfully")
            
            # Step 4: Determine testbench entity to elaborate
            if testbench_entity_name is None:
                # Try to get from top-level testbench in project config
                if not self.project_config["hdl_project_hierarchy"].get("top"):
                    logging.error("No top file set in project configuration and no testbench entity specified")
                    print("[X] No testbench entity specified and no top file configured")
                    return False
                
                top_file = list(self.project_config["hdl_project_hierarchy"]["top"].keys())[0]
                top_file_path = self.project_config["hdl_project_hierarchy"]["top"][top_file]
                
                # Check if this is a testbench file
                tb_exts = [".vhd", ".vhdl"]
                tb_combos = ["_tb", "_tb_top", "_top_tb"]
                
                if not any(top_file.lower().endswith(pattern + ext) for pattern in tb_combos for ext in tb_exts):
                    logging.error(f"Top file {top_file} is not a testbench file")
                    print(f"[X] Top file {top_file} is not a testbench file")
                    return False
                
                # Parse entity name from the top file
                testbench_entity_name = self.parse_entity_name_from_vhdl(top_file_path)
                if not testbench_entity_name:
                    logging.error(f"Could not parse entity name from {top_file_path}")
                    print(f"[X] Could not parse entity name from {top_file}")
                    return False
            
            # Step 5: Elaborate the testbench entity
            print(f"Elaborating testbench entity: {testbench_entity_name}")
            logging.info(f"Elaborating testbench entity: {testbench_entity_name}")
            
            success = self.elaborate(testbench_entity_name)
            if success:
                print(f"[OK] Successfully elaborated {testbench_entity_name}")
                logging.info(f"Successfully elaborated testbench entity: {testbench_entity_name}")
                print(f"Testbench '{testbench_entity_name}' is ready for simulation!")
                return True
            else:
                print(f"[X] Failed to elaborate {testbench_entity_name}")
                logging.error(f"Failed to elaborate testbench entity: {testbench_entity_name}")
                return False
                
        except Exception as e:
            logging.error(f"Error preparing testbench for simulation: {e}")
            print(f"[X] Error preparing testbench: {e}")
            return False

    def behavioral_simulate(self) -> bool: #Note: this function could do with a re-factor, too long
        """Simulate the testbench with GHDL.
        
        This function runs a simulation of the top-level testbench entity
        using GHDL's run command. It generates VCD waveform output in the
        behavioral simulation directory.

        The simulation length must be set in project_configuration prior to this function call, use set_simulation_length() for this
        
        Returns:
            bool: True if simulation was successful, False otherwise
        """
        

        logging.info("Running GHDL behavioral simulation of the testbench")
        # Check that the hierarchy exists
        if not self.check_hierarchy():
            logging.error("Project hierarchy not found. Cannot run simulation.")
            return False    
        #check that the top entity is set
        if not self.project_config["hdl_project_hierarchy"].get("top"):
            logging.info(f"The top file in the project has not been set. GHDL simulation can not continue")
            return False
        #retrieve entity name
        top_file = list(self.project_config["hdl_project_hierarchy"]["top"].keys())[0]
        top_file_path = self.project_config["hdl_project_hierarchy"]["top"][top_file]
        logging.info(f"The top file in the project is: {top_file}")
        #Check if this is a testbench (its filename must include _tb or similar)
        tb_exts = [".vhd", ".vhdl"]
        tb_combos = ["_tb", "_tb_top", "_top_tb"]

        if not any(top_file.lower().endswith(pattern + ext) for pattern in tb_combos for ext in tb_exts):
            logging.error(f"The top file {top_file} is not a valid testbench file. Expected a suffix like _tb.vhd or _tb.vhdl.")
            return False
        #parse top file and extract top entity name
        top_entity_name = self.parse_entity_name_from_vhdl(top_file_path)
        if not top_entity_name:
            logging.error(f"Could not parse entity name from {top_file_path}")
            return False
        #ghdl lowercases entity names automatically
        ghdl_entity_name = top_entity_name.lower()

        # NEW: Prepare testbench for simulation (analyze + elaborate)
        print("Preparing testbench for simulation...")
        if not self.prepare_testbench_for_simulation(top_entity_name):
            logging.error("Failed to prepare testbench for simulation")
            print("[X] Failed to prepare testbench for simulation")
            return False

        ##retrieve simulation length
        sim_settings = self.get_simulation_length()
        if not sim_settings:
            logging.error("Could not retrieve simulation settings.")
            return False

        simulation_length, time_prefix = sim_settings

        logging.info(f"Running GHDL simulation on entity: {top_entity_name}")
        print(f"Running GHDL simulation on entity: {top_entity_name}")
        
        # Get build directory and simulation output directory
        build_dir = self.project_config["project_structure"]["build"][0]
        sim_dir = self.project_config["project_structure"]["sim"]["behavioral"][0]
        
        # Ensure simulation directory exists
        if not os.path.exists(sim_dir):
            logging.warning(f"The projects simulation directory didn't exist. Making it.")
            os.makedirs(sim_dir)
            
        #ensure build directory exists
        if not os.path.exists(build_dir):
            logging.warning(f"The projects build directory didn't exist. Making it.")
            os.makedirs(build_dir)
        
        # Create VCD output path
        vcd_file = os.path.join(sim_dir, f"{ghdl_entity_name}_wave.vcd")
        
        try:
            # Run the simulation with GHDL
            print(f"Simulating: {top_entity_name} (using lowercase for GHDL: {ghdl_entity_name})")
            print(f"VCD output: {vcd_file}")
            
            cmd = [
                self.ghdl_access, "run", 
                self.vhdl_std,
                self.ieee_lib,
                f"--workdir={build_dir}",
                f"--work={self.work_lib_name}" if hasattr(self, 'work_lib_name') and self.work_lib_name else "--work=work",
                ghdl_entity_name,
                f"--vcd={vcd_file}",
                f"--stop-time={simulation_length}{time_prefix}"
            ]
            
            print(cmd)
            logging.info(f"Running command: {' '.join(cmd)}")
            result = subprocess.run(cmd, check=True)
            
            print(f"Simulation completed successfully. VCD file written to: {vcd_file}")
            logging.info(f"Simulation completed successfully. VCD file written to: {vcd_file}")
            
            # Record the successful simulation run
            self.record_simulation_run(top_entity_name, "behavioral", vcd_file, True)
            
            return True
            
        except subprocess.CalledProcessError as e:
            print(f"GHDL simulation failed with error: {e}")
            logging.error(f"GHDL simulation failed with error: {e}")
            
            # Record the failed simulation run
            self.record_simulation_run(top_entity_name, "behavioral", vcd_file, False)
            
            return False
            
        except Exception as e:
            print(f"An error occurred during simulation: {e}")
            logging.error(f"An error occurred during simulation: {e}")
            
            # Record the failed simulation run
            self.record_simulation_run(top_entity_name, "behavioral", vcd_file, False)
            
            return False

    # Alias for backward compatibility
    pre_synth_simulate = behavioral_simulate

    def post_synthesis_simulate(self, entity_name: str = None, testbench_name: str = None) -> bool:
        """
        Run VHDL post-synthesis simulation using GHDL synthesis to VHDL.
        
        VHDL-TO-VHDL POST-SYNTHESIS WORKFLOW:
        This method now provides true post-synthesis simulation by:
        1. Analyzing original VHDL source
        2. Using GHDL synthesis to generate synthesized VHDL netlist
        3. Analyzing synthesized VHDL
        4. Using existing VHDL testbenches with component instantiation
        5. Running simulation with the synthesized entity
        
        This approach allows users to:
        - Write VHDL testbenches (familiar language)
        - Test actual synthesized logic (not just behavioral)
        - Use existing toolchain (GHDL only)
        - Generate comprehensive waveform files
        
        ADVANTAGES:
        - True post-synthesis verification
        - No mixed-language complexity
        - Uses synthesized logic gates
        - Compatible with existing VHDL testbenches
        - Detects synthesis-specific issues
        
        Args:
            entity_name: Name of the entity to synthesize and simulate (auto-detected if None)
            testbench_name: Name of the testbench entity (auto-detected if None)
            
        Returns:
            bool: True if post-synthesis simulation successful, False otherwise
        """
        
        logging.info("Starting VHDL post-synthesis simulation")
        logging.info("Using GHDL synthesis to VHDL followed by VHDL testbench simulation")
        
        # Auto-detect entity name if not provided
        if entity_name is None:
            try:
                # Try to get from top-level entity in project config
                top_files = self.project_config["hdl_project_hierarchy"].get("top", {})
                if top_files:
                    top_file = list(top_files.values())[0]
                    entity_name = self.parse_entity_name_from_vhdl(top_file)
                    if entity_name:
                        logging.info(f"Auto-detected entity: {entity_name}")
                    else:
                        logging.error("Could not auto-detect entity name")
                        return False
                else:
                    logging.error("No top-level entity specified and auto-detection failed")
                    return False
            except Exception as e:
                logging.error(f"Error auto-detecting entity: {e}")
                return False
        
        # Use the GHDLCommands post_synthesis_simulation method
        try:
            # Get simulation time settings (same as behavioral simulation)
            sim_settings = self.get_simulation_length()
            if not sim_settings:
                logging.error("Could not retrieve simulation settings.")
                print("[X] Could not retrieve simulation settings")
                return False

            simulation_length, time_prefix = sim_settings
            logging.info(f"Using simulation settings: {simulation_length}{time_prefix}")
            print(f"Using simulation time: {simulation_length}{time_prefix}")
            
            success = super().post_synthesis_simulation(
                entity_name=entity_name,
                testbench_name=testbench_name,
                analyze_options=None,
                elaborate_options=None,
                run_options=None,
                simulation_time=simulation_length,
                time_prefix=time_prefix
            )
            
            if success:
                logging.info("VHDL post-synthesis simulation completed successfully")
                print("[OK] VHDL post-synthesis simulation completed successfully!")
                print("Tested synthesized logic with VHDL testbench")
                print("Generated synthesized VHDL netlist and simulation waveforms")
                
                # Record the simulation run
                sim_dir = self.project_config["project_structure"]["sim"]["post-synthesis"][0]
                vcd_path = os.path.join(sim_dir, f"{entity_name}_vhdl_post_synth.vcd")
                self.record_simulation_run(entity_name, "post-synthesis", vcd_path, True)
                
                return True
            else:
                logging.error("VHDL post-synthesis simulation failed")
                print("[X] VHDL post-synthesis simulation failed")
                print("Check logs for detailed error information")
                
                # Record the failed simulation run
                sim_dir = self.project_config["project_structure"]["sim"]["post-synthesis"][0]
                vcd_path = os.path.join(sim_dir, f"{entity_name}_vhdl_post_synth.vcd")
                self.record_simulation_run(entity_name, "post-synthesis", vcd_path, False)
                
                return False
                
        except Exception as e:
            logging.error(f"Error in VHDL post-synthesis simulation: {e}")
            print(f"[X] VHDL post-synthesis simulation error: {e}")
            return False

    def add_simulated_entities(self, entity_name : str = None, sim_type : str = None) -> bool:
        """
        Adds simulated entites to the project configuration file

        return True if OK, otherwise false
        """
        #check if sim_type is set
        if sim_type not in self.simulation_types:
            logging.error("Error. Simulation type has not not passed to add_simulated_entities. Valid types are {self.simulation_types}. Exit")
            return False
        #check if entity has been set
        if entity_name == None:
            logging.error("Error. Simulated HDL entity name has not been passed to add_simulated_entities. Exit")
            return False
        # Check if the simulated entities exist in simulation structure
        self.project_config = self.load_config()
        ###.... do stuff
        ##Use update_config()
    
    def launch_wave(self, vcd_file_path: str = None) -> bool:
        """
        Launch GTKWave with the specified VCD file or the latest simulation VCD
        
        Args:
            vcd_file_path (str, optional): Path to VCD file. If None, uses latest behavioral simulation
            
        Returns:
            bool: True if GTKWave launched successfully, False otherwise
        """
        logging.info("Launching GTKWave for waveform viewing")
        
        # Check if GTKWave is available
        if not self.check_gtkwave():
            print("[X] GTKWave is not available. Please configure GTKWave path first.")
            logging.error("Cannot launch GTKWave - tool not available")
            return False
        
        # Determine VCD file to open
        if vcd_file_path is None:
            # Find the latest behavioral simulation VCD
            available_sims = self.get_available_simulations()
            behavioral_sims = available_sims.get("behavioral", [])
            
            if not behavioral_sims:
                print("[X] No behavioral simulation VCD files found")
                logging.error("No VCD files found for GTKWave")
                return False
            
            # Get the most recent VCD file
            latest_sim = max(behavioral_sims, key=lambda x: x["modified"])
            vcd_file_path = latest_sim["path"]
            print(f"Using latest simulation: {latest_sim['name']}")
        
        # Check if VCD file exists
        if not os.path.exists(vcd_file_path):
            print(f"[X] VCD file not found: {vcd_file_path}")
            logging.error(f"VCD file not found: {vcd_file_path}")
            return False
        
        # Get GTKWave access command
        gtkwave_cmd = self._get_gtkwave_access()
        if not gtkwave_cmd:
            print("[X] GTKWave access command not available")
            logging.error("GTKWave access command not available")
            return False
        
        try:
            # Launch GTKWave with the VCD file
            print(f"Launching GTKWave with: {os.path.basename(vcd_file_path)}")
            logging.info(f"Launching GTKWave: {gtkwave_cmd} {vcd_file_path}")
            
            # Launch GTKWave in background
            if os.name == 'nt':  # Windows
                subprocess.Popen([gtkwave_cmd, vcd_file_path], 
                               creationflags=subprocess.CREATE_NEW_CONSOLE)
            else:  # Unix/Linux
                subprocess.Popen([gtkwave_cmd, vcd_file_path])
            
            print("GTKWave launched successfully")
            logging.info("GTKWave launched successfully")
            return True
            
        except Exception as e:
            print(f"[X] Failed to launch GTKWave: {e}")
            logging.error(f"Failed to launch GTKWave: {e}")
            return False

    def set_gtkwave_config_structure(self):
        """Sets up GTKWave configuration structure in project configuration"""
        logging.info("Setting up GTKWave configuration structure")
        
        # GTKWave tool path structure
        gtkwave_structure = {
            "gtkwave": ""
        }
        
        # Check if the structure already exists
        if "gtkwave_tool_path" not in self.project_config:
            logging.info("Creating GTKWave tool path structure in project configuration")
            self.project_config["gtkwave_tool_path"] = gtkwave_structure
            
            # Save to config
            try:
                with open(self.config_path, "w") as config_file:
                    yaml.safe_dump(self.project_config, config_file)
                logging.info("Added GTKWave tool path structure to project configuration")
            except Exception as e:
                logging.error(f"Failed to add GTKWave structure to configuration: {e}")
        else:
            logging.info("GTKWave tool path structure already exists in project configuration")
    
    def check_gtkwave(self) -> bool:
        """
        Check if GTKWave is available through PATH or direct binary paths.
        Similar to ToolChainManager.check_toolchain()
        
        Returns:
            bool: True if GTKWave is available, False otherwise
        """
        STATUS_OK = "OK"
        STATUS_FAIL = "FAIL"
        tool_status = {}
        
        # Check via PATH
        if self.check_gtkwave_path():
            tool_status["PATH"] = STATUS_OK
        else:
            logging.warning("GTKWave is unavailable through system PATH")
            tool_status["PATH"] = STATUS_FAIL
        
        # Check via direct path
        if self.check_gtkwave_direct():
            tool_status["BINARY"] = STATUS_OK
        else:
            logging.warning("GTKWave is unavailable through specified binary path")
            tool_status["BINARY"] = STATUS_FAIL
        
        # Analyze status
        path_status = tool_status.get("PATH")
        binary_status = tool_status.get("BINARY")
        
        if path_status == STATUS_FAIL and binary_status == STATUS_FAIL:
            logging.error("GTKWave is not reachable through PATH or direct path. Configure GTKWave path.")
            self.set_gtkwave_preference("undefined")
            return False
        
        if path_status == STATUS_OK and binary_status == STATUS_OK:
            logging.info("GTKWave is available through both PATH and direct path")
            self.set_gtkwave_preference("path")
        elif path_status == STATUS_OK:
            logging.info("GTKWave is available through PATH")
            self.set_gtkwave_preference("path")
        elif binary_status == STATUS_OK:
            logging.info("GTKWave is available through direct path")
            self.set_gtkwave_preference("direct")
        
        return True
    
    def check_gtkwave_path(self) -> bool:
        """
        Check if GTKWave is available through the PATH environment variable
        
        Returns:
            bool: True if available through PATH, False otherwise
        """
        logging.info("Checking if GTKWave is available through PATH")
        
        gtkwave_tool = "gtkwave"
        try:
            result = subprocess.run([gtkwave_tool, "--version"], 
                                  capture_output=True, text=True, check=True, timeout=10)
            logging.info(f"GTKWave version through PATH:\n{result.stdout}")
            return True
        except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
            logging.error("GTKWave not found or not working through PATH")
            return False
    
    def check_gtkwave_direct(self) -> bool:
        """
        Check if GTKWave is available at the direct path specified in configuration
        
        Returns:
            bool: True if available at direct path, False otherwise
        """
        logging.info("Checking if GTKWave is available at specified direct path")
        
        try:
            tool_path = self.project_config.get("gtkwave_tool_path", {}).get("gtkwave", "")
            if not tool_path:
                logging.info("No direct path configured for GTKWave")
                return False
            
            if not os.path.exists(tool_path):
                logging.error(f"GTKWave not found at configured path: {tool_path}")
                return False
            
            # Test the tool
            result = subprocess.run([tool_path, "--version"], 
                                  capture_output=True, text=True, check=True, timeout=10)
            logging.info(f"GTKWave confirmed working at {tool_path}")
            return True
            
        except Exception as e:
            logging.error(f"Error checking GTKWave at direct path: {e}")
            return False
    
    def add_gtkwave_path(self, path: str) -> bool:
        """
        Add a direct file path for GTKWave tool to the project configuration
        
        Args:
            path (str): Path to GTKWave executable
            
        Returns:
            bool: True if successful, False otherwise
        """
        resolved_path = os.path.normpath(path.strip())
        logging.info(f"Adding GTKWave path: {resolved_path}")
        
        # Check if path exists
        if not os.path.exists(resolved_path):
            logging.error(f"GTKWave path does not exist: {resolved_path}")
            return False
        
        # Check if it's the correct binary
        expected_binary = self.__gtkwave_tool["gtkwave"]
        if not resolved_path.lower().endswith(expected_binary.lower()):
            logging.error(f"Path must end with {expected_binary}")
            return False
        
        # Test the tool
        try:
            result = subprocess.run([resolved_path, "--version"], 
                                  capture_output=True, text=True, check=True, timeout=10)
            logging.info(f"GTKWave test successful at {resolved_path}")
        except Exception as e:
            logging.error(f"GTKWave test failed at {resolved_path}: {e}")
            return False
        
        # Add to configuration
        if "gtkwave_tool_path" not in self.project_config:
            self.set_gtkwave_config_structure()
        
        self.project_config["gtkwave_tool_path"]["gtkwave"] = resolved_path
        
        # Save configuration
        try:
            with open(self.config_path, "w") as config_file:
                yaml.safe_dump(self.project_config, config_file)
            logging.info(f"Added GTKWave path to configuration: {resolved_path}")
            return True
        except Exception as e:
            logging.error(f"Failed to save GTKWave path to configuration: {e}")
            return False
    
    def set_gtkwave_preference(self, preference: str) -> bool:
        """
        Set GTKWave access preference in project configuration
        
        Args:
            preference (str): "path", "direct", or "undefined"
            
        Returns:
            bool: True if successful, False otherwise
        """
        preference = preference.upper()
        supported_preferences = ("PATH", "DIRECT", "UNDEFINED")
        
        if preference not in supported_preferences:
            logging.error(f"Invalid GTKWave preference: {preference}")
            return False
        
        self.project_config["gtkwave_preference"] = preference
        
        try:
            with open(self.config_path, "w") as config_file:
                yaml.safe_dump(self.project_config, config_file)
            logging.info(f"Set GTKWave preference to: {preference}")
            return True
        except Exception as e:
            logging.error(f"Failed to save GTKWave preference: {e}")
            return False
    
    def _get_gtkwave_access(self) -> str:
        """
        Get the GTKWave access command/path based on preference
        
        Returns:
            str: Command or path to use for GTKWave
        """
        preference = self.project_config.get("gtkwave_preference", "PATH")
        
        if preference == "PATH":
            return "gtkwave"
        elif preference == "DIRECT":
            return self.project_config.get("gtkwave_tool_path", {}).get("gtkwave", "")
        else:
            logging.error("GTKWave preference is undefined")
            return ""
    
    def get_available_simulations(self) -> dict:
        """
        Get available simulation VCD files organized by simulation type
        
        Returns:
            dict: Dictionary with simulation types as keys and lists of available VCD files
        """
        available_sims = {
            "behavioral": [],
            "post-synthesis": [],
            "post-implementation": []
        }
        
        try:
            # Get simulation directories from project structure
            sim_structure = self.project_config.get("project_structure", {}).get("sim", {})
            
            # Check behavioral simulations
            behavioral_dir = sim_structure.get("behavioral", [])
            if behavioral_dir and isinstance(behavioral_dir, list):
                behavioral_path = behavioral_dir[0]
                if os.path.exists(behavioral_path):
                    vcd_files = [f for f in os.listdir(behavioral_path) if f.endswith('.vcd')]
                    for vcd_file in vcd_files:
                        file_path = os.path.join(behavioral_path, vcd_file)
                        file_stats = os.stat(file_path)
                        available_sims["behavioral"].append({
                            "name": vcd_file,
                            "path": file_path,
                            "size": file_stats.st_size,
                            "modified": datetime.datetime.fromtimestamp(file_stats.st_mtime),
                            "entity": vcd_file.replace("_wave.vcd", "")
                        })
            
            # Check post-synthesis simulations
            post_synth_dir = sim_structure.get("post-synthesis", [])
            if post_synth_dir and isinstance(post_synth_dir, list):
                post_synth_path = post_synth_dir[0]
                if os.path.exists(post_synth_path):
                    vcd_files = [f for f in os.listdir(post_synth_path) if f.endswith('.vcd')]
                    for vcd_file in vcd_files:
                        file_path = os.path.join(post_synth_path, vcd_file)
                        file_stats = os.stat(file_path)
                        available_sims["post-synthesis"].append({
                            "name": vcd_file,
                            "path": file_path,
                            "size": file_stats.st_size,
                            "modified": datetime.datetime.fromtimestamp(file_stats.st_mtime),
                            "entity": vcd_file.replace("_wave.vcd", "")
                        })
            
            # Check post-implementation simulations
            post_impl_dir = sim_structure.get("post-implementation", [])
            if post_impl_dir and isinstance(post_impl_dir, list):
                post_impl_path = post_impl_dir[0]
                if os.path.exists(post_impl_path):
                    vcd_files = [f for f in os.listdir(post_impl_path) if f.endswith('.vcd')]
                    for vcd_file in vcd_files:
                        file_path = os.path.join(post_impl_path, vcd_file)
                        file_stats = os.stat(file_path)
                        available_sims["post-implementation"].append({
                            "name": vcd_file,
                            "path": file_path,
                            "size": file_stats.st_size,
                            "modified": datetime.datetime.fromtimestamp(file_stats.st_mtime),
                            "entity": vcd_file.replace("_wave.vcd", "")
                        })
            
        except Exception as e:
            logging.error(f"Error getting available simulations: {e}")
        
        return available_sims
    
    def record_simulation_run(self, entity_name: str, sim_type: str, vcd_path: str, success: bool) -> bool:
        """
        Record a simulation run in the project configuration
        
        Args:
            entity_name (str): Name of the simulated entity
            sim_type (str): Type of simulation (behavioral, post-synthesis, post-implementation)
            vcd_path (str): Path to the generated VCD file
            success (bool): Whether the simulation was successful
            
        Returns:
            bool: True if recorded successfully, False otherwise
        """
        if sim_type not in self.simulation_types:
            logging.error(f"Invalid simulation type: {sim_type}")
            return False
        
        try:
            # Initialize simulation history if it doesn't exist
            if "simulation_history" not in self.project_config:
                self.project_config["simulation_history"] = {}
            
            if sim_type not in self.project_config["simulation_history"]:
                self.project_config["simulation_history"][sim_type] = []
            
            # Create simulation record
            sim_record = {
                "entity_name": entity_name,
                "timestamp": datetime.datetime.now().isoformat(),
                "vcd_file": vcd_path,
                "success": success,
                "simulation_time": self.simulation_time,
                "time_prefix": self.time_prefix
            }
            
            # Add to history (keep last 50 records per type)
            self.project_config["simulation_history"][sim_type].append(sim_record)
            if len(self.project_config["simulation_history"][sim_type]) > 50:
                self.project_config["simulation_history"][sim_type] = self.project_config["simulation_history"][sim_type][-50:]
            
            # Save configuration
            with open(self.config_path, "w") as config_file:
                yaml.safe_dump(self.project_config, config_file)
            
            logging.info(f"Recorded {sim_type} simulation for {entity_name}: {'success' if success else 'failure'}")
            return True
            
        except Exception as e:
            logging.error(f"Error recording simulation run: {e}")
            return False

if __name__ == "__main__":
    sim = SimulationManager()
    sim.set_simulation_length(199 , "ns") #Set the simulation length.
    print(sim.get_simulation_length())
    sim.pre_synth_simulate()
    