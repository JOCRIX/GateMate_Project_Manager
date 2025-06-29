#!/usr/bin/env python3
"""Interactive CLI for the Cologne Chip Project Manager.

This module provides an interactive menu-based interface for managing FPGA projects,
including synthesis, simulation, and project setup operations using WASD navigation.
"""
import os
import sys
import yaml
import subprocess
import platform
import stat
import time
import re
import logging
from pathlib import Path

# Import from the cc_project_manager_pkg package
from cc_project_manager_pkg import (
    YosysCommands,
    GHDLCommands, 
    HierarchyManager,
    CreateStructure,
    ToolChainManager,
    PnRCommands,
    SimulationManager
)

# Try to import Windows-specific modules for key detection
if platform.system() == "Windows":
    try:
        import msvcrt
    except ImportError:
        msvcrt = None
else:
    try:
        import termios
        import tty
    except ImportError:
        termios = None
        sys = None
        tty = None

# Cross-platform key detection
if os.name == 'nt':  # Windows
    def get_key():
        """Get a single keypress on Windows."""
        key = msvcrt.getch()
        if isinstance(key, bytes):
            key = key.decode('utf-8')
        return key.lower()
else:  # Unix/Linux/macOS
    def get_key():
        """Get a single keypress on Unix/Linux."""
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            tty.setraw(sys.stdin.fileno())
            key = sys.stdin.read(1)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
        return key.lower()

class MenuSystem:
    def __init__(self):
        # Configure logging to suppress console output during CLI operation
        self._configure_logging_for_cli()
        self.running = True
        self._original_stderr = None
    
    def _configure_logging_for_cli(self):
        """Configure logging to prevent console output during CLI operation."""
        import sys
        
        # Get the root logger and remove any existing console handlers
        root_logger = logging.getLogger()
        
        # Remove all existing handlers from root logger
        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)
        
        # Set root logger to WARNING level to reduce noise
        root_logger.setLevel(logging.WARNING)
        
        # Disable propagation for all loggers that might output to console
        logger_names = ['YosysCommands', 'GHDLCommands', 'PnRCommands', 'HierarchyManager', 'ToolChainManager']
        for logger_name in logger_names:
            logger = logging.getLogger(logger_name)
            logger.propagate = False
        
        # Add a null handler to the root logger to catch any stray messages
        null_handler = logging.NullHandler()
        root_logger.addHandler(null_handler)
    
    # ANSI Color codes for cross-platform terminal colors
    class Colors:
        GREEN = '\033[92m'
        RED = '\033[91m'
        YELLOW = '\033[93m'
        BLUE = '\033[94m'
        CYAN = '\033[96m'
        MAGENTA = '\033[95m'
        WHITE = '\033[97m'
        BOLD = '\033[1m'
        RESET = '\033[0m'
    
    def clear_screen(self):
        """Clear the terminal screen."""
        os.system('cls' if os.name == 'nt' else 'clear')
    
    def display_header(self):
        """Display the application header."""
        print("╔═══════════════════════════════════════════════════╗")
        print(f"║         {self.Colors.CYAN}{self.Colors.BOLD}GateMate Project Manager by JOCRIX{self.Colors.RESET}        ║")
        print("║                   by JOCRIX                       ║")
        print("║                     v0.1                          ║")
        print("╚═══════════════════════════════════════════════════╝")
        print()
    
    def display_controls(self):
        """Display navigation controls."""
        print(f"Controls: {self.Colors.CYAN}[W]{self.Colors.RESET} Up  {self.Colors.MAGENTA}[A]{self.Colors.RESET} Back  {self.Colors.CYAN}[S]{self.Colors.RESET} Down  {self.Colors.GREEN}[D]{self.Colors.RESET} Select (Preferred)  {self.Colors.YELLOW}[Enter]{self.Colors.RESET} Select  {self.Colors.RED}[Q]{self.Colors.RESET} Quit")
        print("─" * 55)
        print("Press any key to navigate...")
    
    def display_input_legend(self):
        """Display cancellation legend for input forms."""
        print("═" * 55)
        print(f"🛑 LEGEND: Type {self.Colors.RED}'cancel'{self.Colors.RESET}, {self.Colors.RED}'abort'{self.Colors.RESET}, or {self.Colors.RED}'exit'{self.Colors.RESET} to abort any input")
        print("═" * 55)
    
    def display_syntax_legend(self, input_type):
        """Display syntax legend for different input types."""
        print(f"{self.Colors.BLUE}📋 SYNTAX EXAMPLES:{self.Colors.RESET}")
        
        if input_type == "file_path":
            print(f"  • Relative: {self.Colors.GREEN}src/counter.vhd{self.Colors.RESET}")
            print(f"  • Absolute: {self.Colors.GREEN}C:\\project\\counter.vhd{self.Colors.RESET}")
            print(f"  • Current dir: {self.Colors.GREEN}./counter.vhd{self.Colors.RESET}")
        elif input_type == "project_name":
            print(f"  • Valid: {self.Colors.GREEN}my_project{self.Colors.RESET}, {self.Colors.GREEN}FPGA_Design{self.Colors.RESET}, {self.Colors.GREEN}counter-v2{self.Colors.RESET}")
            print(f"  • Avoid: {self.Colors.RED}spaces{self.Colors.RESET}, {self.Colors.RED}special chars{self.Colors.RESET}")
        elif input_type == "project_path":
            print(f"  • Current: {self.Colors.GREEN}.{self.Colors.RESET} (recommended)")
            print(f"  • Relative: {self.Colors.GREEN}projects/my_design{self.Colors.RESET}")
            print(f"  • Absolute: {self.Colors.GREEN}C:\\Projects\\FPGA{self.Colors.RESET}")
        elif input_type == "entity_name":
            print(f"  • Valid: {self.Colors.GREEN}counter{self.Colors.RESET}, {self.Colors.GREEN}state_machine{self.Colors.RESET}, {self.Colors.GREEN}ALU_8bit{self.Colors.RESET}")
            print(f"  • Rules: {self.Colors.YELLOW}Must match VHDL entity name{self.Colors.RESET}")
        elif input_type == "testbench_name":
            print(f"  • Valid: {self.Colors.GREEN}counter_tb{self.Colors.RESET}, {self.Colors.GREEN}testbench{self.Colors.RESET}, {self.Colors.GREEN}my_test{self.Colors.RESET}")
            print(f"  • Rules: {self.Colors.YELLOW}Must match elaborated entity name{self.Colors.RESET}")
        
        print()
    
    def display_menu(self, title, options, current_selection):
        """Display a menu with highlighted selection."""
        self.clear_screen()
        self.display_header()
        
        print(f"📋 {title}")
        print("─" * 55)
        
        for i, option in enumerate(options):
            if i == current_selection:
                print(f"{self.Colors.GREEN}▶  {option}  ◀{self.Colors.RESET}")
            else:
                print(f"   {option}")
        
        print()
        self.display_controls()
    
    def main_menu(self):
        """Display and handle main menu."""
        options = [
            "Project Management",
            "Synthesis",
            "Implementation",
            "Simulation", 
            "Configuration",
            "Exit"
        ]
        
        current_selection = 0
        
        while True:
            self.display_menu("Main Menu", options, current_selection)
            
            key = get_key()
            
            if key == 'w':  # Up
                current_selection = (current_selection - 1) % len(options)
            elif key == 's':  # Down
                current_selection = (current_selection + 1) % len(options)
            elif key == '\r' or key == '\n' or key == 'd':  # Enter or D for select
                if current_selection == 0:
                    self.project_management_menu()
                elif current_selection == 1:
                    self.synthesis_menu()
                elif current_selection == 2:
                    self.implementation_menu()
                elif current_selection == 3:
                    self.simulation_menu()
                elif current_selection == 4:
                    self.configuration_menu()
                elif current_selection == 5:
                    self.running = False
                    break
            elif key == 'q':
                self.running = False
                break
    
    def project_management_menu(self):
        """Display and handle project management menu."""
        options = [
            "Create New Project",
            "Add VHDL File",
            "Remove VHDL File",
            "Detect Manual Files",
            "View Project Status",
            "Check Project Configuration",
            "Back to Main Menu"
        ]
        
        current_selection = 0
        
        while True:
            self.display_menu("Project Management", options, current_selection)
            
            key = get_key()
            
            if key == 'w':  # Up
                current_selection = (current_selection - 1) % len(options)
            elif key == 's':  # Down
                current_selection = (current_selection + 1) % len(options)
            elif key == '\r' or key == '\n' or key == 'd':  # Enter or D for select
                if current_selection == 0:
                    self.create_new_project()
                elif current_selection == 1:
                    self.add_vhdl_file()
                elif current_selection == 2:
                    self.remove_vhdl_file()
                elif current_selection == 3:
                    self.detect_manual_files()
                elif current_selection == 4:
                    self.view_project_status()
                elif current_selection == 5:
                    self.check_project_configuration()
                elif current_selection == 6:
                    break  # Back to main menu
            elif key == 'a' or key == 'q':  # A for back or Q for quit
                break
    
    def synthesis_menu(self):
        """Display and handle synthesis menu."""
        options = [
            "Run Synthesis",
            "Configure Synthesis Options",
            "View Synthesis Logs",
            "Back to Main Menu"
        ]
        
        current_selection = 0
        
        while True:
            self.display_menu("Synthesis", options, current_selection)
            
            key = get_key()
            
            if key == 'w':  # Up
                current_selection = (current_selection - 1) % len(options)
            elif key == 's':  # Down
                current_selection = (current_selection + 1) % len(options)
            elif key == '\r' or key == '\n' or key == 'd':  # Enter or D for select
                if current_selection == 0:
                    self.run_synthesis()
                elif current_selection == 1:
                    self.configure_synthesis()
                elif current_selection == 2:
                    self.view_synthesis_logs()
                elif current_selection == 3:
                    break  # Back to main menu
            elif key == 'a' or key == 'q':  # A for back or Q for quit
                break
    
    def implementation_menu(self):
        """Display and handle implementation (P&R) menu."""
        options = [
            "Run Place and Route",
            "Generate Bitstream", 
            "Timing Analysis",
            "Generate Post-Implementation Netlist",
            "Full Implementation Flow",
            "View Implementation Status",
            "View Implementation Logs",
            "Manage Constraint Files",
            "Back to Main Menu"
        ]
        
        current_selection = 0
        
        while True:
            self.display_menu("Implementation (Place & Route)", options, current_selection)
            
            key = get_key()
            
            if key == 'w':  # Up
                current_selection = (current_selection - 1) % len(options)
            elif key == 's':  # Down
                current_selection = (current_selection + 1) % len(options)
            elif key == '\r' or key == '\n' or key == 'd':  # Enter or D for select
                if current_selection == 0:
                    self.run_place_and_route()
                elif current_selection == 1:
                    self.generate_bitstream()
                elif current_selection == 2:
                    self.run_timing_analysis()
                elif current_selection == 3:
                    self.generate_post_impl_netlist()
                elif current_selection == 4:
                    self.run_full_implementation()
                elif current_selection == 5:
                    self.view_implementation_status()
                elif current_selection == 6:
                    self.view_implementation_logs()
                elif current_selection == 7:
                    self.manage_constraint_files()
                elif current_selection == 8:
                    break  # Back to main menu
            elif key == 'a' or key == 'q':  # A for back or Q for quit
                break
    
    def simulation_menu(self):
        """Display and handle simulation menu."""
        options = [
            "Behavioral Simulation",
            "Post-Synthesis Simulation",
            "Launch Simulation",
            "Configure Simulation Settings",
            "Manage Simulation Profiles",
            "View Simulation Logs",
            "Back to Main Menu"
        ]
        
        current_selection = 0
        
        while True:
            self.display_menu("Simulation", options, current_selection)
            
            key = get_key()
            
            if key == 'w':  # Up
                current_selection = (current_selection - 1) % len(options)
            elif key == 's':  # Down
                current_selection = (current_selection + 1) % len(options)
            elif key == '\r' or key == '\n' or key == 'd':  # Enter or D for select
                if current_selection == 0:
                    self.behavioral_simulation()
                elif current_selection == 1:
                    self.post_synthesis_simulation()
                elif current_selection == 2:
                    self.launch_simulation_menu()
                elif current_selection == 3:
                    self.configure_simulation_settings()
                elif current_selection == 4:
                    self.manage_simulation_profiles()
                elif current_selection == 5:
                    self.view_simulation_logs()
                elif current_selection == 6:
                    break  # Back to main menu
            elif key == 'a' or key == 'q':  # A for back or Q for quit
                break
    
    def configuration_menu(self):
        """Display and handle configuration menu."""
        options = [
            "View/Edit Toolchain Paths",
            "Configure GTKWave",
            "View/Edit Project Settings",
            "Back to Main Menu"
        ]
        
        current_selection = 0
        
        while True:
            self.display_menu("Configuration", options, current_selection)
            
            key = get_key()
            
            if key == 'w':  # Up
                current_selection = (current_selection - 1) % len(options)
            elif key == 's':  # Down
                current_selection = (current_selection + 1) % len(options)
            elif key == '\r' or key == '\n' or key == 'd':  # Enter or D for select
                if current_selection == 0:
                    self.edit_toolchain_paths()
                elif current_selection == 1:
                    self.configure_gtkwave()
                elif current_selection == 2:
                    self.edit_project_settings()
                elif current_selection == 3:
                    break  # Back to main menu
            elif key == 'a' or key == 'q':  # A for back or Q for quit
                break
    
    def create_new_project(self):
        """Create a new project."""
        self.clear_screen()
        self.display_header()
        print("📁 Create New Project")
        print("─" * 55)
        self.display_input_legend()
        print()
        
        self.display_syntax_legend("project_name")
        project_name = input(f"{self.Colors.CYAN}Enter project name:{self.Colors.RESET} ").strip()
        if project_name.lower() in ['cancel', 'abort', 'exit']:
            print("❌ Operation cancelled.")
            input("Press Enter to continue...")
            return
            
        if not project_name:
            print("❌ Project name cannot be empty!")
            input("Press Enter to continue...")
            return
        
        self.display_syntax_legend("project_path")
        project_path = input(f"{self.Colors.CYAN}Enter project path (or . for current directory):{self.Colors.RESET} ").strip()
        if project_path.lower() in ['cancel', 'abort', 'exit']:
            print("❌ Operation cancelled.")
            input("Press Enter to continue...")
            return
            
        if not project_path:
            project_path = "."
        
        try:
            creator = CreateStructure(project_name, project_path)
            creator.create_project_config()
            creator.create_dir_struct()
            creator.finalize()
            print(f"✅ Created project '{project_name}' at {project_path}")
        except Exception as e:
            print(f"❌ Failed to create project: {e}")
        
        input("Press Enter to continue...")
    
    def add_vhdl_file(self):
        """Add a VHDL file to the project with file copying functionality."""
        self.clear_screen()
        self.display_header()
        print("📄 Add VHDL File")
        print("─" * 55)
        self.display_input_legend()
        print()
        
        # First check if a valid project exists
        try:
            hierarchy = HierarchyManager()
            if not hierarchy.config or "project_structure" not in hierarchy.config:
                print(f"❌ {self.Colors.RED}No project found!{self.Colors.RESET}")
                print()
                print("You need to create a project first before adding VHDL files.")
                print(f"💡 {self.Colors.CYAN}Use:{self.Colors.RESET} Project Management → Create New Project")
                print()
                input("Press Enter to continue...")
                return
        except Exception as e:
            print(f"❌ {self.Colors.RED}Project configuration error:{self.Colors.RESET} {e}")
            print()
            print(f"💡 {self.Colors.CYAN}Solution:{self.Colors.RESET} Create a new project first")
            print()
            input("Press Enter to continue...")
            return
        
        self.display_syntax_legend("file_path")
        file_path = input(f"{self.Colors.CYAN}Enter VHDL file path:{self.Colors.RESET} ").strip()
        if file_path.lower() in ['cancel', 'abort', 'exit']:
            print("❌ Operation cancelled.")
            input("Press Enter to continue...")
            return
            
        if not file_path or not os.path.exists(file_path):
            print("❌ File not found!")
            input("Press Enter to continue...")
            return
        
        # Check if it's a VHDL file
        if not file_path.lower().endswith(('.vhd', '.vhdl')):
            print("❌ File must be a VHDL file (.vhd or .vhdl)")
            input("Press Enter to continue...")
            return
        
        print(f"\n{self.Colors.BLUE}File types:{self.Colors.RESET}")
        print(f"1. {self.Colors.GREEN}Source (src){self.Colors.RESET} - Main design files")
        print(f"2. {self.Colors.YELLOW}Testbench (testbench){self.Colors.RESET} - Test files")
        print(f"3. {self.Colors.MAGENTA}Top level (top){self.Colors.RESET} - Top-level entity")
        
        choice = input(f"{self.Colors.CYAN}Enter choice (1-3):{self.Colors.RESET} ").strip()
        if choice.lower() in ['cancel', 'abort', 'exit']:
            print("❌ Operation cancelled.")
            input("Press Enter to continue...")
            return
            
        file_types = {"1": "src", "2": "testbench", "3": "top"}
        
        if choice not in file_types:
            print("❌ Invalid choice!")
            input("Press Enter to continue...")
            return
        
        # Ask if user wants to copy the file to project directory
        print(f"\n{self.Colors.BLUE}File handling options:{self.Colors.RESET}")
        print(f"1. {self.Colors.GREEN}Copy file to project directory{self.Colors.RESET} (Recommended)")
        print(f"2. {self.Colors.YELLOW}Reference file in current location{self.Colors.RESET}")
        
        copy_choice = input(f"{self.Colors.CYAN}Enter choice (1-2, default=1):{self.Colors.RESET} ").strip()
        if copy_choice.lower() in ['cancel', 'abort', 'exit']:
            print("❌ Operation cancelled.")
            input("Press Enter to continue...")
            return
        
        copy_to_project = copy_choice != "2"  # Default to copy (option 1)
        
        try:
            result_path = hierarchy.add_file(file_path, file_types[choice], copy_to_project)
            
            if copy_to_project:
                print(f"✅ File copied to project and added as {file_types[choice]} file")
                print(f"📁 Copied to: {self.Colors.GREEN}{result_path}{self.Colors.RESET}")
            else:
                print(f"✅ File referenced as {file_types[choice]} file")
                print(f"📁 Referenced at: {self.Colors.GREEN}{result_path}{self.Colors.RESET}")
                
        except Exception as e:
            print(f"❌ Failed to add file: {e}")
            print()
            if "create a project first" in str(e).lower():
                print(f"💡 {self.Colors.CYAN}Solution:{self.Colors.RESET} Use Project Management → Create New Project")
        
        input("Press Enter to continue...")
    
    def remove_vhdl_file(self):
        """Remove VHDL files from the project hierarchy."""
        self.clear_screen()
        self.display_header()
        print("🗑️ Remove VHDL File")
        print("─" * 55)
        self.display_input_legend()
        print()
        
        # First check if a valid project exists
        try:
            hierarchy = HierarchyManager()
            if not hierarchy.config or "project_structure" not in hierarchy.config:
                print(f"❌ {self.Colors.RED}No project found!{self.Colors.RESET}")
                print()
                print("You need to create a project first before removing VHDL files.")
                print(f"💡 {self.Colors.CYAN}Use:{self.Colors.RESET} Project Management → Create New Project")
                print()
                input("Press Enter to continue...")
                return
        except Exception as e:
            print(f"❌ {self.Colors.RED}Project configuration error:{self.Colors.RESET} {e}")
            print()
            print(f"💡 {self.Colors.CYAN}Solution:{self.Colors.RESET} Create a new project first")
            print()
            input("Press Enter to continue...")
            return
        
        # Get current files in project
        try:
            files_info = hierarchy.get_source_files_info()
            
            # Count total files
            total_files = sum(len(files) for files in files_info.values())
            
            if total_files == 0:
                print(f"{self.Colors.YELLOW}📂 No VHDL files found in project hierarchy.{self.Colors.RESET}")
                print()
                print("There are no files to remove from the project.")
                input("Press Enter to continue...")
                return
            
            # Display current files by category
            print(f"{self.Colors.BLUE}📋 Current VHDL files in project:{self.Colors.RESET}")
            print()
            
            file_list = []
            file_counter = 1
            
            for category, files in files_info.items():
                if files:
                    if category == "src":
                        icon = "🔧"
                        color = self.Colors.BLUE
                        name = "Source Files"
                    elif category == "testbench":
                        icon = "🧪"
                        color = self.Colors.YELLOW
                        name = "Testbench Files"
                    elif category == "top":
                        icon = "🔝"
                        color = self.Colors.MAGENTA
                        name = "Top-Level Files"
                    
                    print(f"{color}{icon} {name}:{self.Colors.RESET}")
                    for file_name, file_path in files.items():
                        # Check if file actually exists on disk
                        if os.path.exists(file_path):
                            status = f"{self.Colors.GREEN}✅{self.Colors.RESET}"
                        else:
                            status = f"{self.Colors.RED}❌ (missing){self.Colors.RESET}"
                        
                        print(f"   {file_counter:2}. {self.Colors.GREEN}{file_name}{self.Colors.RESET} {status}")
                        file_list.append((file_name, category, file_path))
                        file_counter += 1
                    print()
            
            # Show removal options
            print(f"{self.Colors.BLUE}Removal Options:{self.Colors.RESET}")
            print(f"1. {self.Colors.CYAN}Remove specific file by number{self.Colors.RESET}")
            print(f"2. {self.Colors.CYAN}Remove specific file by name{self.Colors.RESET}")
            print(f"3. {self.Colors.YELLOW}Remove all missing files{self.Colors.RESET}")
            print(f"4. {self.Colors.RED}Cancel{self.Colors.RESET}")
            print()
            
            choice = input(f"{self.Colors.CYAN}Enter choice (1-4):{self.Colors.RESET} ").strip()
            if choice.lower() in ['cancel', 'abort', 'exit'] or choice == '4':
                print("❌ Operation cancelled.")
                input("Press Enter to continue...")
                return
            
            if choice == "1":
                # Remove by number
                try:
                    file_num = int(input(f"{self.Colors.CYAN}Enter file number (1-{len(file_list)}):{self.Colors.RESET} ").strip())
                    if 1 <= file_num <= len(file_list):
                        file_name, category, file_path = file_list[file_num - 1]
                        
                        # Confirm removal
                        print(f"\n⚠️  About to remove: {self.Colors.GREEN}{file_name}{self.Colors.RESET} ({category})")
                        print(f"🛡️  {self.Colors.YELLOW}NOTE: This will only remove the file from project tracking.{self.Colors.RESET}")
                        print(f"🛡️  {self.Colors.YELLOW}The actual file will NOT be deleted from disk.{self.Colors.RESET}")
                        
                        confirm = input(f"\n{self.Colors.CYAN}Confirm removal? (y/N):{self.Colors.RESET} ").strip().lower()
                        if confirm in ['y', 'yes']:
                            result = hierarchy.remove_file_from_hierarchy(file_name)
                            if result["removed"]:
                                print(f"✅ Successfully removed {self.Colors.GREEN}{file_name}{self.Colors.RESET} from {result['category']} category")
                            else:
                                print(f"❌ {result['message']}")
                        else:
                            print("❌ Removal cancelled.")
                    else:
                        print("❌ Invalid file number!")
                except ValueError:
                    print("❌ Please enter a valid number!")
                    
            elif choice == "2":
                # Remove by name
                file_name = input(f"{self.Colors.CYAN}Enter file name to remove:{self.Colors.RESET} ").strip()
                if file_name.lower() in ['cancel', 'abort', 'exit']:
                    print("❌ Operation cancelled.")
                elif file_name:
                    # Find the file in the list
                    found_files = [(name, cat, path) for name, cat, path in file_list if name == file_name]
                    if found_files:
                        file_name, category, file_path = found_files[0]
                        
                        # Confirm removal
                        print(f"\n⚠️  About to remove: {self.Colors.GREEN}{file_name}{self.Colors.RESET} ({category})")
                        print(f"🛡️  {self.Colors.YELLOW}NOTE: This will only remove the file from project tracking.{self.Colors.RESET}")
                        print(f"🛡️  {self.Colors.YELLOW}The actual file will NOT be deleted from disk.{self.Colors.RESET}")
                        
                        confirm = input(f"\n{self.Colors.CYAN}Confirm removal? (y/N):{self.Colors.RESET} ").strip().lower()
                        if confirm in ['y', 'yes']:
                            result = hierarchy.remove_file_from_hierarchy(file_name)
                            if result["removed"]:
                                print(f"✅ Successfully removed {self.Colors.GREEN}{file_name}{self.Colors.RESET} from {result['category']} category")
                            else:
                                print(f"❌ {result['message']}")
                        else:
                            print("❌ Removal cancelled.")
                    else:
                        print(f"❌ File '{file_name}' not found in project hierarchy!")
                else:
                    print("❌ File name cannot be empty!")
                    
            elif choice == "3":
                # Remove all missing files
                missing_files = [name for name, cat, path in file_list if not os.path.exists(path)]
                if missing_files:
                    print(f"\n⚠️  About to remove {len(missing_files)} missing files:")
                    for name in missing_files:
                        print(f"   • {self.Colors.RED}{name}{self.Colors.RESET}")
                    
                    print(f"\n🛡️  {self.Colors.YELLOW}NOTE: This will only remove files from project tracking.{self.Colors.RESET}")
                    print(f"🛡️  {self.Colors.YELLOW}No files will be deleted from disk.{self.Colors.RESET}")
                    
                    confirm = input(f"\n{self.Colors.CYAN}Confirm removal of all missing files? (y/N):{self.Colors.RESET} ").strip().lower()
                    if confirm in ['y', 'yes']:
                        result = hierarchy.remove_multiple_files_from_hierarchy(missing_files)
                        print(f"✅ Successfully removed {result['successfully_removed']} missing files from project hierarchy")
                        if result['not_found'] > 0:
                            print(f"⚠️  {result['not_found']} files were not found in hierarchy")
                    else:
                        print("❌ Removal cancelled.")
                else:
                    print("✅ No missing files found - all files in hierarchy exist on disk!")
            else:
                print("❌ Invalid choice!")
                
        except Exception as e:
            print(f"❌ Error during file removal: {e}")
        
        input("Press Enter to continue...")
    
    def view_project_status(self):
        """View current project status."""
        self.clear_screen()
        self.display_header()
        print("📊 Project Status")
        print("─" * 55)
        
        try:
            hierarchy = HierarchyManager()
            project_hierarchy = hierarchy.get_hierarchy()
            
            # Check if hierarchy is valid (get_hierarchy returns True when not found)
            if project_hierarchy is True:
                print("❌ No project hierarchy found. Please set up the project first.")
                print("💡 Use 'Create New Project' or run hierarchy initialization.")
            elif isinstance(project_hierarchy, dict):
                print(f"✅ Project: {self.Colors.CYAN}{hierarchy.config.get('project_name', 'Unknown')}{self.Colors.RESET}")
                print(f"📁 Path: {self.Colors.GREEN}{hierarchy.config.get('project_path', 'Unknown')}{self.Colors.RESET}")
                print()
                
                # Get comprehensive project information
                files_info = hierarchy.get_source_files_info()
                stats = hierarchy.get_project_statistics()
                
                # Display files by category
                for category, category_files in files_info.items():
                    if category == "src":
                        icon = "🔧"
                        color = self.Colors.BLUE
                        name = "Source Files"
                    elif category == "testbench":
                        icon = "🧪"
                        color = self.Colors.BLUE
                        name = "Testbench Files"
                    elif category == "top":
                        icon = "🔝"
                        color = self.Colors.BLUE
                        name = "Top-Level Files"
                    
                    if category_files:
                        print(f"\n{color}{icon} {name}:{self.Colors.RESET}")
                        for file_name, file_path in category_files.items():
                            # Check if file actually exists
                            if os.path.exists(file_path):
                                print(f"   ✅ {self.Colors.GREEN}{file_name}{self.Colors.RESET}")
                            else:
                                print(f"   ❌ {self.Colors.RED}{file_name}{self.Colors.RESET} (missing)")
                    else:
                        print(f"\n{self.Colors.YELLOW}{icon} {name}: None{self.Colors.RESET}")
                
                # Show project statistics
                print(f"\n{self.Colors.BLUE}📈 Project Statistics:{self.Colors.RESET}")
                print(f"   Total Files: {self.Colors.CYAN}{stats['total_files']}{self.Colors.RESET}")
                print(f"   Available Entities: {self.Colors.CYAN}{stats['available_entities']}{self.Colors.RESET}")
                print(f"   Available Testbenches: {self.Colors.CYAN}{stats['available_testbenches']}{self.Colors.RESET}")
                
                if stats['missing_files'] > 0:
                    print(f"   Missing Files: {self.Colors.RED}{stats['missing_files']}{self.Colors.RESET}")
                    print(f"   Status: {self.Colors.YELLOW}⚠️ Issues detected{self.Colors.RESET}")
                else:
                    print(f"   Missing Files: {self.Colors.GREEN}0{self.Colors.RESET}")
                    print(f"   Status: {self.Colors.GREEN}✅ All files present{self.Colors.RESET}")
            else:
                print("❌ Unexpected project hierarchy format.")
                
        except Exception as e:
            print(f"❌ Error reading project status: {e}")
            print("💡 Try initializing the project hierarchy or check configuration files.")
        
        input("\nPress Enter to continue...")
    
    def _find_available_vhdl_entities(self):
        """Find available VHDL entities that can be synthesized.
        
        Returns:
            list: List of entity names found in source files
        """
        try:
            # Use the centralized hierarchy manager method
            hierarchy = HierarchyManager()
            return hierarchy.get_available_entities()
        except Exception as e:
            print(f"⚠️  Could not scan for VHDL entities: {e}")
            return []
    
    def _display_available_vhdl_files(self):
        """Display available VHDL files in the project hierarchy.
        
        Returns:
            dict: Dictionary with file names and paths
        """
        try:
            # Use the centralized hierarchy manager method
            hierarchy = HierarchyManager()
            files_info = hierarchy.get_source_files_info()
            
            if not any(files_info.values()):
                print(f"\n{self.Colors.YELLOW}⚠️  No HDL project hierarchy found.{self.Colors.RESET}")
                print(f"💡 Add VHDL files using the {self.Colors.CYAN}Project Management Menu{self.Colors.RESET}")
                return {}
                
            print(f"\n{self.Colors.BLUE}📋 Available VHDL files:{self.Colors.RESET}")
            
            # Display source files with entity names
            if files_info["src"]:
                print(f"  {self.Colors.MAGENTA}Source files:{self.Colors.RESET}")
                for i, (file_name, file_path) in enumerate(files_info["src"].items(), 1):
                    # Parse entity name from the file
                    entity_name = hierarchy.parse_entity_name_from_vhdl(file_path)
                    entity_display = f" (Entity: {self.Colors.GREEN}{entity_name}{self.Colors.RESET})" if entity_name else f" (Entity: {self.Colors.YELLOW}unknown{self.Colors.RESET})"
                    print(f"    {self.Colors.GREEN}{i:2}. {file_name}{self.Colors.RESET}{entity_display}")
            
            # Display top-level files with entity names
            if files_info["top"]:
                print(f"  {self.Colors.CYAN}Top-level files:{self.Colors.RESET}")
                for i, (file_name, file_path) in enumerate(files_info["top"].items(), 1):
                    # Parse entity name from the file
                    entity_name = hierarchy.parse_entity_name_from_vhdl(file_path)
                    entity_display = f" (Entity: {self.Colors.GREEN}{entity_name}{self.Colors.RESET})" if entity_name else f" (Entity: {self.Colors.YELLOW}unknown{self.Colors.RESET})"
                    print(f"    {self.Colors.GREEN}{i:2}. {file_name}{self.Colors.RESET}{entity_display}")
            
            # Display testbench files with entity names (for reference)
            if files_info["testbench"]:
                print(f"  {self.Colors.YELLOW}Testbench files:{self.Colors.RESET}")
                for i, (file_name, file_path) in enumerate(files_info["testbench"].items(), 1):
                    # Parse entity name from the file
                    entity_name = hierarchy.parse_entity_name_from_vhdl(file_path)
                    entity_display = f" (Entity: {self.Colors.GREEN}{entity_name}{self.Colors.RESET})" if entity_name else f" (Entity: {self.Colors.YELLOW}unknown{self.Colors.RESET})"
                    print(f"    {self.Colors.YELLOW}{i:2}. {file_name}{self.Colors.RESET}{entity_display} (not for synthesis)")
            
            print()
            
            # Combine all files for return value
            all_files = {}
            for category in files_info.values():
                all_files.update(category)
            
            return all_files
            
        except Exception as e:
            print(f"⚠️  Could not scan for VHDL files: {e}")
            return {}
    
    def run_synthesis(self):
        """Run synthesis on the design."""
        self.clear_screen()
        self.display_header()
        print("⚡ Run Synthesis")
        print("─" * 55)
        self.display_input_legend()
        print()
        
        # Get current synthesis configuration
        synth_config = self.get_synthesis_configuration()
        
        print(f"{self.Colors.BLUE}🔧 CURRENT SYNTHESIS CONFIGURATION:{self.Colors.RESET}")
        print("╔" + "═" * 53 + "╗")
        print(f"║ Strategy:      {self.Colors.GREEN}{synth_config['strategy']:<35}{self.Colors.RESET} ║")
        print(f"║ VHDL Standard: {self.Colors.GREEN}{synth_config['vhdl_standard']:<35}{self.Colors.RESET} ║")
        print(f"║ IEEE Library:  {self.Colors.GREEN}{synth_config['ieee_library']:<35}{self.Colors.RESET} ║")
        print("╚" + "═" * 53 + "╝")
        print(f"💡 Use '{self.Colors.CYAN}Configure Synthesis Options{self.Colors.RESET}' in the Synthesis menu to change these settings")
        print()
        
        # Find and display available VHDL files and entities
        available_entities = self._find_available_vhdl_entities()
        vhdl_files = self._display_available_vhdl_files()
        
        if available_entities:
            print(f"{self.Colors.BLUE}💡 Detected entities:{self.Colors.RESET}")
            for i, entity in enumerate(available_entities, 1):
                print(f"  {self.Colors.GREEN}{i:2}. {entity}{self.Colors.RESET}")
            print()
        
        self.display_syntax_legend("entity_name")
        top_entity = input(f"{self.Colors.CYAN}Enter top entity name:{self.Colors.RESET} ").strip()
        if top_entity.lower() in ['cancel', 'abort', 'exit']:
            print("❌ Operation cancelled.")
            input("Press Enter to continue...")
            return
            
        if not top_entity:
            print("❌ Top entity name cannot be empty!")
            input("Press Enter to continue...")
            return
        
        # Check if the entity exists in available entities
        if available_entities and top_entity not in available_entities:
            print(f"{self.Colors.YELLOW}⚠️  Warning: '{top_entity}' not found in detected entities.{self.Colors.RESET}")
            print(f"💡 Make sure the entity name is correct and the VHDL file is added to the project.")
            proceed = input(f"{self.Colors.CYAN}Continue anyway? (y/N):{self.Colors.RESET} ").strip().lower()
            if proceed not in ['y', 'yes']:
                print("❌ Operation cancelled.")
                input("Press Enter to continue...")
                return
        
        # Ask about GateMate-specific synthesis
        gatemate = input(f"{self.Colors.CYAN}Use GateMate-specific synthesis? (y/N):{self.Colors.RESET} ").strip().lower()
        if gatemate in ['cancel', 'abort', 'exit']:
            print("❌ Operation cancelled.")
            input("Press Enter to continue...")
            return
            
        use_gatemate = gatemate in ['y', 'yes']
        
        try:
            print(f"\n🔄 Starting synthesis for {self.Colors.CYAN}{top_entity}{self.Colors.RESET}...")
            print(f"   Strategy: {self.Colors.GREEN}{synth_config['strategy']}{self.Colors.RESET}")
            print(f"   VHDL Standard: {self.Colors.GREEN}{synth_config['vhdl_standard']}{self.Colors.RESET}")
            print(f"   IEEE Library: {self.Colors.GREEN}{synth_config['ieee_library']}{self.Colors.RESET}")
            print(f"   Target: {self.Colors.YELLOW}{'GateMate FPGA' if use_gatemate else 'Generic'}{self.Colors.RESET}")
            print()
            
            from cc_project_manager_pkg.yosys_commands import YosysCommands
            yosys = YosysCommands(
                strategy=synth_config['strategy'],
                vhdl_std=synth_config['vhdl_standard'], 
                ieee_lib=synth_config['ieee_library']
            )
            
            if use_gatemate:
                success = yosys.synthesize_gatemate(top_entity)
            else:
                success = yosys.synthesize(top_entity)
            
            if success:
                print(f"\n✅ {self.Colors.GREEN}Successfully synthesized {top_entity}!{self.Colors.RESET}")
                print("╔" + "═" * 45 + "╗")
                print(f"║ {self.Colors.BOLD}SYNTHESIS COMPLETED{self.Colors.RESET}                     ║")
                print(f"║ Strategy: {self.Colors.GREEN}{synth_config['strategy']:<29}{self.Colors.RESET} ║")
                print(f"║ VHDL Standard: {self.Colors.GREEN}{synth_config['vhdl_standard']:<24}{self.Colors.RESET} ║")
                print(f"║ IEEE Library: {self.Colors.GREEN}{synth_config['ieee_library']:<25}{self.Colors.RESET} ║")
                print(f"║ Target: {self.Colors.YELLOW}{'GateMate FPGA':<31}{self.Colors.RESET} ║" if use_gatemate else f"║ Target: {self.Colors.YELLOW}{'Generic':<31}{self.Colors.RESET} ║")
                print("╚" + "═" * 45 + "╝")
            else:
                print(f"\n❌ {self.Colors.RED}Failed to synthesize {top_entity}{self.Colors.RESET}")
                print("Check the synthesis logs for details.")
        except Exception as e:
            print(f"❌ Synthesis error: {e}")
        
        input("Press Enter to continue...")
    
    def get_synthesis_configuration(self):
        """Get the current synthesis configuration from project config.
        
        Returns:
            dict: Dictionary with synthesis configuration settings
        """
        try:
            # Try to get from toolchain manager config
            tcm = ToolChainManager()
            config = tcm.config
            
            # Get default configuration (from synthesis_options.yml if available, else hardcoded)
            default_config = self._load_synthesis_defaults()
            
            # Check if synthesis configuration exists
            if "synthesis_configuration" not in config:
                # No configuration exists, save defaults automatically
                self.save_synthesis_configuration(default_config)
                synth_config = default_config.copy()
            else:
                # Get existing synthesis configuration
                synth_config = config["synthesis_configuration"]
                
                # Ensure all required keys exist, add missing ones
                updated = False
                for key, default_value in default_config.items():
                    if key not in synth_config:
                        synth_config[key] = default_value
                        updated = True
                
                # Save updated configuration if we added missing keys
                if updated:
                    self.save_synthesis_configuration(synth_config)
                    
            return synth_config
            
        except Exception as e:
            print(f"Warning: Could not read synthesis configuration: {e}")
            # Return hardcoded defaults if config can't be read
            return self._load_synthesis_defaults()

    def _load_synthesis_defaults(self):
        """Load synthesis defaults from synthesis_options.yml or return hardcoded defaults.
        
        Returns:
            dict: Dictionary with default synthesis configuration settings
        """
        try:
            # Try to get from ToolChainManager to access project config paths
            tcm = ToolChainManager()
            
            # Check if synthesis_options_file is defined in project config
            setup_files = tcm.config.get("setup_files_initial", {})
            if "synthesis_options_file" in setup_files:
                synthesis_options_path = setup_files["synthesis_options_file"][0]
            else:
                # Fallback to config directory - try to find synthesis_options.yml
                config_dir = tcm.config.get("project_structure", {}).get("config", [])
                if isinstance(config_dir, list) and config_dir:
                    synthesis_options_path = os.path.join(config_dir[0], "synthesis_options.yml")
                else:
                    synthesis_options_path = os.path.join(config_dir, "synthesis_options.yml")
            
            # Try to load from synthesis_options.yml
            if os.path.exists(synthesis_options_path):
                import yaml
                with open(synthesis_options_path, 'r') as f:
                    synthesis_options = yaml.safe_load(f)
                    
                if synthesis_options and "synthesis_defaults" in synthesis_options:
                    defaults = synthesis_options["synthesis_defaults"]
                    return {
                        "strategy": defaults.get("strategy", "balanced"),
                        "vhdl_standard": defaults.get("vhdl_standard", "VHDL-2008"),
                        "ieee_library": defaults.get("ieee_library", "synopsys")
                    }
            else:
                # If synthesis_options.yml doesn't exist, try to create it by instantiating YosysCommands
                try:
                    from cc_project_manager_pkg.yosys_commands import YosysCommands
                    # This will create the synthesis_options.yml file
                    yosys_temp = YosysCommands()
                    
                    # Try loading again after creation
                    if os.path.exists(synthesis_options_path):
                        import yaml
                        with open(synthesis_options_path, 'r') as f:
                            synthesis_options = yaml.safe_load(f)
                            
                        if synthesis_options and "synthesis_defaults" in synthesis_options:
                            defaults = synthesis_options["synthesis_defaults"]
                            return {
                                "strategy": defaults.get("strategy", "balanced"),
                                "vhdl_standard": defaults.get("vhdl_standard", "VHDL-2008"),
                                "ieee_library": defaults.get("ieee_library", "synopsys")
                            }
                except Exception:
                    # If YosysCommands instantiation fails, continue to hardcoded defaults
                    pass
                    
        except Exception as e:
            # If anything fails, continue to hardcoded defaults
            pass
            
        # Hardcoded fallback defaults
        return {
            "strategy": "balanced",
            "vhdl_standard": "VHDL-2008",
            "ieee_library": "synopsys"
        }
    
    def save_synthesis_configuration(self, config_dict):
        """Save synthesis configuration to project config.
        
        Args:
            config_dict: Dictionary with synthesis configuration settings
            
        Returns:
            bool: True if saved successfully, False otherwise
        """
        try:
            # Use toolchain manager to access config
            tcm = ToolChainManager()
            
            # Update the synthesis configuration section
            tcm.config["synthesis_configuration"] = config_dict
            
            # Write back to config file
            import yaml
            with open(tcm.config_path, "w") as config_file:
                yaml.safe_dump(tcm.config, config_file)
                
            return True
            
        except Exception as e:
            print(f"Error saving synthesis configuration: {e}")
            return False

    def configure_synthesis(self):
        """Configure synthesis options."""
        self.clear_screen()
        self.display_header()
        print("⚙️ Configure Synthesis Options")
        print("─" * 55)
        self.display_input_legend()
        print()
        
        # Get current configuration
        current_config = self.get_synthesis_configuration()
        
        print(f"{self.Colors.BLUE}📋 Current synthesis configuration:{self.Colors.RESET}")
        print(f"   Strategy: {self.Colors.CYAN}{current_config['strategy']}{self.Colors.RESET}")
        print(f"   VHDL Standard: {self.Colors.CYAN}{current_config['vhdl_standard']}{self.Colors.RESET}")
        print(f"   IEEE Library: {self.Colors.CYAN}{current_config['ieee_library']}{self.Colors.RESET}")
        print()
        
        # Import yosys_commands to get available options
        try:
            from cc_project_manager_pkg.yosys_commands import YosysCommands
            
            # Configuration menu with WASD navigation
            config_options = [
                "Configure Synthesis Strategy",
                "Configure VHDL Standard", 
                "Configure IEEE Library",
                "Reset to Defaults",
                "Save and Exit",
                "Exit without Saving"
            ]
            
            current_selection = 0
            
            while True:
                self.clear_screen()
                self.display_header()
                print("⚙️ Configure Synthesis Options")
                print("─" * 55)
                
                print(f"{self.Colors.BLUE}📋 Current synthesis configuration:{self.Colors.RESET}")
                print(f"   Strategy: {self.Colors.CYAN}{current_config['strategy']}{self.Colors.RESET}")
                print(f"   VHDL Standard: {self.Colors.CYAN}{current_config['vhdl_standard']}{self.Colors.RESET}")
                print(f"   IEEE Library: {self.Colors.CYAN}{current_config['ieee_library']}{self.Colors.RESET}")
                print()
                
                print(f"📋 Configuration Menu")
                print("─" * 55)
                
                for i, option in enumerate(config_options):
                    if i == current_selection:
                        print(f"{self.Colors.GREEN}▶  {option}  ◀{self.Colors.RESET}")
                    else:
                        print(f"   {option}")
                
                print()
                self.display_controls()
                
                key = get_key()
                
                if key == 'w':  # Up
                    current_selection = (current_selection - 1) % len(config_options)
                elif key == 's':  # Down
                    current_selection = (current_selection + 1) % len(config_options)
                elif key == '\r' or key == '\n' or key == 'd':  # Enter or D for select
                    if current_selection == 0:
                        # Configure synthesis strategy
                        self._configure_synthesis_strategy(current_config)
                    elif current_selection == 1:
                        # Configure VHDL standard
                        self._configure_vhdl_standard(current_config)
                    elif current_selection == 2:
                        # Configure IEEE library
                        self._configure_ieee_library(current_config)
                    elif current_selection == 3:
                        # Reset to defaults
                        self._reset_synthesis_defaults(current_config)
                    elif current_selection == 4:
                        # Save and exit
                        if self.save_synthesis_configuration(current_config):
                            self.clear_screen()
                            self.display_header()
                            print(f"✅ {self.Colors.GREEN}Synthesis configuration saved successfully!{self.Colors.RESET}")
                            print(f"\n{self.Colors.BLUE}📋 Saved configuration:{self.Colors.RESET}")
                            print(f"   Strategy: {self.Colors.CYAN}{current_config['strategy']}{self.Colors.RESET}")
                            print(f"   VHDL Standard: {self.Colors.CYAN}{current_config['vhdl_standard']}{self.Colors.RESET}")
                            print(f"   IEEE Library: {self.Colors.CYAN}{current_config['ieee_library']}{self.Colors.RESET}")
                            print(f"\n💡 These settings will be used for all future synthesis operations.")
                        else:
                            print(f"❌ {self.Colors.RED}Failed to save synthesis configuration{self.Colors.RESET}")
                        input("Press Enter to continue...")
                        return
                    elif current_selection == 5:
                        # Exit without saving
                        self.clear_screen()
                        self.display_header()
                        print("ℹ️ Configuration changes discarded.")
                        input("Press Enter to continue...")
                        return
                elif key == 'a' or key == 'q':  # A for back or Q for quit
                    # Exit without saving
                    self.clear_screen()
                    self.display_header()
                    print("ℹ️ Configuration changes discarded.")
                    input("Press Enter to continue...")
                    return
                    
        except ImportError as e:
            print(f"❌ Error: Could not import yosys_commands: {e}")
            print("💡 Make sure the yosys_commands module is available.")
            input("Press Enter to continue...")
        except Exception as e:
            print(f"❌ Error configuring synthesis: {e}")
            input("Press Enter to continue...")

    def _configure_synthesis_strategy(self, current_config):
        """Configure synthesis strategy with WASD navigation."""
        from cc_project_manager_pkg.yosys_commands import YosysCommands
        
        strategies = list(YosysCommands.SYNTHESIS_STRATEGIES.keys())
        strategy_descriptions = {
            "area": "Optimize for minimal resource usage (LUTs, logic gates)",
            "speed": "Optimize for maximum performance/frequency", 
            "balanced": "Standard optimization balancing area and speed",
            "quality": "More thorough optimization for better results",
            "timing": "Advanced timing-driven optimization",
            "extreme": "Maximum optimization for performance-critical designs"
        }
        
        # Find current selection index
        try:
            current_selection = strategies.index(current_config['strategy'])
        except ValueError:
            current_selection = strategies.index('balanced')  # Default fallback
        
        while True:
            self.clear_screen()
            self.display_header()
            print("⚙️ Configure Synthesis Strategy")
            print("─" * 55)
            
            print(f"{self.Colors.BLUE}Available synthesis strategies:{self.Colors.RESET}")
            
            for i, strategy in enumerate(strategies):
                if i == current_selection:
                    print(f"{self.Colors.GREEN}▶  {strategy}  ◀{self.Colors.RESET}")
                    print(f"     {self.Colors.YELLOW}{strategy_descriptions[strategy]}{self.Colors.RESET}")
                else:
                    current_marker = f" {self.Colors.CYAN}(current){self.Colors.RESET}" if strategy == current_config['strategy'] else ""
                    print(f"   {strategy}{current_marker}")
                    print(f"     {self.Colors.WHITE}{strategy_descriptions[strategy]}{self.Colors.RESET}")
            
            print()
            self.display_controls()
            
            key = get_key()
            
            if key == 'w':  # Up
                current_selection = (current_selection - 1) % len(strategies)
            elif key == 's':  # Down
                current_selection = (current_selection + 1) % len(strategies)
            elif key == '\r' or key == '\n' or key == 'd':  # Enter or D for select
                current_config['strategy'] = strategies[current_selection]
                self.clear_screen()
                self.display_header()
                print(f"✅ Strategy set to: {self.Colors.GREEN}{strategies[current_selection]}{self.Colors.RESET}")
                input("Press Enter to continue...")
                return
            elif key == 'a' or key == 'q':  # A for back or Q for quit
                return

    def _configure_vhdl_standard(self, current_config):
        """Configure VHDL standard with WASD navigation."""
        from cc_project_manager_pkg.yosys_commands import YosysCommands
        
        standards = list(YosysCommands.VHDL_STANDARDS.keys())
        standard_descriptions = {
            "VHDL-1993": "VHDL-1993 standard (older, limited features)",
            "VHDL-1993c": "VHDL-1993 with relaxed restrictions (partial support)",
            "VHDL-2008": "VHDL-2008 standard (most commonly used, recommended)"
        }
        
        # Find current selection index
        try:
            current_selection = standards.index(current_config['vhdl_standard'])
        except ValueError:
            current_selection = standards.index('VHDL-2008')  # Default fallback
        
        while True:
            self.clear_screen()
            self.display_header()
            print("⚙️ Configure VHDL Standard")
            print("─" * 55)
            
            print(f"{self.Colors.BLUE}Available VHDL standards:{self.Colors.RESET}")
            
            for i, standard in enumerate(standards):
                if i == current_selection:
                    print(f"{self.Colors.GREEN}▶  {standard}  ◀{self.Colors.RESET}")
                    print(f"     {self.Colors.YELLOW}{standard_descriptions[standard]}{self.Colors.RESET}")
                else:
                    current_marker = f" {self.Colors.CYAN}(current){self.Colors.RESET}" if standard == current_config['vhdl_standard'] else ""
                    recommended_marker = f" {self.Colors.GREEN}(recommended){self.Colors.RESET}" if standard == "VHDL-2008" else ""
                    print(f"   {standard}{current_marker}{recommended_marker}")
                    print(f"     {self.Colors.WHITE}{standard_descriptions[standard]}{self.Colors.RESET}")
            
            print()
            self.display_controls()
            
            key = get_key()
            
            if key == 'w':  # Up
                current_selection = (current_selection - 1) % len(standards)
            elif key == 's':  # Down
                current_selection = (current_selection + 1) % len(standards)
            elif key == '\r' or key == '\n' or key == 'd':  # Enter or D for select
                current_config['vhdl_standard'] = standards[current_selection]
                self.clear_screen()
                self.display_header()
                print(f"✅ VHDL standard set to: {self.Colors.GREEN}{standards[current_selection]}{self.Colors.RESET}")
                input("Press Enter to continue...")
                return
            elif key == 'a' or key == 'q':  # A for back or Q for quit
                return

    def _configure_ieee_library(self, current_config):
        """Configure IEEE library with WASD navigation."""
        from cc_project_manager_pkg.yosys_commands import YosysCommands
        
        libraries = list(YosysCommands.IEEE_LIBS.keys())
        library_descriptions = {
            "synopsys": "Most compatible with synthesis tools (recommended)",
            "mentor": "Alternative implementation (Mentor Graphics)",
            "none": "No IEEE libraries (minimal, use with caution)"
        }
        
        # Find current selection index
        try:
            current_selection = libraries.index(current_config['ieee_library'])
        except ValueError:
            current_selection = libraries.index('synopsys')  # Default fallback
        
        while True:
            self.clear_screen()
            self.display_header()
            print("⚙️ Configure IEEE Library")
            print("─" * 55)
            
            print(f"{self.Colors.BLUE}Available IEEE libraries:{self.Colors.RESET}")
            
            for i, library in enumerate(libraries):
                if i == current_selection:
                    print(f"{self.Colors.GREEN}▶  {library}  ◀{self.Colors.RESET}")
                    print(f"     {self.Colors.YELLOW}{library_descriptions[library]}{self.Colors.RESET}")
                else:
                    current_marker = f" {self.Colors.CYAN}(current){self.Colors.RESET}" if library == current_config['ieee_library'] else ""
                    recommended_marker = f" {self.Colors.GREEN}(recommended){self.Colors.RESET}" if library == "synopsys" else ""
                    print(f"   {library}{current_marker}{recommended_marker}")
                    print(f"     {self.Colors.WHITE}{library_descriptions[library]}{self.Colors.RESET}")
            
            print()
            self.display_controls()
            
            key = get_key()
            
            if key == 'w':  # Up
                current_selection = (current_selection - 1) % len(libraries)
            elif key == 's':  # Down
                current_selection = (current_selection + 1) % len(libraries)
            elif key == '\r' or key == '\n' or key == 'd':  # Enter or D for select
                current_config['ieee_library'] = libraries[current_selection]
                self.clear_screen()
                self.display_header()
                print(f"✅ IEEE library set to: {self.Colors.GREEN}{libraries[current_selection]}{self.Colors.RESET}")
                input("Press Enter to continue...")
                return
            elif key == 'a' or key == 'q':  # A for back or Q for quit
                return

    def _reset_synthesis_defaults(self, current_config):
        """Reset synthesis configuration to defaults with confirmation."""
        self.clear_screen()
        self.display_header()
        print("🔄 Reset to Defaults")
        print("─" * 55)
        self.display_input_legend()
        print()
        
        print(f"{self.Colors.YELLOW}⚠️  This will reset all synthesis options to defaults:{self.Colors.RESET}")
        print(f"   Strategy: {self.Colors.CYAN}balanced{self.Colors.RESET}")
        print(f"   VHDL Standard: {self.Colors.CYAN}VHDL-2008{self.Colors.RESET}")
        print(f"   IEEE Library: {self.Colors.CYAN}synopsys{self.Colors.RESET}")
        print()
        
        confirm = input(f"{self.Colors.CYAN}Reset all synthesis options to defaults? (y/N):{self.Colors.RESET} ").strip().lower()
        if confirm.lower() in ['cancel', 'abort', 'exit']:
            print("❌ Operation cancelled.")
            input("Press Enter to continue...")
            return
            
        if confirm in ['y', 'yes']:
            current_config['strategy'] = "balanced"
            current_config['vhdl_standard'] = "VHDL-2008"
            current_config['ieee_library'] = "synopsys"
            print(f"✅ {self.Colors.GREEN}Configuration reset to defaults{self.Colors.RESET}")
        else:
            print("ℹ️ Reset cancelled.")
        input("Press Enter to continue...")
    
    def view_synthesis_logs(self):
        """View synthesis logs."""
        self.clear_screen()
        self.display_header()
        print("📜 Synthesis Logs")
        print("─" * 55)
        
        try:
            # Get the synthesis log file path from project configuration
            from cc_project_manager_pkg.hierarchy_manager import HierarchyManager
            hierarchy = HierarchyManager()
            
            if not hierarchy.config_path or not os.path.exists(hierarchy.config_path):
                print("❌ No project configuration found. Please create or load a project first.")
                input("Press Enter to continue...")
                return
            
            # Load project configuration
            import yaml
            with open(hierarchy.config_path, 'r') as f:
                config = yaml.safe_load(f)
            
            # Get yosys log file path
            yosys_log_path = None
            logs_section = config.get("logs", {})
            yosys_commands = logs_section.get("yosys_commands", {})
            
            if isinstance(yosys_commands, dict):
                yosys_log_path = yosys_commands.get("yosys_commands.log")
            
            if not yosys_log_path or not os.path.exists(yosys_log_path):
                print("❌ No synthesis logs found yet.")
                print()
                print(f"{self.Colors.BLUE}💡 Synthesis logs will be available after running synthesis operations.{self.Colors.RESET}")
                print("   The logs contain detailed output from Yosys including:")
                print("   • Analysis and elaboration results")
                print("   • Synthesis strategy execution")
                print("   • Resource utilization reports")
                print("   • Error messages and warnings")
                input("Press Enter to continue...")
                return
            
            # Display log file info
            try:
                file_size = os.path.getsize(yosys_log_path)
                if file_size < 1024:
                    size_str = f"{file_size} bytes"
                elif file_size < 1024 * 1024:
                    size_str = f"{file_size / 1024:.1f} KB"
                else:
                    size_str = f"{file_size / (1024 * 1024):.1f} MB"
                
                print(f"{self.Colors.BLUE}📄 Log File:{self.Colors.RESET} {os.path.basename(yosys_log_path)}")
                print(f"{self.Colors.BLUE}📊 Size:{self.Colors.RESET} {size_str}")
                print(f"{self.Colors.BLUE}📁 Path:{self.Colors.RESET} {yosys_log_path}")
                print()
            except:
                pass
            
            # Read and display log content
            try:
                with open(yosys_log_path, 'r', encoding='utf-8') as f:
                    logs = f.read()
                
                # Show last 3000 characters for better context
                if len(logs) > 3000:
                    print(f"{self.Colors.YELLOW}📝 Showing last 3000 characters of log file...{self.Colors.RESET}")
                    print("─" * 55)
                    display_content = logs[-3000:]
                else:
                    display_content = logs
                
                # Apply basic color coding for better readability
                lines = display_content.split('\n')
                for line in lines:
                    if ' - ERROR - ' in line:
                        print(f"{self.Colors.RED}{line}{self.Colors.RESET}")
                    elif ' - WARNING - ' in line:
                        print(f"{self.Colors.YELLOW}{line}{self.Colors.RESET}")
                    elif ' - INFO - ' in line:
                        print(f"{self.Colors.GREEN}{line}{self.Colors.RESET}")
                    elif ' - DEBUG - ' in line:
                        print(f"{self.Colors.CYAN}{line}{self.Colors.RESET}")
                    elif 'synthesis' in line.lower() and ('successful' in line.lower() or 'completed' in line.lower()):
                        print(f"{self.Colors.GREEN}{self.Colors.BOLD}{line}{self.Colors.RESET}")
                    elif 'failed' in line.lower() or 'error' in line.lower():
                        print(f"{self.Colors.RED}{self.Colors.BOLD}{line}{self.Colors.RESET}")
                    else:
                        print(line)
                        
            except Exception as e:
                print(f"❌ Error reading logs: {e}")
        
        except Exception as e:
            print(f"❌ Error accessing synthesis logs: {e}")
        
        print()
        input("Press Enter to continue...")
    
    def run_simulation(self):
        """Run simulation."""
        self.clear_screen()
        self.display_header()
        print("🧪 Run Simulation")
        print("─" * 55)
        self.display_input_legend()
        print()
        
        # Find and display available testbenches
        available_testbenches = self._find_available_testbenches()
        testbench_files = self._display_available_testbenches()
        
        if available_testbenches:
            print(f"{self.Colors.BLUE}💡 Detected testbench entities:{self.Colors.RESET}")
            for i, testbench in enumerate(available_testbenches, 1):
                print(f"  {self.Colors.GREEN}{i:2}. {testbench}{self.Colors.RESET}")
            print()
        
        # Display simulation settings
        try:
            from cc_project_manager_pkg.simulation_manager import SimulationManager
            sim_manager = SimulationManager()
            sim_settings = sim_manager.get_simulation_length()
            current_profile = sim_manager.get_current_simulation_profile()
            
            if sim_settings:
                sim_time, time_prefix = sim_settings
                print(f"{self.Colors.BLUE}📊 Current simulation configuration:{self.Colors.RESET}")
                print(f"   Active Profile: {self.Colors.CYAN}{current_profile}{self.Colors.RESET}")
                print(f"   Duration: {self.Colors.CYAN}{sim_time}{time_prefix}{self.Colors.RESET}")
                print()
            else:
                print(f"{self.Colors.YELLOW}⚠️  No simulation settings found. Using defaults.{self.Colors.RESET}")
                print()
        except Exception as e:
            print(f"{self.Colors.YELLOW}⚠️  Could not load simulation settings: {e}{self.Colors.RESET}")
            print()
        
        print(f"{self.Colors.BLUE}💡 Note:{self.Colors.RESET} This will run the complete simulation flow:")
        print(f"   1. {self.Colors.CYAN}Analyze{self.Colors.RESET} all VHDL files (including dependencies)")
        print(f"   2. {self.Colors.CYAN}Elaborate{self.Colors.RESET} the testbench entity")
        print(f"   3. {self.Colors.CYAN}Run{self.Colors.RESET} behavioral simulation")
        print(f"   4. {self.Colors.CYAN}Generate{self.Colors.RESET} VCD waveform file")
        print()
        
        proceed = input(f"{self.Colors.CYAN}Use automatic testbench detection from project? (Y/n):{self.Colors.RESET} ").strip().lower()
        if proceed in ['cancel', 'abort', 'exit']:
            print("❌ Operation cancelled.")
            input("Press Enter to continue...")
            return
            
        use_auto_detection = proceed not in ['n', 'no']
        
        if use_auto_detection:
            print(f"\n🔄 {self.Colors.BLUE}Running automatic behavioral simulation...{self.Colors.RESET}")
            print("   Using top-level testbench from project configuration")
            print()
            
            try:
                from cc_project_manager_pkg.simulation_manager import SimulationManager
                sim_manager = SimulationManager()
                success = sim_manager.behavioral_simulate()
                
                if success:
                    print(f"\n✅ {self.Colors.GREEN}Simulation completed successfully!{self.Colors.RESET}")
                    print(f"📁 Check the {self.Colors.CYAN}sim/behavioral/{self.Colors.RESET} directory for VCD waveform files")
                else:
                    print(f"\n❌ {self.Colors.RED}Simulation failed{self.Colors.RESET}")
                    print("💡 Check the GHDL logs for detailed error information.")
                    print("   Common issues: entity not found, dependency order, timing violations")
            except Exception as e:
                print(f"❌ Simulation error: {e}")
        else:
            # Manual testbench selection
            self.display_syntax_legend("testbench_name")
            testbench = input(f"{self.Colors.CYAN}Enter testbench entity name:{self.Colors.RESET} ").strip()
            if testbench.lower() in ['cancel', 'abort', 'exit']:
                print("❌ Operation cancelled.")
                input("Press Enter to continue...")
                return
                
            if not testbench:
                print("❌ Testbench name cannot be empty!")
                input("Press Enter to continue...")
                return
            
            # Check if the testbench exists in available testbenches
            if available_testbenches and testbench not in available_testbenches:
                print(f"{self.Colors.YELLOW}⚠️  Warning: '{testbench}' not found in detected testbench entities.{self.Colors.RESET}")
                print(f"💡 Make sure the testbench name is correct and the testbench file is added to the project.")
                proceed = input(f"{self.Colors.CYAN}Continue anyway? (y/N):{self.Colors.RESET} ").strip().lower()
                if proceed not in ['y', 'yes']:
                    print("❌ Operation cancelled.")
                    input("Press Enter to continue...")
                    return
            
            try:
                print(f"\n🔄 Running manual simulation for {self.Colors.CYAN}{testbench}{self.Colors.RESET}...")
                from cc_project_manager_pkg.ghdl_commands import GHDLCommands
                ghdl = GHDLCommands()
                success = ghdl.behavioral_simulation(testbench)
                
                if success:
                    print(f"✅ Successfully ran simulation for {testbench}")
                else:
                    print(f"❌ Failed to run simulation for {testbench}")
            except Exception as e:
                print(f"❌ Simulation error: {e}")
        
        input("Press Enter to continue...")
    
    def analyze_testbench(self):
        """Analyze testbench files."""
        self.clear_screen()
        self.display_header()
        print("🔍 Analyze VHDL Files")
        print("─" * 55)
        self.display_input_legend()
        print()
        
        print(f"{self.Colors.BLUE}📋 VHDL Analysis Options:{self.Colors.RESET}")
        print(f"   1. {self.Colors.CYAN}Analyze all project files{self.Colors.RESET} (recommended)")
        print(f"   2. {self.Colors.CYAN}Analyze specific file{self.Colors.RESET}")
        print()
        
        # Find and display available files
        vhdl_files = self._display_available_vhdl_files()
        testbench_files = self._display_available_testbenches()
        
        choice = input(f"{self.Colors.CYAN}Choose analysis option (1/2):{self.Colors.RESET} ").strip()
        if choice.lower() in ['cancel', 'abort', 'exit']:
            print("❌ Operation cancelled.")
            input("Press Enter to continue...")
            return
        
        if choice == "1":
            # Analyze all project files
            print(f"\n🔄 {self.Colors.BLUE}Analyzing all VHDL files in project...{self.Colors.RESET}")
            print("   This will analyze source files, testbenches, and top-level files")
            print()
            
            try:
                from cc_project_manager_pkg.ghdl_commands import GHDLCommands
                ghdl = GHDLCommands()
                
                # Get all VHDL files from project hierarchy
                hierarchy = HierarchyManager()
                files_info = hierarchy.get_source_files_info()
                
                total_files = 0
                analyzed_files = 0
                
                # Analyze source files first
                if files_info["src"]:
                    print(f"{self.Colors.BLUE}📁 Analyzing source files:{self.Colors.RESET}")
                    for file_name, file_path in files_info["src"].items():
                        total_files += 1
                        print(f"   Analyzing: {file_name}")
                        if ghdl.analyze(file_path):
                            analyzed_files += 1
                            print(f"   ✅ {file_name}")
                        else:
                            print(f"   ❌ {file_name} - Analysis failed")
                    print()
                
                # Analyze testbench files
                if files_info["testbench"]:
                    print(f"{self.Colors.BLUE}📁 Analyzing testbench files:{self.Colors.RESET}")
                    for file_name, file_path in files_info["testbench"].items():
                        total_files += 1
                        print(f"   Analyzing: {file_name}")
                        if ghdl.analyze(file_path):
                            analyzed_files += 1
                            print(f"   ✅ {file_name}")
                        else:
                            print(f"   ❌ {file_name} - Analysis failed")
                    print()
                
                # Analyze top-level files
                if files_info["top"]:
                    print(f"{self.Colors.BLUE}📁 Analyzing top-level files:{self.Colors.RESET}")
                    for file_name, file_path in files_info["top"].items():
                        total_files += 1
                        print(f"   Analyzing: {file_name}")
                        if ghdl.analyze(file_path):
                            analyzed_files += 1
                            print(f"   ✅ {file_name}")
                        else:
                            print(f"   ❌ {file_name} - Analysis failed")
                    print()
                
                # Summary
                print(f"📊 {self.Colors.BOLD}Analysis Summary:{self.Colors.RESET}")
                print(f"   Total files: {total_files}")
                print(f"   Successfully analyzed: {self.Colors.GREEN}{analyzed_files}{self.Colors.RESET}")
                print(f"   Failed: {self.Colors.RED}{total_files - analyzed_files}{self.Colors.RESET}")
                
                if analyzed_files == total_files:
                    print(f"\n✅ {self.Colors.GREEN}All files analyzed successfully!{self.Colors.RESET}")
                    print("💡 You can now proceed with elaboration or simulation.")
                else:
                    print(f"\n⚠️  {self.Colors.YELLOW}Some files failed analysis.{self.Colors.RESET}")
                    print("💡 Check the GHDL logs for detailed error information.")
                    
            except Exception as e:
                print(f"❌ Analysis error: {e}")
                
        elif choice == "2":
            # Analyze specific file
            self.display_syntax_legend("file_name")
            file_name = input(f"{self.Colors.CYAN}Enter VHDL file name:{self.Colors.RESET} ").strip()
            if file_name.lower() in ['cancel', 'abort', 'exit']:
                print("❌ Operation cancelled.")
                input("Press Enter to continue...")
                return
                
            if not file_name:
                print("❌ File name cannot be empty!")
                input("Press Enter to continue...")
                return
            
            # Check if the file exists in available files
            all_files = {**vhdl_files, **testbench_files}
            if all_files and file_name not in all_files:
                print(f"{self.Colors.YELLOW}⚠️  Warning: '{file_name}' not found in project files.{self.Colors.RESET}")
                print(f"💡 Make sure the file name is correct and the file is added to the project.")
                proceed = input(f"{self.Colors.CYAN}Continue anyway? (y/N):{self.Colors.RESET} ").strip().lower()
                if proceed not in ['y', 'yes']:
                    print("❌ Operation cancelled.")
                    input("Press Enter to continue...")
                    return
            
            try:
                print(f"\n🔄 Analyzing file: {self.Colors.CYAN}{file_name}{self.Colors.RESET}...")
                from cc_project_manager_pkg.ghdl_commands import GHDLCommands
                ghdl = GHDLCommands()
                
                # If the file is in our hierarchy, use its full path
                if file_name in all_files:
                    file_path = all_files[file_name]
                    success = ghdl.analyze(file_path)
                else:
                    # Try as a direct file path
                    success = ghdl.analyze(file_name)
                
                if success:
                    print(f"✅ Successfully analyzed {file_name}")
                    print(f"💡 File is now ready for elaboration and simulation.")
                else:
                    print(f"❌ Failed to analyze {file_name}")
                    print(f"💡 Check the GHDL logs for detailed error information.")
            except Exception as e:
                print(f"❌ Analysis error: {e}")
        else:
            print("❌ Invalid choice. Please select 1 or 2.")
        
        input("Press Enter to continue...")
    
    def elaborate_testbench(self):
        """Elaborate testbench entities."""
        self.clear_screen()
        self.display_header()
        print("🔗 Elaborate Testbench")
        print("─" * 55)
        self.display_input_legend()
        print()
        
        # Find and display available testbenches
        available_testbenches = self._find_available_testbenches()
        testbench_files = self._display_available_testbenches()
        
        if available_testbenches:
            print(f"{self.Colors.BLUE}💡 Detected testbench entities:{self.Colors.RESET}")
            for i, testbench in enumerate(available_testbenches, 1):
                print(f"  {self.Colors.GREEN}{i:2}. {testbench}{self.Colors.RESET}")
            print()
        
        self.display_syntax_legend("testbench_name")
        testbench_entity = input(f"{self.Colors.CYAN}Enter testbench entity name:{self.Colors.RESET} ").strip()
        if testbench_entity.lower() in ['cancel', 'abort', 'exit']:
            print("❌ Operation cancelled.")
            input("Press Enter to continue...")
            return
            
        if not testbench_entity:
            print("❌ Testbench entity name cannot be empty!")
            input("Press Enter to continue...")
            return
        
        # Check if the entity exists in available testbenches
        if available_testbenches and testbench_entity not in available_testbenches:
            print(f"{self.Colors.YELLOW}⚠️  Warning: '{testbench_entity}' not found in detected testbench entities.{self.Colors.RESET}")
            print(f"💡 Make sure the entity name is correct and the testbench is analyzed first.")
            proceed = input(f"{self.Colors.CYAN}Continue anyway? (y/N):{self.Colors.RESET} ").strip().lower()
            if proceed not in ['y', 'yes']:
                print("❌ Operation cancelled.")
                input("Press Enter to continue...")
                return
        
        try:
            print(f"\n🔄 Elaborating testbench entity: {testbench_entity}...")
            from cc_project_manager_pkg.ghdl_commands import GHDLCommands
            ghdl = GHDLCommands()
            success = ghdl.elaborate(testbench_entity)
            
            if success:
                print(f"✅ Successfully elaborated {testbench_entity}")
            else:
                print(f"❌ Failed to elaborate {testbench_entity}")
        except Exception as e:
            print(f"❌ Elaboration error: {e}")
        
        input("Press Enter to continue...")
    
    def view_simulation_logs(self):
        """View simulation logs."""
        self.clear_screen()
        self.display_header()
        print("📜 Simulation Logs")
        print("─" * 55)
        
        log_path = "logs/ghdl_commands.log"
        if os.path.exists(log_path):
            try:
                with open(log_path, 'r') as f:
                    logs = f.read()
                print(logs[-2000:])  # Show last 2000 chars
            except Exception as e:
                print(f"❌ Error reading logs: {e}")
        else:
            print("❌ No simulation logs found.")
        
        input("Press Enter to continue...")
    
    def check_toolchain_availability(self):
        """Check and display toolchain availability status using ToolChainManager."""
        print(f"{self.Colors.BLUE}🔧 TOOLCHAIN STATUS:{self.Colors.RESET}")
        
        try:
            # Create toolchain manager instance
            tcm = ToolChainManager()
            
            # Check overall toolchain status
            print(f"\n{self.Colors.BOLD}Overall Toolchain Check:{self.Colors.RESET}")
            overall_status = tcm.check_toolchain()
            
            # Show individual tool preferences
            tool_prefs = tcm.config.get("cologne_chip_gatemate_tool_preferences", {})
            legacy_pref = tcm.config.get("cologne_chip_gatemate_toolchain_preference", "PATH")
            
            if tool_prefs:
                print(f"Current Setup: {self.Colors.CYAN}Individual tool preferences{self.Colors.RESET}")
                for tool, pref in tool_prefs.items():
                    print(f"  {tool}: {self.Colors.CYAN}{pref}{self.Colors.RESET}")
            else:
                print(f"Current Setup: {self.Colors.CYAN}Legacy preference - {legacy_pref}{self.Colors.RESET}")
            
            # Display detailed status for each tool
            tools = {
                "GHDL": "ghdl",
                "Yosys": "yosys", 
                "P&R": "p_r",
                "openFPGALoader": "openfpgaloader"
            }
            
            print(f"\n{self.Colors.BOLD}Individual Tool Status:{self.Colors.RESET}")
            
            for tool_name, tool_key in tools.items():
                print(f"\n  {self.Colors.BOLD}{tool_name}:{self.Colors.RESET}")
                
                # Show current preference for this tool
                current_pref = tcm.get_tool_preference(tool_key)
                print(f"    Preference: {self.Colors.CYAN}{current_pref}{self.Colors.RESET}")
                
                # Check PATH availability
                path_available = tcm.check_tool_version_path(tool_key)
                if path_available:
                    print(f"    PATH: {self.Colors.GREEN}✅ Available{self.Colors.RESET}")
                else:
                    print(f"    PATH: {self.Colors.RED}❌ Not available{self.Colors.RESET}")
                
                # Check direct path availability
                direct_available = tcm.check_tool_version_direct(tool_key)
                direct_path = tcm.config.get("cologne_chip_gatemate_toolchain_paths", {}).get(tool_key, "")
                if direct_available:
                    print(f"    DIRECT: {self.Colors.GREEN}✅ Available{self.Colors.RESET} ({direct_path})")
                elif direct_path:
                    print(f"    DIRECT: {self.Colors.RED}❌ Path not found{self.Colors.RESET} ({direct_path})")
                else:
                    print(f"    DIRECT: {self.Colors.YELLOW}⚠️ Not configured{self.Colors.RESET}")
                    
                # Overall status based on current preference
                if current_pref == "PATH" and path_available:
                    print(f"    STATUS: {self.Colors.GREEN}✅ READY (using PATH){self.Colors.RESET}")
                elif current_pref == "DIRECT" and direct_available:
                    print(f"    STATUS: {self.Colors.GREEN}✅ READY (using DIRECT){self.Colors.RESET}")
                elif path_available or direct_available:
                    print(f"    STATUS: {self.Colors.YELLOW}⚠️ Available but using {current_pref} preference{self.Colors.RESET}")
                else:
                    print(f"    STATUS: {self.Colors.RED}❌ NOT AVAILABLE{self.Colors.RESET}")
            
            # Additional checks
            print(f"\n{self.Colors.BOLD}Advanced Checks:{self.Colors.RESET}")
            
            # Check GHDL-Yosys plugin integration
            try:
                ghdl_yosys_ok = tcm.check_ghdl_yosys_link()
                if ghdl_yosys_ok:
                    print(f"  GHDL-Yosys Plugin: {self.Colors.GREEN}✅ Available{self.Colors.RESET}")
                else:
                    print(f"  GHDL-Yosys Plugin: {self.Colors.YELLOW}⚠️ Not working properly{self.Colors.RESET}")
            except Exception as e:
                print(f"  GHDL-Yosys Plugin: {self.Colors.RED}❌ Check failed{self.Colors.RESET}")
                    
        except Exception as e:
            print(f"{self.Colors.RED}❌ Error checking toolchain status: {e}{self.Colors.RESET}")
        
        print()
    
    def _check_tool_in_path(self, tool_name):
        """Check if a tool is available in PATH using ToolChainManager."""
        try:
            tcm = ToolChainManager()
            return tcm.check_tool_version(tool_name)
        except:
            return False

    def edit_toolchain_paths(self):
        """Edit toolchain paths using ToolChainManager integration."""
        self.clear_screen()
        self.display_header()
        print("🔧 Edit Toolchain Paths")
        print("─" * 55)
        self.display_input_legend()
        
        # Display current toolchain availability status
        self.check_toolchain_availability()
        print("─" * 55)
        
        try:
            # Use ToolChainManager for configuration
            tcm = ToolChainManager()
            current_paths = tcm.config.get("cologne_chip_gatemate_toolchain_paths", {})
            
            print(f"\n{self.Colors.BLUE}CURRENT CONFIGURED PATHS:{self.Colors.RESET}")
            print(f"GHDL: {self.Colors.GREEN}{current_paths.get('ghdl', 'Not set')}{self.Colors.RESET}")
            print(f"Yosys: {self.Colors.GREEN}{current_paths.get('yosys', 'Not set')}{self.Colors.RESET}")
            print(f"P&R: {self.Colors.GREEN}{current_paths.get('p_r', 'Not set')}{self.Colors.RESET}")
            print()
            
            self.display_syntax_legend("file_path")
            
            # Get new paths from user
            path_updates = {}
            
            ghdl_path = input(f"{self.Colors.CYAN}Enter new GHDL path (or press Enter to keep current):{self.Colors.RESET} ").strip()
            if ghdl_path.lower() in ['cancel', 'abort', 'exit']:
                print("❌ Operation cancelled.")
                input("Press Enter to continue...")
                return
            if ghdl_path:
                path_updates['ghdl'] = ghdl_path
                
            yosys_path = input(f"{self.Colors.CYAN}Enter new Yosys path (or press Enter to keep current):{self.Colors.RESET} ").strip()
            if yosys_path.lower() in ['cancel', 'abort', 'exit']:
                print("❌ Operation cancelled.")
                input("Press Enter to continue...")
                return
            if yosys_path:
                path_updates['yosys'] = yosys_path
                
            pr_path = input(f"{self.Colors.CYAN}Enter new P&R path (or press Enter to keep current):{self.Colors.RESET} ").strip()
            if pr_path.lower() in ['cancel', 'abort', 'exit']:
                print("❌ Operation cancelled.")
                input("Press Enter to continue...")
                return
            if pr_path:
                path_updates['p_r'] = pr_path
            
            if not path_updates:
                print("ℹ️ No changes made.")
                input("Press Enter to continue...")
                return
            
            # Validate and apply changes using ToolChainManager
            print(f"\n{self.Colors.BLUE}Validating and applying changes...{self.Colors.RESET}")
            success_count = 0
            
            for tool_name, new_path in path_updates.items():
                print(f"\nProcessing {tool_name}: {new_path}")
                
                # Use ToolChainManager's add_tool_path method
                try:
                    success = tcm.add_tool_path(tool_name, new_path)
                    if success:
                        print(f"  ✅ {tool_name.upper()} path updated successfully")
                        success_count += 1
                    else:
                        print(f"  ❌ Failed to update {tool_name.upper()} path")
                        print(f"      Ensure path exists and ends with correct binary name")
                except Exception as e:
                    print(f"  ❌ Error updating {tool_name.upper()}: {e}")
            
            if success_count > 0:
                print(f"\n✅ Successfully updated {success_count}/{len(path_updates)} tool paths")
                
                # Update toolchain preference if needed
                print(f"\n{self.Colors.BLUE}Updating toolchain preference...{self.Colors.RESET}")
                try:
                    # Run a fresh toolchain check to set optimal preference
                    tcm.check_toolchain()
                    new_preference = tcm.config.get("cologne_chip_gatemate_toolchain_preference", "PATH")
                    print(f"Toolchain preference set to: {self.Colors.CYAN}{new_preference}{self.Colors.RESET}")
                except Exception as e:
                    print(f"Warning: Could not update toolchain preference: {e}")
                
                # Show updated status
                print(f"\n{self.Colors.BLUE}UPDATED STATUS:{self.Colors.RESET}")
                self.check_toolchain_availability()
            else:
                print(f"\n❌ No paths were successfully updated")
        
        except Exception as e:
            print(f"❌ Error managing toolchain paths: {e}")
        
        input("Press Enter to continue...")
    
    def edit_project_settings(self):
        """Edit project settings."""
        self.clear_screen()
        self.display_header()
        print("⚙️ Edit Project Settings")
        print("─" * 55)
        print("Project settings configuration coming soon!")
        input("Press Enter to continue...")
    
    def check_project_configuration(self):
        """Check project configuration integrity and advise on issues."""
        self.clear_screen()
        self.display_header()
        print("🔍 Check Project Configuration")
        print("─" * 55)
        self.display_input_legend()
        print()
        
        try:
            hierarchy = HierarchyManager()
            
            print(f"{self.Colors.BLUE}📋 Configuration Analysis{self.Colors.RESET}")
            print("─" * 40)
            
            # Check if project configuration exists
            if not hierarchy.config_path or not os.path.exists(hierarchy.config_path):
                print(f"❌ {self.Colors.RED}No project configuration file found{self.Colors.RESET}")
                print("💡 Create a new project to generate proper configuration.")
                input("\nPress Enter to continue...")
                return
            
            print(f"✅ Configuration file: {self.Colors.GREEN}{hierarchy.config_path}{self.Colors.RESET}")
            
            # Check project hierarchy
            project_hierarchy = hierarchy.get_hierarchy()
            if project_hierarchy is True:
                print(f"❌ {self.Colors.RED}No project hierarchy found in configuration{self.Colors.RESET}")
                print("💡 Project needs to be properly initialized.")
                print("   Use 'Create New Project' to set up the project structure.")
                input("\nPress Enter to continue...")
                return
            
            print(f"✅ Project hierarchy: {self.Colors.GREEN}Found{self.Colors.RESET}")
            
            # Analyze configured paths vs reality
            print(f"\n{self.Colors.BLUE}📁 File Path Analysis{self.Colors.RESET}")
            print("─" * 40)
            
            total_configured = 0
            missing_files = 0
            path_issues = []
            
            for category in ["src", "testbench", "top"]:
                if category in project_hierarchy:
                    print(f"\n{self.Colors.CYAN}{category.upper()} Files:{self.Colors.RESET}")
                    category_files = project_hierarchy[category]
                    
                    if not category_files:
                        print(f"   {self.Colors.YELLOW}(none configured){self.Colors.RESET}")
                        continue
                    
                    for file_name, file_path in category_files.items():
                        total_configured += 1
                        if os.path.exists(file_path):
                            print(f"   ✅ {file_name}")
                        else:
                            missing_files += 1
                            print(f"   ❌ {self.Colors.RED}{file_name}{self.Colors.RESET}")
                            print(f"      Expected: {self.Colors.YELLOW}{file_path}{self.Colors.RESET}")
                            
                            # Check if file exists elsewhere (like wrong drive)
                            file_name_only = os.path.basename(file_path)
                            possible_locations = [
                                os.path.join(hierarchy.project_path, "src", file_name_only),
                                os.path.join(os.getcwd(), "src", file_name_only)
                            ]
                            
                            found_elsewhere = None
                            for location in possible_locations:
                                if os.path.exists(location) and location != file_path:
                                    found_elsewhere = location
                                    break
                            
                            if found_elsewhere:
                                print(f"      Found at: {self.Colors.GREEN}{found_elsewhere}{self.Colors.RESET}")
                                path_issues.append((file_name, file_path, found_elsewhere))
            
            # Summary and recommendations
            print(f"\n{self.Colors.BLUE}📊 Configuration Summary{self.Colors.RESET}")
            print("─" * 40)
            print(f"Total configured files: {self.Colors.CYAN}{total_configured}{self.Colors.RESET}")
            print(f"Missing files: {self.Colors.RED}{missing_files}{self.Colors.RESET}")
            
            if missing_files == 0:
                print(f"Status: {self.Colors.GREEN}✅ Configuration is valid{self.Colors.RESET}")
                print("All configured file paths are correct and files exist.")
            else:
                print(f"Status: {self.Colors.RED}❌ Configuration has issues{self.Colors.RESET}")
                
                if path_issues:
                    print(f"\n{self.Colors.YELLOW}🔍 Detected Issues:{self.Colors.RESET}")
                    print("Files exist but at different paths than configured.")
                    print("This usually happens when:")
                    print("• Project was moved to different drive/location")
                    print("• Configuration was created on different system")
                    print("• Manual edits to configuration file")
                
                print(f"\n{self.Colors.BLUE}💡 Recommended Actions:{self.Colors.RESET}")
                print("1. Use 'Create New Project' to reinitialize with correct paths")
                print("2. Ensure all VHDL files are in the src/ directory")
                print("3. Let the system regenerate the configuration automatically")
                
                print(f"\n{self.Colors.YELLOW}⚠️ Important:{self.Colors.RESET}")
                print("This tool respects your configuration file as the source of truth.")
                print("Manual fixes may cause inconsistencies.")
                print("Project re-initialization is the recommended approach.")
                
                # Offer rebuild option if files exist in wrong locations
                if path_issues:
                    print(f"\n{self.Colors.CYAN}🔧 Quick Fix Option:{self.Colors.RESET}")
                    print("Since files exist at different paths, you can rebuild the hierarchy")
                    print("from the current src/ directory contents.")
                    
                    rebuild = input(f"\n{self.Colors.CYAN}Rebuild project hierarchy from src/ directory? (y/N):{self.Colors.RESET} ").strip().lower()
                    if rebuild in ['cancel', 'abort', 'exit']:
                        print("❌ Operation cancelled.")
                    elif rebuild in ['y', 'yes']:
                        print(f"\n{self.Colors.BLUE}🔄 Rebuilding project hierarchy...{self.Colors.RESET}")
                        
                        try:
                            success = hierarchy.rebuild_hierarchy()
                            if success:
                                print(f"✅ {self.Colors.GREEN}Project hierarchy rebuilt successfully!{self.Colors.RESET}")
                                print("Files have been re-categorized based on naming conventions:")
                                print(f"   • {self.Colors.GREEN}*_tb.vhd{self.Colors.RESET} → testbench")
                                print(f"   • {self.Colors.GREEN}*_top.vhd{self.Colors.RESET} → top-level")
                                print(f"   • {self.Colors.GREEN}*.vhd{self.Colors.RESET} → source")
                                
                                # Show quick status
                                print(f"\n{self.Colors.BLUE}📊 Updated Configuration:{self.Colors.RESET}")
                                updated_hierarchy = hierarchy.get_hierarchy()
                                if isinstance(updated_hierarchy, dict):
                                    total_files = sum(len(files) for files in updated_hierarchy.values())
                                    print(f"   Total files configured: {self.Colors.GREEN}{total_files}{self.Colors.RESET}")
                                    print(f"   Status: {self.Colors.GREEN}✅ All paths updated{self.Colors.RESET}")
                            else:
                                print(f"❌ {self.Colors.RED}Failed to rebuild hierarchy{self.Colors.RESET}")
                                print("💡 Check logs for details or try 'Create New Project'")
                        except Exception as e:
                            print(f"❌ {self.Colors.RED}Error during rebuild: {e}{self.Colors.RESET}")
                    else:
                        print("ℹ️ Rebuild cancelled. Use 'Create New Project' for full reinitialization.")
        
        except Exception as e:
            print(f"❌ Error analyzing configuration: {e}")
            print("💡 Try using 'Create New Project' to establish a clean configuration.")
        
        input("\nPress Enter to continue...")
    
    def _find_available_synthesized_designs(self):
        """Find available synthesized designs that can be used for P&R.
        
        Returns:
            list: List of design names (without extensions) that have synthesized netlists
        """
        try:
            # Use the centralized yosys_commands method
            from cc_project_manager_pkg.yosys_commands import YosysCommands
            yosys = YosysCommands()
            return yosys.get_available_synthesized_designs()
        except Exception as e:
            print(f"⚠️  Could not scan for synthesized designs: {e}")
            return []
    
    def _display_available_designs(self, designs, design_type="synthesized"):
        """Display available designs in a formatted list.
        
        Args:
            designs: List of design names
            design_type: Type of designs being displayed (for title)
        """
        if designs:
            print(f"\n{self.Colors.BLUE}📋 Available {design_type} designs:{self.Colors.RESET}")
            for i, design in enumerate(designs, 1):
                print(f"  {self.Colors.GREEN}{i:2}. {design}{self.Colors.RESET}")
            print()
        else:
            print(f"\n{self.Colors.YELLOW}⚠️  No {design_type} designs found.{self.Colors.RESET}")
            print(f"💡 Synthesize a design first using the {self.Colors.CYAN}Synthesis Menu{self.Colors.RESET}")
            print()

    def run_place_and_route(self):
        """Run place and route on a synthesized design."""
        self.clear_screen()
        self.display_header()
        print("🔧 Run Place and Route")
        print("─" * 55)
        self.display_input_legend()
        print()
        
        # Find and display available synthesized designs
        available_designs = self._find_available_synthesized_designs()
        self._display_available_designs(available_designs, "synthesized")
        
        self.display_syntax_legend("entity_name")
        design_name = input(f"{self.Colors.CYAN}Enter design name:{self.Colors.RESET} ").strip()
        if design_name.lower() in ['cancel', 'abort', 'exit']:
            print("❌ Operation cancelled.")
            input("Press Enter to continue...")
            return
            
        if not design_name:
            print("❌ Design name cannot be empty!")
            input("Press Enter to continue...")
            return
        
        # Check if the design exists in available designs
        if available_designs and design_name not in available_designs:
            print(f"{self.Colors.YELLOW}⚠️  Warning: '{design_name}' not found in available synthesized designs.{self.Colors.RESET}")
            print(f"💡 Make sure to synthesize '{design_name}' first, or check spelling.")
            proceed = input(f"{self.Colors.CYAN}Continue anyway? (y/N):{self.Colors.RESET} ").strip().lower()
            if proceed not in ['y', 'yes']:
                print("❌ Operation cancelled.")
                input("Press Enter to continue...")
                return
        
        print(f"\n{self.Colors.BLUE}Implementation strategies:{self.Colors.RESET}")
        strategies = ["speed", "area", "balanced", "power", "congestion", "custom"]
        strategy_colors = [self.Colors.RED, self.Colors.GREEN, self.Colors.CYAN, 
                          self.Colors.YELLOW, self.Colors.MAGENTA, self.Colors.BLUE]
        
        for i, (strategy, color) in enumerate(zip(strategies, strategy_colors), 1):
            print(f"{i}. {color}{strategy}{self.Colors.RESET}")
        
        choice = input(f"{self.Colors.CYAN}Enter choice (1-6, default is 3 for balanced):{self.Colors.RESET} ").strip()
        if choice.lower() in ['cancel', 'abort', 'exit']:
            print("❌ Operation cancelled.")
            input("Press Enter to continue...")
            return
            
        if not choice:
            choice = "3"
        
        try:
            strategy_idx = int(choice) - 1
            if strategy_idx < 0 or strategy_idx >= len(strategies):
                raise ValueError()
            strategy = strategies[strategy_idx]
        except:
            print("❌ Invalid choice, using balanced strategy")
            strategy = "balanced"
        
        try:
            print(f"\n🔄 Running {strategy} implementation for {design_name}...")
            from cc_project_manager_pkg.pnr_commands import PnRCommands
            pnr = PnRCommands(strategy=strategy)
            
            success = pnr.place_and_route(design_name)
            
            if success:
                print(f"✅ Successfully completed place and route for {design_name}")
            else:
                print(f"❌ Failed to place and route {design_name}")
        except Exception as e:
            print(f"❌ Place and route error: {e}")
        
        input("Press Enter to continue...")
    
    def _find_available_placed_designs(self):
        """Find available placed and routed designs that can be used for bitstream generation.
        
        Returns:
            list: List of design names that have implementation files
        """
        try:
            # Use the centralized pnr_commands method
            from cc_project_manager_pkg.pnr_commands import PnRCommands
            pnr = PnRCommands()
            return pnr.get_available_placed_designs()
        except Exception as e:
            print(f"⚠️  Could not scan for placed designs: {e}")
            return []

    def generate_bitstream(self):
        """Generate bitstream from a placed and routed design."""
        self.clear_screen()
        self.display_header()
        print("💾 Generate Bitstream")
        print("─" * 55)
        self.display_input_legend()
        print()
        
        # Find and display available placed designs
        available_designs = self._find_available_placed_designs()
        self._display_available_designs(available_designs, "placed & routed")
        
        self.display_syntax_legend("entity_name")
        design_name = input(f"{self.Colors.CYAN}Enter design name:{self.Colors.RESET} ").strip()
        if design_name.lower() in ['cancel', 'abort', 'exit']:
            print("❌ Operation cancelled.")
            input("Press Enter to continue...")
            return
            
        if not design_name:
            print("❌ Design name cannot be empty!")
            input("Press Enter to continue...")
            return
        
        # Check if the design exists in available designs
        if available_designs and design_name not in available_designs:
            print(f"{self.Colors.YELLOW}⚠️  Warning: '{design_name}' not found in available placed & routed designs.{self.Colors.RESET}")
            print(f"💡 Make sure to run place & route on '{design_name}' first, or check spelling.")
            proceed = input(f"{self.Colors.CYAN}Continue anyway? (y/N):{self.Colors.RESET} ").strip().lower()
            if proceed not in ['y', 'yes']:
                print("❌ Operation cancelled.")
                input("Press Enter to continue...")
                return
        
        try:
            print(f"\n🔄 Generating bitstream for {design_name}...")
            from cc_project_manager_pkg.pnr_commands import PnRCommands
            pnr = PnRCommands()
            
            success = pnr.generate_bitstream(design_name)
            
            if success:
                print(f"✅ Successfully generated bitstream for {design_name}")
            else:
                print(f"❌ Failed to generate bitstream for {design_name}")
        except Exception as e:
            print(f"❌ Bitstream generation error: {e}")
        
        input("Press Enter to continue...")
    
    def run_timing_analysis(self):
        """Run timing analysis on a placed and routed design."""
        self.clear_screen()
        self.display_header()
        print("⏱️ Timing Analysis")
        print("─" * 55)
        self.display_input_legend()
        print()
        
        # Find and display available placed designs
        available_designs = self._find_available_placed_designs()
        self._display_available_designs(available_designs, "placed & routed")
        
        self.display_syntax_legend("entity_name")
        design_name = input(f"{self.Colors.CYAN}Enter design name:{self.Colors.RESET} ").strip()
        if design_name.lower() in ['cancel', 'abort', 'exit']:
            print("❌ Operation cancelled.")
            input("Press Enter to continue...")
            return
            
        if not design_name:
            print("❌ Design name cannot be empty!")
            input("Press Enter to continue...")
            return
        
        # Check if the design exists in available designs
        if available_designs and design_name not in available_designs:
            print(f"{self.Colors.YELLOW}⚠️  Warning: '{design_name}' not found in available placed & routed designs.{self.Colors.RESET}")
            print(f"💡 Make sure to run place & route on '{design_name}' first, or check spelling.")
            proceed = input(f"{self.Colors.CYAN}Continue anyway? (y/N):{self.Colors.RESET} ").strip().lower()
            if proceed not in ['y', 'yes']:
                print("❌ Operation cancelled.")
                input("Press Enter to continue...")
                return
        
        try:
            print(f"\n🔄 Running timing analysis for {design_name}...")
            from cc_project_manager_pkg.pnr_commands import PnRCommands
            pnr = PnRCommands()
            
            success = pnr.timing_analysis(design_name)
            
            if success:
                print(f"✅ Successfully completed timing analysis for {design_name}")
            else:
                print(f"❌ Failed to run timing analysis for {design_name}")
        except Exception as e:
            print(f"❌ Timing analysis error: {e}")
        
        input("Press Enter to continue...")
    
    def generate_post_impl_netlist(self):
        """Generate post-implementation netlist for simulation."""
        self.clear_screen()
        self.display_header()
        print("📄 Generate Post-Implementation Netlist")
        print("─" * 55)
        self.display_input_legend()
        print()
        
        # Find and display available placed designs
        available_designs = self._find_available_placed_designs()
        self._display_available_designs(available_designs, "placed & routed")
        
        self.display_syntax_legend("entity_name")
        design_name = input(f"{self.Colors.CYAN}Enter design name:{self.Colors.RESET} ").strip()
        if design_name.lower() in ['cancel', 'abort', 'exit']:
            print("❌ Operation cancelled.")
            input("Press Enter to continue...")
            return
            
        if not design_name:
            print("❌ Design name cannot be empty!")
            input("Press Enter to continue...")
            return
        
        # Check if the design exists in available designs
        if available_designs and design_name not in available_designs:
            print(f"{self.Colors.YELLOW}⚠️  Warning: '{design_name}' not found in available placed & routed designs.{self.Colors.RESET}")
            print(f"💡 Make sure to run place & route on '{design_name}' first, or check spelling.")
            proceed = input(f"{self.Colors.CYAN}Continue anyway? (y/N):{self.Colors.RESET} ").strip().lower()
            if proceed not in ['y', 'yes']:
                print("❌ Operation cancelled.")
                input("Press Enter to continue...")
                return
        
        print(f"\n{self.Colors.BLUE}Netlist formats:{self.Colors.RESET}")
        formats = ["vhdl", "verilog", "json"]
        format_colors = [self.Colors.GREEN, self.Colors.YELLOW, self.Colors.CYAN]
        
        for i, (fmt, color) in enumerate(zip(formats, format_colors), 1):
            print(f"{i}. {color}{fmt.upper()}{self.Colors.RESET}")
        
        choice = input(f"{self.Colors.CYAN}Enter choice (1-3, default is 1 for VHDL):{self.Colors.RESET} ").strip()
        if choice.lower() in ['cancel', 'abort', 'exit']:
            print("❌ Operation cancelled.")
            input("Press Enter to continue...")
            return
            
        if not choice:
            choice = "1"
        
        try:
            format_idx = int(choice) - 1
            if format_idx < 0 or format_idx >= len(formats):
                raise ValueError()
            netlist_format = formats[format_idx]
        except:
            print("❌ Invalid choice, using VHDL format")
            netlist_format = "vhdl"
        
        try:
            print(f"\n🔄 Generating {netlist_format.upper()} post-implementation netlist for {design_name}...")
            from cc_project_manager_pkg.pnr_commands import PnRCommands
            pnr = PnRCommands()
            
            success = pnr.generate_post_impl_netlist(design_name, netlist_format)
            
            if success:
                print(f"✅ Successfully generated {netlist_format.upper()} netlist for {design_name}")
            else:
                print(f"❌ Failed to generate {netlist_format.upper()} netlist for {design_name}")
        except Exception as e:
            print(f"❌ Post-implementation netlist generation error: {e}")
        
        input("Press Enter to continue...")
    
    def run_full_implementation(self):
        """Run the complete implementation flow."""
        self.clear_screen()
        self.display_header()
        print("🚀 Full Implementation Flow")
        print("─" * 55)
        self.display_input_legend()
        print()
        
        # Find and display available synthesized designs
        available_designs = self._find_available_synthesized_designs()
        self._display_available_designs(available_designs, "synthesized")
        
        self.display_syntax_legend("entity_name")
        design_name = input(f"{self.Colors.CYAN}Enter design name:{self.Colors.RESET} ").strip()
        if design_name.lower() in ['cancel', 'abort', 'exit']:
            print("❌ Operation cancelled.")
            input("Press Enter to continue...")
            return
            
        if not design_name:
            print("❌ Design name cannot be empty!")
            input("Press Enter to continue...")
            return
        
        # Check if the design exists in available designs
        if available_designs and design_name not in available_designs:
            print(f"{self.Colors.YELLOW}⚠️  Warning: '{design_name}' not found in available synthesized designs.{self.Colors.RESET}")
            print(f"💡 Make sure to synthesize '{design_name}' first, or check spelling.")
            proceed = input(f"{self.Colors.CYAN}Continue anyway? (y/N):{self.Colors.RESET} ").strip().lower()
            if proceed not in ['y', 'yes']:
                print("❌ Operation cancelled.")
                input("Press Enter to continue...")
                return
        
        print(f"\n{self.Colors.BLUE}Implementation strategies:{self.Colors.RESET}")
        strategies = ["speed", "area", "balanced", "power", "congestion", "custom"]
        strategy_colors = [self.Colors.RED, self.Colors.GREEN, self.Colors.CYAN, 
                          self.Colors.YELLOW, self.Colors.MAGENTA, self.Colors.BLUE]
        
        for i, (strategy, color) in enumerate(zip(strategies, strategy_colors), 1):
            print(f"{i}. {color}{strategy}{self.Colors.RESET}")
        
        choice = input(f"{self.Colors.CYAN}Enter choice (1-6, default is 3 for balanced):{self.Colors.RESET} ").strip()
        if choice.lower() in ['cancel', 'abort', 'exit']:
            print("❌ Operation cancelled.")
            input("Press Enter to continue...")
            return
            
        if not choice:
            choice = "3"
        
        try:
            strategy_idx = int(choice) - 1
            if strategy_idx < 0 or strategy_idx >= len(strategies):
                raise ValueError()
            strategy = strategies[strategy_idx]
        except:
            print("❌ Invalid choice, using balanced strategy")
            strategy = "balanced"
        
        # Ask about optional steps
        generate_bitstream = input(f"{self.Colors.CYAN}Generate bitstream? (Y/n):{self.Colors.RESET} ").strip().lower()
        if generate_bitstream in ['cancel', 'abort', 'exit']:
            print("❌ Operation cancelled.")
            input("Press Enter to continue...")
            return
        generate_bitstream = generate_bitstream not in ['n', 'no']
        
        run_timing_analysis = input(f"{self.Colors.CYAN}Run timing analysis? (Y/n):{self.Colors.RESET} ").strip().lower()
        if run_timing_analysis in ['cancel', 'abort', 'exit']:
            print("❌ Operation cancelled.")
            input("Press Enter to continue...")
            return
        run_timing_analysis = run_timing_analysis not in ['n', 'no']
        
        generate_sim_netlist = input(f"{self.Colors.CYAN}Generate post-implementation netlist? (Y/n):{self.Colors.RESET} ").strip().lower()
        if generate_sim_netlist in ['cancel', 'abort', 'exit']:
            print("❌ Operation cancelled.")
            input("Press Enter to continue...")
            return
        generate_sim_netlist = generate_sim_netlist not in ['n', 'no']
        
        try:
            print(f"\n🔄 Running full {strategy} implementation flow for {design_name}...")
            from cc_project_manager_pkg.pnr_commands import PnRCommands
            pnr = PnRCommands(strategy=strategy)
            
            success = pnr.full_implementation_flow(
                design_name, 
                generate_bitstream=generate_bitstream,
                run_timing_analysis=run_timing_analysis,
                generate_sim_netlist=generate_sim_netlist
            )
            
            if success:
                print(f"✅ Successfully completed full implementation flow for {design_name}")
            else:
                print(f"❌ Failed to complete implementation flow for {design_name}")
        except Exception as e:
            print(f"❌ Implementation flow error: {e}")
        
        input("Press Enter to continue...")
    
    def view_implementation_status(self):
        """View implementation status for a design."""
        self.clear_screen()
        self.display_header()
        print("📊 Implementation Status")
        print("─" * 55)
        self.display_input_legend()
        print()
        
        self.display_syntax_legend("entity_name")
        design_name = input(f"{self.Colors.CYAN}Enter design name:{self.Colors.RESET} ").strip()
        if design_name.lower() in ['cancel', 'abort', 'exit']:
            print("❌ Operation cancelled.")
            input("Press Enter to continue...")
            return
            
        if not design_name:
            print("❌ Design name cannot be empty!")
            input("Press Enter to continue...")
            return
        
        try:
            print(f"\n📋 Implementation status for {self.Colors.CYAN}{design_name}{self.Colors.RESET}:")
            print("─" * 40)
            
            pnr = PnRCommands()
            status = pnr.get_implementation_status(design_name)
            
            # Display status with colors
            status_icons = {
                True: f"{self.Colors.GREEN}✅",
                False: f"{self.Colors.RED}❌"
            }
            
            print(f"\n{self.Colors.BLUE}🔧 Implementation Steps:{self.Colors.RESET}")
            print(f"   Placed: {status_icons[status['placed']]} {self.Colors.RESET}")
            print(f"   Routed: {status_icons[status['routed']]} {self.Colors.RESET}")
            print(f"   Timing Analyzed: {status_icons[status['timing_analyzed']]} {self.Colors.RESET}")
            print(f"   Bitstream Generated: {status_icons[status['bitstream_generated']]} {self.Colors.RESET}")
            print(f"   Post-Impl Netlist: {status_icons[status['post_impl_netlist']]} {self.Colors.RESET}")
            
            # Calculate completion percentage
            completed_steps = sum(status.values())
            total_steps = len(status)
            completion_percent = (completed_steps / total_steps) * 100
            
            print(f"\n{self.Colors.BLUE}📈 Progress:{self.Colors.RESET}")
            print(f"   Completed: {self.Colors.CYAN}{completed_steps}/{total_steps} steps{self.Colors.RESET}")
            print(f"   Progress: {self.Colors.CYAN}{completion_percent:.1f}%{self.Colors.RESET}")
            
            if completion_percent == 100:
                print(f"   Status: {self.Colors.GREEN}✅ Implementation Complete{self.Colors.RESET}")
            elif completion_percent > 0:
                print(f"   Status: {self.Colors.YELLOW}⚠️ Partially Implemented{self.Colors.RESET}")
            else:
                print(f"   Status: {self.Colors.RED}❌ Not Implemented{self.Colors.RESET}")
                
        except Exception as e:
            print(f"❌ Error checking implementation status: {e}")
        
        input("Press Enter to continue...")
    
    def view_implementation_logs(self):
        """View implementation logs."""
        self.clear_screen()
        self.display_header()
        print("📜 Implementation Logs")
        print("─" * 55)
        
        log_path = "logs/pnr_commands.log"
        if os.path.exists(log_path):
            try:
                with open(log_path, 'r') as f:
                    logs = f.read()
                print(logs[-2000:])  # Show last 2000 chars
            except Exception as e:
                print(f"❌ Error reading logs: {e}")
        else:
            print("❌ No implementation logs found.")
            print("💡 Logs will be created after running implementation commands.")
        
        input("Press Enter to continue...")

    def _find_available_testbenches(self):
        """Find available testbench entities that can be simulated.
        
        Returns:
            list: List of testbench entity names found in testbench files
        """
        try:
            # Use the centralized hierarchy manager method
            hierarchy = HierarchyManager()
            return hierarchy.get_available_testbenches()
        except Exception as e:
            print(f"⚠️  Could not scan for testbench entities: {e}")
            return []
    
    def _display_available_testbenches(self):
        """Display available testbench files in the project hierarchy.
        
        Returns:
            dict: Dictionary with testbench file names and paths
        """
        try:
            # Use the centralized hierarchy manager method
            hierarchy = HierarchyManager()
            files_info = hierarchy.get_source_files_info()
            
            if not files_info["testbench"] and not any('_tb' in f.lower() for f in files_info["top"].keys()):
                print(f"\n{self.Colors.YELLOW}⚠️  No HDL project hierarchy found.{self.Colors.RESET}")
                print(f"💡 Add testbench files using the {self.Colors.CYAN}Project Management Menu{self.Colors.RESET}")
                return {}
                
            print(f"\n{self.Colors.BLUE}📋 Available testbench files:{self.Colors.RESET}")
            
            testbench_files = {}
            
            # Display testbench files with entity names
            if files_info["testbench"]:
                print(f"  {self.Colors.YELLOW}Testbench files:{self.Colors.RESET}")
                for i, (file_name, file_path) in enumerate(files_info["testbench"].items(), 1):
                    # Parse entity name from the file
                    entity_name = hierarchy.parse_entity_name_from_vhdl(file_path)
                    entity_display = f" (Entity: {self.Colors.GREEN}{entity_name}{self.Colors.RESET})" if entity_name else f" (Entity: {self.Colors.YELLOW}unknown{self.Colors.RESET})"
                    print(f"    {self.Colors.GREEN}{i:2}. {file_name}{self.Colors.RESET}{entity_display}")
                    testbench_files[file_name] = file_path
            
            # Display top-level testbenches (those ending with _tb) with entity names
            tb_files_in_top = {k: v for k, v in files_info["top"].items() 
                             if '_tb' in k.lower() and (k.endswith('.vhd') or k.endswith('.vhdl'))}
            if tb_files_in_top:
                print(f"  {self.Colors.CYAN}Top-level testbenches:{self.Colors.RESET}")
                for i, (file_name, file_path) in enumerate(tb_files_in_top.items(), 1):
                    # Parse entity name from the file
                    entity_name = hierarchy.parse_entity_name_from_vhdl(file_path)
                    entity_display = f" (Entity: {self.Colors.GREEN}{entity_name}{self.Colors.RESET})" if entity_name else f" (Entity: {self.Colors.YELLOW}unknown{self.Colors.RESET})"
                    print(f"    {self.Colors.GREEN}{i:2}. {file_name}{self.Colors.RESET}{entity_display}")
                    testbench_files[file_name] = file_path
            
            print()
            
            if not testbench_files:
                print(f"\n{self.Colors.YELLOW}⚠️  No testbench files found.{self.Colors.RESET}")
                print(f"💡 Add testbench files using the {self.Colors.CYAN}Project Management Menu{self.Colors.RESET}")
                
            return testbench_files
            
        except Exception as e:
            print(f"⚠️  Could not scan for testbench files: {e}")
            return {}

    def run(self):
        """Run the main application loop."""
        try:
            while self.running:
                self.main_menu()
        finally:
            # Ensure logging is restored on exit
            self._restore_logging()

    def configure_simulation_settings(self):
        """Configure simulation settings using the simulation_config.yml system."""
        from cc_project_manager_pkg.simulation_manager import SimulationManager
        
        try:
            sim_manager = SimulationManager()
        except Exception as e:
            self.clear_screen()
            self.display_header()
            print("❌ Failed to initialize SimulationManager")
            print(f"Error: {e}")
            input("Press Enter to continue...")
            return
        
        config_options = [
            "View Current Settings",
            "Set Custom Simulation Time",
            "Apply Simulation Preset",
            "Configure Advanced Options",
            "Reset to Defaults",
            "Back to Simulation Menu"
        ]
        
        current_selection = 0
        
        while True:
            self.clear_screen()
            self.display_header()
            print("⚙️ Configure Simulation Settings")
            print("─" * 55)
            
            # Display current simulation settings
            try:
                current_profile = sim_manager.get_current_simulation_profile()
                sim_settings = sim_manager.get_simulation_length()
                
                if sim_settings:
                    sim_time, time_prefix = sim_settings
                    print(f"{self.Colors.BLUE}📋 Current simulation configuration:{self.Colors.RESET}")
                    print(f"   Active Profile: {self.Colors.CYAN}{current_profile}{self.Colors.RESET}")
                    print(f"   Simulation Time: {self.Colors.CYAN}{sim_time}{time_prefix}{self.Colors.RESET}")
                    print()
                else:
                    print(f"{self.Colors.YELLOW}⚠️  Could not load current settings{self.Colors.RESET}")
                    print()
            except Exception as e:
                print(f"{self.Colors.YELLOW}⚠️  Error loading settings: {e}{self.Colors.RESET}")
                print()
            
            print(f"📋 Configuration Menu")
            print("─" * 55)
            
            for i, option in enumerate(config_options):
                if i == current_selection:
                    print(f"{self.Colors.GREEN}▶  {option}  ◀{self.Colors.RESET}")
                else:
                    print(f"   {option}")
            
            print()
            self.display_controls()
            
            key = get_key()
            
            if key == 'w':  # Up
                current_selection = (current_selection - 1) % len(config_options)
            elif key == 's':  # Down
                current_selection = (current_selection + 1) % len(config_options)
            elif key == '\r' or key == '\n' or key == 'd':  # Enter or D for select
                if current_selection == 0:
                    self._view_current_simulation_settings(sim_manager)
                elif current_selection == 1:
                    self._set_custom_simulation_time(sim_manager)
                elif current_selection == 2:
                    self._apply_simulation_preset(sim_manager)
                elif current_selection == 3:
                    self._configure_advanced_simulation_options(sim_manager)
                elif current_selection == 4:
                    self._reset_simulation_defaults(sim_manager)
                elif current_selection == 5:
                    break  # Back to simulation menu
            elif key == 'a' or key == 'q':  # A for back or Q for quit
                break

    def _view_current_simulation_settings(self, sim_manager):
        """View detailed current simulation settings."""
        self.clear_screen()
        self.display_header()
        print("📊 Current Simulation Settings")
        print("─" * 55)
        
        try:
            # Get current settings
            current_profile = sim_manager.get_current_simulation_profile()
            sim_settings = sim_manager.get_simulation_length()
            supported_prefixes = sim_manager.supported_time_prefixes
            
            print(f"{self.Colors.BLUE}📋 ACTIVE CONFIGURATION:{self.Colors.RESET}")
            print("╔" + "═" * 53 + "╗")
            
            if sim_settings:
                sim_time, time_prefix = sim_settings
                print(f"║ Profile Name:     {self.Colors.GREEN}{current_profile:<35}{self.Colors.RESET} ║")
                print(f"║ Simulation Time:  {self.Colors.GREEN}{sim_time} {time_prefix:<30}{self.Colors.RESET} ║")
            else:
                print(f"║ Status:           {self.Colors.RED}No settings found{self.Colors.RESET}                 ║")
            
            print("╚" + "═" * 53 + "╝")
            print()
            
            print(f"{self.Colors.BLUE}📋 SUPPORTED TIME PREFIXES:{self.Colors.RESET}")
            for i, prefix in enumerate(supported_prefixes):
                color = self.Colors.GREEN if prefix == (sim_settings[1] if sim_settings else None) else self.Colors.WHITE
                print(f"   {color}{prefix}{self.Colors.RESET}", end="")
                if i < len(supported_prefixes) - 1:
                    print(" | ", end="")
            print("\n")
            
            # Show available presets
            presets = sim_manager.get_simulation_presets()
            if presets:
                print(f"{self.Colors.BLUE}📋 AVAILABLE PRESETS:{self.Colors.RESET}")
                for name, preset in presets.items():
                    is_current = name == current_profile
                    marker = f" {self.Colors.CYAN}(current){self.Colors.RESET}" if is_current else ""
                    print(f"   {self.Colors.GREEN if is_current else self.Colors.WHITE}{name}: {preset['simulation_time']}{preset['time_prefix']}{self.Colors.RESET} - {preset.get('description', '')}{marker}")
                print()
            
            # Show user profiles
            user_profiles = sim_manager.get_user_simulation_profiles()
            if user_profiles:
                print(f"{self.Colors.BLUE}📋 USER PROFILES:{self.Colors.RESET}")
                for name, profile in user_profiles.items():
                    is_current = name == current_profile
                    marker = f" {self.Colors.CYAN}(current){self.Colors.RESET}" if is_current else ""
                    print(f"   {self.Colors.GREEN if is_current else self.Colors.WHITE}{name}: {profile['simulation_time']}{profile['time_prefix']}{self.Colors.RESET} - {profile.get('description', '')}{marker}")
                print()
            
        except Exception as e:
            print(f"❌ Error retrieving simulation settings: {e}")
        
        input("Press Enter to continue...")

    def _set_custom_simulation_time(self, sim_manager):
        """Set custom simulation time."""
        self.clear_screen()
        self.display_header()
        print("⏱️ Set Custom Simulation Time")
        print("─" * 55)
        self.display_input_legend()
        print()
        
        # Show current settings
        try:
            sim_settings = sim_manager.get_simulation_length()
            if sim_settings:
                sim_time, time_prefix = sim_settings
                print(f"{self.Colors.BLUE}Current: {self.Colors.CYAN}{sim_time}{time_prefix}{self.Colors.RESET}")
            
            # Show supported prefixes
            supported_prefixes = sim_manager.supported_time_prefixes
            print(f"{self.Colors.BLUE}Supported time prefixes:{self.Colors.RESET}")
            print("   " + " | ".join([f"{self.Colors.GREEN}{p}{self.Colors.RESET}" for p in supported_prefixes]))
            print()
        except Exception as e:
            print(f"{self.Colors.YELLOW}⚠️  Could not load current settings: {e}{self.Colors.RESET}")
            print()
        
        self.display_syntax_legend("simulation_time")
        
        # Get simulation time
        time_input = input(f"{self.Colors.CYAN}Enter simulation time (number only):{self.Colors.RESET} ").strip()
        if time_input.lower() in ['cancel', 'abort', 'exit']:
            print("❌ Operation cancelled.")
            input("Press Enter to continue...")
            return
        
        try:
            simulation_time = int(time_input)
            if simulation_time <= 0:
                raise ValueError("Time must be positive")
        except ValueError:
            print("❌ Invalid simulation time. Must be a positive integer.")
            input("Press Enter to continue...")
            return
        
        # Get time prefix
        time_prefix = input(f"{self.Colors.CYAN}Enter time prefix (ns, us, ms, etc.):{self.Colors.RESET} ").strip()
        if time_prefix.lower() in ['cancel', 'abort', 'exit']:
            print("❌ Operation cancelled.")
            input("Press Enter to continue...")
            return
        
        if not time_prefix:
            time_prefix = "ns"  # Default
        
        # Validate prefix
        try:
            if time_prefix not in sim_manager.supported_time_prefixes:
                print(f"❌ Unsupported time prefix '{time_prefix}'")
                print(f"Supported: {', '.join(sim_manager.supported_time_prefixes)}")
                input("Press Enter to continue...")
                return
        except Exception as e:
            print(f"❌ Error validating time prefix: {e}")
            input("Press Enter to continue...")
            return
        
        # Apply the settings
        try:
            success = sim_manager.set_simulation_length(simulation_time, time_prefix)
            if success:
                print(f"✅ {self.Colors.GREEN}Simulation time set to {simulation_time}{time_prefix}{self.Colors.RESET}")
            else:
                print("❌ Failed to set simulation time")
        except Exception as e:
            print(f"❌ Error setting simulation time: {e}")
        
        input("Press Enter to continue...")

    def _apply_simulation_preset(self, sim_manager):
        """Apply a predefined simulation preset."""
        self.clear_screen()
        self.display_header()
        print("📋 Apply Simulation Preset")
        print("─" * 55)
        
        try:
            presets = sim_manager.get_simulation_presets()
            if not presets:
                print("❌ No simulation presets available")
                input("Press Enter to continue...")
                return
            
            # Display available presets
            preset_list = list(presets.items())
            current_profile = sim_manager.get_current_simulation_profile()
            
            print(f"{self.Colors.BLUE}Available simulation presets:{self.Colors.RESET}")
            print()
            
            for i, (name, preset) in enumerate(preset_list):
                is_current = name == current_profile
                marker = f" {self.Colors.CYAN}(current){self.Colors.RESET}" if is_current else ""
                color = self.Colors.GREEN if is_current else self.Colors.WHITE
                print(f"{i+1:2}. {color}{name}{self.Colors.RESET}: {preset['simulation_time']}{preset['time_prefix']} - {preset.get('description', '')}{marker}")
            
            print()
            self.display_input_legend()
            
            choice = input(f"{self.Colors.CYAN}Enter preset number (1-{len(preset_list)}):{self.Colors.RESET} ").strip()
            if choice.lower() in ['cancel', 'abort', 'exit']:
                print("❌ Operation cancelled.")
                input("Press Enter to continue...")
                return
            
            try:
                choice_idx = int(choice) - 1
                if choice_idx < 0 or choice_idx >= len(preset_list):
                    raise ValueError()
                
                preset_name = preset_list[choice_idx][0]
                preset_data = preset_list[choice_idx][1]
                
                # Confirm application
                print(f"\n{self.Colors.BLUE}Selected preset:{self.Colors.RESET}")
                print(f"   Name: {self.Colors.GREEN}{preset_name}{self.Colors.RESET}")
                print(f"   Time: {self.Colors.GREEN}{preset_data['simulation_time']}{preset_data['time_prefix']}{self.Colors.RESET}")
                print(f"   Description: {preset_data.get('description', 'No description')}")
                print()
                
                confirm = input(f"{self.Colors.CYAN}Apply this preset? (Y/n):{self.Colors.RESET} ").strip().lower()
                if confirm.lower() in ['cancel', 'abort', 'exit']:
                    print("❌ Operation cancelled.")
                    input("Press Enter to continue...")
                    return
                
                if confirm not in ['n', 'no']:
                    success = sim_manager.apply_simulation_preset(preset_name)
                    if success:
                        print(f"✅ {self.Colors.GREEN}Applied preset '{preset_name}'{self.Colors.RESET}")
                    else:
                        print(f"❌ Failed to apply preset '{preset_name}'")
                else:
                    print("ℹ️ Preset not applied.")
                
            except ValueError:
                print("❌ Invalid choice. Please enter a valid number.")
            except Exception as e:
                print(f"❌ Error applying preset: {e}")
        
        except Exception as e:
            print(f"❌ Error loading presets: {e}")
        
        input("Press Enter to continue...")

    def _configure_advanced_simulation_options(self, sim_manager):
        """Configure advanced simulation options (placeholder for future features)."""
        self.clear_screen()
        self.display_header()
        print("🔧 Advanced Simulation Options")
        print("─" * 55)
        
        print(f"{self.Colors.BLUE}Advanced simulation configuration options:{self.Colors.RESET}")
        print()
        print(f"{self.Colors.YELLOW}💡 Coming soon:{self.Colors.RESET}")
        print("   • GHDL optimization levels")
        print("   • Waveform output formats (VCD, GHW)")
        print("   • Assertion and timing check settings")
        print("   • Coverage analysis options")
        print("   • Custom GHDL flags")
        print()
        print("These features will be available in a future update.")
        print("Current configuration is managed through simulation_config.yml")
        
        input("Press Enter to continue...")

    def _reset_simulation_defaults(self, sim_manager):
        """Reset simulation settings to defaults."""
        self.clear_screen()
        self.display_header()
        print("🔄 Reset Simulation Settings")
        print("─" * 55)
        self.display_input_legend()
        print()
        
        try:
            defaults = sim_manager.sim_config.get("default_simulation_settings", {})
            default_time = defaults.get("simulation_time", 1000)
            default_prefix = defaults.get("time_prefix", "ns")
            
            print(f"{self.Colors.YELLOW}⚠️  This will reset simulation settings to defaults:{self.Colors.RESET}")
            print(f"   Simulation Time: {self.Colors.CYAN}{default_time}{default_prefix}{self.Colors.RESET}")
            print(f"   Profile: {self.Colors.CYAN}standard{self.Colors.RESET}")
            print()
            
            confirm = input(f"{self.Colors.CYAN}Reset simulation settings to defaults? (y/N):{self.Colors.RESET} ").strip().lower()
            if confirm.lower() in ['cancel', 'abort', 'exit']:
                print("❌ Operation cancelled.")
                input("Press Enter to continue...")
                return
            
            if confirm in ['y', 'yes']:
                success = sim_manager.set_simulation_length(default_time, default_prefix)
                if success:
                    # Also reset to standard preset if available
                    try:
                        sim_manager.apply_simulation_preset("standard")
                    except:
                        pass  # Ignore if standard preset doesn't exist
                    
                    print(f"✅ {self.Colors.GREEN}Simulation settings reset to defaults{self.Colors.RESET}")
                else:
                    print("❌ Failed to reset simulation settings")
            else:
                print("ℹ️ Reset cancelled.")
                
        except Exception as e:
            print(f"❌ Error resetting simulation settings: {e}")
        
        input("Press Enter to continue...")

    def manage_simulation_profiles(self):
        """Manage simulation profiles (create, delete, import, export)."""
        from cc_project_manager_pkg.simulation_manager import SimulationManager
        
        try:
            sim_manager = SimulationManager()
        except Exception as e:
            self.clear_screen()
            self.display_header()
            print("❌ Failed to initialize SimulationManager")
            print(f"Error: {e}")
            input("Press Enter to continue...")
            return
        
        profile_options = [
            "View All Profiles",
            "Create New Profile",
            "Delete User Profile",
            "Export Profile",
            "Import Profile",
            "Back to Simulation Menu"
        ]
        
        current_selection = 0
        
        while True:
            self.clear_screen()
            self.display_header()
            print("📋 Manage Simulation Profiles")
            print("─" * 55)
            
            # Show quick summary
            try:
                presets = sim_manager.get_simulation_presets()
                user_profiles = sim_manager.get_user_simulation_profiles()
                current_profile = sim_manager.get_current_simulation_profile()
                
                print(f"{self.Colors.BLUE}📊 Profile Summary:{self.Colors.RESET}")
                print(f"   Active Profile: {self.Colors.CYAN}{current_profile}{self.Colors.RESET}")
                print(f"   System Presets: {self.Colors.GREEN}{len(presets)}{self.Colors.RESET}")
                print(f"   User Profiles: {self.Colors.GREEN}{len(user_profiles)}{self.Colors.RESET}")
                print()
            except Exception as e:
                print(f"{self.Colors.YELLOW}⚠️  Error loading profile summary: {e}{self.Colors.RESET}")
                print()
            
            print(f"📋 Profile Management Menu")
            print("─" * 55)
            
            for i, option in enumerate(profile_options):
                if i == current_selection:
                    print(f"{self.Colors.GREEN}▶  {option}  ◀{self.Colors.RESET}")
                else:
                    print(f"   {option}")
            
            print()
            self.display_controls()
            
            key = get_key()
            
            if key == 'w':  # Up
                current_selection = (current_selection - 1) % len(profile_options)
            elif key == 's':  # Down
                current_selection = (current_selection + 1) % len(profile_options)
            elif key == '\r' or key == '\n' or key == 'd':  # Enter or D for select
                if current_selection == 0:
                    self._view_all_simulation_profiles(sim_manager)
                elif current_selection == 1:
                    self._create_new_simulation_profile(sim_manager)
                elif current_selection == 2:
                    self._delete_user_simulation_profile(sim_manager)
                elif current_selection == 3:
                    self._export_simulation_profile(sim_manager)
                elif current_selection == 4:
                    self._import_simulation_profile(sim_manager)
                elif current_selection == 5:
                    break  # Back to simulation menu
            elif key == 'a' or key == 'q':  # A for back or Q for quit
                break

    def _view_all_simulation_profiles(self, sim_manager):
        """View all available simulation profiles."""
        self.clear_screen()
        self.display_header()
        print("📋 All Simulation Profiles")
        print("─" * 55)
        
        try:
            all_profiles = sim_manager.list_all_simulation_profiles()
            current_profile = sim_manager.get_current_simulation_profile()
            
            if not all_profiles:
                print("❌ No simulation profiles found")
                input("Press Enter to continue...")
                return
            
            # Separate by type
            presets = {k: v for k, v in all_profiles.items() if v.get('type') == 'preset'}
            user_profiles = {k: v for k, v in all_profiles.items() if v.get('type') == 'user'}
            
            if presets:
                print(f"{self.Colors.BLUE}📋 SYSTEM PRESETS:{self.Colors.RESET}")
                for name, profile in presets.items():
                    is_current = name == current_profile
                    marker = f" {self.Colors.CYAN}(active){self.Colors.RESET}" if is_current else ""
                    color = self.Colors.GREEN if is_current else self.Colors.WHITE
                    print(f"   {color}{name:15}{self.Colors.RESET} | {profile['simulation_time']:>6}{profile['time_prefix']:>3} | {profile.get('description', 'No description')}{marker}")
                print()
            
            if user_profiles:
                print(f"{self.Colors.BLUE}📋 USER PROFILES:{self.Colors.RESET}")
                for name, profile in user_profiles.items():
                    is_current = name == current_profile
                    marker = f" {self.Colors.CYAN}(active){self.Colors.RESET}" if is_current else ""
                    color = self.Colors.GREEN if is_current else self.Colors.WHITE
                    print(f"   {color}{name:15}{self.Colors.RESET} | {profile['simulation_time']:>6}{profile['time_prefix']:>3} | {profile.get('description', 'No description')}{marker}")
                print()
            
            if not user_profiles:
                print(f"{self.Colors.YELLOW}💡 No user profiles created yet. Use 'Create New Profile' to add custom profiles.{self.Colors.RESET}")
                print()
                
        except Exception as e:
            print(f"❌ Error loading profiles: {e}")
        
        input("Press Enter to continue...")

    def _create_new_simulation_profile(self, sim_manager):
        """Create a new user simulation profile."""
        self.clear_screen()
        self.display_header()
        print("➕ Create New Simulation Profile")
        print("─" * 55)
        self.display_input_legend()
        print()
        
        try:
            # Show existing user profiles
            user_profiles = sim_manager.get_user_simulation_profiles()
            if user_profiles:
                print(f"{self.Colors.BLUE}Existing user profiles:{self.Colors.RESET}")
                for name, profile in user_profiles.items():
                    print(f"   {name}: {profile['simulation_time']}{profile['time_prefix']}")
                print()
            
            # Show supported prefixes
            supported_prefixes = sim_manager.supported_time_prefixes
            print(f"{self.Colors.BLUE}Supported time prefixes:{self.Colors.RESET}")
            print("   " + " | ".join([f"{self.Colors.GREEN}{p}{self.Colors.RESET}" for p in supported_prefixes]))
            print()
            
            self.display_syntax_legend("profile_name")
            
            # Get profile name
            profile_name = input(f"{self.Colors.CYAN}Enter profile name:{self.Colors.RESET} ").strip()
            if profile_name.lower() in ['cancel', 'abort', 'exit']:
                print("❌ Operation cancelled.")
                input("Press Enter to continue...")
                return
            
            if not profile_name:
                print("❌ Profile name cannot be empty!")
                input("Press Enter to continue...")
                return
            
            # Check if profile already exists
            if profile_name in user_profiles:
                print(f"❌ Profile '{profile_name}' already exists!")
                input("Press Enter to continue...")
                return
            
            # Get simulation time
            time_input = input(f"{self.Colors.CYAN}Enter simulation time (number only):{self.Colors.RESET} ").strip()
            if time_input.lower() in ['cancel', 'abort', 'exit']:
                print("❌ Operation cancelled.")
                input("Press Enter to continue...")
                return
            
            try:
                simulation_time = int(time_input)
                if simulation_time <= 0:
                    raise ValueError("Time must be positive")
            except ValueError:
                print("❌ Invalid simulation time. Must be a positive integer.")
                input("Press Enter to continue...")
                return
            
            # Get time prefix
            time_prefix = input(f"{self.Colors.CYAN}Enter time prefix (ns, us, ms, etc.):{self.Colors.RESET} ").strip()
            if time_prefix.lower() in ['cancel', 'abort', 'exit']:
                print("❌ Operation cancelled.")
                input("Press Enter to continue...")
                return
            
            if not time_prefix:
                time_prefix = "ns"  # Default
            
            if time_prefix not in supported_prefixes:
                print(f"❌ Unsupported time prefix '{time_prefix}'")
                print(f"Supported: {', '.join(supported_prefixes)}")
                input("Press Enter to continue...")
                return
            
            # Get description (optional)
            description = input(f"{self.Colors.CYAN}Enter description (optional):{self.Colors.RESET} ").strip()
            if description.lower() in ['cancel', 'abort', 'exit']:
                print("❌ Operation cancelled.")
                input("Press Enter to continue...")
                return
            
            # Create the profile
            success = sim_manager.create_user_simulation_profile(profile_name, simulation_time, time_prefix, description)
            if success:
                print(f"✅ {self.Colors.GREEN}Created profile '{profile_name}': {simulation_time}{time_prefix}{self.Colors.RESET}")
                
                # Ask if user wants to apply this profile immediately
                apply_now = input(f"{self.Colors.CYAN}Apply this profile now? (Y/n):{self.Colors.RESET} ").strip().lower()
                if apply_now not in ['n', 'no']:
                    apply_success = sim_manager.apply_simulation_preset(profile_name)
                    if apply_success:
                        print(f"✅ {self.Colors.GREEN}Profile '{profile_name}' is now active{self.Colors.RESET}")
                    else:
                        print(f"❌ Failed to apply profile '{profile_name}'")
            else:
                print(f"❌ Failed to create profile '{profile_name}'")
                
        except Exception as e:
            print(f"❌ Error creating profile: {e}")
        
        input("Press Enter to continue...")

    def _delete_user_simulation_profile(self, sim_manager):
        """Delete a user simulation profile."""
        self.clear_screen()
        self.display_header()
        print("🗑️ Delete User Profile")
        print("─" * 55)
        self.display_input_legend()
        print()
        
        try:
            user_profiles = sim_manager.get_user_simulation_profiles()
            
            if not user_profiles:
                print("❌ No user profiles to delete")
                print("💡 System presets cannot be deleted.")
                input("Press Enter to continue...")
                return
            
            # Display user profiles
            profile_list = list(user_profiles.items())
            current_profile = sim_manager.get_current_simulation_profile()
            
            print(f"{self.Colors.BLUE}User profiles available for deletion:{self.Colors.RESET}")
            print()
            
            for i, (name, profile) in enumerate(profile_list):
                is_current = name == current_profile
                marker = f" {self.Colors.CYAN}(current){self.Colors.RESET}" if is_current else ""
                color = self.Colors.YELLOW if is_current else self.Colors.WHITE
                print(f"{i+1:2}. {color}{name}{self.Colors.RESET}: {profile['simulation_time']}{profile['time_prefix']} - {profile.get('description', '')}{marker}")
            
            print()
            
            choice = input(f"{self.Colors.CYAN}Enter profile number to delete (1-{len(profile_list)}):{self.Colors.RESET} ").strip()
            if choice.lower() in ['cancel', 'abort', 'exit']:
                print("❌ Operation cancelled.")
                input("Press Enter to continue...")
                return
            
            try:
                choice_idx = int(choice) - 1
                if choice_idx < 0 or choice_idx >= len(profile_list):
                    raise ValueError()
                
                profile_name = profile_list[choice_idx][0]
                profile_data = profile_list[choice_idx][1]
                is_current = profile_name == current_profile
                
                # Confirm deletion
                print(f"\n{self.Colors.YELLOW}⚠️  Confirm deletion:{self.Colors.RESET}")
                print(f"   Profile: {self.Colors.YELLOW}{profile_name}{self.Colors.RESET}")
                print(f"   Settings: {profile_data['simulation_time']}{profile_data['time_prefix']}")
                if is_current:
                    print(f"   {self.Colors.RED}Warning: This is your currently active profile!{self.Colors.RESET}")
                print()
                
                confirm = input(f"{self.Colors.CYAN}Delete this profile? (y/N):{self.Colors.RESET} ").strip().lower()
                if confirm.lower() in ['cancel', 'abort', 'exit']:
                    print("❌ Operation cancelled.")
                    input("Press Enter to continue...")
                    return
                
                if confirm in ['y', 'yes']:
                    success = sim_manager.delete_user_simulation_profile(profile_name)
                    if success:
                        print(f"✅ {self.Colors.GREEN}Deleted profile '{profile_name}'{self.Colors.RESET}")
                        
                        # If deleted profile was current, suggest switching
                        if is_current:
                            print(f"{self.Colors.YELLOW}💡 Deleted profile was active. Consider applying a different profile.{self.Colors.RESET}")
                    else:
                        print(f"❌ Failed to delete profile '{profile_name}'")
                else:
                    print("ℹ️ Deletion cancelled.")
                
            except ValueError:
                print("❌ Invalid choice. Please enter a valid number.")
            except Exception as e:
                print(f"❌ Error deleting profile: {e}")
                
        except Exception as e:
            print(f"❌ Error loading user profiles: {e}")
        
        input("Press Enter to continue...")

    def _export_simulation_profile(self, sim_manager):
        """Export a simulation profile to a file."""
        self.clear_screen()
        self.display_header()
        print("📤 Export Simulation Profile")
        print("─" * 55)
        self.display_input_legend()
        print()
        
        try:
            all_profiles = sim_manager.list_all_simulation_profiles()
            
            if not all_profiles:
                print("❌ No profiles available to export")
                input("Press Enter to continue...")
                return
            
            # Display all profiles
            profile_list = list(all_profiles.items())
            
            print(f"{self.Colors.BLUE}Available profiles for export:{self.Colors.RESET}")
            print()
            
            for i, (name, profile) in enumerate(profile_list):
                profile_type = profile.get('type', 'unknown')
                type_color = self.Colors.GREEN if profile_type == 'preset' else self.Colors.CYAN
                print(f"{i+1:2}. {name:15} | {profile['simulation_time']:>6}{profile['time_prefix']:>3} | {type_color}{profile_type:>7}{self.Colors.RESET} | {profile.get('description', '')}")
            
            print()
            
            choice = input(f"{self.Colors.CYAN}Enter profile number to export (1-{len(profile_list)}):{self.Colors.RESET} ").strip()
            if choice.lower() in ['cancel', 'abort', 'exit']:
                print("❌ Operation cancelled.")
                input("Press Enter to continue...")
                return
            
            try:
                choice_idx = int(choice) - 1
                if choice_idx < 0 or choice_idx >= len(profile_list):
                    raise ValueError()
                
                profile_name = profile_list[choice_idx][0]
                
                # Get export path
                self.display_syntax_legend("file_path")
                default_filename = f"{profile_name}_profile.yml"
                export_path = input(f"{self.Colors.CYAN}Enter export file path (default: {default_filename}):{self.Colors.RESET} ").strip()
                if export_path.lower() in ['cancel', 'abort', 'exit']:
                    print("❌ Operation cancelled.")
                    input("Press Enter to continue...")
                    return
                
                if not export_path:
                    export_path = default_filename
                
                # Export the profile
                success = sim_manager.export_simulation_profile(profile_name, export_path)
                if success:
                    print(f"✅ {self.Colors.GREEN}Exported profile '{profile_name}' to {export_path}{self.Colors.RESET}")
                else:
                    print(f"❌ Failed to export profile '{profile_name}'")
                
            except ValueError:
                print("❌ Invalid choice. Please enter a valid number.")
            except Exception as e:
                print(f"❌ Error exporting profile: {e}")
                
        except Exception as e:
            print(f"❌ Error loading profiles: {e}")
        
        input("Press Enter to continue...")

    def _import_simulation_profile(self, sim_manager):
        """Import a simulation profile from a file."""
        self.clear_screen()
        self.display_header()
        print("📥 Import Simulation Profile")
        print("─" * 55)
        self.display_input_legend()
        print()
        
        print(f"{self.Colors.BLUE}💡 Import a simulation profile from a YAML file{self.Colors.RESET}")
        print("   The file should be created by the export function or follow the same format.")
        print()
        
        self.display_syntax_legend("file_path")
        
        import_path = input(f"{self.Colors.CYAN}Enter path to profile file:{self.Colors.RESET} ").strip()
        if import_path.lower() in ['cancel', 'abort', 'exit']:
            print("❌ Operation cancelled.")
            input("Press Enter to continue...")
            return
        
        if not import_path:
            print("❌ File path cannot be empty!")
            input("Press Enter to continue...")
            return
        
        # Check if file exists
        if not os.path.exists(import_path):
            print(f"❌ File not found: {import_path}")
            input("Press Enter to continue...")
            return
        
        try:
            # Import the profile
            success = sim_manager.import_simulation_profile(import_path)
            if success:
                print(f"✅ {self.Colors.GREEN}Successfully imported profile from {import_path}{self.Colors.RESET}")
                
                # Ask if user wants to apply the imported profile
                apply_now = input(f"{self.Colors.CYAN}Apply the imported profile now? (Y/n):{self.Colors.RESET} ").strip().lower()
                if apply_now not in ['n', 'no']:
                    # We need to get the profile name from the file
                    try:
                        import yaml
                        with open(import_path, 'r') as f:
                            imported_data = yaml.safe_load(f)
                        profile_name = imported_data.get("profile_name")
                        
                        if profile_name:
                            apply_success = sim_manager.apply_simulation_preset(profile_name)
                            if apply_success:
                                print(f"✅ {self.Colors.GREEN}Profile '{profile_name}' is now active{self.Colors.RESET}")
                            else:
                                print(f"❌ Failed to apply profile '{profile_name}'")
                    except Exception as e:
                        print(f"❌ Could not apply imported profile: {e}")
            else:
                print(f"❌ Failed to import profile from {import_path}")
                print("💡 Check that the file format is correct and the profile doesn't already exist.")
                
        except Exception as e:
            print(f"❌ Error importing profile: {e}")
        
        input("Press Enter to continue...")

    def behavioral_simulation(self):
        """Run behavioral simulation."""
        self.clear_screen()
        self.display_header()
        print("🧪 Behavioral Simulation")
        print("─" * 55)
        self.display_input_legend()
        print()
        
        # Find and display available testbenches
        available_testbenches = self._find_available_testbenches()
        testbench_files = self._display_available_testbenches()
        
        if available_testbenches:
            print(f"{self.Colors.BLUE}💡 Detected testbench entities:{self.Colors.RESET}")
            for i, testbench in enumerate(available_testbenches, 1):
                print(f"  {self.Colors.GREEN}{i:2}. {testbench}{self.Colors.RESET}")
            print()
        
        # Display simulation settings
        try:
            from cc_project_manager_pkg.simulation_manager import SimulationManager
            sim_manager = SimulationManager()
            sim_settings = sim_manager.get_simulation_length()
            current_profile = sim_manager.get_current_simulation_profile()
            
            if sim_settings:
                sim_time, time_prefix = sim_settings
                print(f"{self.Colors.BLUE}📊 Current simulation configuration:{self.Colors.RESET}")
                print(f"   Active Profile: {self.Colors.CYAN}{current_profile}{self.Colors.RESET}")
                print(f"   Duration: {self.Colors.CYAN}{sim_time}{time_prefix}{self.Colors.RESET}")
                print()
            else:
                print(f"{self.Colors.YELLOW}⚠️  No simulation settings found. Using defaults.{self.Colors.RESET}")
                print()
        except Exception as e:
            print(f"{self.Colors.YELLOW}⚠️  Could not load simulation settings: {e}{self.Colors.RESET}")
            print()
        
        print(f"{self.Colors.BLUE}💡 This will run the complete behavioral simulation flow:{self.Colors.RESET}")
        print(f"   1. {self.Colors.CYAN}Prepare{self.Colors.RESET} testbench (analyze & elaborate all files)")
        print(f"   2. {self.Colors.CYAN}Simulate{self.Colors.RESET} the testbench entity")
        print(f"   3. {self.Colors.CYAN}Generate{self.Colors.RESET} VCD waveform file")
        print()
        
        # Ask if user wants to use automatic testbench detection or specify manually
        proceed = input(f"{self.Colors.CYAN}Use automatic testbench detection from project? (Y/n):{self.Colors.RESET} ").strip().lower()
        if proceed in ['cancel', 'abort', 'exit']:
            print("❌ Operation cancelled.")
            input("Press Enter to continue...")
            return
            
        use_auto_detection = proceed not in ['n', 'no']
        
        if use_auto_detection:
            print(f"\n🔄 {self.Colors.BLUE}Running automatic behavioral simulation...{self.Colors.RESET}")
            print("   Using top-level testbench from project configuration")
            print()
            
            try:
                success = sim_manager.behavioral_simulate()
                
                if success:
                    print(f"\n✅ {self.Colors.GREEN}Behavioral simulation completed successfully!{self.Colors.RESET}")
                    print(f"📁 Check the {self.Colors.CYAN}sim/behavioral/{self.Colors.RESET} directory for VCD waveform files")
                    print(f"🔬 Use GTKWave or similar tool to view the waveforms")
                else:
                    print(f"\n❌ {self.Colors.RED}Behavioral simulation failed{self.Colors.RESET}")
                    print("💡 Check the output above for detailed error information.")
                    print("   Common issues: syntax errors, missing entities, incorrect dependencies")
            except Exception as e:
                print(f"❌ Simulation error: {e}")
        else:
            # Manual testbench selection
            self.display_syntax_legend("testbench_name")
            testbench = input(f"{self.Colors.CYAN}Enter testbench entity name:{self.Colors.RESET} ").strip()
            if testbench.lower() in ['cancel', 'abort', 'exit']:
                print("❌ Operation cancelled.")
                input("Press Enter to continue...")
                return
                
            if not testbench:
                print("❌ Testbench name cannot be empty!")
                input("Press Enter to continue...")
                return
            
            # Check if the testbench exists in available testbenches
            if available_testbenches and testbench not in available_testbenches:
                print(f"{self.Colors.YELLOW}⚠️  Warning: '{testbench}' not found in detected testbench entities.{self.Colors.RESET}")
                print(f"💡 Make sure the testbench name is correct and the testbench file is in the project.")
                proceed = input(f"{self.Colors.CYAN}Continue anyway? (y/N):{self.Colors.RESET} ").strip().lower()
                if proceed not in ['y', 'yes']:
                    print("❌ Operation cancelled.")
                    input("Press Enter to continue...")
                    return
            
            try:
                print(f"\n🔄 {self.Colors.BLUE}Running behavioral simulation for {self.Colors.CYAN}{testbench}{self.Colors.RESET}...")
                print("   This includes automatic preparation (analyze & elaborate)")
                print()
                
                # Prepare the specific testbench
                success = sim_manager.prepare_testbench_for_simulation(testbench)
                if not success:
                    print(f"❌ Failed to prepare testbench '{testbench}' for simulation")
                    input("Press Enter to continue...")
                    return
                
                # Now run the simulation using the built-in behavioral simulation method
                print(f"🚀 Running simulation for {testbench}...")
                
                # Get simulation settings
                sim_settings = sim_manager.get_simulation_length()
                if sim_settings:
                    simulation_time, time_prefix = sim_settings
                else:
                    simulation_time, time_prefix = 1000, "ns"
                
                # Since we've already prepared the testbench, we can call the GHDL behavioral_simulation directly
                success = sim_manager.behavioral_simulation(
                    testbench, 
                    options=None,  # No special command options needed
                    run_options=[f"--stop-time={simulation_time}{time_prefix}"]  # Pass simulation time as run option
                )
                
                if success:
                    print(f"\n✅ {self.Colors.GREEN}Behavioral simulation completed successfully!{self.Colors.RESET}")
                    print(f"📁 Check the {self.Colors.CYAN}sim/behavioral/{self.Colors.RESET} directory for VCD waveform files")
                    print(f"🔬 Use GTKWave or similar tool to view the waveforms")
                else:
                    print(f"\n❌ {self.Colors.RED}Behavioral simulation failed{self.Colors.RESET}")
                    print("💡 Check the GHDL logs for detailed error information.")
                
            except Exception as e:
                print(f"❌ Simulation error: {e}")
        
        input("Press Enter to continue...")

    def post_synthesis_simulation(self):
        """Run post-synthesis simulation using synthesized netlist."""
        self.clear_screen()
        self.display_header()
        print("🔬 Post-Synthesis Simulation")
        print("─" * 55)
        self.display_input_legend()
        print()
        
        # Check if synthesis has been completed
        synth_dir = None
        available_netlists = []
        
        try:
            hierarchy = HierarchyManager()
            if hierarchy.config and "project_structure" in hierarchy.config:
                synth_dir = hierarchy.config["project_structure"]["synth"][0]
                
                # Check for available synthesized netlists
                if os.path.exists(synth_dir):
                    available_netlists = [f for f in os.listdir(synth_dir) if f.endswith('.v')]
                    
            if not available_netlists:
                print(f"❌ {self.Colors.RED}No synthesized netlists found!{self.Colors.RESET}")
                print()
                print("You need to run synthesis first before post-synthesis simulation.")
                print(f"💡 {self.Colors.CYAN}Use:{self.Colors.RESET} Synthesis → Run Synthesis")
                print()
                input("Press Enter to continue...")
                return
                
            print(f"{self.Colors.BLUE}📋 Available synthesized netlists:{self.Colors.RESET}")
            for i, netlist in enumerate(available_netlists, 1):
                entity_name = netlist.replace('_synth.v', '').replace('.v', '')
                print(f"  {self.Colors.GREEN}{i:2}. {netlist}{self.Colors.RESET} (Entity: {entity_name})")
            print()
                
        except Exception as e:
            print(f"❌ {self.Colors.RED}Project configuration error:{self.Colors.RESET} {e}")
            print()
            input("Press Enter to continue...")
            return
        
        # Display simulation settings without excessive logging
        try:
            from cc_project_manager_pkg.simulation_manager import SimulationManager
            
            # Temporarily suppress all output during SimulationManager initialization
            import sys
            original_stdout = sys.stdout
            original_stderr = sys.stderr
            
            with open(os.devnull, 'w') as devnull:
                sys.stdout = devnull
                sys.stderr = devnull
                try:
                    sim_manager = SimulationManager()
                    sim_settings = sim_manager.get_simulation_length()
                    current_profile = sim_manager.get_current_simulation_profile()
                finally:
                    sys.stdout = original_stdout
                    sys.stderr = original_stderr
            
            if sim_settings:
                sim_time, time_prefix = sim_settings
                print(f"{self.Colors.BLUE}📊 Current simulation configuration:{self.Colors.RESET}")
                print(f"   Active Profile: {self.Colors.CYAN}{current_profile}{self.Colors.RESET}")
                print(f"   Duration: {self.Colors.CYAN}{sim_time}{time_prefix}{self.Colors.RESET}")
                print()
        except Exception:
            print(f"{self.Colors.YELLOW}📊 Using default simulation settings{self.Colors.RESET}")
            print()
        
        print(f"{self.Colors.BLUE}💡 VHDL Post-synthesis simulation:{self.Colors.RESET}")
        print(f"   • Synthesizes VHDL to netlist, then simulates with VHDL testbenches")
        print(f"   • Tests actual synthesized logic, not behavioral code")
        print(f"   • Uses existing GHDL toolchain and familiar VHDL testbenches")
        print()
        
        # Ask user to select entity to simulate
        self.display_syntax_legend("entity_name")
        
        # Select entity to simulate
        entity_name = input(f"{self.Colors.CYAN}Enter synthesized entity name to simulate:{self.Colors.RESET} ").strip()
        if entity_name.lower() in ['cancel', 'abort', 'exit']:
            print("❌ Operation cancelled.")
            input("Press Enter to continue...")
            return
            
        if not entity_name:
            print("❌ Entity name cannot be empty!")
            input("Press Enter to continue...")
            return
        
        # Check if corresponding netlist exists
        expected_netlist = f"{entity_name}_synth.v"
        if expected_netlist not in available_netlists:
            print(f"❌ Synthesized netlist not found: {expected_netlist}")
            print(f"💡 Available netlists: {', '.join(available_netlists)}")
            input("Press Enter to continue...")
            return
        
        # Ask for testbench selection
        proceed = input(f"{self.Colors.CYAN}Use automatic testbench detection? (Y/n):{self.Colors.RESET} ").strip().lower()
        if proceed in ['cancel', 'abort', 'exit']:
            print("❌ Operation cancelled.")
            input("Press Enter to continue...")
            return
            
        use_auto_detection = proceed not in ['n', 'no']
        
        try:
            print(f"\n🔄 {self.Colors.BLUE}Running post-synthesis simulation...{self.Colors.RESET}")
            print(f"   Entity: {entity_name}")
            print()
            
            # Suppress output during simulation execution
            with open(os.devnull, 'w') as devnull:
                original_stdout = sys.stdout
                original_stderr = sys.stderr
                sys.stdout = devnull
                sys.stderr = devnull
                
                try:
                    if use_auto_detection:
                        success = sim_manager.post_synthesis_simulate(entity_name)
                    else:
                        # Manual testbench selection
                        sys.stdout = original_stdout
                        sys.stderr = original_stderr
                        
                        testbench = input(f"{self.Colors.CYAN}Enter testbench entity name:{self.Colors.RESET} ").strip()
                        if testbench.lower() in ['cancel', 'abort', 'exit']:
                            print("❌ Operation cancelled.")
                            input("Press Enter to continue...")
                            return
                            
                        if not testbench:
                            print("❌ Testbench name cannot be empty!")
                            input("Press Enter to continue...")
                            return
                        
                        sys.stdout = devnull
                        sys.stderr = devnull
                        success = sim_manager.post_synthesis_simulate(entity_name, testbench)
                finally:
                    sys.stdout = original_stdout
                    sys.stderr = original_stderr
            
            if success:
                print(f"✅ {self.Colors.GREEN}Post-synthesis simulation completed successfully!{self.Colors.RESET}")
                print(f"📁 Check the {self.Colors.CYAN}sim/post-synthesis/{self.Colors.RESET} directory for VCD waveform files")
                print(f"🔬 Use GTKWave to view the waveforms and compare with behavioral simulation")
            else:
                print(f"❌ {self.Colors.RED}Post-synthesis simulation failed{self.Colors.RESET}")
                print("💡 Check the GHDL logs for detailed error information.")
                    
        except Exception as e:
            print(f"❌ Post-synthesis simulation error: {e}")
        
        input("Press Enter to continue...")

    def launch_simulation_menu(self):
        """Launch simulation menu to select and open VCD files with GTKWave."""
        from cc_project_manager_pkg.simulation_manager import SimulationManager
        
        sim_manager = SimulationManager()
        
        # Check GTKWave availability first
        if not sim_manager.check_gtkwave():
            self.clear_screen()
            self.display_header()
            print("🌊 Launch Simulation")
            print("─" * 55)
            print()
            print(f"❌ {self.Colors.RED}GTKWave is not available{self.Colors.RESET}")
            print("💡 Please configure GTKWave path in Configuration menu first.")
            print()
            input("Press Enter to continue...")
            return
        
        options = [
            "Behavioral Simulations",
            "Post-Synthesis Simulations",
            "Launch Simulation",
            "Configure Simulation Settings",
            "Manage Simulation Profiles",
            "View Simulation Logs",
            "Back to Simulation Menu"
        ]
        
        current_selection = 0
        
        while True:
            self.clear_screen()
            self.display_header()
            self.display_menu("Launch Simulation", options, current_selection)
            
            # Display available simulations count
            available_sims = sim_manager.get_available_simulations()
            print(f"\n{self.Colors.BLUE}📊 Available Simulations:{self.Colors.RESET}")
            print(f"   Behavioral: {self.Colors.GREEN}{len(available_sims['behavioral'])}{self.Colors.RESET}")
            print(f"   Post-Synthesis: {self.Colors.GREEN}{len(available_sims['post-synthesis'])}{self.Colors.RESET}")
            print(f"   Post-Implementation: {self.Colors.GREEN}{len(available_sims['post-implementation'])}{self.Colors.RESET}")
            
            key = get_key()
            
            if key == 'w':  # Up
                current_selection = (current_selection - 1) % len(options)
            elif key == 's':  # Down
                current_selection = (current_selection + 1) % len(options)
            elif key == '\r' or key == '\n' or key == 'd':  # Enter or D for select
                if current_selection == 0:
                    self._launch_simulation_by_type("behavioral", available_sims["behavioral"])
                elif current_selection == 1:
                    self._launch_simulation_by_type("post-synthesis", available_sims["post-synthesis"])
                elif current_selection == 2:
                    self._launch_simulation_by_type("post-implementation", available_sims["post-implementation"])
                elif current_selection == 3:
                    self._launch_latest_simulation(sim_manager)
                elif current_selection == 4:
                    self._launch_latest_simulation(sim_manager)
                elif current_selection == 5:
                    self._launch_latest_simulation(sim_manager)
                elif current_selection == 6:
                    break  # Back to simulation menu
            elif key == 'a' or key == 'q':  # A for back or Q for quit
                break
    
    def _launch_simulation_by_type(self, sim_type: str, simulations: list):
        """Launch a specific simulation by type."""
        self.clear_screen()
        self.display_header()
        print(f"🌊 {sim_type.title()} Simulations")
        print("─" * 55)
        
        if not simulations:
            print(f"❌ No {sim_type} simulations found")
            print(f"💡 Run a {sim_type} simulation first to generate VCD files")
            input("Press Enter to continue...")
            return
        
        print(f"{self.Colors.BLUE}Available {sim_type} simulations:{self.Colors.RESET}")
        print()
        
        for i, sim in enumerate(simulations, 1):
            size_mb = sim["size"] / (1024 * 1024)
            print(f"{i:2d}. {self.Colors.GREEN}{sim['name']}{self.Colors.RESET}")
            print(f"     Entity: {sim['entity']}")
            print(f"     Size: {size_mb:.2f} MB")
            print(f"     Modified: {sim['modified'].strftime('%Y-%m-%d %H:%M:%S')}")
            print()
        
        self.display_input_legend()
        choice = input(f"{self.Colors.CYAN}Select simulation (1-{len(simulations)}) or 'cancel':{self.Colors.RESET} ").strip()
        
        if choice.lower() in ['cancel', 'abort', 'exit']:
            return
        
        try:
            selection = int(choice) - 1
            if 0 <= selection < len(simulations):
                selected_sim = simulations[selection]
                print(f"🌊 Launching GTKWave with {selected_sim['name']}...")
                
                from cc_project_manager_pkg.simulation_manager import SimulationManager
                sim_manager = SimulationManager()
                
                if sim_manager.launch_wave(selected_sim['path']):
                    print("✅ GTKWave launched successfully!")
                else:
                    print("❌ Failed to launch GTKWave")
            else:
                print("❌ Invalid selection")
        except ValueError:
            print("❌ Invalid input. Please enter a number.")
        
        input("Press Enter to continue...")
    
    def _launch_latest_simulation(self, sim_manager):
        """Launch the most recent simulation VCD file."""
        self.clear_screen()
        self.display_header()
        print("🌊 Launch Latest Simulation")
        print("─" * 55)
        
        print("🔍 Finding latest simulation...")
        
        if sim_manager.launch_wave():
            print("✅ GTKWave launched with latest simulation!")
        else:
            print("❌ No simulations found or failed to launch GTKWave")
        
        input("Press Enter to continue...")

    def configure_gtkwave(self):
        """Configure GTKWave settings."""
        from cc_project_manager_pkg.simulation_manager import SimulationManager
        
        options = [
            "Check GTKWave Status",
            "Set GTKWave Path",
            "Test GTKWave",
            "Back to Configuration Menu"
        ]
        
        current_selection = 0
        
        while True:
            self.clear_screen()
            self.display_header()
            self.display_menu("Configure GTKWave", options, current_selection)
            
            # Display current GTKWave status
            sim_manager = SimulationManager()
            preference = sim_manager.project_config.get("gtkwave_preference", "UNDEFINED")
            gtkwave_path = sim_manager.project_config.get("gtkwave_tool_path", {}).get("gtkwave", "Not configured")
            
            print(f"\n{self.Colors.BLUE}📊 Current GTKWave Status:{self.Colors.RESET}")
            print(f"   Preference: {self.Colors.GREEN if preference != 'UNDEFINED' else self.Colors.RED}{preference}{self.Colors.RESET}")
            print(f"   Path: {self.Colors.GREEN if gtkwave_path != 'Not configured' else self.Colors.YELLOW}{gtkwave_path}{self.Colors.RESET}")
            
            key = get_key()
            
            if key == 'w':  # Up
                current_selection = (current_selection - 1) % len(options)
            elif key == 's':  # Down
                current_selection = (current_selection + 1) % len(options)
            elif key == '\r' or key == '\n' or key == 'd':  # Enter or D for select
                if current_selection == 0:
                    self._check_gtkwave_status()
                elif current_selection == 1:
                    self._set_gtkwave_path()
                elif current_selection == 2:
                    self._test_gtkwave()
                elif current_selection == 3:
                    break  # Back to configuration menu
            elif key == 'a' or key == 'q':  # A for back or Q for quit
                break
    
    def _check_gtkwave_status(self):
        """Check and display GTKWave availability status."""
        self.clear_screen()
        self.display_header()
        print("🔍 GTKWave Status Check")
        print("─" * 55)
        print()
        
        from cc_project_manager_pkg.simulation_manager import SimulationManager
        sim_manager = SimulationManager()
        
        print("🔍 Checking GTKWave availability...")
        print()
        
        # Check PATH availability
        print(f"{self.Colors.BOLD}PATH Availability:{self.Colors.RESET}")
        if sim_manager.check_gtkwave_path():
            print(f"   {self.Colors.GREEN}✅ GTKWave available through PATH{self.Colors.RESET}")
        else:
            print(f"   {self.Colors.RED}❌ GTKWave not available through PATH{self.Colors.RESET}")
        
        print()
        
        # Check direct path availability
        print(f"{self.Colors.BOLD}Direct Path Availability:{self.Colors.RESET}")
        if sim_manager.check_gtkwave_direct():
            print(f"   {self.Colors.GREEN}✅ GTKWave available at configured path{self.Colors.RESET}")
            direct_path = sim_manager.project_config.get("gtkwave_tool_path", {}).get("gtkwave", "")
            print(f"   Path: {direct_path}")
        else:
            print(f"   {self.Colors.YELLOW}⚠️ GTKWave not configured or not working at direct path{self.Colors.RESET}")
        
        print()
        
        # Overall status
        print(f"{self.Colors.BOLD}Overall Status:{self.Colors.RESET}")
        if sim_manager.check_gtkwave():
            print(f"   {self.Colors.GREEN}✅ GTKWave is available and ready to use{self.Colors.RESET}")
        else:
            print(f"   {self.Colors.RED}❌ GTKWave is not available{self.Colors.RESET}")
            print(f"   💡 Configure GTKWave path using option 2")
        
        input("\nPress Enter to continue...")
    
    def _set_gtkwave_path(self):
        """Set GTKWave executable path."""
        self.clear_screen()
        self.display_header()
        print("📂 Set GTKWave Path")
        print("─" * 55)
        self.display_input_legend()
        print()
        
        print(f"{self.Colors.BLUE}💡 Enter the full path to GTKWave executable:{self.Colors.RESET}")
        if os.name == 'nt':  # Windows
            print("   Example: C:\\gtkwave\\bin\\gtkwave.exe")
        else:  # Unix/Linux
            print("   Example: /usr/bin/gtkwave")
        print()
        
        path = input(f"{self.Colors.CYAN}GTKWave path:{self.Colors.RESET} ").strip()
        
        if path.lower() in ['cancel', 'abort', 'exit']:
            print("❌ Operation cancelled.")
            input("Press Enter to continue...")
            return
        
        if not path:
            print("❌ No path provided.")
            input("Press Enter to continue...")
            return
        
        try:
            from cc_project_manager_pkg.simulation_manager import SimulationManager
            sim_manager = SimulationManager()
            
            print(f"🔍 Testing GTKWave at: {path}")
            
            if sim_manager.add_gtkwave_path(path):
                print(f"✅ {self.Colors.GREEN}GTKWave path configured successfully!{self.Colors.RESET}")
                print(f"📁 Path: {path}")
            else:
                print(f"❌ {self.Colors.RED}Failed to configure GTKWave path{self.Colors.RESET}")
                print("💡 Check that the path exists and points to a valid GTKWave executable")
                
        except Exception as e:
            print(f"❌ Error configuring GTKWave: {e}")
        
        input("Press Enter to continue...")
    
    def _test_gtkwave(self):
        """Test GTKWave functionality."""
        self.clear_screen()
        self.display_header()
        print("🧪 Test GTKWave")
        print("─" * 55)
        print()
        
        from cc_project_manager_pkg.simulation_manager import SimulationManager
        sim_manager = SimulationManager()
        
        print("🧪 Testing GTKWave functionality...")
        print()
        
        # Check if GTKWave is available
        if not sim_manager.check_gtkwave():
            print(f"❌ {self.Colors.RED}GTKWave is not available{self.Colors.RESET}")
            print("💡 Please configure GTKWave path first (option 2)")
            input("Press Enter to continue...")
            return
        
        # Check for available simulations
        available_sims = sim_manager.get_available_simulations()
        total_sims = len(available_sims["behavioral"]) + len(available_sims["post-synthesis"]) + len(available_sims["post-implementation"])
        
        if total_sims == 0:
            print(f"⚠️ {self.Colors.YELLOW}No VCD files found to test with{self.Colors.RESET}")
            print("💡 Run a simulation first to generate VCD files for testing")
            print()
            print("Testing GTKWave version check...")
            
            # Test version check
            gtkwave_cmd = sim_manager._get_gtkwave_access()
            try:
                import subprocess
                result = subprocess.run([gtkwave_cmd, "--version"], 
                                      capture_output=True, text=True, check=True, timeout=10)
                print(f"✅ {self.Colors.GREEN}GTKWave version check successful{self.Colors.RESET}")
                print(f"Version info: {result.stdout.strip()}")
            except Exception as e:
                print(f"❌ {self.Colors.RED}GTKWave version check failed: {e}{self.Colors.RESET}")
        else:
            print(f"✅ {self.Colors.GREEN}GTKWave is configured and ready{self.Colors.RESET}")
            print(f"📊 Found {total_sims} VCD files available for viewing")
            print("💡 You can test GTKWave by using 'Launch Simulation' menu")
        
        input("Press Enter to continue...")

    def manage_constraint_files(self):
        """Manage constraint files for Place & Route operations."""
        from cc_project_manager_pkg.pnr_commands import PnRCommands
        
        try:
            pnr = PnRCommands()
        except Exception as e:
            self.clear_screen()
            self.display_header()
            print("❌ Failed to initialize PnRCommands")
            print(f"Error: {e}")
            input("Press Enter to continue...")
            return
        
        options = [
            "View Constraint Files",
            "Create Default Constraint File",
            "Select Constraint File for P&R",
            "Back to Implementation Menu"
        ]
        
        current_selection = 0
        
        while True:
            self.clear_screen()
            self.display_header()
            print("📋 Manage Constraint Files")
            print("─" * 55)
            
            # Show quick summary
            try:
                constraint_files = pnr.list_available_constraint_files()
                default_file = pnr.get_default_constraint_file_path()
                default_exists = pnr.check_constraint_file_exists()
                
                print(f"{self.Colors.BLUE}📊 Constraint Files Status:{self.Colors.RESET}")
                print(f"   Available: {self.Colors.GREEN}{len(constraint_files)}{self.Colors.RESET}")
                print(f"   Default ({os.path.basename(default_file)}): {'✅' if default_exists else '❌'}")
                print()
            except Exception as e:
                print(f"{self.Colors.YELLOW}⚠️  Error loading constraint files: {e}{self.Colors.RESET}")
                print()
            
            print(f"📋 Constraint Management Menu")
            print("─" * 55)
            
            for i, option in enumerate(options):
                if i == current_selection:
                    print(f"{self.Colors.GREEN}▶  {option}  ◀{self.Colors.RESET}")
                else:
                    print(f"   {option}")
            
            print()
            self.display_controls()
            
            key = get_key()
            
            if key == 'w':  # Up
                current_selection = (current_selection - 1) % len(options)
            elif key == 's':  # Down
                current_selection = (current_selection + 1) % len(options)
            elif key == '\r' or key == '\n' or key == 'd':  # Enter or D for select
                if current_selection == 0:
                    self._view_constraint_files(pnr)
                elif current_selection == 1:
                    self._create_default_constraint_file(pnr)
                elif current_selection == 2:
                    self._select_constraint_file(pnr)
                elif current_selection == 3:
                    break  # Back to implementation menu
            elif key == 'a' or key == 'q':  # A for back or Q for quit
                break

    def _view_constraint_files(self, pnr):
        """View all available constraint files."""
        self.clear_screen()
        self.display_header()
        print("📋 View Constraint Files")
        print("─" * 55)
        
        try:
            constraint_files = pnr.list_available_constraint_files()
            default_file_path = pnr.get_default_constraint_file_path()
            default_file_name = os.path.basename(default_file_path)
            
            if not constraint_files:
                print(f"{self.Colors.YELLOW}ℹ️  No constraint files found in constraints directory{self.Colors.RESET}")
                print(f"📁 Constraints directory: {pnr.constraints_dir}")
                print()
                print("💡 You can create a default constraint file from the menu")
            else:
                print(f"{self.Colors.BLUE}📋 Available constraint files:{self.Colors.RESET}")
                print(f"📁 Location: {pnr.constraints_dir}")
                print()
                
                for i, file_name in enumerate(constraint_files, 1):
                    is_default = file_name == default_file_name
                    status_icon = "⭐" if is_default else "📄"
                    status_text = " (default)" if is_default else ""
                    file_path = pnr.get_constraint_file_path(file_name)
                    
                    print(f"   {status_icon} {self.Colors.GREEN}{file_name}{self.Colors.RESET}{status_text}")
                    print(f"      📁 {file_path}")
                    
                    # Check if file exists and show size
                    if os.path.exists(file_path):
                        file_size = os.path.getsize(file_path)
                        print(f"      📊 Size: {file_size} bytes")
                    else:
                        print(f"      ❌ {self.Colors.RED}File not found{self.Colors.RESET}")
                    print()
                
        except Exception as e:
            print(f"❌ Error viewing constraint files: {e}")
        
        input("Press Enter to continue...")

    def _create_default_constraint_file(self, pnr):
        """Create or recreate the default constraint file."""
        self.clear_screen()
        self.display_header()
        print("➕ Create Default Constraint File")
        print("─" * 55)
        
        default_file_path = pnr.get_default_constraint_file_path()
        default_file_name = os.path.basename(default_file_path)
        file_exists = pnr.check_constraint_file_exists()
        
        print(f"{self.Colors.BLUE}Default constraint file:{self.Colors.RESET}")
        print(f"   📄 Name: {self.Colors.CYAN}{default_file_name}{self.Colors.RESET}")
        print(f"   📁 Path: {default_file_path}")
        print(f"   Status: {'✅ Exists' if file_exists else '❌ Not found'}")
        print()
        
        if file_exists:
            print(f"{self.Colors.YELLOW}⚠️  Default constraint file already exists.{self.Colors.RESET}")
            print("Creating a new one will overwrite the existing file.")
            print()
            
            confirm = input(f"{self.Colors.CYAN}Overwrite existing file? (y/N):{self.Colors.RESET} ").strip().lower()
            if confirm not in ['y', 'yes']:
                print("ℹ️ Operation cancelled.")
                input("Press Enter to continue...")
                return
            overwrite = True
        else:
            print("💡 This will create a template constraint file with common pin assignments.")
            print()
            overwrite = False
        
        try:
            success = pnr.create_default_constraint_file(overwrite=overwrite)
            if success:
                print(f"✅ {self.Colors.GREEN}Default constraint file created successfully!{self.Colors.RESET}")
                print(f"📄 File: {default_file_name}")
                print("💡 Edit the file to add your project-specific pin assignments.")
            else:
                print(f"❌ Failed to create default constraint file")
        except Exception as e:
            print(f"❌ Error creating constraint file: {e}")
        
        input("Press Enter to continue...")

    def _select_constraint_file(self, pnr):
        """Select a constraint file for P&R operations."""
        self.clear_screen()
        self.display_header()
        print("📌 Select Constraint File")
        print("─" * 55)
        
        try:
            constraint_files = pnr.list_available_constraint_files()
            
            if not constraint_files:
                print(f"{self.Colors.YELLOW}ℹ️  No constraint files found{self.Colors.RESET}")
                print("💡 Create a default constraint file first")
                input("Press Enter to continue...")
                return
            
            print(f"{self.Colors.BLUE}Available constraint files:{self.Colors.RESET}")
            print()
            
            # Add option for default (automatic selection)
            print(f"   0. {self.Colors.CYAN}Use default/automatic selection{self.Colors.RESET}")
            
            for i, file_name in enumerate(constraint_files, 1):
                print(f"   {i}. {self.Colors.GREEN}{file_name}{self.Colors.RESET}")
            
            print()
            
            choice = input(f"{self.Colors.CYAN}Enter choice (0-{len(constraint_files)}):{self.Colors.RESET} ").strip()
            if choice.lower() in ['cancel', 'abort', 'exit']:
                print("❌ Operation cancelled.")
                input("Press Enter to continue...")
                return
            
            try:
                choice_idx = int(choice)
                if choice_idx == 0:
                    print("✅ Set to use default/automatic constraint file selection")
                    print("💡 P&R will automatically use the default constraint file if available")
                elif 1 <= choice_idx <= len(constraint_files):
                    selected_file = constraint_files[choice_idx - 1]
                    print(f"✅ Selected constraint file: {self.Colors.GREEN}{selected_file}{self.Colors.RESET}")
                    print("💡 This selection is for information only. Use the P&R menu to specify constraint files.")
                else:
                    print("❌ Invalid choice")
                    
            except ValueError:
                print("❌ Invalid choice. Please enter a valid number.")
                
        except Exception as e:
            print(f"❌ Error selecting constraint file: {e}")
        
        input("Press Enter to continue...")

    def detect_manual_files(self):
        """Detect and optionally add manually placed files in project directories."""
        self.clear_screen()
        self.display_header()
        print("🔍 Detect Manual Files")
        print("─" * 55)
        print("This feature scans your project directories for VHDL files")
        print("that you may have manually added but are not tracked in the project.")
        print()
        
        try:
            hierarchy = HierarchyManager()
            detected_files = hierarchy.detect_manual_files()
            
            # Count total detected files
            total_detected = sum(len(files) for files in detected_files.values())
            
            if total_detected == 0:
                print(f"✅ {self.Colors.GREEN}No untracked files found!{self.Colors.RESET}")
                print("All VHDL files in your project directories are already tracked.")
                input("\nPress Enter to continue...")
                return
            
            print(f"🔍 {self.Colors.CYAN}Found {total_detected} untracked VHDL file(s):{self.Colors.RESET}")
            print()
            
            # Display detected files by category
            for category, files in detected_files.items():
                if files:
                    if category == "src":
                        icon = "🔧"
                        color = self.Colors.BLUE
                        name = "Source Files"
                    elif category == "testbench":
                        icon = "🧪"
                        color = self.Colors.YELLOW
                        name = "Testbench Files"
                    elif category == "top":
                        icon = "🔝"
                        color = self.Colors.MAGENTA
                        name = "Top-Level Files"
                    
                    print(f"{color}{icon} {name}:{self.Colors.RESET}")
                    for file_name, file_path in files.items():
                        print(f"   • {self.Colors.GREEN}{file_name}{self.Colors.RESET}")
                        print(f"     {self.Colors.CYAN}{file_path}{self.Colors.RESET}")
                    print()
            
            # Ask user what to do
            print(f"{self.Colors.BLUE}Options:{self.Colors.RESET}")
            print(f"1. {self.Colors.GREEN}Add all detected files{self.Colors.RESET}")
            print(f"2. {self.Colors.YELLOW}Add only source files{self.Colors.RESET}")
            print(f"3. {self.Colors.YELLOW}Add only testbench files{self.Colors.RESET}")
            print(f"4. {self.Colors.YELLOW}Add only top-level files{self.Colors.RESET}")
            print(f"5. {self.Colors.RED}Don't add any files{self.Colors.RESET}")
            
            self.display_input_legend()
            choice = input(f"{self.Colors.CYAN}Enter choice (1-5):{self.Colors.RESET} ").strip()
            
            if choice.lower() in ['cancel', 'abort', 'exit']:
                print("❌ Operation cancelled.")
                input("Press Enter to continue...")
                return
            
            if choice == "1":
                categories_to_add = ["src", "testbench", "top"]
            elif choice == "2":
                categories_to_add = ["src"]
            elif choice == "3":
                categories_to_add = ["testbench"]
            elif choice == "4":
                categories_to_add = ["top"]
            elif choice == "5":
                print("ℹ️  No files were added to the project.")
                input("Press Enter to continue...")
                return
            else:
                print("❌ Invalid choice!")
                input("Press Enter to continue...")
                return
            
            # Add the selected files
            try:
                added_summary = hierarchy.add_detected_files(detected_files, categories_to_add)
                
                print()
                print(f"✅ {self.Colors.GREEN}Successfully added {added_summary['total']} files:{self.Colors.RESET}")
                if added_summary['src'] > 0:
                    print(f"   🔧 Source files: {added_summary['src']}")
                if added_summary['testbench'] > 0:
                    print(f"   🧪 Testbench files: {added_summary['testbench']}")
                if added_summary['top'] > 0:
                    print(f"   🔝 Top-level files: {added_summary['top']}")
                
                print(f"\n💡 {self.Colors.CYAN}Tip:{self.Colors.RESET} Use 'View Project Status' to see all tracked files.")
                
            except Exception as e:
                print(f"❌ Failed to add detected files: {e}")
            
        except Exception as e:
            print(f"❌ Error during file detection: {e}")
        
        input("\nPress Enter to continue...")

    def _restore_logging(self):
        """Restore original stderr if it was redirected."""
        if hasattr(self, '_original_stderr') and self._original_stderr:
            import sys
            sys.stderr = self._original_stderr

def main():
    app = MenuSystem()
    try:
        app.run()
    except KeyboardInterrupt:
        print("\n\n👋 Goodbye!")
    except Exception as e:
        print(f"\n❌ An unexpected error occurred: {e}")
    finally:
        # Ensure cleanup happens even if there's an exception
        app._restore_logging()

if __name__ == "__main__":
    main() 