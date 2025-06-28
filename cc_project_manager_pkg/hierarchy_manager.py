import yaml
import logging
import os
import shutil

class HierarchyManager:
    """Manages HDL project hierarchy, configuration, and source files."""
    def __init__(self, top_module : str = None):
        """Initialize the HDL hierarchy with specified top module.\n
        top modules must be terminated with a "_top" suffix.
        
        Args:
            top_module: Name of the top module file i.e. "SomeModule_top.vhd"
        """
        self.top = top_module
        #Get path to project directory - use current working directory instead of package directory
        self.project_path = os.getcwd()
        
        # Initialize logging flag and log file path
        self.log_file = None
        self.logging_configured = False
        self.initializing = True  # Flag to prevent logging during init
        
        #Find configuration path and config first (without logging)
        self.config_path = self._find_config_path()
        self.config = self.load_config()
        
        # Initialization complete, logging can now be used
        self.initializing = False
        self.initialized_once = False

    def _ensure_logging_configured(self):
        """Ensure logging is properly configured before any logging operations."""
        if not self.logging_configured and not self.initializing:
            # Only configure logging if we have a valid project
            if self.config and self.config_path:
                self._setup_logging()
                self.logging_configured = True

    def _setup_logging(self):
        """Set up logging using the path from configuration file."""
        try:
            # Only set up logging if we have a valid project configuration
            if not self.config or not self.config_path:
                # No valid project found, skip logging setup
                self.log_file = None
                return
            
            # Use actual project path instead of potentially incorrect configuration paths
            actual_logs_dir = os.path.join(self.project_path, "logs")
            
            # Ensure the logs directory exists
            if not os.path.exists(actual_logs_dir):
                os.makedirs(actual_logs_dir, exist_ok=True)
            
            # Set log file path using actual project location
            self.log_file = os.path.join(actual_logs_dir, "project_manager.log")
            
            # Configure logging only if we have a valid log file path
            if self.log_file:
                # Get or create a logger specific to this class
                logger = logging.getLogger('HierarchyManager')
                logger.setLevel(logging.DEBUG)
                logger.propagate = False  # Prevent propagation to root logger
                
                # Remove any existing handlers to avoid duplicates
                for handler in logger.handlers[:]:
                    logger.removeHandler(handler)
                
                # Add file handler
                file_handler = logging.FileHandler(self.log_file)
                file_handler.setLevel(logging.DEBUG)
                formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
                file_handler.setFormatter(formatter)
                logger.addHandler(file_handler)
                
                # Log initialization message
                logger.info(f"HierarchyManager logging initialized to {self.log_file}")
            
        except Exception as e:
            # If logging setup fails, continue without file logging
            # This prevents initialization from failing due to logging issues
            self.log_file = None
            print(f"Warning: Could not set up logging: {e}")

    def _log(self, level, message):
        """Internal logging method that ensures logging is configured."""
        # Skip logging during initialization
        if self.initializing:
            return
            
        self._ensure_logging_configured()
        
        if self.log_file:
            logger = logging.getLogger('HierarchyManager')
            logger.propagate = False  # Prevent propagation to root logger
            getattr(logger, level)(message)
        # If no file logging available, silently continue

    def _find_config_path(self) -> str:
        """Find project configuration file in project directory.
        
        Returns:
           (str) Path to configuration file or None if not found
        """
        config_path = None
        self._log("info", "Searching for project configuration")
        
        # Search in current directory and subdirectories for project config files
        for root, dirs, files in os.walk(self.project_path):
            for file in files:
                if file.endswith('project_config.yml'):
                    config_path = os.path.join(root, file)
                    self._log("info", f"Project configuration file found at {config_path}")
                    return config_path
        
        # If not found in subdirectories, also check the current directory directly
        current_dir_files = os.listdir(self.project_path) if os.path.exists(self.project_path) else []
        for file in current_dir_files:
            if file.endswith('project_config.yml') and os.path.isfile(os.path.join(self.project_path, file)):
                config_path = os.path.join(self.project_path, file)
                self._log("info", f"Project configuration file found in current directory at {config_path}")
                return config_path
                
        self._log("error", f"Project configuration file not found in {self.project_path}")
        return None

    def load_config(self) -> dict:
        """Load project configuration from YAML file.
        
        Returns:
            Configuration as dictionary or empty dict if loading fails
        """
        config = None
        self._log("info", f"Attempting to load the project configuration file at {self.config_path}")
        try:
            with open(self.config_path, "r") as file:
                config = yaml.safe_load(file)
                self._log("info", f"Project configuration loaded at {self.config_path}")
                return config
        except Exception as e:
            self._log("error", f"Failed to open configuration file at {self.config_path}. {e}")
            # Return empty config instead of None to prevent NoneType errors
            return {}
    
    def find_hdl_sources(self) -> list:
        """Find all HDL source files in src directory.
        
        Returns:
            (list) List of HDL source files
        """
        src_path = self.config["project_structure"]["src"][0] # the src value is stored as a list, we must add [0] to index it properly
        
        #Finding all .vhd .vhdl sources in the src directory
        self._log("info", f"Finding .vhd .vhdl sources in src directory at {src_path}")
        hdl_sources = None
        try:
            hdl_sources = os.listdir(src_path)
            self._log("info", f".vhd .vhdl src found at {src_path}: {hdl_sources}")
        except Exception as e:
            self._log("error", f"Failed to find HDL sources in {src_path}: {e}")
        return hdl_sources
    
    def sort_hdl_sources(self, hdl_sources : list) -> dict:
        """Sort HDL sources into top, testbench, and src categories.
        
        Args:
            (list) hdl_sources: List of HDL source files
            
        Returns:
            (dict) Dictionary of categorized sources with file paths
        """
        #sorting HDL sources into SRC, TOP, TB etc
        self._log("info", f"Sorting HDL sources {hdl_sources}")   
        sorted_sources = {
                        "top" : {},
                        "testbench" : {},
                        "src" : {}
        }
        #Sorting the modules into sorted_sources
        #self._log("info", f"Finding top module in {hdl_sources}")   
        for file in hdl_sources:
            lower_file = file.lower() #lower case everything
            #construct file path
            file_path = os.path.join(self.config["project_structure"]["src"][0], file)
            if lower_file.endswith("_tb.vhd") or lower_file.endswith("_tb.vhdl"):
                sorted_sources["testbench"][file] = file_path
            elif lower_file.endswith("_top.vhd") or lower_file.endswith("_top.vhdl"):
                sorted_sources["top"][file] = file_path
            elif lower_file.endswith(".vhd") or lower_file.endswith(".vhdl"):
                sorted_sources["src"][file] = file_path
            else:
                self._log("warning", f"Unrecognized HDL file format: {file}")
        self._log("info", f"Sorted HDL files: {sorted_sources}")
        return sorted_sources

    def append_config_file(self, sorted_sources) -> dict:
        """Add sorted sources to configuration file.
        
        Args:
           (dict) sorted_sources: Dictionary of categorized sources
        """
        self.config["hdl_project_hierarchy"] = sorted_sources
        try:
            self._log("info", f"Adding {sorted_sources} to local config")
            with open(self.config_path, "w") as config_file:
                yaml.safe_dump(self.config, config_file)
        except Exception as e:
            self._log("error", f"Failed to append to the configuration file: {e}")

    def init_sources(self):
        """Initialize project sources and hierarchy structure with all the sources located in %root%/src/."""
        if self.initialized_once == True:
            self._log("error", f"Attempted to initialize sources, but it has already happened. Return.")
            return None
        hdl_sources = self.find_hdl_sources()
        sorted_hdl_sources = self.sort_hdl_sources(hdl_sources)
        self.append_config_file(sorted_hdl_sources)
        self.initialized_once = True

    def add_source(self, new_source : str):
        """Add a single source file to the project.
        
        Args:
           (str) new_source: Source file name to add i.e. "SomeSource.vhd"
        """
        #Check if the src file exists in the src directory

        src_dir = self.find_hdl_sources()        
        if new_source not in src_dir:
            self._log("error", f"New source file {new_source} is not found in src directory. Exit.")
            return None
        #Making path for the new source file
        new_source_path = os.path.join(self.config["project_structure"]["src"][0], new_source)
        
        self._log("info", f"Attempting to add {new_source} to local config")
        # Append the new source to the existing dictionary under the "src" key
        #check that the structure is A-ok
        if "hdl_project_hierarchy" not in self.config: 
            self.config["hdl_project_hierarchy"] = {}
            self._log("warning", "hdl_project_hierarchy didn't exist. Remaking it.")
        #initialize src if it doesnt exist
        if "src" not in self.config["hdl_project_hierarchy"]:
            self.config["hdl_project_hierarchy"]["src"] = {}
            self._log("warning", "src didnt exist in hdl_project_hierarchy. Remaking it.")

        #add the new source as key value pair
        self.config["hdl_project_hierarchy"]["src"][new_source] = new_source_path
        self._log("info", f"Added src {new_source} at {new_source_path} to local config.")
        self.update_config()

    def remove_source(self, source_file, do_update : bool = False):
        """Remove a source file from configuration.
        
        Args:
           (str) source_file: File name to remove i.e. "SomeSource.vhd"
           (bool) do_update: Whether to update config file immediately. True = update config file
        """
        self._log("info", f"Attempting to remove {source_file} from config")
        #check if the source file exists in the config

        for category, sources in self.config["hdl_project_hierarchy"].items():
                if source_file in sources:
                    del self.config["hdl_project_hierarchy"][category][source_file]
                    self._log("info", f"{source_file} removed from local config")
                    #optionally update? may want to remove more
                    if do_update == True:
                        self._log("info", f"Removing {source_file} from project configuration file")
                        self.update_config()
                    return
        self._log("error", f"Can't remove {source_file} from config, it doesn't exist.")

    def set_top(self, new_top_mod):
        """Set the top module for the project.\n
        top modules must be terminated with a "_top" suffix.
        There can only be 1 top module active at any time.
        Args:
           (str) new_top_mod: Name of file to set as top module i.e. "SomeModule_top.vhd"
        """
        self._log("info", f"Attempting to set new HDL TOP module in local config")

        #check that the structure is A-ok
        if "hdl_project_hierarchy" not in self.config: 
            self.config["hdl_project_hierarchy"] = {}
            self._log("warning", "hdl_project_hierarchy didn't exist. Remaking it.")
        #initialize src if it doesnt exist
        if "top" not in self.config["hdl_project_hierarchy"]:
            self.config["hdl_project_hierarchy"]["top"] = {}
            self._log("warning", "top didnt exist in hdl_project_hierarchy. Remaking it.")
        #Check that the new top module exists
        src_dir = self.find_hdl_sources()
        if new_top_mod not in src_dir:
            self._log("error", f"New TOP module file {new_top_mod} is not found in src directory. Add it first. Exit.")
            return None     
        #get path of the new top module file
        top_mod_path = os.path.join(self.config["project_structure"]["src"][0], new_top_mod)        
        #change the top
        self._log("info", f"HDL TOP module set to {new_top_mod} in local config")
        self.config["hdl_project_hierarchy"]["top"] = {new_top_mod : top_mod_path} 
        #Update the config file
        self.update_config()
        self._log("info", f"HDL TOP module set to {new_top_mod} in config file")

    def set_testbench(self, new_tb):
        """Set the testbench file for the project.\n
        testbenches must be terminated with a "_tb" suffix.
        There can only be 1 testbench active at any time.
        Args:
            new_tb: Name of file to set as testbench
        """
        self._log("info", f"Attempting to set new testbench in local config")

        #check that the structure is A-ok
        if "hdl_project_hierarchy" not in self.config: 
            self.config["hdl_project_hierarchy"] = {}
            self._log("warning", "hdl_project_hierarchy didn't exist. Remaking it.")
        #initialize src if it doesnt exist
        if "top" not in self.config["hdl_project_hierarchy"]:
            self.config["hdl_project_hierarchy"]["testbench"] = {}
            self._log("warning", "testbench didnt exist in hdl_project_hierarchy. Remaking it.")
        #Check that the new top module exists
        src_dir = self.find_hdl_sources()
        if new_tb not in src_dir:
            self._log("error", f"New testbench file {new_tb} is not found in src directory. Add it first. Exit.")
            return None     
        #get path of the new testbench file
        tb_path = os.path.join(self.config["project_structure"]["src"][0], new_tb)        
        #change the testbench
        self._log("info", f"HDL TOP module set to {new_tb} in local config")
        self.config["hdl_project_hierarchy"]["testbench"] = {new_tb : tb_path} 
        #Update the config file
        self.update_config()
        self._log("info", f"Testbench set to {new_tb} in config file")

    def update_config(self):
        """Write current configuration to config file."""
        try:
            self._log("info", f"Updating configuration file")
            with open(self.config_path, "w") as config_file:
                yaml.safe_dump(self.config, config_file)
        except Exception as e:
            self._log("error", f"Failed to update the configuration file: {e}")
    
    def get_hierarchy(self) -> bool|dict:
        """Get the current HDL project hierarchy structure.
        
        Returns:
            (bool) Project hierarchy as dictionary or True if not found
        """
        #check that the project hierarchy structure is A-ok
        if "hdl_project_hierarchy" not in self.config: 
            self._log("error", "Can't get project hierarchy. It doesn't exist. Is the project and hierarchy_manager initialized?")
            return True
        self._log("info", f"Getting hdl_project_hierarchy")
        return self.config["hdl_project_hierarchy"]
    
    def rebuild_hierarchy(self) -> bool:
        """Rebuild the project hierarchy from scratch by re-scanning the src directory.
        
        This method bypasses the initialized_once flag and completely rebuilds 
        the hdl_project_hierarchy section of the configuration file based on 
        current files in the src directory. Uses actual project path instead
        of potentially incorrect configuration paths.
        
        Returns:
            (bool) True if successful, False if failed
        """
        self._log("info", "Starting project hierarchy rebuild")
        
        try:
            # Use actual project path instead of configuration path
            actual_src_path = os.path.join(self.project_path, "src")
            
            if not os.path.exists(actual_src_path):
                self._log("error", f"Source directory does not exist at {actual_src_path}")
                return False
            
            # Find HDL sources in the actual src directory
            self._log("info", f"Scanning for HDL sources in {actual_src_path}")
            hdl_sources = []
            try:
                all_files = os.listdir(actual_src_path)
                hdl_sources = [f for f in all_files if f.endswith(('.vhd', '.vhdl'))]
                self._log("info", f"Found HDL files: {hdl_sources}")
            except Exception as e:
                self._log("error", f"Failed to scan src directory: {e}")
                return False
            
            if not hdl_sources:
                self._log("warning", "No HDL sources found in src directory")
                # Still proceed to create empty hierarchy
                hdl_sources = []
            
            self._log("info", f"Found {len(hdl_sources)} HDL files for hierarchy rebuild")
            
            # Sort sources into categories using actual paths
            self._log("info", f"Sorting HDL sources {hdl_sources}")
            sorted_sources = {
                "top": {},
                "testbench": {},
                "src": {}
            }
            
            for file in hdl_sources:
                lower_file = file.lower()
                # Use actual project path for file paths
                file_path = os.path.join(actual_src_path, file)
                
                if lower_file.endswith("_tb.vhd") or lower_file.endswith("_tb.vhdl"):
                    sorted_sources["testbench"][file] = file_path
                elif lower_file.endswith("_top.vhd") or lower_file.endswith("_top.vhdl"):
                    sorted_sources["top"][file] = file_path
                elif lower_file.endswith(".vhd") or lower_file.endswith(".vhdl"):
                    sorted_sources["src"][file] = file_path
                else:
                    self._log("warning", f"Unrecognized HDL file format: {file}")
            
            self._log("info", f"Sorted HDL files: {sorted_sources}")
            
            # Backup existing hierarchy if it exists
            old_hierarchy = self.config.get("hdl_project_hierarchy", {})
            if old_hierarchy:
                self._log("info", "Backing up existing hierarchy before rebuild")
            
            # Replace hierarchy in configuration
            self.config["hdl_project_hierarchy"] = sorted_sources
            
            # Update project structure paths to reflect actual location
            if "project_structure" in self.config and "src" in self.config["project_structure"]:
                self.config["project_structure"]["src"][0] = actual_src_path
                self._log("info", f"Updated project structure src path to {actual_src_path}")
            
            # Update log paths to use correct project path
            if "logs" in self.config:
                actual_logs_path = os.path.join(self.project_path, "logs")
                
                # Update each log path
                for log_category, log_files in self.config["logs"].items():
                    if isinstance(log_files, dict):
                        for log_name, log_path in log_files.items():
                            # Extract just the filename and rebuild path with correct location
                            log_filename = os.path.basename(log_path)
                            new_log_path = os.path.join(actual_logs_path, log_filename)
                            self.config["logs"][log_category][log_name] = new_log_path
                            self._log("info", f"Updated log path for {log_category}/{log_name} to {new_log_path}")
                
                # Ensure logs directory exists
                if not os.path.exists(actual_logs_path):
                    os.makedirs(actual_logs_path, exist_ok=True)
                    self._log("info", f"Created logs directory at {actual_logs_path}")
            
            # Update project path in configuration
            if "project_path" in self.config:
                self.config["project_path"] = self.project_path
                self._log("info", f"Updated project path to {self.project_path}")
            
            # Write to configuration file
            try:
                with open(self.config_path, "w") as config_file:
                    yaml.safe_dump(self.config, config_file)
                self._log("info", "Successfully updated configuration file with rebuilt hierarchy")
            except Exception as e:
                # Restore backup on write failure
                if old_hierarchy:
                    self.config["hdl_project_hierarchy"] = old_hierarchy
                    self._log("error", f"Failed to write configuration, restored backup: {e}")
                else:
                    self._log("error", f"Failed to write configuration: {e}")
                return False
            
            # Reset initialization flag so init_sources can be called again if needed
            self.initialized_once = False
            
            self._log("info", "Project hierarchy rebuild completed successfully")
            return True
            
        except Exception as e:
            self._log("error", f"Error during hierarchy rebuild: {e}")
            return False

    def parse_entity_name_from_vhdl(self, file_path):
        """Parse entity name from a VHDL file.
        
        Args:
            file_path: Path to the VHDL file
            
        Returns:
            str: Entity name or None if not found
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                # Look for entity declaration
                import re
                # Pattern to match: entity <name> is (case insensitive search but preserve original case)
                pattern = r'\bentity\s+(\w+)\s+is'
                match = re.search(pattern, content, re.IGNORECASE)
                if match:
                    return match.group(1)
        except Exception as e:
            self._log("warning", f"Could not parse entity from {file_path}: {e}")
        return None
    
    def get_available_entities(self):
        """Get list of available VHDL entities that can be synthesized.
        
        Returns:
            list: List of entity names found in source and top files
        """
        entities = []
        try:
            hierarchy = self.get_hierarchy()
            if hierarchy is True or not isinstance(hierarchy, dict):
                self._log("warning", "No project hierarchy found for entity scan")
                return entities
                
            # Check both 'src' and 'top' sections for source files
            for section in ["src", "top"]:
                if section in hierarchy and isinstance(hierarchy[section], dict):
                    for file_name, file_path in hierarchy[section].items():
                        if file_name.endswith('.vhd') or file_name.endswith('.vhdl'):
                            entity_name = self.parse_entity_name_from_vhdl(file_path)
                            if entity_name and entity_name not in entities:
                                entities.append(entity_name)
                                self._log("info", f"Found entity '{entity_name}' in {file_name}")
                            elif not entity_name:
                                # Fallback to filename without extension
                                fallback_name = os.path.splitext(file_name)[0]
                                if fallback_name not in entities:
                                    entities.append(fallback_name)
                                    self._log("info", f"Using filename as entity '{fallback_name}' for {file_name}")
        except Exception as e:
            self._log("error", f"Error scanning for VHDL entities: {e}")
            
        return sorted(entities)
    
    def get_available_testbenches(self):
        """Get list of available testbench entities that can be simulated.
        
        Returns:
            list: List of testbench entity names found in testbench files
        """
        testbenches = []
        try:
            hierarchy = self.get_hierarchy()
            if hierarchy is True or not isinstance(hierarchy, dict):
                self._log("warning", "No project hierarchy found for testbench scan")
                return testbenches
                
            # Check 'testbench' section for testbench files
            if "testbench" in hierarchy and isinstance(hierarchy["testbench"], dict):
                for file_name, file_path in hierarchy["testbench"].items():
                    if file_name.endswith('.vhd') or file_name.endswith('.vhdl'):
                        entity_name = self.parse_entity_name_from_vhdl(file_path)
                        if entity_name and entity_name not in testbenches:
                            testbenches.append(entity_name)
                            self._log("info", f"Found testbench entity '{entity_name}' in {file_name}")
                        elif not entity_name:
                            # Fallback to filename without extension
                            fallback_name = os.path.splitext(file_name)[0]
                            if fallback_name not in testbenches:
                                testbenches.append(fallback_name)
                                self._log("info", f"Using filename as testbench '{fallback_name}' for {file_name}")
            
            # Also check 'top' section for testbench files (those ending with _tb)
            if "top" in hierarchy and isinstance(hierarchy["top"], dict):
                for file_name, file_path in hierarchy["top"].items():
                    if (file_name.endswith('.vhd') or file_name.endswith('.vhdl')) and '_tb' in file_name.lower():
                        entity_name = self.parse_entity_name_from_vhdl(file_path)
                        if entity_name and entity_name not in testbenches:
                            testbenches.append(entity_name)
                            self._log("info", f"Found testbench entity '{entity_name}' in top section: {file_name}")
                        elif not entity_name:
                            fallback_name = os.path.splitext(file_name)[0]
                            if fallback_name not in testbenches:
                                testbenches.append(fallback_name)
                                self._log("info", f"Using filename as testbench '{fallback_name}' for {file_name}")
        except Exception as e:
            self._log("error", f"Error scanning for testbench entities: {e}")
            
        return sorted(testbenches)
    
    def get_source_files_info(self):
        """Get detailed information about source files in the project hierarchy.
        
        Returns:
            dict: Dictionary with file names and their full paths organized by category
        """
        files_info = {
            "src": {},
            "top": {},
            "testbench": {}
        }
        
        try:
            hierarchy = self.get_hierarchy()
            if hierarchy is True or not isinstance(hierarchy, dict):
                self._log("warning", "No project hierarchy found for file info scan")
                return files_info
                
            # Collect files from each section
            for section in ["src", "top", "testbench"]:
                if section in hierarchy and isinstance(hierarchy[section], dict):
                    for file_name, file_path in hierarchy[section].items():
                        files_info[section][file_name] = file_path
                        
            self._log("info", f"Retrieved source file info: {len(files_info['src'])} src, {len(files_info['top'])} top, {len(files_info['testbench'])} testbench files")
            
        except Exception as e:
            self._log("error", f"Error getting source file info: {e}")
            
        return files_info
    
    def get_project_statistics(self):
        """Get project statistics including file counts and status.
        
        Returns:
            dict: Dictionary with project statistics
        """
        stats = {
            "total_files": 0,
            "missing_files": 0,
            "src_files": 0,
            "top_files": 0,
            "testbench_files": 0,
            "available_entities": 0,
            "available_testbenches": 0
        }
        
        try:
            hierarchy = self.get_hierarchy()
            if hierarchy is True or not isinstance(hierarchy, dict):
                return stats
                
            # Count files and check existence
            for category in ["src", "testbench", "top"]:
                if category in hierarchy and isinstance(hierarchy[category], dict):
                    category_count = len(hierarchy[category])
                    stats[f"{category}_files"] = category_count
                    stats["total_files"] += category_count
                    
                    # Check for missing files
                    for file_name, file_path in hierarchy[category].items():
                        if not os.path.exists(file_path):
                            stats["missing_files"] += 1
            
            # Count entities and testbenches
            stats["available_entities"] = len(self.get_available_entities())
            stats["available_testbenches"] = len(self.get_available_testbenches())
            
            self._log("info", f"Project statistics: {stats}")
            
        except Exception as e:
            self._log("error", f"Error calculating project statistics: {e}")
            
        return stats

    def add_file(self, file_path, file_type, copy_to_project=True):
        """Add a file to the project hierarchy.
        
        Args:
            file_path: Path to the file to add
            file_type: Type of file ('src', 'testbench', 'top')
            copy_to_project: Whether to copy the file to the project directory (default: True)
        """
        self._log("info", f"Adding file {file_path} as {file_type}, copy_to_project={copy_to_project}")
        
        # Validate that a proper project configuration exists
        if not self.config or "project_structure" not in self.config:
            self._log("error", "No valid project configuration found. Please create a project first.")
            raise Exception("No valid project configuration found. Please create a project first using 'Create New Project'.")
        
        # Validate file type
        if file_type not in ['src', 'testbench', 'top']:
            self._log("error", f"Invalid file type: {file_type}. Must be 'src', 'testbench', or 'top'")
            raise ValueError(f"Invalid file type: {file_type}")
        
        # Check if file exists
        if not os.path.exists(file_path):
            self._log("error", f"File does not exist: {file_path}")
            raise FileNotFoundError(f"File does not exist: {file_path}")
        
        # Get file name
        file_name = os.path.basename(file_path)
        
        # Determine destination directory based on file type with proper validation
        if file_type == 'src' or file_type == 'top':
            dest_dir = self.config.get("project_structure", {}).get("src", [])
            if dest_dir and isinstance(dest_dir, list) and len(dest_dir) > 0:
                dest_dir = dest_dir[0]
            else:
                self._log("error", "Project source directory not properly configured")
                raise Exception("Project source directory not properly configured. Please create a project first.")
        elif file_type == 'testbench':
            dest_dir = self.config.get("project_structure", {}).get("testbench", [])
            if dest_dir and isinstance(dest_dir, list) and len(dest_dir) > 0:
                dest_dir = dest_dir[0]
            else:
                self._log("error", "Project testbench directory not properly configured")
                raise Exception("Project testbench directory not properly configured. Please create a project first.")
        
        # Validate that destination directory is not just current directory
        if dest_dir == "." or dest_dir == os.getcwd():
            self._log("error", "Invalid project directory configuration - would create files in CLI directory")
            raise Exception("Invalid project configuration. Please create a proper project first using 'Create New Project'.")
        
        # Ensure destination directory exists
        if not os.path.exists(dest_dir):
            os.makedirs(dest_dir, exist_ok=True)
            self._log("info", f"Created directory: {dest_dir}")
        
        # Copy file to project directory if requested
        if copy_to_project:
            dest_file_path = os.path.join(dest_dir, file_name)
            
            # Check if file already exists at destination
            if os.path.exists(dest_file_path):
                self._log("warning", f"File already exists at destination: {dest_file_path}")
                # Ask if we should overwrite (for CLI usage, we'll assume yes for now)
                # You can modify this behavior as needed
                
            try:
                shutil.copy2(file_path, dest_file_path)
                self._log("info", f"Copied file from {file_path} to {dest_file_path}")
                file_path_to_store = dest_file_path  # Store the new path in config
            except Exception as e:
                self._log("error", f"Failed to copy file: {e}")
                raise Exception(f"Failed to copy file: {e}")
        else:
            # If not copying, use the original file path
            file_path_to_store = file_path
        
        # Ensure hierarchy structure exists
        if "hdl_project_hierarchy" not in self.config:
            self.config["hdl_project_hierarchy"] = {}
            
        if file_type not in self.config["hdl_project_hierarchy"]:
            self.config["hdl_project_hierarchy"][file_type] = {}
        
        # Add the file to configuration
        self.config["hdl_project_hierarchy"][file_type][file_name] = file_path_to_store
        
        # Update configuration file
        self.update_config()
        
        self._log("info", f"Successfully added {file_name} to {file_type} section")
        return dest_file_path if copy_to_project else file_path_to_store

    def detect_manual_files(self):
        """Detect and optionally add manually placed files in project directories.
        
        Returns:
            dict: Dictionary of detected files organized by category
        """
        self._log("info", "Detecting manually added files in project directories")
        
        detected_files = {
            "src": {},
            "testbench": {},
            "top": {}
        }
        
        try:
            # Get current hierarchy to compare against
            current_hierarchy = self.get_hierarchy()
            if current_hierarchy is True:
                current_hierarchy = {}
            
            # Define directory mappings
            directories_to_check = {}
            
            # Get src directory
            src_dirs = self.config.get("project_structure", {}).get("src", [])
            if src_dirs:
                src_dir = src_dirs[0] if isinstance(src_dirs, list) else src_dirs
                if os.path.exists(src_dir):
                    directories_to_check["src"] = src_dir
                    directories_to_check["top"] = src_dir  # Top files are also in src directory
            
            # Get testbench directory
            tb_dirs = self.config.get("project_structure", {}).get("testbench", [])
            if tb_dirs:
                tb_dir = tb_dirs[0] if isinstance(tb_dirs, list) else tb_dirs
                if os.path.exists(tb_dir):
                    directories_to_check["testbench"] = tb_dir
            
            # Scan each directory for VHDL files
            for category, directory in directories_to_check.items():
                self._log("info", f"Scanning {directory} for {category} files")
                
                try:
                    for file_name in os.listdir(directory):
                        if file_name.endswith(('.vhd', '.vhdl')):
                            file_path = os.path.join(directory, file_name)
                            
                            # Check if file is already in hierarchy
                            already_tracked = False
                            if isinstance(current_hierarchy, dict):
                                for tracked_category in ["src", "testbench", "top"]:
                                    if (tracked_category in current_hierarchy and 
                                        isinstance(current_hierarchy[tracked_category], dict) and
                                        file_name in current_hierarchy[tracked_category]):
                                        already_tracked = True
                                        break
                            
                            if not already_tracked:
                                # Categorize the file based on naming convention
                                lower_file = file_name.lower()
                                if category == "testbench" or lower_file.endswith("_tb.vhd") or lower_file.endswith("_tb.vhdl"):
                                    detected_files["testbench"][file_name] = file_path
                                elif lower_file.endswith("_top.vhd") or lower_file.endswith("_top.vhdl"):
                                    detected_files["top"][file_name] = file_path
                                else:
                                    detected_files["src"][file_name] = file_path
                                
                                self._log("info", f"Detected untracked file: {file_name} in {category}")
                                
                except Exception as e:
                    self._log("error", f"Error scanning directory {directory}: {e}")
            
            # Log summary
            total_detected = sum(len(files) for files in detected_files.values())
            self._log("info", f"Detection complete: {total_detected} untracked files found")
            
        except Exception as e:
            self._log("error", f"Error during manual file detection: {e}")
        
        return detected_files

    def add_detected_files(self, detected_files, categories_to_add=None):
        """Add detected files to the project hierarchy.
        
        Args:
            detected_files: Dictionary from detect_manual_files()
            categories_to_add: List of categories to add (default: all)
        
        Returns:
            dict: Summary of added files
        """
        if categories_to_add is None:
            categories_to_add = ["src", "testbench", "top"]
        
        added_summary = {
            "src": 0,
            "testbench": 0,
            "top": 0,
            "total": 0
        }
        
        try:
            # Ensure hierarchy structure exists
            if "hdl_project_hierarchy" not in self.config:
                self.config["hdl_project_hierarchy"] = {}
            
            for category in categories_to_add:
                if category in detected_files and detected_files[category]:
                    if category not in self.config["hdl_project_hierarchy"]:
                        self.config["hdl_project_hierarchy"][category] = {}
                    
                    for file_name, file_path in detected_files[category].items():
                        self.config["hdl_project_hierarchy"][category][file_name] = file_path
                        added_summary[category] += 1
                        added_summary["total"] += 1
                        self._log("info", f"Added detected file {file_name} to {category}")
            
            # Update configuration file
            if added_summary["total"] > 0:
                self.update_config()
                self._log("info", f"Added {added_summary['total']} detected files to project hierarchy")
            
        except Exception as e:
            self._log("error", f"Error adding detected files: {e}")
            raise Exception(f"Error adding detected files: {e}")
        
        return added_summary

    def remove_file_from_hierarchy(self, file_name, file_category=None):
        """Remove a file from the project hierarchy without deleting the actual file.
        
        Args:
            file_name: Name of the file to remove (e.g., "counter.vhd")
            file_category: Specific category to search in ('src', 'testbench', 'top'), or None to search all
        
        Returns:
            dict: Summary of removal operation
        """
        self._log("info", f"Removing file {file_name} from project hierarchy, category={file_category}")
        
        # Validate that a proper project configuration exists
        if not self.config or "hdl_project_hierarchy" not in self.config:
            self._log("error", "No valid project hierarchy found")
            raise Exception("No valid project hierarchy found. Please create a project first.")
        
        removal_summary = {
            "removed": False,
            "category": None,
            "file_path": None,
            "message": ""
        }
        
        hierarchy = self.config["hdl_project_hierarchy"]
        
        # If specific category provided, search only in that category
        if file_category:
            categories_to_search = [file_category] if file_category in hierarchy else []
        else:
            # Search in all categories
            categories_to_search = ["src", "testbench", "top"]
        
        try:
            for category in categories_to_search:
                if category in hierarchy and isinstance(hierarchy[category], dict):
                    if file_name in hierarchy[category]:
                        # Found the file, remove it
                        file_path = hierarchy[category][file_name]
                        del hierarchy[category][file_name]
                        
                        # Update configuration file
                        self.update_config()
                        
                        removal_summary.update({
                            "removed": True,
                            "category": category,
                            "file_path": file_path,
                            "message": f"Successfully removed {file_name} from {category} category"
                        })
                        
                        self._log("info", f"Successfully removed {file_name} from {category} category")
                        return removal_summary
            
            # File not found in any category
            removal_summary["message"] = f"File {file_name} not found in project hierarchy"
            self._log("warning", f"File {file_name} not found in project hierarchy")
            
        except Exception as e:
            self._log("error", f"Error removing file from hierarchy: {e}")
            removal_summary["message"] = f"Error removing file: {e}"
            raise Exception(f"Error removing file from hierarchy: {e}")
        
        return removal_summary

    def remove_multiple_files_from_hierarchy(self, file_names, file_category=None):
        """Remove multiple files from the project hierarchy.
        
        Args:
            file_names: List of file names to remove
            file_category: Specific category to search in, or None to search all
        
        Returns:
            dict: Summary of removal operations
        """
        self._log("info", f"Removing multiple files from hierarchy: {file_names}")
        
        summary = {
            "total_requested": len(file_names),
            "successfully_removed": 0,
            "not_found": 0,
            "removed_files": [],
            "not_found_files": []
        }
        
        for file_name in file_names:
            try:
                result = self.remove_file_from_hierarchy(file_name, file_category)
                if result["removed"]:
                    summary["successfully_removed"] += 1
                    summary["removed_files"].append({
                        "name": file_name,
                        "category": result["category"],
                        "path": result["file_path"]
                    })
                else:
                    summary["not_found"] += 1
                    summary["not_found_files"].append(file_name)
            except Exception as e:
                summary["not_found"] += 1
                summary["not_found_files"].append(file_name)
                self._log("error", f"Failed to remove {file_name}: {e}")
        
        self._log("info", f"Batch removal complete: {summary['successfully_removed']} removed, {summary['not_found']} not found")
        return summary

if __name__ == "__main__":
    hierarchy = HierarchyManager(None)
    #test = hierarchy.find_hdl_sources()
    #hierarchy.sort_hdl_sources(test)
    hierarchy.init_sources()
    #hierarchy.remove_source("test.vhd", do_update=True)
    #hierarchy.set_testbench("anothertb_tb.vhd")
   # hierarchy.scan_hdl_sources() 