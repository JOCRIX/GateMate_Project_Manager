# Cologne Chip Project Manager

A comprehensive FPGA project management tool for GHDL, Yosys, and Place & Route workflows, specifically designed for Cologne Chip GateMate FPGAs. 

## Features

- **🖥️ Modern GUI Interface** - Beautiful PyQt5-based graphical interface with tabbed layout
- **📁 Project Management** - Create and manage FPGA project structures
![image](https://github.com/user-attachments/assets/99af9d5b-effe-418a-99c9-ab1523c78d87)

- **⚙️ VHDL Synthesis** - Integration with Yosys for VHDL synthesis with multiple optimization strategies
- **🔍 Simulation** - GHDL-based behavioral simulation with GTKWave integration
- **🛠️ Implementation** - Place & Route with Cologne Chip tools
- **🔧 Toolchain Management** - Automatic detection and configuration of FPGA tools
- **📊 Real-time Logging** - Live output window showing operation progress

## 🆕 GUI Interface Features

- **Tabbed Organization** - Project Management, Synthesis, Implementation, Simulation, and Configuration tabs
- **Real-time Log Display** - Color-coded log messages with different levels (INFO, WARNING, ERROR)
- **Threaded Operations** - Long-running operations don't freeze the interface
- **Dialog-based Configuration** - Easy-to-use dialogs for project creation and settings
- **Toolbar and Menus** - Standard GUI controls for better user experience
- **Status Bar** - Shows current operation status

## Package Structure

```
cc_project_manager/
├── cc_project_manager_pkg/            # Core package modules
│   ├── __init__.py                    # Package initialization
│   ├── __main__.py                   # Main entry point
│   ├── gui.py                        # PyQt5 GUI interface
│   ├── create_structure.py           # Project structure creation
│   ├── yosys_commands.py             # Yosys synthesis integration
│   ├── ghdl_commands.py              # GHDL simulation integration
│   ├── pnr_commands.py               # Place & Route commands
│   ├── simulation_manager.py         # Simulation management
│   ├── hierarchy_manager.py          # Project hierarchy management
│   ├── toolchain_manager.py          # Toolchain detection and management
│   ├── openfpgaloader_manager.py     # FPGA programming support
│   ├── vhdl_to_verilog_converter.py  # VHDL to Verilog conversion
│   ├── setup_openfpgaloader_path.py  # openFPGALoader setup helper
│   └── requirements.txt              # Python dependencies
├── setup.py                          # Package installation script
├── MANIFEST.in                       # Package manifest
├── .gitignore                        # Git ignore rules
├── GUI_QUICKSTART.md                 # GUI user guide
└── README.md                         # This file
```

## Installation

1. **Clone the repository:**
   ```bash
   git clone <repository-url>
   cd cc_project_manager
   ```

2. **Install Python dependencies:**
   ```bash
   pip install -r requirements.txt
   ```
   This installs PyQt5 for the GUI interface and other required packages.

3. **Install as a package (optional, for global commands):**
   ```bash
   pip install -e .
   ```
   This creates global commands (see Usage section below).

4. **Install FPGA toolchain:**
   - GHDL (for VHDL simulation)
   - Yosys (for synthesis)
   - Cologne Chip GateMate tools (for implementation)

5. **Configure openFPGALoader (optional but recommended):**
   ```bash
   python -m cc_project_manager_pkg.setup_openfpgaloader_path
   ```
   This helper script will detect and configure openFPGALoader for FPGA programming.

## Usage

### 🖥️ GUI Interface

**Using the package command:**
```bash
gmpm                           # Launches GUI by default
```

**Using Python module:**
```bash
python -m cc_project_manager_pkg       # Launches GUI by default
python -m cc_project_manager_pkg.gui   # Explicitly launch GUI
```

### 🎯 GUI Interface Guide

The GUI is organized into tabs for different operations:

#### **Project Management Tab**
- **Create New Project** - Opens a dialog to create new project structure
- **Add VHDL File** - Browse and add VHDL files to the project
- **Remove VHDL File** - Remove files from the project
- **View Project Status** - Display project information and file list
- **Detect Manual Files** - Scan for manually added files

#### **Synthesis Tab**
- **Run Synthesis** - Perform VHDL synthesis with Yosys
- **Configure Synthesis** - Set synthesis options (VHDL standard, target device, etc.)
- **View Synthesis Logs** - Open synthesis reports and logs

#### **Implementation Tab**
- **Place & Route** - Run place and route operations
- **Generate Bitstream** - Create programming files
- **Timing Analysis** - Perform timing analysis
- **Full Implementation** - Run complete implementation flow

#### **Simulation Tab**
- **Behavioral Simulation** - Run pre-synthesis simulation
- **Post-Synthesis Simulation** - Simulate synthesized design
- **Configure Simulation** - Set simulation parameters
- **Launch Waveform Viewer** - Open GTKWave for results

#### **Upload Tab**
- **Device Detection** - Automatically detect connected FPGA boards
- **Bitstream Upload** - Program the FPGA with generated bitstreams
- **Board Selection** - Choose target board type
- **Upload Progress** - Monitor programming status

#### **Configuration Tab**
- **Check Toolchain** - Verify tool availability
- **Edit Toolchain Paths** - Configure tool locations
- **Project Settings** - Modify project-specific settings

#### **Output Window**
The bottom panel shows real-time log messages with:
- **Color coding** - Different colors for INFO, WARNING, ERROR messages
- **Auto-scroll** - Automatically scrolls to show latest messages
- **Save Log** - Export log messages to file
- **Clear** - Clear the log display

## Available Commands After Installation

| Command | Description |
|---------|-------------|
| `gmpm` | Main launcher (GUI interface) |

## Requirements

- **Python 3.8+**
- **PyQt5 5.15+** (for GUI interface)
- **GHDL 5.0.1+**
- **Yosys 0.9+**
- **Cologne Chip GateMate toolchain**

### Creating a New Project

1. **Click "Create New Project"** in the Project Management tab
2. **Enter project name** and select directory
3. **Click "Create"**

The tool will create a complete project structure with folders for source files, simulation, synthesis, and implementation.

### Project Structure

Each project includes:
```
project_name/
├── src/                    # VHDL source files
├── testbench/             # VHDL testbench files
├── constraints/           # Constraint files
├── synth/                 # Synthesis outputs
├── sim/                   # Simulation outputs
│   ├── behavioral/        # Behavioral simulation
│   ├── post-synthesis/    # Post-synthesis simulation
│   └── post-implementation/ # Post-implementation simulation
├── impl/                  # Implementation outputs
│   ├── bitstream/         # Generated bitstreams
│   ├── timing/            # Timing analysis
│   └── netlist/           # Post-implementation netlists
├── build/                 # Build artifacts
├── logs/                  # Log files
└── config/                # Configuration files
```

## Testing

Test the package installation:
```bash
python test_package.py
```

## License

Do whatever you want with it.

## Author

JOCRIX

## Version

0.1.0

## Synthesis Strategies

The tool supports multiple synthesis optimization strategies:

- **area** - Minimize resource usage (LUTs, logic gates)
- **speed** - Maximize performance/frequency
- **balanced** - Balance area and speed (default)
- **quality** - Thorough optimization for better results
- **timing** - Advanced timing-driven optimization
- **extreme** - Maximum optimization for performance-critical designs

## Simulation Features

- **Behavioral Simulation** - Simulate original VHDL code
- **Post-Synthesis Simulation** - Simulate synthesized netlist
- **Post-Implementation Simulation** - Simulate placed & routed design
- **GTKWave Integration** - Automatic waveform viewer launch
- **Simulation Profiles** - Save and reuse simulation settings

## Implementation Features

- **Place & Route** - Automatic placement and routing with intelligent constraint file auto-detection
- **Bitstream Generation** - Generate programming files
- **Timing Analysis** - Check timing constraints
- **Multiple Strategies** - Speed, area, balanced, power optimization
- **FPGA Programming** - Direct upload to FPGA via openFPGALoader integration

## Configuration

The tool automatically detects installed FPGA tools and can be configured to use:
- **PATH** - Tools available in system PATH
- **DIRECT** - Direct paths to tool binaries

## Recent Project Memory

The application automatically remembers and reopens the most recently used project:
- **Automatic Loading** - Reopens last project on startup
- **Cross-Session** - Remembers projects between application restarts
- **Settings Storage** - Stored in user home directory (`~/.cc_project_manager/settings.json`) 
