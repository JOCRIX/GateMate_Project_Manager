# 🖥️ GUI Quick Start Guide

Welcome to the **Cologne Chip Project Manager GUI**! This modern interface makes FPGA development more intuitive and user-friendly.

## 🚀 Quick Launch

### Method 1: Using the Package Command (Recommended)
```bash
gmpm           # Launches GUI by default
```

### Method 2: Using Python Module
```bash
python -m cc_project_manager_pkg
```

### Method 3: Direct Module Launch
```bash
python -m cc_project_manager_pkg.gui
```

## 🎯 First Time Setup

1. **Install the Package**
   ```bash
   pip install -e .
   ```

2. **Configure openFPGALoader (Optional)**
   ```bash
   python -m cc_project_manager_pkg.setup_openfpgaloader_path
   ```

3. **Launch the Application**
   ```bash
   gmpm
   ```

## 📋 Interface Overview

The GUI is organized into **6 main tabs**:

### 1. 📁 Project Management
- **Create New Project** - Set up a new FPGA project with proper directory structure
- **Load Existing Project** - Open an existing project
- **Add VHDL File** - Import VHDL source files into your project
- **Remove VHDL File** - Remove files from the project
- **View Project Status** - See project overview and file listing
- **Detect Manual Files** - Find files added outside the tool

### 2. ⚙️ Synthesis
- **Run Synthesis** - Convert VHDL to gate-level netlist using Yosys
- **Configure Synthesis** - Set VHDL standard, target device, optimization strategy
- **View Synthesis Logs** - Check synthesis reports and timing information

### 3. 🛠️ Implementation
- **Place & Route** - Physical implementation of the design
- **Generate Bitstream** - Create programming file for the FPGA
- **Timing Analysis** - Verify timing constraints are met
- **Full Implementation** - Complete implementation flow
- **View Status** - Check implementation results

### 4. 🔍 Simulation
- **Behavioral Simulation** - Test original VHDL code functionality
- **Post-Synthesis Simulation** - Verify synthesized netlist behavior
- **Configure Simulation** - Set simulation time, options, and profiles
- **Launch Waveform Viewer** - Open GTKWave for signal analysis

### 5. 📤 Upload
- **Device Detection** - Automatically detect connected FPGA boards
- **Bitstream Upload** - Program the FPGA with generated bitstreams
- **Board Selection** - Choose target board type
- **Upload Progress** - Monitor programming status

### 6. 🔧 Configuration
- **Check Toolchain** - Verify required tools are installed
- **Edit Toolchain Paths** - Configure paths to synthesis tools
- **Project Settings** - Modify project-specific configurations

## 📊 Output Window

The **bottom panel** shows real-time information:

- **🟢 INFO** - General information messages
- **🟡 WARNING** - Important notices
- **🔴 ERROR** - Error messages requiring attention
- **Auto-scroll** - Automatically shows latest messages
- **Save Log** - Export messages to a text file
- **Clear** - Reset the log display

## 🎮 How to Use

### Creating Your First Project

1. **Click "Create New Project"** in the Project Management tab
2. **Enter project name** (e.g., "my_counter")
3. **Select directory** (or use current directory)
4. **Click "Create"**

The tool will create a complete project structure with folders for source files, simulation, synthesis, and implementation.

### Adding VHDL Files

1. **Click "Add VHDL File"**
2. **Browse and select** your `.vhd` or `.vhdl` files
3. Files are automatically added to the project configuration

### Running Synthesis

1. **Go to Synthesis tab**
2. **Click "Configure Synthesis"** (optional - to change settings)
3. **Click "Run Synthesis"**
4. **Watch the Output Window** for progress
5. **Check logs** when complete

### Running Simulation

1. **Go to Simulation tab**
2. **Choose simulation type** (Behavioral or Post-Synthesis)
3. **Click the appropriate button**
4. **Monitor progress** in the Output Window
5. **Launch waveform viewer** to see results

### Programming Your FPGA

1. **Go to Upload tab**
2. **Connect your FPGA board**
3. **Click "Refresh Status"** to detect the board
4. **Select your bitstream file**
5. **Click "Upload to SRAM"** to program the FPGA

## 🎨 Interface Features

### Visual Design
- **Modern layout** with clean, organized tabs
- **Color-coded buttons** for different operations
- **Tooltips** on hover for helpful information
- **Professional styling** with consistent colors

### User Experience
- **Non-blocking operations** - GUI remains responsive during long tasks
- **Progress feedback** - Real-time status updates
- **Error handling** - Clear error messages and recovery options
- **Recent project memory** - Automatically reopens last project

### Log Management
- **Persistent logging** - All operations logged with timestamps
- **Color coding** - Different colors for different message types
- **Export capability** - Save logs for later analysis
- **Automatic cleanup** - Prevents log overflow

## 🛠️ Troubleshooting

### Application Won't Start
```bash
# Check if the package is installed
gmpm

# If command not found, reinstall:
pip install -e .
```

### Missing Dependencies
```bash
# Check if PyQt5 is installed
python -c "import PyQt5; print('PyQt5 OK')"

# If not installed:
pip install PyQt5
```

### Tool Chain Issues
1. **Click "Check Toolchain"** in Configuration tab
2. **Follow the recommendations** shown in the output
3. **Install missing tools** as needed
4. **Run the setup script** if openFPGALoader issues persist:
   ```bash
   python -m cc_project_manager_pkg.setup_openfpgaloader_path
   ```

## 🔄 CLI Alternative

You can also use the CLI interface:

```bash
# CLI Mode
gmpm --cli

# Or directly
python -m cc_project_manager_pkg.cli
```

## 📈 Performance Tips

- **Use threaded operations** - Long tasks run in background
- **Monitor the Output Window** - Shows real-time progress
- **Save logs regularly** - Export important session logs
- **Clear logs periodically** - Prevents memory buildup
- **Auto-refresh Upload tab** - Bitstreams refresh automatically when switching tabs

## 🎯 Best Practices

1. **Create projects in dedicated directories**
2. **Use descriptive project names**
3. **Check toolchain before starting**
4. **Monitor synthesis and implementation logs**
5. **Save important log files**
6. **Use simulation profiles for complex testbenches**
7. **Test with simulation before implementation**

## 🆘 Getting Help

- **Tooltips** - Hover over buttons for quick help
- **Output Window** - Shows detailed operation information
- **README.md** - Comprehensive documentation
- **Auto-detect preview** - See which constraint files will be used

## 🎉 Enjoy the GUI!

The GUI interface makes FPGA development much more accessible and user-friendly. Take your time to explore the different tabs and features, especially the new Upload tab for easy FPGA programming! 