# GateMate FPGA Project Manager

A comprehensive FPGA project management tool for GHDL, Yosys, and Place & Route workflows, specifically designed for Cologne Chip GateMate FPGAs. 

**The project is work-in-progress.**

## Features

- **📁 Project Management** - Create and manage FPGA project structures
![image](https://github.com/user-attachments/assets/99af9d5b-effe-418a-99c9-ab1523c78d87)

- **⚙️ VHDL Synthesis** - Integration with Yosys for VHDL synthesis with multiple optimization strategies

![image](https://github.com/user-attachments/assets/a0ae843a-f137-4827-b7ca-ab9f64bcf8c2)
 
- **🔍 Simulation** - GHDL-based behavioral simulation with GTKWave integration

![image](https://github.com/user-attachments/assets/a5212d34-19b4-4ca4-8e08-613a908ae48b)


- **🛠️ Implementation** - Place & Route with Cologne Chip tools

![image](https://github.com/user-attachments/assets/0c745c4f-4d77-4323-b3bc-b838b603b9cb)

- **🔧 Toolchain Management** - Automatic detection and configuration of FPGA tools

![image](https://github.com/user-attachments/assets/bf4547df-9f65-486d-b3e5-100dec155580)

- **📊 Uploading to FPGA** - Program the FPGA SRAM or onboard flash memory
 - Currently support Olimex GateMate boards, make requests to add more boards until I come up with a better way of handling this.

![image](https://github.com/user-attachments/assets/e0ddd854-169a-4420-8319-9c48c042dc69)

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
   cd GateMate_Project_Manager
   ```

2. **Install Python dependencies:**
   ```bash
   cd cc_project_manager_pkg
   pip install -r requirements.txt
   ```
   This installs PyQt5 for the GUI interface and other required packages.

3. **Install as a package (optional, for global commands):**
   ```bash
   cd..
   pip install -e .
   ```
   This creates global commands (see Usage section below).

4. **Install Cologne Chip FPGA toolchain:**
   - Tested with the Cologne Chip Legacy Toolchain Packages for Windows (11.06.2025)
   - GHDL (for VHDL simulation)
   - Yosys (for synthesis)
   - Cologne Chip GateMate tools (for implementation)

5. **Get openFPGALoader for uploading to the FPGA**
   - Uploading bitstreams to a development board with openFPGALoader may require additional software, like dirtyJTAG, Zadig. See the documentation
     for the development board you got.

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

0.2.0

