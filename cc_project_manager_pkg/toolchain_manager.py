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
            Check if the tools are available through PATH or direct binary paths.

        Returns:
            bool: True if at least one method works, False otherwise.
        """
        STATUS_OK = "OK"
        STATUS_FAIL = "FAIL"
        tool_status = {}

        # Check via PATH
        if self.check_toolchain_path():
            tool_status["PATH"] = STATUS_OK
        else:
            logging.warning("Some or all GateMate tools are unavailable through Windows PATH.")
            tool_status["PATH"] = STATUS_FAIL

        # Check via direct paths
        if self.check_toolchain_direct(override_exit=True):
            tool_status["BINARY"] = STATUS_OK
        else:
            logging.warning("Some or all GateMate tools are unavailable through the specified binary paths.")
            tool_status["BINARY"] = STATUS_FAIL

        # Analyze status and log accordingly
        path_status = tool_status.get("PATH")
        binary_status = tool_status.get("BINARY")
        
        if path_status == STATUS_FAIL and binary_status == STATUS_FAIL:
            logging.error("GateMate tool chain is not reachable through PATH or directly specified paths. Re-configure toolchain manager and check tool chain installation.")
            print("GateMate tool chain is not reachable through PATH or directly specified paths. Re-configure toolchain manager and check tool chain installation.")
            self.set_toolchain_preference("undefined")
            return False

        if path_status == STATUS_OK and binary_status == STATUS_OK:
            logging.info("GateMate tool chain is available through both PATH and the directly specified binary paths.")
            print("GateMate tool chain is available through both PATH and the directly specified binary paths.")
            self.set_toolchain_preference("path")
        else:
            if path_status == STATUS_OK:
                logging.info("GateMate tool chain is available through PATH, but not through file system path")
                print(f"GateMate tool chain is available through PATH, but not through file system path")
                self.set_toolchain_preference("path")
            if binary_status == STATUS_OK:
                logging.info("GateMate tool chain is available with direct file system path, but not the PATH environment variable.")
                print(f"GateMate tool chain is available with direct file system path, but not the PATH environment variable.")
                self.set_toolchain_preference("direct")

        #Check Yosys + GHDL plugin
        if self.check_ghdl_yosys_link():
            logging.info("The Yosys + GHDL plugin in the Cologne Chip' pre-compiled toolchain is OK")
        else:
            logging.warning("The Yosys + GHDL plugin in the Cologne Chip' pre-compiled toolchain may not be working correctly.")

        #Add availability to project configuration.
     

        return True

    def set_toolchain_preference(self, preference : str = "PATH") -> bool:
        """
        Set the toolchain access preference in the project configuration.

        This method updates the project configuration file to specify how the toolchain 
        should be accessed—either through the system's PATH environment variable 
        ("PATH") or by using explicitly defined file system paths to the binaries ("DIRECT").

        Parameters:
            preference (str): Toolchain access preference. Must be one of:
                            "PATH" (use environment variable),
                            "DIRECT" (use explicit paths),
                            "UNDEFINED" (unspecified).
                            Defaults to "PATH".

        Returns:
            bool: True if the configuration was updated successfully, False otherwise.
        """
        new_preference = preference.upper()
        supported_preferences = ("PATH", "DIRECT", "UNDEFINED")
        if new_preference not in supported_preferences:
            logging.error(f"New toolchain preference {preference} is not in supported_preferences {supported_preferences}. Return.")
            return False
        #add preference to project configuration file.
        self.config["cologne_chip_gatemate_toolchain_preference"] = new_preference
        #write to configuration file
        try:
            logging.info(f"Updating project configuration with new tool chain access preference: {new_preference}")
            with open(self.config_path, "w") as config_file:
                yaml.safe_dump(self.config, config_file)
                return True
        except Exception as e:
            logging.error(f"Failed to update project configuration file: {e}")
            return False


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

        yosys_access = ""
        #Check if Yosys should be accessed through PATH
        if self.config.get("cologne_chip_gatemate_toolchain_preference", "PATH") == "DIRECT":
            #get cologne chip pre-compiled yosys tool path
            if "cologne_chip_gatemate_toolchain_paths" not in self.config:
                logging.error(f"The toolchain structure does not exist. Run set_config_path_structure() first.")
                return
            #Check yosys path
            yosys_access = self.config["cologne_chip_gatemate_toolchain_paths"].get("yosys", "")
            if yosys_access != "":
                logging.info(f"Yosys path is set to: {yosys_access}")
            else:
                logging.error("Yosys path is not set or is empty.")
                return False
        else: #use PATH for Yosys instead.
            yosys_access = "yosys"

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

    def check_tool_version(self, tool_name : str = None) -> bool:
        """Checks if tool is available and logs the version.
        
        Args:
            (str) the name of the tool. "ghdl", "yosys", "p_r", "openfpgaloader"
        Returns:
            (bool)  Returns '1' if OK, '0' otherwise.       
        """
        if tool_name not in self.__tool_chain:
            #print(f"Unsupported tool in tool check: {tool_name}, valid tools are {self.__tool_chain}")
            logging.error(f"Unsupported tool in tool check: {tool_name}, valid tools are {self.__tool_chain}")
            return False
        
        # Determine which command to use based on toolchain preference
        preference = self.config.get("cologne_chip_gatemate_toolchain_preference", "PATH")
        
        if preference == "DIRECT":
            # Use direct path if available
            tool_paths = self.config.get("cologne_chip_gatemate_toolchain_paths", {})
            tool_command = tool_paths.get(tool_name, "")
            if not tool_command or not os.path.exists(tool_command):
                logging.error(f"Direct path for {tool_name} not found or invalid: {tool_command}")
                return False
        else:
            # Use PATH - get the actual binary name from the tool chain dictionary
            tool_command = self.__tool_chain[tool_name]
        
        # Use appropriate version flag for each tool
        version_flag = "--version"
        if tool_name == "openfpgaloader":
            version_flag = "--Version"  # openFPGALoader uses capital V
        
        try:
            result = subprocess.run([tool_command, version_flag], capture_output=True, text=True, check=True)    
            #print(f"{tool_name} version :\n{result.stdout}")
            logging.info(f"{tool_name} version :\n{result.stdout}")
        except FileNotFoundError:
            #print(f"Error: '{tool_name}' not found in PATH.")
            if preference == "DIRECT":
                logging.error(f"Error: '{tool_name}' not found at direct path: {tool_command}")
            else:
                logging.error(f"Error: '{tool_command}' not found in PATH.")
            return False
        except subprocess.CalledProcessError as e:
            #print(f"Error: '{tool_name}' not found in PATH.")
            if preference == "DIRECT":
                logging.error(f"Error: '{tool_name}' failed at direct path: {tool_command}")
            else:
                logging.error(f"Error: '{tool_command}' not found in PATH.")
            return False
        if result:
            return True


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
        
