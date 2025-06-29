import os
import yaml
import logging
import subprocess
from .hierarchy_manager import HierarchyManager


class ToolChainManager(HierarchyManager):
    """Controls what the GateMate toolchain is doing"""
    
    #GateMate tool chain definitions and binaries
    __tool_chain = {"ghdl" : "ghdl.exe" ,  #VHDL compiler and analysis, yosys plugin
                    "yosys" : "yosys.exe", #HDL synthesizer
                    "p_r" : "p_r.exe",      #Cologne Chip Place and Router for GateMate A1
                    "openfpgaloader" : "openFPGALoader.exe"}  #Universal FPGA programmer
    

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

        # Check Yosys + GHDL plugin if both tools are available
        if (tool_results.get("yosys", {}).get("available", False) and 
            tool_results.get("ghdl", {}).get("available", False)):
            if self.check_ghdl_yosys_link():
                logging.info("The Yosys + GHDL plugin is working correctly")
            else:
                logging.warning("The Yosys + GHDL plugin may not be working correctly.")
        else:
            logging.info("Skipping GHDL-Yosys plugin check (one or both tools not available)")

        return True

    def initialize_individual_tool_preferences(self):
        """Initialize individual tool preferences if they don't exist."""
        if "cologne_chip_gatemate_tool_preferences" not in self.config:
            self.config["cologne_chip_gatemate_tool_preferences"] = {}
        
        # Ensure all tools have a preference entry
        for tool_name in self.__tool_chain:
            if tool_name not in self.config["cologne_chip_gatemate_tool_preferences"]:
                self.config["cologne_chip_gatemate_tool_preferences"][tool_name] = "PATH"
        
        # Also initialize GTKWave preference
        if "gtkwave" not in self.config["cologne_chip_gatemate_tool_preferences"]:
            self.config["cologne_chip_gatemate_tool_preferences"]["gtkwave"] = "PATH"
        
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
            
            # Set the preference
            self.config["cologne_chip_gatemate_tool_preferences"][tool_name] = preference.upper()
            logging.info(f"Set {tool_name} preference to {preference.upper()}")
            
            # Save configuration
            return self.update_config()
        
        if tool_name not in self.__tool_chain:
            logging.error(f"Unknown tool: {tool_name}")
            return False
        
        # Ensure the preferences structure exists
        if "cologne_chip_gatemate_tool_preferences" not in self.config:
            self.config["cologne_chip_gatemate_tool_preferences"] = {}
        
        # Set the preference
        self.config["cologne_chip_gatemate_tool_preferences"][tool_name] = preference.upper()
        logging.info(f"Set {tool_name} preference to {preference.upper()}")
        
        # Save configuration
        return self.update_config()

    def check_tool_version_path(self, tool_name: str) -> bool:
        """Check if a specific tool is available through PATH."""
        if tool_name not in self.__tool_chain:
            return False
        
        try:
            # Use the actual binary name from the tool chain dictionary
            tool_command = self.__tool_chain[tool_name]
            
            # Use appropriate version flag
            version_flag = "--version"
            if tool_name == "openfpgaloader":
                version_flag = "--Version"
            
            result = subprocess.run([tool_command, version_flag], capture_output=True, text=True, check=True)
            logging.debug(f"{tool_name} PATH check successful: {result.stdout[:100]}")
            return True
        except (FileNotFoundError, subprocess.CalledProcessError) as e:
            logging.debug(f"{tool_name} PATH check failed: {e}")
            return False

    def check_tool_version_direct(self, tool_name: str) -> bool:
        """Check if a specific tool is available through direct path."""
        if tool_name not in self.__tool_chain:
            return False
        
        tool_paths = self.config.get("cologne_chip_gatemate_toolchain_paths", {})
        tool_path = tool_paths.get(tool_name, "")
        
        if not tool_path or not os.path.exists(tool_path):
            return False
        
        try:
            # Use appropriate version flag
            version_flag = "--version"
            if tool_name == "openfpgaloader":
                version_flag = "--Version"
            
            result = subprocess.run([tool_path, version_flag], capture_output=True, text=True, check=True)
            logging.debug(f"{tool_name} DIRECT check successful: {result.stdout[:100]}")
            return True
        except (FileNotFoundError, subprocess.CalledProcessError) as e:
            logging.debug(f"{tool_name} DIRECT check failed: {e}")
            return False

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
        
        if preference == "DIRECT":
            tool_paths = self.config.get("cologne_chip_gatemate_toolchain_paths", {})
            tool_path = tool_paths.get(tool_name, "")
            if tool_path and os.path.exists(tool_path):
                return tool_path
            else:
                logging.warning(f"{tool_name} preference is DIRECT but path not found, falling back to PATH")
                return self.__tool_chain[tool_name]
        elif preference == "PATH":
            return self.__tool_chain[tool_name]
        else:
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
                version = subprocess.run([f"{tool_path}","--version"], capture_output=True, text=True, check=True)
                if not version:
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
                logging.warning("No configuration file path available. Configuration not saved.")
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
        """
        Check whether the GHDL plugin is available in the configured Yosys binary.

        This verifies that the Yosys path is set in the config and that invoking
        'yosys -p "help ghdl"' returns expected plugin output. Returns True if the
        GHDL plugin is available, otherwise logs an error or warning and returns False.

        Returns:
            bool: True if the GHDL plugin is found, False otherwise.
        """
        logging.info("Verifying Yosys' GHDL plugin installation.")

        # Use the new get_tool_command method to get the correct yosys command
        yosys_access = self.get_tool_command("yosys")
        
        if not yosys_access:
            logging.error("Yosys is not available - cannot check GHDL plugin")
            return False

        #Query Yosys for GHDL
        try:
            result = subprocess.run([yosys_access, "-p" , "help ghdl"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
            logging.info(f"Querying Yosys for GHDL plugin with: \"{yosys_access} -p 'help ghdl'\"")
            if result.stdout:
                logging.info(f"Yosys STDOUT:\n{result.stdout}")
            elif result.stderr:
                logging.info(f"Yosys STDERR:\n{result.stderr}")
            #print(result.stdout)
        except subprocess.CalledProcessError as e:
            logging.error(f"An error occured querying the yosys binary. Run check_toolchain() to verify the toolchain installation. Error {e}")
            return False
        #Check if the GHDL plugin was available
        keywords = ("Analyse", "elaborate", "vhdl standard", "ghdl [options] unit [arch]")

        if any(word.lower() in result.stdout.lower() for word in keywords):
            logging.info("GHDL plugin is available in Yosys.")
            return True
        else:
            logging.warning("GHDL plugin may not be properly installed in Yosys.")
            return False


    def add_tool_path(self, tool_name : str = None,  path : str = None) -> bool:
        """Adds a toolpath to the project configuration file
        tool_name must be in __tool_chain

        Syntax:
            path must follow "F:\\GateMate_toolchain\\ghdl\bin\\ghdl.exe" syntax. Double backslashes required.
        
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
    
        #Loading this one into the project config
        tool_path_structure = { 
            "ghdl" : "",
            "yosys" : "",
            "p_r"   : "",
            "openfpgaloader" : ""
        }

        #Check if the structure already exist
        if "cologne_chip_gatemate_toolchain_paths" in self.config:
            logging.warning(f"The toolchain structure already exists in the project configuration. Skipping.")
            return
        
        #It didnt. Making it
        logging.info(f"Creating a tool path structure in the project configuration file.")
        self.config["cologne_chip_gatemate_toolchain_paths"] = tool_path_structure

        try:
            logging.info(f"Adding tool chain path structure {tool_path_structure} to local config")
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
        
        # Use appropriate version flag for each tool
        version_flag = "--version"
        if tool_name == "openfpgaloader":
            version_flag = "--Version"  # openFPGALoader uses capital V
        
        try:
            result = subprocess.run([tool_command, version_flag], capture_output=True, text=True, check=True)    
            logging.info(f"{tool_name} version check successful:\n{result.stdout}")
            return True
        except FileNotFoundError:
            preference = self.get_tool_preference(tool_name)
            if preference == "DIRECT":
                logging.error(f"Error: '{tool_name}' not found at direct path: {tool_command}")
            else:
                logging.error(f"Error: '{tool_command}' not found in PATH.")
            return False
        except subprocess.CalledProcessError as e:
            preference = self.get_tool_preference(tool_name)
            if preference == "DIRECT":
                logging.error(f"Error: '{tool_name}' failed at direct path: {tool_command}")
            else:
                logging.error(f"Error: '{tool_command}' failed in PATH.")
            return False


if __name__ == "__main__":
    """
    Usage:
    Insantiate ToolChainManager.
    Set tool paths for ghdl, pnr, yosys with add_tool_path()
    Run check_toolchain()
    """

    tcm = ToolChainManager()
    tcm.add_tool_path("ghdl"," C:\\cc-toolchain-win\\ghdl-mcode-5.0.1-mingw64\\bin\\ghdl.exe")
    tcm.add_tool_path("p_r"," C:\\cc-toolchain-win\\cc-toolchain-win\\bin\\p_r\\p_r.exe")
    tcm.add_tool_path("yosys"," C:\\cc-toolchain-win\\cc-toolchain-win\\bin\\yosys\\yosys.exe")
    tcm.check_toolchain()
    #tcm.set_toolchain_preference("direct")
    #tcm.check_ghdl_yosys_link()
   # tcm.check_tool_version("ghdl")
    
    #print(tcm.check_tool_version("lol"))
    #tcm.check_toolchain()
    ##tcm.set_config_path_structure()
        
