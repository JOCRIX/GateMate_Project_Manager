""""
Creates the folder structure for VHDL projects
"""

import os
import yaml
import logging
import shutil
from time import sleep
# Setup log file for project manager
# Removed global logging setup to prevent creating log files in project root during import

class CreateStructure:
    """Creates and manages folder structure for VHDL projects."""
    def __init__(self, project_name : str, project_path: str = None):
        """Initialize the project structure creator.
        
        Args:
            project_name: Name of the VHDL project
            project_path: Path where the project should be created. If None, uses current directory.
        """
        self.project_name = project_name
        
        if project_path is None:
            # No path specified, use script directory
            self.project_path = os.path.dirname(__file__)
        elif project_path == ".":
            # Current directory specified, create a subdirectory with project name
            current_dir = os.getcwd()
            self.project_path = os.path.join(current_dir, project_name)
            # Create the project directory if it doesn't exist
            if not os.path.exists(self.project_path):
                os.makedirs(self.project_path, exist_ok=True)
        else:
            # Specific path provided, use as absolute path and create project subdirectory
            base_path = os.path.abspath(project_path)
            self.project_path = os.path.join(base_path, project_name)
            # Create the project directory if it doesn't exist
            if not os.path.exists(self.project_path):
                os.makedirs(self.project_path, exist_ok=True)
        
        # Initialize logging - will be set up when first logging call is made
        self.log_file = None
        self.logging_configured = False
        
        self._log("info", "### CreateStructure initialized ###")

    def _log(self, level, message):
        """Internal logging method that ensures logging is configured."""
        if not self.logging_configured:
            self._setup_logging()
            self.logging_configured = True
        
        if self.log_file:
            logger = logging.getLogger('CreateStructure')
            getattr(logger, level)(message)
    
    def _setup_logging(self):
        """Set up logging using the project's logs directory."""
        try:
            # Use logs directory if it exists, otherwise create it
            logs_dir = os.path.join(self.project_path, "logs")
            if not os.path.exists(logs_dir):
                os.makedirs(logs_dir, exist_ok=True)
            
            self.log_file = os.path.join(logs_dir, "project_manager.log")
            
            # Configure logging only if we have a valid log file path
            if self.log_file:
                # Get or create a logger specific to this class
                logger = logging.getLogger('CreateStructure')
                logger.setLevel(logging.DEBUG)
                
                # Remove any existing handlers to avoid duplicates
                for handler in logger.handlers[:]:
                    logger.removeHandler(handler)
                
                # Add file handler
                file_handler = logging.FileHandler(self.log_file)
                file_handler.setLevel(logging.DEBUG)
                formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
                file_handler.setFormatter(formatter)
                logger.addHandler(file_handler)
                
        except Exception as e:
            # If logging setup fails, continue without file logging
            self.log_file = None
            print(f"Warning: Could not set up logging in CreateStructure: {e}")

    def exterminatus(self, order : str):
        """
        **Dangerous**: Deletes all directories in the project folder, destroying their contents.

        **Args**:
            order (str): Confirmation string must be **"I hereby sign the death warrant of an entire world, and consign a million souls to oblivion!"** to proceed.
        """
        if order != "I hereby sign the death warrant of an entire world, and consign a million souls to oblivion!":
            self._log("error", "Exterminatus aborted: Incorrect confirmation order, requires inquisitorial approval!")
            print("Exterminatus aborted: Incorrect confirmation order, requires inquisitorial approval!")
            return False
        # Ensure logging is shut down to release file locks
        self._log("warning", "Shutting down logging to release file locks before deletion")
        logging.shutdown()
        try:
            #Get all entries in the project directory
            entries = os.listdir(self.project_path)
            #filter out the directories
            directories = [entry for entry in entries if os.path.isdir(os.path.join(self.project_path, entry))]
            for dir in directories:
                dir_path = os.path.join(self.project_path, dir)
                try:
                    shutil.rmtree(dir_path, ignore_errors=False)
                    print(f"Deleted: {dir_path}")
                except Exception as e:
                    print(f"Failed to delete {dir_path}: {e}")
            
        except Exception as e:
            print("Failed to list directories in project folder")
            return 
        print(f"Directories in {self.project_path} : {entries} have been deleted")
        print(f"The Emperor Protects!")

    def finalize(self):
        """Finalize the project structure, move config file and log file to destination folders."""
        self._log("info", "Finalizing project structure setup")
        
        #Get current config path
        config_path = os.path.join(self.project_path, f"{self.project_name}_project_config.yml")

        #verify that it exists
        if not os.path.exists(config_path):
            self._log("error", f"Project configuration file not found at {config_path}. Exit")
            return
        #Load the configuration file
        try:
            with open(config_path, "r") as config_file:
                self._log("info", f"Loaded the project configuration file at {config_path}")
                config = yaml.safe_load(config_file)
        except Exception as e:
            self._log("error", f"Failed to open project config file at {config_path}. {e}")
            return

        #Move the initial setup files to their destinations
        new_paths = self._move_files(config_path, config)

        #Re-start logging at new log file path
        self._restart_logging(new_paths["log"])
        
        #Adding log project_manager.log to configuration file.
        self._append_log_to_config(new_paths["config"], config)

    def _move_files(self, config_path, config) -> dict:
        """Move setup files to their destinations.
        
        Args:
            config_path: Path to the project configuration file
            config: Dictionary containing project configuration
            
        Returns:
            Dictionary with paths to relocated log and config files
        """
        new_paths = {
            "log": None,
            "config": None
        }
        
        # Log files that will be moved
        file_moves = []
        for file_key, paths in config["setup_files_initial"].items():
            source = paths[0]
            dest_dir = paths[1]
            dest_path = os.path.join(dest_dir, os.path.basename(source))
            file_moves.append(f"{file_key}: {source} -> {dest_path}")
        
        self._log("info", f"Files to be moved: {file_moves}")
        
        #Move all the initial setup files
        try:
            for file_key, paths in config["setup_files_initial"].items(): #items() returns key-value pairs of the dictionary
                try: #Get the source and destination paths
                    source = paths[0]
                    dest_dir = paths[1]
                    
                    #construct the destination path
                    dest_path = os.path.join(dest_dir, os.path.basename(source)) #basename() returns the final part of a filepath, i.e. filename itself
                    
                    #Moving file
                    if os.path.exists(source): #Check that the source exists first
                        # Special handling for log file - must use copy instead of rename
                        if source == self.log_file: #did we find the log file
                            self._log("warning", f"Shutting down logging to release log file lock and moving the log file {source}")
                            # We need to shutdown logging to release the file lock
                            logging.shutdown()
                            
                            try:
                                # Try to move file using shutil instead of os.rename
                                shutil.copy2(source, dest_path)
                                # After successful copy, try to remove original
                                if os.path.exists(dest_path):
                                    try:
                                        os.remove(source)
                                    except:
                                        continue
                                new_paths["log"] = os.path.join(dest_dir, "project_manager.log") #save path of new destination for log file
                            except Exception as e:
                                continue
                        else:
                            # For config file and others, use rename
                            # First check if destination exists
                            if os.path.exists(dest_path):
                                os.remove(dest_path)  # Remove existing file if it exists
                            os.rename(source, dest_path)
                            self._log("info", f"Moved {file_key} from {source} to {dest_path}")
                            
                            if source == config_path:
                                new_paths["config"] = dest_path #save path of new destination for config file
                    else:
                        self._log("warning", f"Source file {source} for {file_key} does not exist. Skipping.")
                except Exception as e:
                    self._log("error", f"Failed to move file {file_key}: {e}")
                    continue
        except Exception as e:
            self._log("error", f"Failed to process setup_files_initial: {e}")
        
        return new_paths


    def _append_log_to_config(self, new_config_path, config):
        """Add log file entry to project configuration.
        
        Args:
            new_config_path: Path to the relocated configuration file
            config: Dictionary containing project configuration
        """

        # Get the correct log file path
        log_path = os.path.join(config["setup_files_initial"]["log_file"][1], "project_manager.log")
            
        # Make sure logs exists at top level with project_manager key
        if "logs" not in config:
            config["logs"] = {}
            
        if "project_manager" not in config.get("logs", {}):
            config["logs"]["project_manager"] = {"project_manager.log": log_path}
        
        # Ensure project_structure logs stays as a list of directory paths
        if "logs" in config["project_structure"]:
            if isinstance(config["project_structure"]["logs"], dict) and "project_manager" in config["project_structure"]["logs"]:
                # Remove the nested structure if it was accidentally added to project_structure
                logs_paths = config["project_structure"]["logs"].get("paths", [])
                if not logs_paths and "project_manager" in config["project_structure"]["logs"]:
                    # Get the directory path
                    logs_dir = os.path.dirname(config["project_structure"]["logs"]["project_manager"]["project_manager.log"])
                    logs_paths = [logs_dir]
                # Reset to simple list
                config["project_structure"]["logs"] = logs_paths
        
        try:
            with open(new_config_path, "w") as config_file:
                self._log("info", f"Updated the project config at {new_config_path}")
                yaml.safe_dump(config, config_file)
        except Exception as e:
            self._log("error", f"Failed to open project config file at {new_config_path}. {e}")

    def _restart_logging(self, new_log_path : str):
        """Restart logging with the new log file path.
        
        Args:
            new_log_path: Path to the relocated log file
        """
        #Check that the new log file path is specified
        if not new_log_path:
            self._log("error", "New log file path is None. Can't restart logging.")
            return
        
        # Update our log file path and reconfigure
        self.log_file = new_log_path
        self.logging_configured = False  # Force reconfiguration
        
        self._log("info", f"Logging restarted at {new_log_path}")



    def create_project_config(self):
        """Create the project configuration file with default directory structure."""
        config = {
            "project_name": self.project_name,
            "project_path": self.project_path,
            "setup_files_initial" : {
                "config_file" :[],
                "log_file" : []
            },
            "project_structure" : { 
                                   "env" : [os.path.join(self.project_path, "env")],
                                   "logs": [os.path.join(self.project_path, "logs")],
                                   "build" :[os.path.join(self.project_path, "build")],
                                   "constraints" :[os.path.join(self.project_path, "constraints")],
                                   "config" :[os.path.join(self.project_path, "config")],
                                   "sim" : {
                                            "behavioral" : [os.path.join(self.project_path, "sim", "behavioral")],
                                            "post-synthesis" : [os.path.join(self.project_path, "sim", "post-synthesis")],
                                            "post-implementation" : [os.path.join(self.project_path, "sim", "post-implementation")]},
                                   "src" : [os.path.join(self.project_path, "src")],
                                   "testbench" : [os.path.join(self.project_path, "testbench")],
                                   "impl" : {
                                            "bitstream" : [os.path.join(self.project_path, "bitstream")],
                                            "logs" : [os.path.join(self.project_path, "logs")],
                                            "timing" : [os.path.join(self.project_path, "timing")],
                                            "netlist" : [os.path.join(self.project_path, "netlist")]},
                                   "synth" :[os.path.join(self.project_path, "synth")]                  
            },
        }

        config_path = os.path.join(self.project_path, f"{self.project_name}_project_config.yml")
        
        #append config_file and log_file paths to config
        config["setup_files_initial"]["config_file"] = [config_path, os.path.join(self.project_path, "config")]
        config["setup_files_initial"]["log_file"] = [self.log_file, os.path.join(self.project_path, "logs")]

        # Add initial logs structure outside of project_structure
        log_path = os.path.join(self.project_path, "logs", "project_manager.log")
        config["logs"] = {
            "project_manager": {
                "project_manager.log": log_path
            }
        }

        #Check if config file exists
        self._log("info", "Checking if project configuration file exists")

        if not os.path.exists(config_path):
            self._log("info", f"Project configuration file does not exist at {config_path}. Creating configuration file")
        else :
            self._log("info", f"Project configuration file already exists. Overwriting configuration file at {config_path}")
 
        #Create new project configuration file
        try :
            with open(config_path, "w") as f: #a file automatically closes() after a with open()... no need to close manually
                self._log("info", f"Project configuration file created at {config_path}")
                yaml.dump(config, f)
        except Exception as e:
                self._log("error", f"Error occured creating configuration file: {e}")
        
        #Project configuration file complete
        self._log("info", "Adding directory paths to configuration file")
        print(config)
        print(config_path)

    def create_dir_struct(self) :
        """Create the directory structure based on project configuration."""
        #Get the config_path
        config_path = os.path.join(self.project_path, f"{self.project_name}_project_config.yml")

        #Verify the config file exists
        if not os.path.exists(config_path):
            self._log("error", f"No configuration file found at {config_path}. Exit")
            return
        #Load all the contents of the configuration file.
        self._log("info", f"Attempting to load contents of configuration file at {config_path}")
        try :
            with open(config_path, "r") as file:
                config_file = yaml.safe_load(file)
                self._log("info", f"Successfully loaded configuration file at {config_path}")
        except Exception as e:
                self._log("error", f"Failed to load configuration file at {config_path}. {e}")

        #Create folder structure from configuration file
        self._log("info", f"Attempting to create project folder structure at {self.project_path}")

        def create_directories_from_config(structure, base_path=""):
            """Recursively create directories from configuration structure."""
            for key, value in structure.items():
                if isinstance(value, list):
                    # List of directory paths - create each one
                    for dir_path in value:
                        if not os.path.exists(dir_path):
                            try:
                                self._log("info", f"Creating directory: {dir_path}")
                                os.makedirs(dir_path, exist_ok=True)
                            except Exception as e:
                                self._log("error", f"Failed to create directory {dir_path}. {e}")
                        else:
                            self._log("info", f"Directory already exists: {dir_path}")
                elif isinstance(value, dict):
                    # Nested structure - recurse
                    create_directories_from_config(value, base_path)
        
        # Create all directories from the project structure
        create_directories_from_config(config_file["project_structure"])
        
        self._log("info", f"Project structure specified in project {config_path} created successfully.")
        
        # Create default constraint file for the project
        self._create_default_constraint_file()

    def _create_default_constraint_file(self):
        """Create a default constraint file for the project using PnRCommands."""
        try:
            self._log("info", "Creating default constraint file for the project")
            
            # Import PnRCommands to create the constraint file
            from .pnr_commands import PnRCommands
            
            # Create PnRCommands instance to generate constraint file
            pnr = PnRCommands()
            
            # Create the default constraint file
            success = pnr.create_default_constraint_file()
            
            if success:
                self._log("info", f"Successfully created default constraint file: {pnr.get_default_constraint_file_path()}")
            else:
                self._log("warning", "Failed to create default constraint file")
                
        except Exception as e:
            self._log("error", f"Error creating default constraint file: {e}")
            # Don't fail the entire project creation if constraint file creation fails


if __name__ == "__main__":
    create_structure = CreateStructure("test")
    create_structure.create_project_config()
    create_structure.create_dir_struct()
    create_structure.finalize()
    #create_structure.exterminatus("The Emperor Protects!")






