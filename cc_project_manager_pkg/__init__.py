"""
Cologne Chip Project Manager Package

A comprehensive FPGA project management tool for GHDL, Yosys, and PnR workflows.
"""

# Import all main classes for easy access
from .create_structure import CreateStructure
from .yosys_commands import YosysCommands  
from .ghdl_commands import GHDLCommands
from .pnr_commands import PnRCommands
from .nextpnr_commands import NextPnRCommands
from .openfpgaloader_manager import OpenFPGALoaderManager
from .simulation_manager import SimulationManager
from .hierarchy_manager import HierarchyManager
from .toolchain_manager import ToolChainManager
from .boards_manager import BoardsManager

# Package metadata
__version__ = "0.4.0"
__author__ = "JOCRIX"
__description__ = "FPGA project management tool for Cologne Chip GateMate (OSS CAD Suite / nextpnr)"

# All exports
__all__ = [
    "CreateStructure",
    "YosysCommands", 
    "GHDLCommands",
    "PnRCommands",
    "NextPnRCommands",
    "OpenFPGALoaderManager",
    "SimulationManager", 
    "HierarchyManager",
    "ToolChainManager",
    "BoardsManager"
] 