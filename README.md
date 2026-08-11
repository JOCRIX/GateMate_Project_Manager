# GateMate FPGA Project Manager

A comprehensive FPGA project management tool for GHDL, Yosys, and Place & Route workflows, specifically designed for Cologne Chip GateMate FPGAs.

**The project is work-in-progress.**

**Current version: 0.4.2**

## Features

- **📁 Project Management** - Create and manage FPGA project structures
![image](https://github.com/user-attachments/assets/99af9d5b-effe-418a-99c9-ab1523c78d87)

- **⚙️ VHDL Synthesis** - GHDL elaboration + Yosys `synth_gatemate` (OSS CAD Suite), with strategy presets and command preview

![image](https://github.com/user-attachments/assets/a0ae843a-f137-4827-b7ca-ab9f64bcf8c2)
 
- **🔍 Simulation** - Behavioral and post-synthesis (GHDL) plus **post-implementation** (Icarus Verilog + post-P&R netlist / SDF when available), with GTKWave for VCD waveforms. Post-impl is a functional post-P&R check with the open toolchain; full SDF timing models are not supplied by Cologne Chip in this flow yet.

![image](https://github.com/user-attachments/assets/a5212d34-19b4-4ca4-8e08-613a908ae48b)


- **🛠️ Implementation** - Place & Route with **nextpnr-himbaechel** and bitstream packing with **gmpack** (OSS CAD Suite). Includes presets, multi-seed search (optional parallel jobs), timing reports, placed/routed SVG previews, and optional post-impl sim netlist (`--write` + `*_pnr.v`).

![image](https://github.com/user-attachments/assets/0c745c4f-4d77-4323-b3bc-b838b603b9cb)

- **🔧 Toolchain Management** - Automatic detection and configuration of FPGA tools (PATH / DIRECT), with version display for OSS CAD tools
  
![image](https://github.com/user-attachments/assets/bf4547df-9f65-486d-b3e5-100dec155580)

  - Automagically install all the required tools for getting started with the GateMate series of FPGAs
    
![image](https://github.com/JOCRIX/GateMate_Project_Manager/blob/main/images/Autosetup.svg)
 
- **📊 Uploading to FPGA** - Program FPGA SRAM or onboard flash memory
  - **Zector Instruments Logic 1.0 GateMate (ZI-0001-0001)** — serial programming via the bundled ZI FPGA Loader (COM port, live progress in Output; Test Connection queries firmware `VERSION`)
  - **Olimex GateMate EVB** and other boards — openFPGALoader (JTAG/SPI)
  - Make requests to add more boards until a more flexible board plug-in system is in place.

![image](https://github.com/user-attachments/assets/e0ddd854-169a-4420-8319-9c48c042dc69)

## Package Structure

```
GateMate_Project_Manager/
├── cc_project_manager_pkg/            # Core package modules
│   ├── __init__.py                    # Package initialization and version (0.4.2)
│   ├── __main__.py                    # Main entry point
│   ├── gui.py                         # PyQt5 GUI interface
│   ├── cli.py                         # Interactive CLI interface
│   ├── create_structure.py            # Project structure creation
│   ├── yosys_commands.py              # Yosys synthesis integration
│   ├── ghdl_commands.py               # GHDL simulation integration
│   ├── nextpnr_commands.py            # nextpnr-himbaechel + gmpack (primary P&R)
│   ├── place_and_route_dialog.py      # Place & Route settings + multi-seed UI
│   ├── toolchain_autosetup.py         # Pinned toolchain download/extract
│   ├── toolchain_autosetup_dialog.py  # Auto-Setup Toolchain GUI
│   ├── pnr_commands.py                # Legacy Cologne Chip p_r helpers (compat)
│   ├── simulation_manager.py          # Simulation management (incl. Icarus post-impl)
│   ├── hierarchy_manager.py           # Project hierarchy management
│   ├── toolchain_manager.py           # Toolchain detection and management
│   ├── boards_manager.py              # FPGA board definitions
│   ├── openfpgaloader_manager.py      # openFPGALoader programming support
│   ├── zi_fpga_loader.py              # Zector ZI-0001 serial FPGA loader
│   ├── zi_fpga_loader_manager.py      # ZI loader manager for the GUI
│   ├── upload_manager_factory.py      # Routes upload to the correct loader
│   ├── resources/gatemate/            # Bundled GateMate sim helpers (e.g. cpesim.v)
│   └── requirements.txt               # Python dependencies
├── setup.py                           # Package installation script
├── CHANGELOG.md                       # Version history and release notes
├── MANIFEST.in                        # Package manifest
├── .gitignore                         # Git ignore rules
├── GUI_QUICKSTART.md                  # GUI user guide
└── README.md                          # This file
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
   This installs PyQt5 for the GUI, pyserial for Zector board programming, and other required packages.

3. **Install as a package (optional, for global commands):**
   ```bash
   cd ..
   pip install -e .
   ```
   This creates global commands (see Usage section below).

4. **Install the FPGA toolchain (OSS CAD Suite recommended):**
   - Prefer **Configuration → Auto-Setup Toolchain** for a one-time machine install of pinned OSS CAD Suite + standalone GHDL (sets User PATH / `YOSYSHQ_ROOT`; GTKWave, openFPGALoader, and Icarus `iverilog`/`vvp` come from the suite)
   - Or install manually: [OSS CAD Suite](https://github.com/YosysHQ/oss-cad-suite-build) (`yosys`, `nextpnr-himbaechel`, `gmpack`, GTKWave, Icarus) plus standalone GHDL
   - Configure or verify tool paths under **Configuration** if needed

5. **Get openFPGALoader for uploading to the FPGA (non-Zector boards)**
   - Uploading bitstreams to a development board with openFPGALoader may require additional software, like dirtyJTAG, Zadig. See the documentation for the development board you are using.

6. **Zector Instruments ZI-0001 boards**
   - No openFPGALoader required. Configure the COM port in **Upload → FPGA Board Selection**.
   - **Test Connection** opens the port and queries the STM32 `VERSION` command.
   - Requires a `.bit` file (generated by Place & Route / gmpack).

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
- **Run Synthesis** - Perform VHDL synthesis with GHDL + Yosys `synth_gatemate`
- **Configure Synthesis** - Set synthesis options (strategy, target, command preview)
- **View Synthesis Logs** - Open synthesis reports and logs

#### **Implementation Tab**
- **Place & Route** - nextpnr-himbaechel with presets, multi-seed, and optional parallel jobs
- **Generate Bitstream** - Pack implementation with gmpack
- **Timing Analysis** - Review timing from nextpnr reports
- **Full Implementation** - Run complete implementation flow

#### **Simulation Tab**
- **Behavioral Simulation** - Run pre-synthesis VHDL simulation (GHDL)
- **Post-Synthesis Simulation** - Simulate GHDL synthesis netlist
- **Post-Implementation Simulation** - Icarus + Verilog TB + post-P&R netlist/SDF (functional post-P&R check with open models; see dialog limitations)
- **Add Verilog Testbench** - Register `.v` / `.sv` testbenches under `testbench/verilog/`
- **Configure Simulation** - Set simulation parameters
- **Launch Waveform Viewer** - Open GTKWave for the latest (or selected) VCD

#### **Upload Tab**
- **Device Detection** - Detect connected FPGA boards (openFPGALoader) or test serial + VERSION (Zector)
- **Program SRAM** - Program the FPGA with a generated bitstream
- **Board Selection** - Choose target board; configure COM port for Zector boards
- **Upload Progress** - Progress bar and live serial output during programming

#### **Configuration Tab**
- **Check Toolchain** - Verify tool availability and show versions
- **Edit Toolchain Paths** - Configure tool locations (GHDL, Yosys, nextpnr, gmpack, iverilog, vvp, …)
- **Auto-Setup Toolchain** - One-time machine setup: download pinned OSS CAD Suite / GHDL, run `environment.ps1`, persist User PATH / `YOSYSHQ_ROOT` for all future projects (GTKWave + openFPGALoader + Icarus come from OSS CAD Suite)
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
- **pyserial 3.5+** (for Zector ZI-0001 serial programming)
- **GHDL 5.0.1+**
- **Yosys** with GateMate support (`synth_gatemate`) — typically via OSS CAD Suite
- **nextpnr-himbaechel** and **gmpack** — typically via OSS CAD Suite
- **Icarus Verilog** (`iverilog` / `vvp`) — for post-implementation simulation (OSS CAD Suite)
- **openFPGALoader** (for JTAG/SPI boards such as Olimex GateMate EVB)

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
├── testbench/              # VHDL testbenches
│   └── verilog/            # Verilog/SystemVerilog TBs (post-impl sim)
├── constraints/            # Constraint files
├── synth/                  # Synthesis outputs
├── bitstream/              # Generated bitstreams
├── timing/                 # Timing / SDF / seed reports & SVGs
├── netlist/                # Post-implementation netlists (*_pnr.v / JSON)
├── sim/                    # Simulation outputs (behavioral / post-synth / post-impl VCDs)
├── build/                  # Build artifacts
├── logs/                   # Log files
└── config/                 # Configuration files
```

## Testing

Test the package installation:
```bash
python test_package.py
```

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for version history and release notes.

## License

Do whatever you want with it.

## Author

JOCRIX

## Version

0.4.2
