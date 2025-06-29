#!/usr/bin/env python3
"""PyQt5 GUI for the Cologne Chip Project Manager.

This module provides a modern graphical interface for managing FPGA projects,
including synthesis, simulation, and project setup operations.
"""

import sys
import os
import logging
import threading
import time
import subprocess
import datetime
from typing import Optional, Dict, Any
from pathlib import Path

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QGridLayout, QPushButton, QLabel, QTextEdit, QScrollArea, QFrame,
    QSplitter, QMessageBox, QInputDialog, QFileDialog, QDialog,
    QFormLayout, QLineEdit, QComboBox, QCheckBox, QSpinBox,
    QTabWidget, QGroupBox, QProgressBar, QStatusBar, QMenuBar,
    QAction, QToolBar, QListWidget, QTableWidget, QTableWidgetItem,
    QTreeWidget, QTreeWidgetItem, QStyle, QHeaderView, QSizePolicy,
    QAbstractItemView
)
from PyQt5.QtCore import (
    Qt, QThread, pyqtSignal, QTimer, QSize, QRect, pyqtSlot
)
from PyQt5.QtGui import (
    QFont, QPixmap, QIcon, QPalette, QColor, QTextCursor, 
    QTextCharFormat, QSyntaxHighlighter, QTextDocument
)

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


class LogHandler(logging.Handler):
    """Custom logging handler to redirect logs to the GUI output window."""
    
    def __init__(self, text_widget):
        super().__init__()
        self.text_widget = text_widget
        self.setFormatter(logging.Formatter(
            '%(asctime)s - %(levelname)s - %(message)s'
        ))
    
    def emit(self, record):
        """Emit a log record to the text widget."""
        try:
            msg = self.format(record)
            # Use Qt's thread-safe mechanism to update GUI
            self.text_widget.append_log.emit(msg, record.levelname)
        except Exception:
            pass


class LogTextWidget(QTextEdit):
    """Enhanced text widget for displaying logs with color coding."""
    
    append_log = pyqtSignal(str, str)  # message, level
    
    def __init__(self):
        super().__init__()
        self.setReadOnly(True)
        self.max_lines = 1000  # Limit log history
        self.current_lines = 0
        
        # Set up colors for different log levels (dark theme compatible)
        self.log_colors = {
            'DEBUG': '#888888',
            'INFO': '#E0E0E0',        # Light gray for dark background
            'WARNING': '#FFA500',     # Orange
            'ERROR': '#FF6B6B',       # Light red
            'CRITICAL': '#FF4444'     # Bright red
        }
        
        # Connect signal to slot
        self.append_log.connect(self._append_log_message)
        
        # Set font (optimized for dark theme)
        font = QFont("Consolas", 10)
        font.setStyleHint(QFont.Monospace)
        font.setWeight(QFont.Normal)
        self.setFont(font)
    
    @pyqtSlot(str, str)
    def _append_log_message(self, message: str, level: str):
        """Append a log message with appropriate color."""
        color = self.log_colors.get(level, '#000000')
        
        # Check if we need to remove old lines
        if self.current_lines >= self.max_lines:
            # Remove the first line
            cursor = self.textCursor()
            cursor.movePosition(QTextCursor.Start)
            cursor.movePosition(QTextCursor.Down, QTextCursor.KeepAnchor)
            cursor.removeSelectedText()
            self.current_lines -= 1
        
        # Format the message with HTML color
        html_message = f'<span style="color: {color};">{message}</span>'
        
        # Move cursor to end and append
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.setTextCursor(cursor)
        self.insertHtml(html_message + '<br>')
        self.current_lines += 1
        
        # Auto scroll to bottom
        scrollbar = self.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
    
    def clear(self):
        """Override clear method to reset line count."""
        super().clear()
        self.current_lines = 0


class WorkerThread(QThread):
    """Worker thread for running long-running operations without blocking the GUI."""
    
    finished = pyqtSignal(bool, str)  # success, message
    progress = pyqtSignal(str)  # progress message
    
    def __init__(self, operation, *args, **kwargs):
        super().__init__()
        self.operation = operation
        self.args = args
        self.kwargs = kwargs
    
    def run(self):
        """Run the operation in a separate thread."""
        try:
            if callable(self.operation):
                result = self.operation(*self.args, **self.kwargs)
                self.finished.emit(True, str(result) if result else "Operation completed successfully")
            else:
                self.finished.emit(False, "Invalid operation")
        except Exception as e:
            import traceback
            error_msg = f"Error: {str(e)}"
            logging.error(f"WorkerThread exception: {error_msg}")
            logging.error(f"Traceback: {traceback.format_exc()}")
            self.finished.emit(False, error_msg)


class ProjectDialog(QDialog):
    """Dialog for creating new projects."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Create New Project")
        self.setModal(True)
        self.resize(400, 200)
        
        layout = QFormLayout()
        
        self.project_name = QLineEdit()
        self.project_path = QLineEdit()
        self.project_path.setText(".")
        
        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self.browse_path)
        
        path_layout = QHBoxLayout()
        path_layout.addWidget(self.project_path)
        path_layout.addWidget(browse_btn)
        
        layout.addRow("Project Name:", self.project_name)
        layout.addRow("Project Path:", path_layout)
        
        # Buttons
        button_layout = QHBoxLayout()
        ok_btn = QPushButton("Create")
        cancel_btn = QPushButton("Cancel")
        
        ok_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)
        
        button_layout.addWidget(ok_btn)
        button_layout.addWidget(cancel_btn)
        
        layout.addRow(button_layout)
        self.setLayout(layout)
    
    def browse_path(self):
        """Browse for project directory."""
        path = QFileDialog.getExistingDirectory(self, "Select Project Directory")
        if path:
            self.project_path.setText(path)
    
    def get_project_info(self):
        """Get the project information."""
        return {
            'name': self.project_name.text().strip(),
            'path': self.project_path.text().strip()
        }


class ToolchainPathDialog(QDialog):
    """Dialog for editing toolchain paths."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Toolchain Paths")
        self.setModal(True)
        self.resize(700, 500)
        
        # Initialize ToolChainManager to get current paths
        try:
            from cc_project_manager_pkg.toolchain_manager import ToolChainManager
            self.tcm = ToolChainManager()
            self.current_paths = self.tcm.config.get("cologne_chip_gatemate_toolchain_paths", {})
        except Exception as e:
            self.tcm = None
            self.current_paths = {}
            logging.error(f"Failed to initialize ToolChainManager: {e}")
        
        self.init_ui()
    
    def init_ui(self):
        """Initialize the dialog UI."""
        layout = QVBoxLayout(self)
        
        # Header
        header_label = QLabel("🔧 Toolchain Path Configuration")
        header_label.setFont(QFont("Arial", 14, QFont.Bold))
        header_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(header_label)
        
        # Current status section (expanded to take more space)
        status_group = QGroupBox("Current Toolchain Status")
        status_layout = QVBoxLayout(status_group)
        
        self.status_text = QTextEdit()
        self.status_text.setReadOnly(True)
        # Remove height restriction to let it expand
        status_layout.addWidget(self.status_text)
        
        layout.addWidget(status_group, 2)  # Give status section more space (stretch factor 2)
        
        # Path configuration section
        paths_group = QGroupBox("Tool Paths Configuration")
        paths_layout = QFormLayout(paths_group)
        
        # Tool path inputs
        self.path_inputs = {}
        tools = [
            ("ghdl", "GHDL", "Path to ghdl.exe (VHDL compiler and analyzer)"),
            ("yosys", "Yosys", "Path to yosys.exe (HDL synthesizer)"),
            ("p_r", "P&R", "Path to p_r.exe (Place & Route tool)"),
            ("openfpgaloader", "openFPGALoader", "Path to openFPGALoader.exe (FPGA programmer)")
        ]
        
        for tool_key, tool_name, tooltip in tools:
            # Create horizontal layout for path input and browse button
            path_layout = QHBoxLayout()
            
            # Path input field
            path_input = QLineEdit()
            path_input.setPlaceholderText(f"Enter path to {tool_name} binary...")
            path_input.setToolTip(tooltip)
            current_path = self.current_paths.get(tool_key, "")
            if current_path:
                path_input.setText(current_path)
            
            # Browse button
            browse_btn = QPushButton("📁 Browse")
            browse_btn.setMinimumWidth(100)
            browse_btn.setMaximumWidth(120)
            browse_btn.clicked.connect(lambda checked, key=tool_key: self.browse_path(key))
            
            # Validate button
            validate_btn = QPushButton("✓ Test")
            validate_btn.setMinimumWidth(80)
            validate_btn.setMaximumWidth(100)
            validate_btn.clicked.connect(lambda checked, key=tool_key: self.validate_path(key))
            
            path_layout.addWidget(path_input)
            path_layout.addWidget(browse_btn)
            path_layout.addWidget(validate_btn)
            
            self.path_inputs[tool_key] = path_input
            paths_layout.addRow(f"{tool_name}:", path_layout)
        
        layout.addWidget(paths_group, 1)  # Give paths section normal space (stretch factor 1)
        
        # Refresh Status button (moved here from status section)
        refresh_status_btn = QPushButton("🔄 Refresh Status")
        refresh_status_btn.clicked.connect(self.refresh_status)
        refresh_status_btn.setMaximumWidth(200)
        refresh_layout = QHBoxLayout()
        refresh_layout.addStretch()
        refresh_layout.addWidget(refresh_status_btn)
        refresh_layout.addStretch()
        layout.addLayout(refresh_layout)
        
        # Instructions
        instructions = QLabel(
            "💡 Instructions:\n"
            "• Use 'Browse' to select the executable file for each tool\n"
            "• Use 'Test' to validate that the path works correctly\n"
            "• Paths must point to the actual .exe files (e.g., ghdl.exe, yosys.exe, p_r.exe, openFPGALoader.exe)\n"
            "• Leave empty to use PATH environment variable"
        )
        instructions.setWordWrap(True)
        instructions.setStyleSheet("color: #64b5f6; font-size: 11px; padding: 10px;")
        layout.addWidget(instructions, 0)  # Give instructions minimal space (stretch factor 0)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        # Reset button
        reset_btn = QPushButton("🔄 Reset to Current")
        reset_btn.clicked.connect(self.reset_paths)
        button_layout.addWidget(reset_btn)
        
        button_layout.addStretch()
        
        # Cancel and Apply buttons
        cancel_btn = QPushButton("❌ Cancel")
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)
        
        apply_btn = QPushButton("✅ Apply Changes")
        apply_btn.clicked.connect(self.apply_changes)
        apply_btn.setDefault(True)
        button_layout.addWidget(apply_btn)
        
        layout.addLayout(button_layout)
        
        # Initial status refresh
        self.refresh_status()
    
    def refresh_status(self):
        """Refresh the toolchain status display."""
        if not self.tcm:
            self.status_text.setText("❌ ToolChainManager not available")
            return
        
        try:
            # Get current preference
            preference = self.tcm.config.get("cologne_chip_gatemate_toolchain_preference", "PATH")
            
            status_text = f"Current Preference: {preference}\n\n"
            
            # Check each tool
            tools = {"GHDL": "ghdl", "Yosys": "yosys", "P&R": "p_r", "openFPGALoader": "openfpgaloader"}
            
            for tool_name, tool_key in tools.items():
                status_text += f"{tool_name}:\n"
                
                # Check PATH availability
                try:
                    path_available = self.tcm.check_tool_version(tool_key)
                    if path_available:
                        status_text += "  PATH: ✅ Available\n"
                    else:
                        status_text += "  PATH: ❌ Not available\n"
                except:
                    status_text += "  PATH: ❌ Not available\n"
                
                # Check direct path
                direct_path = self.current_paths.get(tool_key, "")
                if direct_path:
                    if os.path.exists(direct_path):
                        status_text += f"  DIRECT: ✅ Available ({direct_path})\n"
                    else:
                        status_text += f"  DIRECT: ❌ Path not found ({direct_path})\n"
                else:
                    status_text += "  DIRECT: ⚠️ Not configured\n"
                
                status_text += "\n"
            
            self.status_text.setText(status_text)
            
        except Exception as e:
            self.status_text.setText(f"❌ Error checking status: {e}")
    
    def browse_path(self, tool_key):
        """Browse for a tool path."""
        tool_names = {"ghdl": "GHDL", "yosys": "Yosys", "p_r": "P&R", "openfpgaloader": "openFPGALoader"}
        tool_name = tool_names.get(tool_key, tool_key)
        
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            f"Select {tool_name} Executable",
            "",
            "Executable Files (*.exe);;All Files (*)"
        )
        
        if file_path:
            self.path_inputs[tool_key].setText(file_path)
    
    def validate_path(self, tool_key):
        """Validate a tool path."""
        path = self.path_inputs[tool_key].text().strip()
        tool_names = {"ghdl": "GHDL", "yosys": "Yosys", "p_r": "P&R", "openfpgaloader": "openFPGALoader"}
        tool_name = tool_names.get(tool_key, tool_key)
        
        if not path:
            QMessageBox.information(self, "Validation", f"{tool_name} path is empty - will use PATH environment variable")
            return
        
        if not os.path.exists(path):
            QMessageBox.warning(self, "Validation Failed", f"{tool_name} path does not exist:\n{path}")
            return
        
        if not os.path.isfile(path):
            QMessageBox.warning(self, "Validation Failed", f"{tool_name} path is not a file:\n{path}")
            return
        
        # Check if it's the correct executable
        expected_names = {"ghdl": "ghdl.exe", "yosys": "yosys.exe", "p_r": "p_r.exe", "openfpgaloader": "openFPGALoader.exe"}
        expected_name = expected_names.get(tool_key, f"{tool_key}.exe")
        
        if not path.lower().endswith(expected_name.lower()):
            QMessageBox.warning(
                self, 
                "Validation Warning", 
                f"{tool_name} path should end with '{expected_name}':\n{path}\n\nContinue anyway?"
            )
            return
        
        # Try to run version command (use appropriate flag for each tool)
        version_flag = "--version"
        if tool_key == "openfpgaloader":
            version_flag = "--Version"  # openFPGALoader uses capital V
        
        try:
            result = subprocess.run([path, version_flag], capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                QMessageBox.information(
                    self, 
                    "Validation Successful", 
                    f"✅ {tool_name} is working correctly!\n\nVersion info:\n{result.stdout[:200]}..."
                )
            else:
                QMessageBox.warning(
                    self, 
                    "Validation Failed", 
                    f"❌ {tool_name} returned error code {result.returncode}\n\nError:\n{result.stderr[:200]}..."
                )
        except subprocess.TimeoutExpired:
            QMessageBox.warning(self, "Validation Failed", f"❌ {tool_name} validation timed out")
        except Exception as e:
            QMessageBox.warning(self, "Validation Failed", f"❌ Error testing {tool_name}:\n{str(e)}")
    
    def reset_paths(self):
        """Reset paths to current configuration."""
        for tool_key, path_input in self.path_inputs.items():
            current_path = self.current_paths.get(tool_key, "")
            path_input.setText(current_path)
    
    def apply_changes(self):
        """Apply the path changes."""
        if not self.tcm:
            QMessageBox.critical(self, "Error", "ToolChainManager not available")
            return
        
        # Get new paths
        new_paths = {}
        for tool_key, path_input in self.path_inputs.items():
            path = path_input.text().strip()
            if path and path != self.current_paths.get(tool_key, ""):
                new_paths[tool_key] = path
        
        if not new_paths:
            QMessageBox.information(self, "No Changes", "No path changes detected.")
            return
        
        # Confirm changes
        changes_text = "\n".join([f"• {tool_key.upper()}: {path}" for tool_key, path in new_paths.items()])
        reply = QMessageBox.question(
            self,
            "Confirm Changes",
            f"Apply the following path changes?\n\n{changes_text}",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply != QMessageBox.Yes:
            return
        
        # Apply changes
        success_count = 0
        errors = []
        
        for tool_key, new_path in new_paths.items():
            try:
                success = self.tcm.add_tool_path(tool_key, new_path)
                if success:
                    success_count += 1
                    logging.info(f"Updated {tool_key} path to: {new_path}")
                else:
                    errors.append(f"Failed to update {tool_key} path")
            except Exception as e:
                errors.append(f"Error updating {tool_key}: {str(e)}")
        
        # Show results
        if success_count > 0:
            # Run toolchain check to update preference
            try:
                self.tcm.check_toolchain()
            except Exception as e:
                logging.warning(f"Error running toolchain check: {e}")
            
            # Update current paths for status refresh
            self.current_paths = self.tcm.config.get("cologne_chip_gatemate_toolchain_paths", {})
            self.refresh_status()
            
            if errors:
                QMessageBox.warning(
                    self,
                    "Partial Success",
                    f"✅ Successfully updated {success_count}/{len(new_paths)} paths\n\n❌ Errors:\n" + "\n".join(errors)
                )
            else:
                QMessageBox.information(
                    self,
                    "Success",
                    f"✅ Successfully updated {success_count} tool path(s)!\n\nToolchain preference has been automatically updated."
                )
                self.accept()
        else:
            QMessageBox.critical(
                self,
                "Failed",
                f"❌ Failed to update any paths:\n\n" + "\n".join(errors)
            )


#!/usr/bin/env python3
"""PyQt5 GUI for the Cologne Chip Project Manager.

This module provides a modern graphical interface for managing FPGA projects,
including synthesis, simulation, and project setup operations.
"""

import sys
import os
import logging
import threading
import time
import subprocess
import datetime
from typing import Optional, Dict, Any
from pathlib import Path

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QGridLayout, QPushButton, QLabel, QTextEdit, QScrollArea, QFrame,
    QSplitter, QMessageBox, QInputDialog, QFileDialog, QDialog,
    QFormLayout, QLineEdit, QComboBox, QCheckBox, QSpinBox,
    QTabWidget, QGroupBox, QProgressBar, QStatusBar, QMenuBar,
    QAction, QToolBar, QListWidget, QTableWidget, QTableWidgetItem,
    QTreeWidget, QTreeWidgetItem, QStyle, QHeaderView, QSizePolicy,
    QAbstractItemView
)
from PyQt5.QtCore import (
    Qt, QThread, pyqtSignal, QTimer, QSize, QRect, pyqtSlot
)
from PyQt5.QtGui import (
    QFont, QPixmap, QIcon, QPalette, QColor, QTextCursor, 
    QTextCharFormat, QSyntaxHighlighter, QTextDocument
)

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


class LogHandler(logging.Handler):
    """Custom logging handler to redirect logs to the GUI output window."""
    
    def __init__(self, text_widget):
        super().__init__()
        self.text_widget = text_widget
        self.setFormatter(logging.Formatter(
            '%(asctime)s - %(levelname)s - %(message)s'
        ))
    
    def emit(self, record):
        """Emit a log record to the text widget."""
        try:
            msg = self.format(record)
            # Use Qt's thread-safe mechanism to update GUI
            self.text_widget.append_log.emit(msg, record.levelname)
        except Exception:
            pass


class LogTextWidget(QTextEdit):
    """Enhanced text widget for displaying logs with color coding."""
    
    append_log = pyqtSignal(str, str)  # message, level
    
    def __init__(self):
        super().__init__()
        self.setReadOnly(True)
        self.max_lines = 1000  # Limit log history
        self.current_lines = 0
        
        # Set up colors for different log levels (dark theme compatible)
        self.log_colors = {
            'DEBUG': '#888888',
            'INFO': '#E0E0E0',        # Light gray for dark background
            'WARNING': '#FFA500',     # Orange
            'ERROR': '#FF6B6B',       # Light red
            'CRITICAL': '#FF4444'     # Bright red
        }
        
        # Connect signal to slot
        self.append_log.connect(self._append_log_message)
        
        # Set font (optimized for dark theme)
        font = QFont("Consolas", 10)
        font.setStyleHint(QFont.Monospace)
        font.setWeight(QFont.Normal)
        self.setFont(font)
    
    @pyqtSlot(str, str)
    def _append_log_message(self, message: str, level: str):
        """Append a log message with appropriate color."""
        color = self.log_colors.get(level, '#000000')
        
        # Check if we need to remove old lines
        if self.current_lines >= self.max_lines:
            # Remove the first line
            cursor = self.textCursor()
            cursor.movePosition(QTextCursor.Start)
            cursor.movePosition(QTextCursor.Down, QTextCursor.KeepAnchor)
            cursor.removeSelectedText()
            self.current_lines -= 1
        
        # Format the message with HTML color
        html_message = f'<span style="color: {color};">{message}</span>'
        
        # Move cursor to end and append
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.End)
        self.setTextCursor(cursor)
        self.insertHtml(html_message + '<br>')
        self.current_lines += 1
        
        # Auto scroll to bottom
        scrollbar = self.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
    
    def clear(self):
        """Override clear method to reset line count."""
        super().clear()
        self.current_lines = 0


class WorkerThread(QThread):
    """Worker thread for running long-running operations without blocking the GUI."""
    
    finished = pyqtSignal(bool, str)  # success, message
    progress = pyqtSignal(str)  # progress message
    
    def __init__(self, operation, *args, **kwargs):
        super().__init__()
        self.operation = operation
        self.args = args
        self.kwargs = kwargs
    
    def run(self):
        """Run the operation in a separate thread."""
        try:
            if callable(self.operation):
                result = self.operation(*self.args, **self.kwargs)
                self.finished.emit(True, str(result) if result else "Operation completed successfully")
            else:
                self.finished.emit(False, "Invalid operation")
        except Exception as e:
            import traceback
            error_msg = f"Error: {str(e)}"
            logging.error(f"WorkerThread exception: {error_msg}")
            logging.error(f"Traceback: {traceback.format_exc()}")
            self.finished.emit(False, error_msg)


class ProjectDialog(QDialog):
    """Dialog for creating new projects."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Create New Project")
        self.setModal(True)
        self.resize(400, 200)
        
        layout = QFormLayout()
        
        self.project_name = QLineEdit()
        self.project_path = QLineEdit()
        self.project_path.setText(".")
        
        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self.browse_path)
        
        path_layout = QHBoxLayout()
        path_layout.addWidget(self.project_path)
        path_layout.addWidget(browse_btn)
        
        layout.addRow("Project Name:", self.project_name)
        layout.addRow("Project Path:", path_layout)
        
        # Buttons
        button_layout = QHBoxLayout()
        ok_btn = QPushButton("Create")
        cancel_btn = QPushButton("Cancel")
        
        ok_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)
        
        button_layout.addWidget(ok_btn)
        button_layout.addWidget(cancel_btn)
        
        layout.addRow(button_layout)
        self.setLayout(layout)
    
    def browse_path(self):
        """Browse for project directory."""
        path = QFileDialog.getExistingDirectory(self, "Select Project Directory")
        if path:
            self.project_path.setText(path)
    
    def get_project_info(self):
        """Get the project information."""
        return {
            'name': self.project_name.text().strip(),
            'path': self.project_path.text().strip()
        }


class GTKWaveConfigDialog(QDialog):
    """Dialog for configuring GTKWave settings."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Configure GTKWave")
        self.setModal(True)
        self.resize(600, 400)
        
        # Initialize SimulationManager to get current settings
        try:
            from cc_project_manager_pkg.simulation_manager import SimulationManager
            self.sim_manager = SimulationManager()
            self.current_path = self.sim_manager.project_config.get("gtkwave_tool_path", {}).get("gtkwave", "")
            self.current_preference = self.sim_manager.project_config.get("gtkwave_preference", "UNDEFINED")
        except Exception as e:
            self.sim_manager = None
            self.current_path = ""
            self.current_preference = "UNDEFINED"
            logging.error(f"Failed to initialize SimulationManager: {e}")
        
        self.init_ui()
    
    def init_ui(self):
        """Initialize the dialog UI."""
        layout = QVBoxLayout(self)
        
        # Header
        header_label = QLabel("🌊 GTKWave Configuration")
        header_label.setFont(QFont("Arial", 14, QFont.Bold))
        header_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(header_label)
        
        # Current status section
        status_group = QGroupBox("Current GTKWave Status")
        status_layout = QVBoxLayout(status_group)
        
        self.status_text = QTextEdit()
        self.status_text.setReadOnly(True)
        self.status_text.setMaximumHeight(150)
        status_layout.addWidget(self.status_text)
        
        layout.addWidget(status_group)
        
        # Path configuration section
        path_group = QGroupBox("GTKWave Path Configuration")
        path_layout = QFormLayout(path_group)
        
        # Path input field
        path_input_layout = QHBoxLayout()
        
        self.path_input = QLineEdit()
        self.path_input.setPlaceholderText("Enter path to GTKWave executable...")
        self.path_input.setToolTip("Path to gtkwave.exe (Windows) or gtkwave (Linux/Mac)")
        if self.current_path:
            self.path_input.setText(self.current_path)
        
        # Browse button
        browse_btn = QPushButton("📁 Browse")
        browse_btn.setMinimumWidth(100)
        browse_btn.setMaximumWidth(120)
        browse_btn.clicked.connect(self.browse_path)
        
        # Test button
        test_btn = QPushButton("✓ Test")
        test_btn.setMinimumWidth(80)
        test_btn.setMaximumWidth(100)
        test_btn.clicked.connect(self.test_path)
        
        path_input_layout.addWidget(self.path_input)
        path_input_layout.addWidget(browse_btn)
        path_input_layout.addWidget(test_btn)
        
        path_layout.addRow("GTKWave Path:", path_input_layout)
        
        layout.addWidget(path_group)
        
        # Refresh Status button
        refresh_status_btn = QPushButton("🔄 Refresh Status")
        refresh_status_btn.clicked.connect(self.refresh_status)
        refresh_status_btn.setMaximumWidth(200)
        refresh_layout = QHBoxLayout()
        refresh_layout.addStretch()
        refresh_layout.addWidget(refresh_status_btn)
        refresh_layout.addStretch()
        layout.addLayout(refresh_layout)
        
        # Instructions
        instructions = QLabel(
            "💡 Instructions:\n"
            "• Use 'Browse' to select the GTKWave executable file\n"
            "• Use 'Test' to validate that the path works correctly\n"
            "• Path must point to the actual executable (e.g., gtkwave.exe, gtkwave)\n"
            "• Leave empty to use PATH environment variable"
        )
        instructions.setWordWrap(True)
        instructions.setStyleSheet("color: #64b5f6; font-size: 11px; padding: 10px;")
        layout.addWidget(instructions)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        # Reset button
        reset_btn = QPushButton("🔄 Reset to Current")
        reset_btn.clicked.connect(self.reset_path)
        button_layout.addWidget(reset_btn)
        
        button_layout.addStretch()
        
        # Cancel and Apply buttons
        cancel_btn = QPushButton("❌ Cancel")
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)
        
        apply_btn = QPushButton("✅ Apply Changes")
        apply_btn.clicked.connect(self.apply_changes)
        apply_btn.setDefault(True)
        button_layout.addWidget(apply_btn)
        
        layout.addLayout(button_layout)
        
        # Initial status refresh
        self.refresh_status()
    
    def refresh_status(self):
        """Refresh the GTKWave status display."""
        if not self.sim_manager:
            self.status_text.setText("❌ SimulationManager not available")
            return
        
        try:
            # Get current preference and path
            preference = self.sim_manager.project_config.get("gtkwave_preference", "UNDEFINED")
            configured_path = self.sim_manager.project_config.get("gtkwave_tool_path", {}).get("gtkwave", "")
            
            status_text = f"Current Preference: {preference}\n\n"
            
            # Check PATH availability
            try:
                path_available = self.sim_manager.check_gtkwave_path()
                if path_available:
                    status_text += "PATH: ✅ Available\n"
                else:
                    status_text += "PATH: ❌ Not available\n"
            except:
                status_text += "PATH: ❌ Not available\n"
            
            # Check direct path
            if configured_path:
                if os.path.exists(configured_path):
                    status_text += f"DIRECT: ✅ Available ({configured_path})\n"
                else:
                    status_text += f"DIRECT: ❌ Path not found ({configured_path})\n"
            else:
                status_text += "DIRECT: ⚠️ Not configured\n"
            
            # Overall status
            status_text += "\nOverall Status: "
            if self.sim_manager.check_gtkwave():
                status_text += "✅ GTKWave is available and ready to use"
            else:
                status_text += "❌ GTKWave is not available"
            
            self.status_text.setText(status_text)
            
        except Exception as e:
            self.status_text.setText(f"❌ Error checking status: {e}")
    
    def browse_path(self):
        """Browse for GTKWave executable path."""
        if os.name == 'nt':  # Windows
            file_filter = "Executable Files (*.exe);;All Files (*)"
            default_name = "gtkwave.exe"
        else:  # Unix/Linux
            file_filter = "All Files (*)"
            default_name = "gtkwave"
        
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            f"Select {default_name}",
            "",
            file_filter
        )
        
        if file_path:
            self.path_input.setText(file_path)
    
    def test_path(self):
        """Test the GTKWave path."""
        path = self.path_input.text().strip()
        
        if not path:
            QMessageBox.warning(self, "No Path", "Please enter a path to test.")
            return
        
        if not os.path.exists(path):
            QMessageBox.critical(self, "Path Not Found", f"The specified path does not exist:\n{path}")
            return
        
        try:
            # Test the GTKWave executable
            import subprocess
            result = subprocess.run([path, "--version"], 
                                  capture_output=True, text=True, check=True, timeout=10)
            QMessageBox.information(
                self, 
                "Test Successful", 
                f"✅ GTKWave test successful!\n\nVersion info:\n{result.stdout.strip()}"
            )
        except subprocess.TimeoutExpired:
            QMessageBox.warning(self, "Test Timeout", "GTKWave test timed out after 10 seconds.")
        except subprocess.CalledProcessError as e:
            QMessageBox.critical(
                self, 
                "Test Failed", 
                f"❌ GTKWave test failed!\n\nError: {e}\nOutput: {e.stdout}\nError: {e.stderr}"
            )
        except Exception as e:
            QMessageBox.critical(self, "Test Error", f"❌ Error testing GTKWave:\n{e}")
    
    def reset_path(self):
        """Reset path to current configuration."""
        self.path_input.setText(self.current_path)
    
    def apply_changes(self):
        """Apply the GTKWave configuration changes."""
        if not self.sim_manager:
            QMessageBox.critical(self, "Error", "SimulationManager not available")
            return
        
        new_path = self.path_input.text().strip()
        
        try:
            if new_path:
                # Add the new path
                if self.sim_manager.add_gtkwave_path(new_path):
                    QMessageBox.information(
                        self,
                        "Success",
                        f"✅ GTKWave path configured successfully!\n\nPath: {new_path}"
                    )
                    self.accept()
                else:
                    QMessageBox.critical(
                        self,
                        "Failed",
                        f"❌ Failed to configure GTKWave path.\n\nCheck that the path exists and points to a valid GTKWave executable."
                    )
            else:
                # Clear the path (use PATH only)
                self.sim_manager.project_config.setdefault("gtkwave_tool_path", {})["gtkwave"] = ""
                
                # Save configuration
                import yaml
                with open(self.sim_manager.config_path, "w") as config_file:
                    yaml.safe_dump(self.sim_manager.project_config, config_file)
                
                QMessageBox.information(
                    self,
                    "Success",
                    "✅ GTKWave path cleared. Will use PATH environment variable."
                )
                self.accept()
                
        except Exception as e:
            QMessageBox.critical(self, "Error", f"❌ Error applying changes:\n{e}")


class SimulationConfigDialog(QDialog):
    """Dialog for configuring simulation settings."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Configure Simulation Settings")
        self.setModal(True)
        self.resize(500, 400)
        
        # Initialize SimulationManager to get current settings
        try:
            from cc_project_manager_pkg.simulation_manager import SimulationManager
            self.sim_manager = SimulationManager()
            self.current_settings = self.sim_manager.get_simulation_length()
            self.current_profile = self.sim_manager.get_current_simulation_profile()
            self.supported_prefixes = self.sim_manager.supported_time_prefixes
        except Exception as e:
            self.sim_manager = None
            self.current_settings = (1000, "ns")
            self.current_profile = "standard"
            self.supported_prefixes = ["ns", "us", "ms"]
            logging.error(f"Failed to initialize SimulationManager: {e}")
        
        self.init_ui()
    
    def init_ui(self):
        """Initialize the dialog UI."""
        layout = QVBoxLayout(self)
        
        # Header
        header_label = QLabel("🧪 Simulation Configuration")
        header_label.setFont(QFont("Arial", 14, QFont.Bold))
        header_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(header_label)
        
        # Current settings section
        current_group = QGroupBox("Current Settings")
        current_layout = QVBoxLayout(current_group)
        
        if self.current_settings:
            sim_time, time_prefix = self.current_settings
            current_text = f"Profile: {self.current_profile}\nDuration: {sim_time}{time_prefix}"
        else:
            current_text = "Profile: Unknown\nDuration: Unknown"
        
        current_label = QLabel(current_text)
        current_label.setStyleSheet("color: #64b5f6; font-size: 12px;")
        current_layout.addWidget(current_label)
        
        layout.addWidget(current_group)
        
        # Settings configuration section
        settings_group = QGroupBox("Simulation Settings")
        settings_layout = QFormLayout(settings_group)
        
        # Simulation time input
        self.time_input = QSpinBox()
        self.time_input.setRange(1, 1000000)
        self.time_input.setValue(self.current_settings[0] if self.current_settings else 1000)
        self.time_input.setToolTip("Simulation duration (numeric value)")
        
        # Time prefix selection
        self.prefix_combo = QComboBox()
        self.prefix_combo.addItems(self.supported_prefixes)
        if self.current_settings:
            current_prefix = self.current_settings[1]
            if current_prefix in self.supported_prefixes:
                self.prefix_combo.setCurrentText(current_prefix)
        self.prefix_combo.setToolTip("Time unit for simulation duration")
        
        # Time layout
        time_layout = QHBoxLayout()
        time_layout.addWidget(self.time_input)
        time_layout.addWidget(self.prefix_combo)
        
        settings_layout.addRow("Simulation Duration:", time_layout)
        
        layout.addWidget(settings_group)
        
        # Profile management section
        profile_group = QGroupBox("Profile Management")
        profile_layout = QVBoxLayout(profile_group)
        
        # Profile selection
        profile_select_layout = QHBoxLayout()
        profile_select_layout.addWidget(QLabel("Active Profile:"))
        
        self.profile_combo = QComboBox()
        self._load_available_profiles()
        profile_select_layout.addWidget(self.profile_combo)
        
        apply_profile_btn = QPushButton("Apply Profile")
        apply_profile_btn.clicked.connect(self.apply_profile)
        profile_select_layout.addWidget(apply_profile_btn)
        
        profile_layout.addLayout(profile_select_layout)
        
        # Profile creation
        create_profile_layout = QHBoxLayout()
        self.new_profile_input = QLineEdit()
        self.new_profile_input.setPlaceholderText("Enter new profile name...")
        create_profile_layout.addWidget(self.new_profile_input)
        
        create_profile_btn = QPushButton("Create Profile")
        create_profile_btn.clicked.connect(self.create_profile)
        create_profile_layout.addWidget(create_profile_btn)
        
        profile_layout.addLayout(create_profile_layout)
        
        layout.addWidget(profile_group)
        
        # Instructions
        instructions = QLabel(
            "💡 Instructions:\n"
            "• Set simulation duration and time unit\n"
            "• Create custom profiles for different test scenarios\n"
            "• Apply existing profiles to quickly switch settings\n"
            "• Changes are saved to the project configuration"
        )
        instructions.setWordWrap(True)
        instructions.setStyleSheet("color: #64b5f6; font-size: 11px; padding: 10px;")
        layout.addWidget(instructions)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        # Reset button
        reset_btn = QPushButton("🔄 Reset to Defaults")
        reset_btn.clicked.connect(self.reset_to_defaults)
        button_layout.addWidget(reset_btn)
        
        button_layout.addStretch()
        
        # Cancel and Apply buttons
        cancel_btn = QPushButton("❌ Cancel")
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)
        
        apply_btn = QPushButton("✅ Apply Settings")
        apply_btn.clicked.connect(self.apply_settings)
        apply_btn.setDefault(True)
        button_layout.addWidget(apply_btn)
        
        layout.addLayout(button_layout)
    
    def _load_available_profiles(self):
        """Load available simulation profiles."""
        if not self.sim_manager:
            return
        
        try:
            # Get all available profiles (presets + user profiles)
            presets = self.sim_manager.get_simulation_presets()
            user_profiles = self.sim_manager.get_user_simulation_profiles()
            
            self.profile_combo.clear()
            
            # Add presets
            for name in presets.keys():
                self.profile_combo.addItem(f"{name} (preset)")
            
            # Add user profiles
            for name in user_profiles.keys():
                self.profile_combo.addItem(f"{name} (user)")
            
            # Set current profile
            if self.current_profile:
                # Find and select current profile
                for i in range(self.profile_combo.count()):
                    item_text = self.profile_combo.itemText(i)
                    if self.current_profile in item_text:
                        self.profile_combo.setCurrentIndex(i)
                        break
                        
        except Exception as e:
            logging.error(f"Error loading simulation profiles: {e}")
    
    def apply_profile(self):
        """Apply selected profile settings."""
        if not self.sim_manager:
            return
        
        try:
            selected_text = self.profile_combo.currentText()
            if not selected_text:
                return
            
            # Extract profile name (remove " (preset)" or " (user)" suffix)
            profile_name = selected_text.split(" (")[0]
            
            # Get profile settings
            if "(preset)" in selected_text:
                presets = self.sim_manager.get_simulation_presets()
                if profile_name in presets:
                    profile_data = presets[profile_name]
                else:
                    return
            else:
                user_profiles = self.sim_manager.get_user_simulation_profiles()
                if profile_name in user_profiles:
                    profile_data = user_profiles[profile_name]
                else:
                    return
            
            # Update UI with profile settings
            self.time_input.setValue(profile_data["simulation_time"])
            self.prefix_combo.setCurrentText(profile_data["time_prefix"])
            
            QMessageBox.information(self, "Profile Applied", f"Applied settings from profile: {profile_name}")
            
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error applying profile: {e}")
    
    def create_profile(self):
        """Create a new user profile."""
        if not self.sim_manager:
            return
        
        profile_name = self.new_profile_input.text().strip()
        if not profile_name:
            QMessageBox.warning(self, "Invalid Name", "Please enter a profile name.")
            return
        
        try:
            # Get current settings from UI
            sim_time = self.time_input.value()
            time_prefix = self.prefix_combo.currentText()
            
            # Create the profile
            success = self.sim_manager.create_user_simulation_profile(
                profile_name, sim_time, time_prefix, f"User profile - {sim_time}{time_prefix}"
            )
            
            if success:
                QMessageBox.information(self, "Profile Created", f"Created profile: {profile_name}")
                self.new_profile_input.clear()
                self._load_available_profiles()  # Refresh profile list
            else:
                QMessageBox.critical(self, "Error", "Failed to create profile.")
                
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error creating profile: {e}")
    
    def reset_to_defaults(self):
        """Reset settings to defaults."""
        self.time_input.setValue(1000)
        self.prefix_combo.setCurrentText("ns")
    
    def apply_settings(self):
        """Apply the simulation settings."""
        if not self.sim_manager:
            QMessageBox.critical(self, "Error", "SimulationManager not available")
            return
        
        try:
            sim_time = self.time_input.value()
            time_prefix = self.prefix_combo.currentText()
            
            # Update simulation settings
            success = self.sim_manager.set_simulation_length(sim_time, time_prefix)
            
            if success:
                QMessageBox.information(
                    self,
                    "Settings Applied",
                    f"✅ Simulation settings updated!\n\nDuration: {sim_time}{time_prefix}"
                )
                self.accept()
            else:
                QMessageBox.critical(self, "Error", "Failed to apply simulation settings.")
                
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Error applying settings: {e}")


class SimulationRunDialog(QDialog):
    """Dialog for configuring and running simulation with time settings."""
    
    def __init__(self, parent=None, simulation_type="behavioral"):
        super().__init__(parent)
        self.simulation_type = simulation_type
        self.setWindowTitle(f"Run {simulation_type.title()} Simulation")
        self.setModal(True)
        self.resize(450, 350)
        
        # Initialize SimulationManager to get current settings
        try:
            from cc_project_manager_pkg.simulation_manager import SimulationManager
            self.sim_manager = SimulationManager()
            self.current_settings = self.sim_manager.get_simulation_length()
            self.supported_prefixes = self.sim_manager.supported_time_prefixes
        except Exception as e:
            self.sim_manager = None
            self.current_settings = (1000, "ns")
            self.supported_prefixes = ["ns", "us", "ms"]
            logging.error(f"Failed to initialize SimulationManager: {e}")
        
        self.init_ui()
    
    def init_ui(self):
        """Initialize the dialog UI."""
        layout = QVBoxLayout(self)
        
        # Header
        header_label = QLabel(f"🧪 {self.simulation_type.title()} Simulation")
        header_label.setFont(QFont("Arial", 14, QFont.Bold))
        header_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(header_label)
        
        # Simulation info section
        info_group = QGroupBox("Simulation Information")
        info_layout = QVBoxLayout(info_group)
        
        # Show selected testbench if available
        if hasattr(self.parent(), 'selected_testbench') and self.parent().selected_testbench:
            testbench_info = f"Selected Testbench: {self.parent().selected_testbench}"
            testbench_label = QLabel(testbench_info)
            testbench_label.setStyleSheet("color: #4CAF50; font-weight: bold;")
        else:
            testbench_label = QLabel("Selected Testbench: None (will use default)")
            testbench_label.setStyleSheet("color: #FFA726; font-weight: bold;")
        
        info_layout.addWidget(testbench_label)
        
        # Current settings
        if self.current_settings:
            sim_time, time_prefix = self.current_settings
            current_text = f"Current Settings: {sim_time}{time_prefix}"
        else:
            current_text = "Current Settings: 1000ns (default)"
        
        current_label = QLabel(current_text)
        current_label.setStyleSheet("color: #64b5f6; font-size: 11px;")
        info_layout.addWidget(current_label)
        
        layout.addWidget(info_group)
        
        # Simulation time configuration
        time_group = QGroupBox("Simulation Duration")
        time_layout = QFormLayout(time_group)
        
        # Simulation time input
        self.time_input = QSpinBox()
        self.time_input.setRange(1, 1000000)
        self.time_input.setValue(self.current_settings[0] if self.current_settings else 1000)
        self.time_input.setToolTip("Simulation duration (numeric value)")
        
        # Time prefix selection
        self.prefix_combo = QComboBox()
        self.prefix_combo.addItems(self.supported_prefixes)
        if self.current_settings:
            current_prefix = self.current_settings[1]
            if current_prefix in self.supported_prefixes:
                self.prefix_combo.setCurrentText(current_prefix)
        self.prefix_combo.setToolTip("Time unit for simulation duration")
        
        # Time layout
        time_input_layout = QHBoxLayout()
        time_input_layout.addWidget(self.time_input)
        time_input_layout.addWidget(self.prefix_combo)
        
        time_layout.addRow("Duration:", time_input_layout)
        
        # Save settings checkbox
        self.save_settings_cb = QCheckBox("Save as default simulation time")
        self.save_settings_cb.setChecked(True)
        self.save_settings_cb.setToolTip("Save these settings for future simulations")
        time_layout.addRow("", self.save_settings_cb)
        
        layout.addWidget(time_group)
        
        # Instructions
        instructions = QLabel(
            "💡 Instructions:\n"
            "• Set the simulation duration and time unit\n"
            "• Optionally save settings as default for future simulations\n"
            "• Click 'Run Simulation' to start the simulation process"
        )
        instructions.setWordWrap(True)
        instructions.setStyleSheet("color: #64b5f6; font-size: 11px; padding: 10px;")
        layout.addWidget(instructions)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        # Cancel button
        cancel_btn = QPushButton("❌ Cancel")
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)
        
        button_layout.addStretch()
        
        # Run simulation button
        run_btn = QPushButton(f"🚀 Run {self.simulation_type.title()} Simulation")
        run_btn.clicked.connect(self.accept)
        run_btn.setDefault(True)
        run_btn.setStyleSheet("QPushButton { background-color: #4CAF50; color: white; font-weight: bold; }")
        button_layout.addWidget(run_btn)
        
        layout.addLayout(button_layout)
    
    def get_simulation_settings(self):
        """Get the configured simulation settings."""
        simulation_time = self.time_input.value()
        time_prefix = self.prefix_combo.currentText()
        save_settings = self.save_settings_cb.isChecked()
        
        return {
            'simulation_time': simulation_time,
            'time_prefix': time_prefix,
            'save_settings': save_settings,
            'simulation_type': self.simulation_type
        }

class SynthesisConfigDialog(QDialog):
    """Dialog for configuring synthesis settings."""
    
    def __init__(self, parent=None, current_config=None):
        super().__init__(parent)
        self.setWindowTitle("Synthesis Configuration")
        self.setModal(True)
        self.resize(500, 400)
        
        layout = QFormLayout()
        
        # VHDL Standard
        self.vhdl_standard = QComboBox()
        self.vhdl_standard.addItems(['--std=08', '--std=93', '--std=87'])
        
        # IEEE Library
        self.ieee_library = QComboBox()
        self.ieee_library.addItems(['--ieee=synopsys', '--ieee=standard'])
        
        # Default synthesis strategy
        self.default_strategy = QComboBox()
        self.default_strategy.addItems(['area', 'speed', 'balanced', 'quality', 'timing', 'extreme'])
        self.default_strategy.setCurrentText('balanced')
        
        # Default target platform
        self.default_target = QComboBox()
        self.default_target.addItems(['Generic FPGA', 'GateMate FPGA'])
        self.default_target.setCurrentText('GateMate FPGA')
        
        # Options
        self.verbose = QCheckBox("Verbose output")
        self.keep_hierarchy = QCheckBox("Keep hierarchy")
        
        layout.addRow("VHDL Standard:", self.vhdl_standard)
        layout.addRow("IEEE Library:", self.ieee_library)
        layout.addRow("Default Strategy:", self.default_strategy)
        layout.addRow("Default Target:", self.default_target)
        layout.addRow("", self.verbose)
        layout.addRow("", self.keep_hierarchy)
        
        # Load current config if provided
        if current_config:
            self.load_config(current_config)
        
        # Buttons
        button_layout = QHBoxLayout()
        ok_btn = QPushButton("OK")
        cancel_btn = QPushButton("Cancel")
        reset_btn = QPushButton("Reset to Defaults")
        
        ok_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)
        reset_btn.clicked.connect(self.reset_defaults)
        
        button_layout.addWidget(reset_btn)
        button_layout.addStretch()
        button_layout.addWidget(ok_btn)
        button_layout.addWidget(cancel_btn)
        
        layout.addRow(button_layout)
        self.setLayout(layout)
    
    def load_config(self, config):
        """Load configuration into the dialog."""
        if 'vhdl_standard' in config:
            index = self.vhdl_standard.findText(config['vhdl_standard'])
            if index >= 0:
                self.vhdl_standard.setCurrentIndex(index)
        
        if 'ieee_library' in config:
            index = self.ieee_library.findText(config['ieee_library'])
            if index >= 0:
                self.ieee_library.setCurrentIndex(index)
        
        if 'default_strategy' in config:
            index = self.default_strategy.findText(config['default_strategy'])
            if index >= 0:
                self.default_strategy.setCurrentIndex(index)
        
        if 'default_target' in config:
            index = self.default_target.findText(config['default_target'])
            if index >= 0:
                self.default_target.setCurrentIndex(index)
        
        self.verbose.setChecked(config.get('verbose', False))
        self.keep_hierarchy.setChecked(config.get('keep_hierarchy', False))
    
    def reset_defaults(self):
        """Reset to default values."""
        self.vhdl_standard.setCurrentText('--std=08')
        self.ieee_library.setCurrentText('--ieee=synopsys')
        self.default_strategy.setCurrentText('balanced')
        self.default_target.setCurrentText('GateMate FPGA')
        self.verbose.setChecked(False)
        self.keep_hierarchy.setChecked(False)
    
    def get_config(self):
        """Get the configuration from the dialog."""
        return {
            'vhdl_standard': self.vhdl_standard.currentText(),
            'ieee_library': self.ieee_library.currentText(),
            'default_strategy': self.default_strategy.currentText(),
            'default_target': self.default_target.currentText(),
            'verbose': self.verbose.isChecked(),
            'keep_hierarchy': self.keep_hierarchy.isChecked()
        }


class SimulationConfigDialog(QDialog):
    """Dialog for configuring simulation settings."""
    
    def __init__(self, parent=None, current_config=None):
        super().__init__(parent)
        self.setWindowTitle("Simulation Configuration")
        self.setModal(True)
        self.resize(500, 400)
        
        layout = QFormLayout()
        
        # VHDL Standard
        self.vhdl_standard = QComboBox()
        self.vhdl_standard.addItems(['VHDL-2008', 'VHDL-1993', 'VHDL-1993c'])
        self.vhdl_standard.setCurrentText('VHDL-2008')
        
        # IEEE Library
        self.ieee_library = QComboBox()
        self.ieee_library.addItems(['synopsys', 'mentor', 'none'])
        self.ieee_library.setCurrentText('synopsys')
        
        # Default simulation time
        self.simulation_time = QSpinBox()
        self.simulation_time.setRange(1, 999999)
        self.simulation_time.setValue(1000)
        self.simulation_time.setSuffix(" time units")
        
        # Time prefix
        self.time_prefix = QComboBox()
        self.time_prefix.addItems(['ns', 'us', 'ms', 'ps', 'fs', 'sec'])
        self.time_prefix.setCurrentText('ns')
        
        # Options
        self.verbose = QCheckBox("Verbose GHDL output")
        self.save_waveforms = QCheckBox("Always save waveforms (VCD files)")
        self.save_waveforms.setChecked(True)
        
        layout.addRow("VHDL Standard:", self.vhdl_standard)
        layout.addRow("IEEE Library:", self.ieee_library)
        layout.addRow("Default Simulation Time:", self.simulation_time)
        layout.addRow("Time Unit:", self.time_prefix)
        layout.addRow("", self.verbose)
        layout.addRow("", self.save_waveforms)
        
        # Load current config if provided
        if current_config:
            self.load_config(current_config)
        
        # Buttons
        button_layout = QHBoxLayout()
        ok_btn = QPushButton("OK")
        cancel_btn = QPushButton("Cancel")
        reset_btn = QPushButton("Reset to Defaults")
        
        ok_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)
        reset_btn.clicked.connect(self.reset_defaults)
        
        button_layout.addWidget(reset_btn)
        button_layout.addStretch()
        button_layout.addWidget(ok_btn)
        button_layout.addWidget(cancel_btn)
        
        layout.addRow(button_layout)
        self.setLayout(layout)
    
    def load_config(self, config):
        """Load configuration into the dialog."""
        if 'vhdl_standard' in config:
            index = self.vhdl_standard.findText(config['vhdl_standard'])
            if index >= 0:
                self.vhdl_standard.setCurrentIndex(index)
        
        if 'ieee_library' in config:
            index = self.ieee_library.findText(config['ieee_library'])
            if index >= 0:
                self.ieee_library.setCurrentIndex(index)
        
        if 'simulation_time' in config:
            self.simulation_time.setValue(config['simulation_time'])
        
        if 'time_prefix' in config:
            index = self.time_prefix.findText(config['time_prefix'])
            if index >= 0:
                self.time_prefix.setCurrentIndex(index)
        
        self.verbose.setChecked(config.get('verbose', False))
        self.save_waveforms.setChecked(config.get('save_waveforms', True))
    
    def reset_defaults(self):
        """Reset to default values."""
        self.vhdl_standard.setCurrentText('VHDL-2008')
        self.ieee_library.setCurrentText('synopsys')
        self.simulation_time.setValue(1000)
        self.time_prefix.setCurrentText('ns')
        self.verbose.setChecked(False)
        self.save_waveforms.setChecked(True)
    
    def get_config(self):
        """Get the configuration from the dialog."""
        return {
            'vhdl_standard': self.vhdl_standard.currentText(),
            'ieee_library': self.ieee_library.currentText(),
            'simulation_time': self.simulation_time.value(),
            'time_prefix': self.time_prefix.currentText(),
            'verbose': self.verbose.isChecked(),
            'save_waveforms': self.save_waveforms.isChecked()
        }


class SynthesisRunDialog(QDialog):
    """Dialog for running synthesis with top entity and GateMate options."""
    
    def __init__(self, parent=None, synth_config=None, available_entities=None):
        super().__init__(parent)
        self.setWindowTitle("Run Synthesis")
        self.setModal(True)
        self.resize(500, 400)
        
        self.synth_config = synth_config or {}
        self.available_entities = available_entities or []
        
        self.init_ui()
    
    def init_ui(self):
        """Initialize the dialog UI."""
        layout = QVBoxLayout(self)
        
        # Header
        header_label = QLabel("⚡ Run Synthesis")
        header_label.setFont(QFont("Arial", 14, QFont.Bold))
        header_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(header_label)
        
        # Current configuration display
        config_group = QGroupBox("Current Synthesis Configuration")
        config_layout = QVBoxLayout(config_group)
        
        config_text = QTextEdit()
        config_text.setReadOnly(True)
        config_text.setMaximumHeight(100)
        
        config_info = f"""Strategy: {self.synth_config.get('strategy', 'balanced')}
VHDL Standard: {self.synth_config.get('vhdl_standard', 'VHDL-2008')}
IEEE Library: {self.synth_config.get('ieee_library', 'synopsys')}"""
        config_text.setPlainText(config_info)
        config_layout.addWidget(config_text)
        
        layout.addWidget(config_group)
        
        # Available entities display
        if self.available_entities:
            entities_group = QGroupBox("Detected VHDL Entities")
            entities_layout = QVBoxLayout(entities_group)
            
            entities_text = QTextEdit()
            entities_text.setReadOnly(True)
            entities_text.setMaximumHeight(120)
            
            entities_info = "\n".join(f"{i+1:2}. {entity}" for i, entity in enumerate(self.available_entities))
            entities_text.setPlainText(entities_info)
            entities_layout.addWidget(entities_text)
            
            layout.addWidget(entities_group)
        
        # Input section
        input_group = QGroupBox("Synthesis Parameters")
        input_layout = QFormLayout(input_group)
        
        # Top entity input
        self.top_entity_input = QLineEdit()
        self.top_entity_input.setPlaceholderText("Enter the name of the top-level entity")
        
        # If we have available entities, create a combo box with them
        if self.available_entities:
            entity_layout = QHBoxLayout()
            self.entity_combo = QComboBox()
            self.entity_combo.addItem("-- Select Entity --")
            self.entity_combo.addItems(list(self.available_entities.keys()))
            self.entity_combo.currentTextChanged.connect(self._on_entity_selected)
            
            entity_layout.addWidget(self.entity_combo)
            entity_layout.addWidget(QLabel("or"))
            entity_layout.addWidget(self.top_entity_input)
            
            input_layout.addRow("Top Entity:", entity_layout)
        else:
            input_layout.addRow("Top Entity:", self.top_entity_input)
        
        # Target platform selection
        self.target_combo = QComboBox()
        self.target_combo.addItems(['Generic FPGA', 'GateMate FPGA'])
        
        # Set default from configuration
        default_target = self.synth_config.get('default_target', 'GateMate FPGA')
        if default_target == 'GateMate FPGA':
            self.target_combo.setCurrentText('GateMate FPGA')
        else:
            self.target_combo.setCurrentText('Generic FPGA')
            
        self.target_combo.setToolTip("Select target FPGA platform for synthesis")
        input_layout.addRow("Target Platform:", self.target_combo)
        
        layout.addWidget(input_group)
        
        # Warning label
        self.warning_label = QLabel()
        self.warning_label.setStyleSheet("color: orange; font-weight: bold;")
        self.warning_label.setWordWrap(True)
        self.warning_label.hide()
        layout.addWidget(self.warning_label)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        self.run_button = QPushButton("Run Synthesis")
        self.run_button.setDefault(True)
        self.run_button.clicked.connect(self._validate_and_accept)
        
        cancel_button = QPushButton("Cancel")
        cancel_button.clicked.connect(self.reject)
        
        button_layout.addStretch()
        button_layout.addWidget(self.run_button)
        button_layout.addWidget(cancel_button)
        
        layout.addLayout(button_layout)
        
        # Connect validation
        self.top_entity_input.textChanged.connect(self._validate_input)
        self._validate_input()
    
    def _on_entity_selected(self, entity_name):
        """Handle entity selection from combo box."""
        if entity_name and entity_name != "-- Select Entity --":
            self.top_entity_input.setText(entity_name)
    
    def _validate_input(self):
        """Validate the input and update UI accordingly."""
        top_entity = self.top_entity_input.text().strip()
        
        if not top_entity:
            self.run_button.setEnabled(False)
            self.warning_label.hide()
            return
        
        # Check if entity exists in available entities
        if self.available_entities and top_entity not in self.available_entities:
            self.warning_label.setText(
                f"⚠️ Warning: '{top_entity}' not found in detected entities.\n"
                "Make sure the entity name is correct and the VHDL file is added to the project."
            )
            self.warning_label.show()
        else:
            self.warning_label.hide()
        
        self.run_button.setEnabled(True)
    
    def _validate_and_accept(self):
        """Validate input and accept dialog if valid."""
        top_entity = self.top_entity_input.text().strip()
        
        if not top_entity:
            QMessageBox.warning(self, "Invalid Input", "Top entity name cannot be empty!")
            return
        
        # If entity not found in available entities, ask for confirmation
        if self.available_entities and top_entity not in self.available_entities:
            reply = QMessageBox.question(
                self, "Entity Not Found",
                f"'{top_entity}' was not found in detected entities.\n\n"
                "Make sure the entity name is correct and the VHDL file is added to the project.\n\n"
                "Continue anyway?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            
            if reply != QMessageBox.Yes:
                return
        
        self.accept()
    
    def get_synthesis_params(self):
        """Get the synthesis parameters from the dialog."""
        return {
            'top_entity': self.top_entity_input.text().strip(),
            'use_gatemate': self.target_combo.currentText() == 'GateMate FPGA'
        }


class SynthesisStrategyDialog(QDialog):
    """Dialog for selecting synthesis strategy for a specific entity."""
    
    def __init__(self, parent=None, entity_name=None, synth_config=None):
        super().__init__(parent)
        self.entity_name = entity_name
        self.synth_config = synth_config or {}
        self.setWindowTitle(f"Run Synthesis - {entity_name}")
        self.setModal(True)
        self.setFixedSize(500, 400)
        self.init_ui()
    
    def init_ui(self):
        """Initialize the dialog UI."""
        layout = QVBoxLayout(self)
        
        # Entity info
        entity_frame = QFrame()
        entity_frame.setFrameStyle(QFrame.StyledPanel)
        entity_layout = QVBoxLayout(entity_frame)
        
        entity_label = QLabel(f"Synthesizing Entity: {self.entity_name}")
        entity_label.setStyleSheet("font-weight: bold; font-size: 14px; color: #4CAF50;")
        entity_layout.addWidget(entity_label)
        
        layout.addWidget(entity_frame)
        
        # Strategy selection
        strategy_group = QGroupBox("Synthesis Strategy")
        strategy_layout = QVBoxLayout(strategy_group)
        
        # Load available strategies from synthesis_options.yml
        self.strategies = self._load_synthesis_strategies()
        
        self.strategy_combo = QComboBox()
        for strategy, description in self.strategies.items():
            self.strategy_combo.addItem(f"{strategy.title()} - {description}", strategy)
        
        # Set default from configuration or fallback to balanced
        default_strategy = self.synth_config.get('default_strategy', 'balanced')
        strategy_index = self.strategy_combo.findData(default_strategy)
        if strategy_index >= 0:
            self.strategy_combo.setCurrentIndex(strategy_index)
        else:
            # Fallback to balanced if default not found
            balanced_index = self.strategy_combo.findData("balanced")
            if balanced_index >= 0:
                self.strategy_combo.setCurrentIndex(balanced_index)
        
        strategy_layout.addWidget(QLabel("Select Strategy:"))
        strategy_layout.addWidget(self.strategy_combo)
        
        # Strategy description
        self.description_label = QLabel()
        self.description_label.setWordWrap(True)
        self.description_label.setStyleSheet("color: #888888; font-style: italic; padding: 10px;")
        self.update_description()
        
        # Connect signal to update description
        self.strategy_combo.currentTextChanged.connect(self.update_description)
        
        strategy_layout.addWidget(self.description_label)
        
        layout.addWidget(strategy_group)
        
        # GateMate option
        gatemate_group = QGroupBox("Target Options")
        gatemate_layout = QVBoxLayout(gatemate_group)
        
        self.gatemate_checkbox = QCheckBox("Use GateMate FPGA-specific synthesis")
        self.gatemate_checkbox.setToolTip("Enable GateMate-specific optimizations for better results on Cologne Chip FPGAs")
        
        # Set default from configuration
        default_target = self.synth_config.get('default_target', 'GateMate FPGA')
        self.gatemate_checkbox.setChecked(default_target == 'GateMate FPGA')
        
        gatemate_layout.addWidget(self.gatemate_checkbox)
        
        layout.addWidget(gatemate_group)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        
        explain_btn = QPushButton("Explain Strategy")
        explain_btn.clicked.connect(self.show_strategy_explanation)
        explain_btn.setStyleSheet("QPushButton { background-color: #2196F3; color: white; font-weight: bold; }")
        
        self.run_btn = QPushButton("Run Synthesis")
        self.run_btn.clicked.connect(self.accept)
        self.run_btn.setDefault(True)
        self.run_btn.setStyleSheet("QPushButton { background-color: #4CAF50; color: white; font-weight: bold; }")
        
        button_layout.addWidget(cancel_btn)
        button_layout.addWidget(explain_btn)
        button_layout.addWidget(self.run_btn)
        
        layout.addLayout(button_layout)
    
    def update_description(self):
        """Update the strategy description based on selection."""
        current_strategy = self.strategy_combo.currentData()
        if current_strategy in self.strategies:
            description = self.strategies[current_strategy]
            self.description_label.setText(f"Description: {description}")
    
    def _load_synthesis_strategies(self):
        """Load synthesis strategies from synthesis_options.yml file.
        
        Returns:
            dict: Dictionary of strategy_name -> description
        """
        try:
            from cc_project_manager_pkg.toolchain_manager import ToolChainManager
            import yaml
            
            tcm = ToolChainManager()
            
            # Get synthesis options file path
            setup_files = tcm.config.get("setup_files_initial", {})
            if "synthesis_options_file" in setup_files:
                synthesis_options_path = setup_files["synthesis_options_file"][0]
            else:
                # Fallback to config directory
                config_dir = tcm.config.get("project_structure", {}).get("config", [])
                if isinstance(config_dir, list) and config_dir:
                    synthesis_options_path = os.path.join(config_dir[0], "synthesis_options.yml")
                else:
                    synthesis_options_path = os.path.join(config_dir, "synthesis_options.yml")
            
            # Load synthesis options
            if os.path.exists(synthesis_options_path):
                with open(synthesis_options_path, 'r') as f:
                    synthesis_options = yaml.safe_load(f)
                
                strategies = {}
                if synthesis_options and 'synthesis_strategies' in synthesis_options:
                    for strategy_name, strategy_config in synthesis_options['synthesis_strategies'].items():
                        description = strategy_config.get('description', 'No description available')
                        # Mark custom strategies
                        if strategy_config.get('custom', False):
                            description = f"[Custom] {description}"
                        strategies[strategy_name] = description
                
                if strategies:
                    return strategies
            
        except Exception as e:
            logging.error(f"Error loading synthesis strategies: {e}")
        
        # Fallback to hardcoded strategies if loading fails
        return {
            "area": "Optimize for minimal resource usage (LUTs, logic gates)",
            "speed": "Optimize for maximum performance/frequency", 
            "balanced": "Standard optimization balancing area and speed",
            "quality": "More thorough optimization for better results",
            "timing": "Advanced timing-driven optimization",
            "extreme": "Maximum optimization for performance-critical designs"
        }
    
    def show_strategy_explanation(self):
        """Show the strategy explanation dialog with flow diagram."""
        current_strategy = self.strategy_combo.currentData()
        dialog = StrategyExplanationDialog(self, current_strategy)
        dialog.exec_()
    
    def get_synthesis_params(self):
        """Get the synthesis parameters from the dialog."""
        return {
            "strategy": self.strategy_combo.currentData(),
            "use_gatemate": self.gatemate_checkbox.isChecked(),
            "entity_name": self.entity_name
        }


class StrategyExplanationDialog(QDialog):
    """Dialog for explaining synthesis strategies with visual flow diagram."""
    
    def __init__(self, parent=None, strategy_name="balanced"):
        super().__init__(parent)
        self.strategy_name = strategy_name
        self.setWindowTitle(f"Strategy Explanation - {strategy_name.title()}")
        self.setModal(True)
        self.resize(800, 600)
        self.init_ui()
    
    def init_ui(self):
        """Initialize the dialog UI."""
        layout = QVBoxLayout(self)
        
        # Title
        title = QLabel(f"Synthesis Strategy: {self.strategy_name.title()}")
        title.setFont(QFont("Arial", 16, QFont.Bold))
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("color: #2196F3; margin: 10px;")
        layout.addWidget(title)
        
        # Create tab widget for different views
        tab_widget = QTabWidget()
        
        # Flow Diagram Tab
        flow_tab = QWidget()
        flow_layout = QVBoxLayout(flow_tab)
        
        # Strategy flow diagram
        diagram_label = QLabel("Synthesis Flow Diagram:")
        diagram_label.setFont(QFont("Arial", 12, QFont.Bold))
        flow_layout.addWidget(diagram_label)
        
        # Create the flow diagram as HTML
        diagram_html = self._create_strategy_diagram()
        diagram_view = QTextEdit()
        diagram_view.setHtml(diagram_html)
        diagram_view.setReadOnly(True)
        diagram_view.setMinimumHeight(300)
        flow_layout.addWidget(diagram_view)
        
        tab_widget.addTab(flow_tab, "Flow Diagram")
        
        # Command Details Tab
        details_tab = QWidget()
        details_layout = QVBoxLayout(details_tab)
        
        # Strategy commands
        commands_label = QLabel("Yosys Commands:")
        commands_label.setFont(QFont("Arial", 12, QFont.Bold))
        details_layout.addWidget(commands_label)
        
        commands_text = self._get_strategy_commands()
        commands_view = QTextEdit()
        commands_view.setPlainText(commands_text)
        commands_view.setReadOnly(True)
        commands_view.setFont(QFont("Courier", 10))
        details_layout.addWidget(commands_view)
        
        # Strategy description
        description_label = QLabel("Description:")
        description_label.setFont(QFont("Arial", 12, QFont.Bold))
        details_layout.addWidget(description_label)
        
        description_text = self._get_strategy_description()
        description_view = QTextEdit()
        description_view.setHtml(description_text)
        description_view.setReadOnly(True)
        description_view.setMaximumHeight(150)
        details_layout.addWidget(description_view)
        
        tab_widget.addTab(details_tab, "Command Details")
        
        layout.addWidget(tab_widget)
        
        # Close button
        button_layout = QHBoxLayout()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        close_btn.setDefault(True)
        button_layout.addStretch()
        button_layout.addWidget(close_btn)
        layout.addLayout(button_layout)
    
    def _create_strategy_diagram(self):
        """Create HTML representation of the strategy flow diagram."""
        # Define strategy-specific commands
        strategy_commands = {
            "area": ["abc -lut 4 -dress", "opt_clean", "opt -full", "clean"],
            "speed": ["abc -fast", "opt", "clean"],
            "balanced": ["abc", "opt", "clean"],
            "quality": ["opt -full", "abc", "opt -full", "clean"],
            "timing": ["abc -lut 4", "opt_clean", "abc -lut 4 -dff -D 0.1", "opt -full", "clean"],
            "extreme": ["opt -full", "abc -lut 4", "opt -full -fine", "abc -lut 4 -dff -D 0.01", "opt -full -fine", "clean"]
        }
        
        commands = strategy_commands.get(self.strategy_name, ["abc", "opt", "clean"])
        
        html = f"""
        <html>
        <head>
            <style>
                .flow-container {{
                    font-family: Arial, sans-serif;
                    text-align: center;
                    padding: 20px;
                    background-color: white;
                }}
                .flow-box {{
                    background-color: #ffffff;
                    border: 3px solid #2196F3;
                    border-radius: 8px;
                    padding: 15px;
                    margin: 10px auto;
                    max-width: 300px;
                    font-weight: bold;
                    font-size: 14px;
                    color: #1565C0;
                    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                }}
                .strategy-box {{
                    background-color: #ffffff;
                    border: 3px solid #4CAF50;
                    border-radius: 8px;
                    padding: 15px;
                    margin: 10px auto;
                    max-width: 450px;
                    font-weight: bold;
                    color: #2E7D32;
                    font-size: 14px;
                    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                }}
                .arrow {{
                    font-size: 28px;
                    color: #2196F3;
                    margin: 8px;
                    font-weight: bold;
                }}
                .command {{
                    background-color: #F8F9FA;
                    border: 2px solid #FF9800;
                    border-radius: 6px;
                    padding: 8px;
                    margin: 5px;
                    font-family: 'Courier New', monospace;
                    font-size: 13px;
                    font-weight: bold;
                    color: #E65100;
                    display: inline-block;
                    min-width: 120px;
                }}
            </style>
        </head>
        <body>
            <div class="flow-container">
                <div class="flow-box">VHDL Input Files</div>
                <div class="arrow">↓</div>
                <div class="flow-box">synth -top {{entity}} -flatten</div>
                <div class="arrow">↓</div>
                <div class="strategy-box">
                    <strong>{self.strategy_name.title()} Strategy</strong><br/><br/>
                    {self._format_commands_html(commands)}
                </div>
                <div class="arrow">↓</div>
                <div class="flow-box">Output Generation</div>
                <div class="arrow">↓</div>
                <div class="flow-box">write_verilog<br/>write_json</div>
            </div>
        </body>
        </html>
        """
        return html
    
    def _format_commands_html(self, commands):
        """Format commands as HTML."""
        formatted = ""
        for cmd in commands:
            formatted += f'<div class="command">{cmd}</div>'
        return formatted
    
    def _get_strategy_commands(self):
        """Get the full command sequence for the strategy."""
        # Load strategy commands from YosysCommands
        try:
            from cc_project_manager_pkg.yosys_commands import YosysCommands
            strategies = YosysCommands.SYNTHESIS_STRATEGIES
            
            if self.strategy_name in strategies:
                commands = strategies[self.strategy_name]
                full_sequence = [
                    "# VHDL Analysis and Elaboration",
                    "ghdl --std=08 --ieee=synopsys [vhdl_files] -e [entity]",
                    "",
                    "# Synthesis Strategy Commands",
                ]
                
                for i, cmd in enumerate(commands, 1):
                    full_sequence.append(f"{i}. {cmd}")
                
                full_sequence.extend([
                    "",
                    "# Output Generation", 
                    "write_verilog -noattr [output].v",
                    "write_json [output].json"
                ])
                
                return "\n".join(full_sequence)
        except Exception:
            pass
        
        return f"Commands for {self.strategy_name} strategy not available."
    
    def _get_strategy_description(self):
        """Get detailed description of the strategy."""
        descriptions = {
            "area": """
                <h3>Area-Optimized Strategy</h3>
                <p><strong>Goal:</strong> Minimize resource usage (LUTs, logic gates)</p>
                <p><strong>Key Features:</strong></p>
                <ul>
                    <li><code>abc -lut 4 -dress</code>: Maps to 4-input LUTs with area optimization</li>
                    <li><code>opt_clean</code>: Removes unused cells and wires</li>
                    <li><code>opt -full</code>: Performs comprehensive optimizations</li>
                </ul>
                <p><strong>Best for:</strong> Designs with tight area constraints or large designs that need to fit in smaller FPGAs</p>
                <p><strong>Trade-offs:</strong> May sacrifice some performance for smaller area</p>
            """,
            "speed": """
                <h3>Speed-Optimized Strategy</h3>
                <p><strong>Goal:</strong> Maximize performance/frequency</p>
                <p><strong>Key Features:</strong></p>
                <ul>
                    <li><code>abc -fast</code>: Fast technology mapping optimized for speed</li>
                    <li><code>opt</code>: Basic optimizations to maintain speed focus</li>
                </ul>
                <p><strong>Best for:</strong> High-performance designs where timing is critical</p>
                <p><strong>Trade-offs:</strong> May use more resources to achieve higher speed</p>
            """,
            "balanced": """
                <h3>Balanced Strategy</h3>
                <p><strong>Goal:</strong> Balance area and speed optimization</p>
                <p><strong>Key Features:</strong></p>
                <ul>
                    <li><code>abc</code>: Standard technology mapping</li>
                    <li><code>opt</code>: Basic optimizations</li>
                </ul>
                <p><strong>Best for:</strong> General-purpose designs with no extreme constraints</p>
                <p><strong>Trade-offs:</strong> Good compromise between area and speed</p>
            """,
            "quality": """
                <h3>Quality-Optimized Strategy</h3>
                <p><strong>Goal:</strong> Achieve best overall results through thorough optimization</p>
                <p><strong>Key Features:</strong></p>
                <ul>
                    <li><code>opt -full</code>: Multiple full optimization passes</li>
                    <li><code>abc</code>: Standard technology mapping between optimizations</li>
                </ul>
                <p><strong>Best for:</strong> Production designs where synthesis time is less important than results</p>
                <p><strong>Trade-offs:</strong> Longer synthesis time for better quality</p>
            """,
            "timing": """
                <h3>Timing-Driven Strategy</h3>
                <p><strong>Goal:</strong> Advanced timing-driven optimization</p>
                <p><strong>Key Features:</strong></p>
                <ul>
                    <li><code>abc -lut 4</code>: 4-input LUT mapping</li>
                    <li><code>abc -lut 4 -dff -D 0.1</code>: Timing-driven mapping with 0.1ns delay target</li>
                    <li><code>opt_clean</code> and <code>opt -full</code>: Comprehensive optimizations</li>
                </ul>
                <p><strong>Best for:</strong> Designs with critical timing requirements and complex timing paths</p>
                <p><strong>Trade-offs:</strong> Longer synthesis time, focus on meeting timing constraints</p>
            """,
            "extreme": """
                <h3>Extreme Performance Strategy</h3>
                <p><strong>Goal:</strong> Maximum optimization for highest performance</p>
                <p><strong>Key Features:</strong></p>
                <ul>
                    <li><code>opt -full</code>: Multiple full optimization passes</li>
                    <li><code>opt -full -fine</code>: Fine-grained optimizations</li>
                    <li><code>abc -lut 4 -dff -D 0.01</code>: Aggressive timing-driven mapping with 0.01ns target</li>
                </ul>
                <p><strong>Best for:</strong> Performance-critical designs where synthesis time is not a concern</p>
                <p><strong>Trade-offs:</strong> Significantly longer synthesis time (3-10x), maximum resource usage for performance</p>
            """
        }
        
        return descriptions.get(self.strategy_name, f"<p>Description for {self.strategy_name} strategy not available.</p>")


class CustomStrategyDialog(QDialog):
    """Dialog for creating and managing custom synthesis strategies."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Custom Synthesis Strategy")
        self.setModal(True)
        self.resize(700, 600)
        self.init_ui()
    
    def init_ui(self):
        layout = QVBoxLayout(self)
        
        # Title and description
        title = QLabel("Create Custom Synthesis Strategy")
        title.setFont(QFont("Arial", 12, QFont.Bold))
        layout.addWidget(title)
        
        description = QLabel("Create a custom synthesis strategy with your own Yosys commands and options. This strategy will be available in the Run Synthesis dialog.")
        description.setWordWrap(True)
        layout.addWidget(description)
        
        # Strategy details
        details_group = QGroupBox("Strategy Details")
        details_layout = QFormLayout(details_group)
        
        self.strategy_name_input = QLineEdit()
        self.strategy_name_input.setPlaceholderText("Enter strategy name (e.g., my_custom_strategy)")
        details_layout.addRow("Strategy Name:", self.strategy_name_input)
        
        self.strategy_description_input = QLineEdit()
        self.strategy_description_input.setPlaceholderText("Enter description (e.g., Custom optimization for my design)")
        details_layout.addRow("Description:", self.strategy_description_input)
        
        self.recommended_for_input = QLineEdit()
        self.recommended_for_input.setPlaceholderText("Enter recommended use case (e.g., High-speed designs with custom constraints)")
        details_layout.addRow("Recommended For:", self.recommended_for_input)
        
        layout.addWidget(details_group)
        
        # Yosys commands
        commands_group = QGroupBox("Yosys Commands")
        commands_layout = QVBoxLayout(commands_group)
        
        commands_info = QLabel("Define the Yosys synthesis commands for this strategy. Use {top} as placeholder for the top entity name.")
        commands_info.setWordWrap(True)
        commands_layout.addWidget(commands_info)
        
        self.commands_list = QListWidget()
        self.commands_list.setMaximumHeight(150)
        
        # Add default commands as starting point
        default_commands = [
            "synth -top {top} -flatten",
            "abc",
            "opt",
            "clean"
        ]
        for cmd in default_commands:
            self.commands_list.addItem(cmd)
        
        commands_layout.addWidget(QLabel("Synthesis Commands:"))
        commands_layout.addWidget(self.commands_list)
        
        # Add/remove commands
        cmd_buttons_layout = QHBoxLayout()
        
        self.new_command_input = QLineEdit()
        self.new_command_input.setPlaceholderText("Enter Yosys command (e.g., abc -fast, opt -full)")
        
        add_cmd_btn = QPushButton("Add Command")
        add_cmd_btn.clicked.connect(self.add_command)
        
        remove_cmd_btn = QPushButton("Remove Selected")
        remove_cmd_btn.clicked.connect(self.remove_command)
        
        cmd_buttons_layout.addWidget(self.new_command_input)
        cmd_buttons_layout.addWidget(add_cmd_btn)
        cmd_buttons_layout.addWidget(remove_cmd_btn)
        
        commands_layout.addLayout(cmd_buttons_layout)
        
        layout.addWidget(commands_group)
        
        # Command-line options
        options_group = QGroupBox("Additional Command-Line Options")
        options_layout = QVBoxLayout(options_group)
        
        options_info = QLabel("Optional: Add command-line options that will be passed to Yosys (e.g., -v for verbose, -T for timing).")
        options_info.setWordWrap(True)
        options_layout.addWidget(options_info)
        
        self.options_list = QListWidget()
        self.options_list.setMaximumHeight(100)
        
        options_layout.addWidget(QLabel("Command-Line Options:"))
        options_layout.addWidget(self.options_list)
        
        # Add/remove options
        opt_buttons_layout = QHBoxLayout()
        
        self.new_option_input = QLineEdit()
        self.new_option_input.setPlaceholderText("Enter option (e.g., -v, -T, -l logfile.log)")
        
        add_opt_btn = QPushButton("Add Option")
        add_opt_btn.clicked.connect(self.add_option)
        
        remove_opt_btn = QPushButton("Remove Selected")
        remove_opt_btn.clicked.connect(self.remove_option)
        
        opt_buttons_layout.addWidget(self.new_option_input)
        opt_buttons_layout.addWidget(add_opt_btn)
        opt_buttons_layout.addWidget(remove_opt_btn)
        
        options_layout.addLayout(opt_buttons_layout)
        
        layout.addWidget(options_group)
        
        # Examples
        examples_group = QGroupBox("Common Yosys Commands Examples")
        examples_layout = QVBoxLayout(examples_group)
        
        examples_text = QTextEdit()
        examples_text.setReadOnly(True)
        examples_text.setMaximumHeight(100)
        examples_text.setPlainText("""Common Yosys synthesis commands:
• synth -top {top} -flatten : Main synthesis command
• abc -fast : Fast technology mapping
• abc -lut 4 : Map to 4-input LUTs
• opt -full : Full optimization
• opt_clean : Remove unused cells
• clean : Clean up design""")
        examples_layout.addWidget(examples_text)
        
        layout.addWidget(examples_group)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        load_btn = QPushButton("Load Existing")
        load_btn.clicked.connect(self.load_existing_strategy)
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        
        save_btn = QPushButton("Save Strategy")
        save_btn.clicked.connect(self.save_strategy)
        save_btn.setDefault(True)
        
        button_layout.addWidget(load_btn)
        button_layout.addStretch()
        button_layout.addWidget(cancel_btn)
        button_layout.addWidget(save_btn)
        
        layout.addLayout(button_layout)
        
        # Connect Enter key
        self.new_command_input.returnPressed.connect(self.add_command)
        self.new_option_input.returnPressed.connect(self.add_option)
    
    def add_command(self):
        """Add a new command to the list."""
        command = self.new_command_input.text().strip()
        if command:
            self.commands_list.addItem(command)
            self.new_command_input.clear()
    
    def remove_command(self):
        """Remove the selected command from the list."""
        current_row = self.commands_list.currentRow()
        if current_row >= 0:
            self.commands_list.takeItem(current_row)
    
    def add_option(self):
        """Add a new option to the list."""
        option = self.new_option_input.text().strip()
        if option:
            # Validate option format (should start with -)
            if not option.startswith('-'):
                self.show_warning("Invalid Option", "Command-line options should start with '-' (e.g., -v, -T)")
                return
            
            # Check for duplicates
            existing_options = [self.options_list.item(i).text() for i in range(self.options_list.count())]
            if option in existing_options:
                self.show_warning("Duplicate Option", f"Option '{option}' is already in the list.")
                return
            
            self.options_list.addItem(option)
            self.new_option_input.clear()
    
    def remove_option(self):
        """Remove the selected option from the list."""
        current_row = self.options_list.currentRow()
        if current_row >= 0:
            self.options_list.takeItem(current_row)
    
    def load_existing_strategy(self):
        """Load an existing custom strategy for editing."""
        # This would show a dialog to select from existing custom strategies
        self.show_info("Load Strategy", "Loading existing strategies functionality - to be implemented")
    
    def save_strategy(self):
        """Save the custom strategy to synthesis_options.yml."""
        strategy_name = self.strategy_name_input.text().strip()
        if not strategy_name:
            self.show_warning("Missing Information", "Please enter a strategy name.")
            return
        
        # Validate strategy name (no spaces, alphanumeric + underscore)
        import re
        if not re.match(r'^[a-zA-Z0-9_]+$', strategy_name):
            self.show_warning("Invalid Name", "Strategy name should only contain letters, numbers, and underscores.")
            return
        
        description = self.strategy_description_input.text().strip()
        if not description:
            self.show_warning("Missing Information", "Please enter a description.")
            return
        
        recommended_for = self.recommended_for_input.text().strip()
        if not recommended_for:
            self.show_warning("Missing Information", "Please enter recommended use case.")
            return
        
        # Get commands
        commands = [self.commands_list.item(i).text() for i in range(self.commands_list.count())]
        if not commands:
            self.show_warning("Missing Commands", "Please add at least one Yosys command.")
            return
        
        # Get options
        options = [self.options_list.item(i).text() for i in range(self.options_list.count())]
        
        # Create strategy data
        strategy_data = {
            'description': description,
            'recommended_for': recommended_for,
            'yosys_commands': commands,
            'custom': True  # Mark as custom strategy
        }
        
        if options:
            strategy_data['command_line_options'] = options
        
        self.strategy_name = strategy_name
        self.strategy_data = strategy_data
        
        self.accept()
    
    def show_warning(self, title, message):
        """Show a warning message."""
        from PyQt5.QtWidgets import QMessageBox
        QMessageBox.warning(self, title, message)
    
    def show_info(self, title, message):
        """Show an info message."""
        from PyQt5.QtWidgets import QMessageBox
        QMessageBox.information(self, title, message)
    
    def get_strategy_data(self):
        """Get the strategy data."""
        return getattr(self, 'strategy_name', None), getattr(self, 'strategy_data', None)


class MainWindow(QMainWindow):
    """Main application window."""
    
    def __init__(self):
        super().__init__()
        self.init_ui()
        self.setup_logging()
        self.current_project_path = None
        self.worker_thread = None
        # Initialize constraint file mapping for tracking which constraint file was used for each design
        self.design_constraint_mapping = {}
        # Initialize selected board (default to Olimex GateMate EVB)
        self.selected_board = {
            'name': 'Olimex GateMate EVB',
            'identifier': 'olimex_gatemateevb'
        }
        
        # Load and open the most recently used project
        self.load_recent_project_on_startup()
        
    def get_settings_file_path(self):
        """Get the path to the application settings file."""
        # Store settings in the user's home directory
        home_dir = os.path.expanduser("~")
        settings_dir = os.path.join(home_dir, ".cc_project_manager")
        os.makedirs(settings_dir, exist_ok=True)
        return os.path.join(settings_dir, "settings.json")
    
    def save_recent_project_path(self, project_path):
        """Save the most recently opened project path to settings."""
        try:
            import json
            settings_file = self.get_settings_file_path()
            
            # Load existing settings or create new ones
            settings = {}
            if os.path.exists(settings_file):
                try:
                    with open(settings_file, 'r') as f:
                        settings = json.load(f)
                except:
                    settings = {}
            
            # Update the recent project path
            settings['recent_project_path'] = os.path.abspath(project_path)
            settings['last_updated'] = time.time()
            
            # Save settings
            with open(settings_file, 'w') as f:
                json.dump(settings, f, indent=2)
                
            logging.info(f"💾 Saved recent project path: {project_path}")
            
        except Exception as e:
            logging.warning(f"Failed to save recent project path: {e}")
    
    def load_recent_project_path(self):
        """Load the most recently opened project path from settings."""
        try:
            import json
            settings_file = self.get_settings_file_path()
            
            if not os.path.exists(settings_file):
                return None
                
            with open(settings_file, 'r') as f:
                settings = json.load(f)
            
            recent_path = settings.get('recent_project_path')
            if recent_path and os.path.exists(recent_path):
                logging.info(f"📂 Found recent project path: {recent_path}")
                return recent_path
            else:
                if recent_path:
                    logging.warning(f"Recent project path no longer exists: {recent_path}")
                return None
                
        except Exception as e:
            logging.warning(f"Failed to load recent project path: {e}")
            return None
    
    def load_recent_project_on_startup(self):
        """Load the most recent project on application startup."""
        try:
            recent_path = self.load_recent_project_path()
            
            if recent_path:
                # Check if it's a valid project
                project_config_path, project_dir = self.find_project_config(recent_path)
                
                if project_config_path:
                    logging.info(f"🔄 Auto-loading recent project: {os.path.basename(recent_path)}")
                    os.chdir(recent_path)
                    self.current_project_path = recent_path
                    logging.info(f"✅ Successfully loaded recent project from: {recent_path}")
                    return True
                else:
                    logging.warning(f"Recent project path is not a valid project: {recent_path}")
            else:
                logging.info("No recent project found, starting in current directory")
                
        except Exception as e:
            logging.error(f"Error loading recent project on startup: {e}")
            
        return False
    
    def clear_recent_project(self):
        """Clear the recent project setting."""
        try:
            import json
            settings_file = self.get_settings_file_path()
            
            if os.path.exists(settings_file):
                with open(settings_file, 'r') as f:
                    settings = json.load(f)
                
                if 'recent_project_path' in settings:
                    del settings['recent_project_path']
                    settings['last_updated'] = time.time()
                    
                    with open(settings_file, 'w') as f:
                        json.dump(settings, f, indent=2)
                    
                    logging.info("Recent project setting cleared")
                    self.show_message("Recent Project Cleared", 
                                    "Recent project setting has been cleared.\n\n"
                                    "The application will no longer automatically load a project on startup.", 
                                    "info")
                else:
                    self.show_message("No Recent Project", 
                                    "No recent project setting found to clear.", 
                                    "info")
            else:
                self.show_message("No Settings File", 
                                "No settings file found. Nothing to clear.", 
                                "info")
                
        except Exception as e:
            logging.error(f"Failed to clear recent project: {e}")
            self.show_message("Error", 
                            f"Failed to clear recent project setting:\n{e}", 
                            "error")
        
    def init_ui(self):
        """Initialize the user interface."""
        self.setWindowTitle("GateMate Project Manager by JOCRIX v0.1 - Dark Mode")
        self.setGeometry(100, 100, 1200, 800)
        
        # Set application icon (if available)
        # self.setWindowIcon(QIcon('icon.png'))
        
        # Create central widget and main layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # Create main splitter (horizontal)
        main_splitter = QSplitter(Qt.Vertical)
        central_widget.setLayout(QVBoxLayout())
        central_widget.layout().addWidget(main_splitter)
        
        # Create the main content area
        content_widget = self.create_content_area()
        main_splitter.addWidget(content_widget)
        
        # Create output window
        self.output_widget = self.create_output_area()
        main_splitter.addWidget(self.output_widget)
        
        # Set splitter proportions (70% content, 30% output)
        main_splitter.setStretchFactor(0, 7)
        main_splitter.setStretchFactor(1, 3)
        
        # Create menu bar
        self.create_menu_bar()
        
        # Create status bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready")
        
        # Apply stylesheet for better appearance
        self.apply_stylesheet()
        
        # Perform initial status checks after UI is fully initialized
        QTimer.singleShot(100, self.refresh_toolchain_status)
        QTimer.singleShot(200, self.refresh_project_status)
        QTimer.singleShot(300, self.refresh_synthesis_status)
        QTimer.singleShot(400, self.refresh_implementation_status)
        QTimer.singleShot(500, self.refresh_simulation_status)
    
    def create_content_area(self):
        """Create the main content area with tabs for different sections."""
        self.tab_widget = QTabWidget()
        
        # Project Management Tab
        project_tab = self.create_project_tab()
        self.tab_widget.addTab(project_tab, "Project Management")
        
        # Synthesis Tab
        synthesis_tab = self.create_synthesis_tab()
        self.tab_widget.addTab(synthesis_tab, "Synthesis")
        
        # Implementation Tab
        implementation_tab = self.create_implementation_tab()
        self.tab_widget.addTab(implementation_tab, "Implementation")
        
        # Simulation Tab
        simulation_tab = self.create_simulation_tab()
        self.tab_widget.addTab(simulation_tab, "Simulation")
        
        # Upload Tab
        upload_tab = self.create_upload_tab()
        self.tab_widget.addTab(upload_tab, "Upload")
        
        # Configuration Tab
        config_tab = self.create_config_tab()
        self.tab_widget.addTab(config_tab, "Configuration")
        
        # Connect tab change signal for automatic refresh
        self.tab_widget.currentChanged.connect(self.on_tab_changed)
        
        return self.tab_widget
    
    def create_project_tab(self):
        """Create the project management tab."""
        widget = QWidget()
        main_layout = QHBoxLayout(widget)
        
        # Left side - Project Operations
        project_group = QGroupBox("Project Operations")
        project_group.setMaximumWidth(400)  # Limit container width
        project_layout = QVBoxLayout(project_group)
        
        # Project buttons
        buttons = [
            ("Create New Project", self.create_new_project, "Create a new FPGA project with directory structure"),
            ("Load Existing Project", self.load_existing_project, "Load and open an existing project from directory"),
            ("Add VHDL Files", self.add_vhdl_file, "Add VHDL source files to the current project (supports multiple selection)"),
            ("Remove VHDL File", self.remove_vhdl_file, "Remove VHDL file from the project"),
            ("Detect Manual Files", self.detect_manual_files, "Scan for VHDL files added manually to the project"),
            ("View Project Logs", self.view_project_logs, "View project manager log files and operations history")
        ]
        
        for text, callback, tooltip in buttons:
            btn = QPushButton(text)
            btn.clicked.connect(callback)
            btn.setToolTip(tooltip)
            btn.setMinimumHeight(40)
            btn.setMaximumWidth(380)  # Limit button width
            project_layout.addWidget(btn)
        
        # Add stretch to keep buttons at top with consistent spacing
        project_layout.addStretch()
        
        # Right side - Project Status Panel
        self.project_status_widget = self.create_project_status_widget()
        
        # Layout
        main_layout.addWidget(project_group)
        main_layout.addWidget(self.project_status_widget, 1)  # Give status panel more space
        
        return widget
    
    def create_synthesis_tab(self):
        """Create the synthesis tab."""
        widget = QWidget()
        main_layout = QHBoxLayout(widget)
        
        # Left side - Synthesis Operations
        synthesis_group = QGroupBox("Synthesis Operations")
        synthesis_group.setMaximumWidth(400)  # Limit container width
        synthesis_layout = QVBoxLayout(synthesis_group)
        
        buttons = [
            ("Run Synthesis", self.run_synthesis, "Synthesize VHDL design to netlist"),
            ("Configure Synthesis", self.configure_synthesis, "Configure synthesis settings and options"),
            ("Custom Strategy", self.configure_custom_strategy, "Create and manage custom synthesis strategies"),
            ("View Synthesis Logs", self.view_synthesis_logs, "View synthesis log files and reports")
        ]
        
        for text, callback, tooltip in buttons:
            btn = QPushButton(text)
            btn.clicked.connect(callback)
            btn.setToolTip(tooltip)
            btn.setMinimumHeight(40)
            btn.setMaximumWidth(380)  # Limit button width
            synthesis_layout.addWidget(btn)
        
        # Add stretch to keep buttons at top with consistent spacing
        synthesis_layout.addStretch()
        
        # Right side - Synthesis Status Panel
        self.synthesis_status_widget = self.create_synthesis_status_widget()
        
        # Layout
        main_layout.addWidget(synthesis_group)
        main_layout.addWidget(self.synthesis_status_widget, 1)  # Give status panel more space
        
        return widget
    
    def create_implementation_tab(self):
        """Create the implementation tab."""
        widget = QWidget()
        main_layout = QHBoxLayout(widget)
        
        # Left side - Implementation Operations
        impl_group = QGroupBox("Implementation Operations")
        impl_group.setMaximumWidth(400)  # Limit container width
        impl_layout = QVBoxLayout(impl_group)
        

        
        buttons = [
            ("Place && Route", self.run_place_and_route, "Run place and route on synthesized design (automatically generates bitstream)"),
            ("Add Constraints File", self.add_constraints_file, "Add .ccf constraints file to the project (supports multiple selection)"),
            ("Remove Constraints File", self.remove_constraints_file, "Remove selected constraints file from the project (does not delete the source file)"),
            ("Generate Post-Impl Netlist", self.generate_post_impl_netlist, "Generate post-implementation netlist for simulation"),
            ("View Implementation Logs", self.view_implementation_logs, "View raw implementation log files and reports")
        ]
        
        for text, callback, tooltip in buttons:
            btn = QPushButton(text)
            btn.clicked.connect(callback)
            btn.setToolTip(tooltip)
            btn.setMinimumHeight(40)
            btn.setMaximumWidth(380)  # Limit button width
            impl_layout.addWidget(btn)
        
        # Add separator
        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setFrameShadow(QFrame.Sunken)
        impl_layout.addWidget(separator)
        
        # Analysis section header
        analysis_label = QLabel("📊 Analysis Reports")
        analysis_label.setFont(QFont("Arial", 10, QFont.Bold))
        analysis_label.setStyleSheet("color: #4CAF50; margin: 10px 0px 5px 0px;")
        impl_layout.addWidget(analysis_label)
        
        # Analysis note
        analysis_note = QLabel("Click on an implemented design in the Design/File container to select it for analysis:")
        analysis_note.setFont(QFont("Arial", 9))
        analysis_note.setStyleSheet("color: #888888; margin: 10px 0px 10px 0px; font-style: italic;")
        analysis_note.setWordWrap(True)
        impl_layout.addWidget(analysis_note)
        
        # Status label for selected design
        self.selected_design_status = QLabel("No design selected")
        self.selected_design_status.setStyleSheet("color: #888888; font-size: 11px; margin: 5px 0px 10px 0px;")
        impl_layout.addWidget(self.selected_design_status)
        
        analysis_buttons = [
            ("⏱️ View Timing Report", self.view_timing_report, "View detailed timing analysis report"),
            ("📊 View Utilization Report", self.view_utilization_report, "View resource utilization report"),
            ("📍 View Placement Report", self.view_placement_report, "View placement and routing details"),
            ("⚡ View Power Analysis", self.view_power_analysis, "View power consumption analysis")
        ]
        
        for text, callback, tooltip in analysis_buttons:
            btn = QPushButton(text)
            btn.clicked.connect(callback)
            btn.setToolTip(tooltip)
            btn.setMinimumHeight(35)
            btn.setMaximumWidth(380)
            btn.setStyleSheet("QPushButton { background-color: #2E3440; color: #D8DEE9; border: 1px solid #4C566A; }")
            impl_layout.addWidget(btn)
        
        # Add stretch to keep buttons at top with consistent spacing
        impl_layout.addStretch()
        
        # Right side - Implementation Status Panel
        self.implementation_status_widget = self.create_implementation_status_widget()
        
        # Layout
        main_layout.addWidget(impl_group)
        main_layout.addWidget(self.implementation_status_widget, 1)  # Give status panel more space
        
        # Initialize design selection
        self.selected_design = None
        self.selected_tree_item = None
        
        # Initialize highlighting state
        self._clear_item_highlighting()
        
        return widget
    
    def create_simulation_tab(self):
        """Create the simulation tab."""
        widget = QWidget()
        main_layout = QHBoxLayout(widget)
        
        # Left side - Simulation Operations
        sim_group = QGroupBox("Simulation Operations")
        sim_group.setMaximumWidth(400)  # Limit container width
        sim_layout = QVBoxLayout(sim_group)
        
        buttons = [
            ("Behavioral Simulation", self.behavioral_simulation, "Run behavioral simulation with configuration options"),
            ("Post-Synthesis Simulation", self.post_synthesis_simulation, "Run post-synthesis simulation with configuration options"),
            ("Configure Simulation", self.configure_simulation, "Configure simulation settings and VHDL/IEEE standards"),
            ("Launch Waveform Viewer", self.launch_waveform_viewer, "Open GTKWave for waveform analysis"),
            ("View Simulation Logs", self.view_simulation_logs, "View simulation log files and reports")
        ]
        
        for text, callback, tooltip in buttons:
            btn = QPushButton(text)
            btn.clicked.connect(callback)
            btn.setToolTip(tooltip)
            btn.setMinimumHeight(40)
            btn.setMaximumWidth(380)  # Limit button width
            sim_layout.addWidget(btn)
        
        # Add stretch to keep buttons at top with consistent spacing
        sim_layout.addStretch()
        
        # Right side - Simulation Status Panel
        self.simulation_status_widget = self.create_simulation_status_widget()
        
        # Layout
        main_layout.addWidget(sim_group)
        main_layout.addWidget(self.simulation_status_widget, 1)  # Give status panel more space
        
        return widget
    
    def create_upload_tab(self):
        """Create the upload tab for FPGA programming."""
        widget = QWidget()
        main_layout = QHBoxLayout(widget)
        
        # Left side - Upload Operations
        upload_group = QGroupBox("Upload Operations")
        upload_group.setMaximumWidth(400)  # Limit container width
        upload_layout = QVBoxLayout(upload_group)
        
        # Upload operations section
        operations_label = QLabel("📤 Upload Operations")
        operations_label.setFont(QFont("Arial", 10, QFont.Bold))
        operations_label.setStyleSheet("color: #4CAF50; margin: 10px 0px 5px 0px;")
        upload_layout.addWidget(operations_label)
        
        buttons = [
            ("FPGA Board Selection", self.open_board_selection_dialog, "Select and configure FPGA board for programming"),
            ("Program SRAM", self.program_sram, "Program bitstream to FPGA SRAM (volatile)"),
            ("Program Flash", self.program_flash, "Program bitstream to FPGA Flash (non-volatile)"),
            ("Detect Devices", self.detect_fpga_devices, "Detect connected FPGA devices and cables"),
            ("Verify Bitstream", self.verify_bitstream, "Verify programmed bitstream against file"),
            ("View Upload Logs", self.view_upload_logs, "View openFPGALoader log files and programming history")
        ]
        
        for text, callback, tooltip in buttons:
            btn = QPushButton(text)
            btn.clicked.connect(callback)
            btn.setToolTip(tooltip)
            btn.setMinimumHeight(40)
            btn.setMaximumWidth(380)  # Limit button width
            upload_layout.addWidget(btn)
        
        # Add stretch to keep buttons at top with consistent spacing
        upload_layout.addStretch()
        
        # Right side - Upload Status Panel
        self.upload_status_widget = self.create_upload_status_widget()
        
        # Layout
        main_layout.addWidget(upload_group)
        main_layout.addWidget(self.upload_status_widget, 1)  # Give status panel more space
        
        return widget
    
    def create_config_tab(self):
        """Create the configuration tab."""
        widget = QWidget()
        main_layout = QHBoxLayout(widget)
        
        # Left side - Toolchain buttons
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        
        # Initialize the dropdown dictionary
        self.tool_preference_dropdowns = {}
        
        # Toolchain group
        toolchain_group = QGroupBox("Toolchain Configuration")
        toolchain_group.setMaximumWidth(400)  # Limit container width
        toolchain_layout = QVBoxLayout(toolchain_group)
        
        buttons = [
            ("Check Toolchain", self.check_toolchain_availability, "Check availability of required tools"),
            ("Edit Toolchain Paths", self.edit_toolchain_paths, "Configure paths to synthesis tools"),
            ("Configure GTKWave", self.configure_gtkwave, "Configure GTKWave path for simulation")
        ]
        
        for text, callback, tooltip in buttons:
            btn = QPushButton(text)
            btn.clicked.connect(callback)
            btn.setToolTip(tooltip)
            btn.setMinimumHeight(40)
            btn.setMaximumWidth(380)  # Limit button width
            toolchain_layout.addWidget(btn)
        
        left_layout.addWidget(toolchain_group)
        left_layout.addStretch()
        
        # Right side - Status panel
        self.status_widget = self.create_toolchain_status_widget()
        
        # Add both sides to main layout
        main_layout.addWidget(left_widget)
        main_layout.addWidget(self.status_widget)
        main_layout.setStretch(0, 0)  # Don't stretch left side
        main_layout.setStretch(1, 1)  # Allow right side to expand
        
        return widget
    
    def create_toolchain_status_widget(self):
        """Create the toolchain status display widget."""
        status_group = QGroupBox("Toolchain Status")
        status_layout = QVBoxLayout(status_group)
        

        
        # Individual tools section
        tools_frame = QFrame()
        tools_frame.setFrameStyle(QFrame.StyledPanel)
        tools_layout = QVBoxLayout(tools_frame)
        
        tools_title = QLabel("Individual Tool Status:")
        tools_title.setFont(QFont("Arial", 10, QFont.Bold))
        tools_layout.addWidget(tools_title)
        
        # Create status labels and preference dropdowns for each tool
        self.tool_status_labels = {}
        tools = ["GHDL", "Yosys", "P&R", "openFPGALoader", "GTKWave"]
        
        for tool in tools:
            tool_frame = QFrame()
            tool_frame.setFrameStyle(QFrame.Box)
            tool_layout = QVBoxLayout(tool_frame)
            
            # Tool title and preference in header
            tool_header_layout = QHBoxLayout()
            tool_title = QLabel(f"{tool}:")
            tool_title.setFont(QFont("Arial", 9, QFont.Bold))
            tool_header_layout.addWidget(tool_title)
            
            # Add preference dropdown for all tools
            if True:  # Include all tools now
                tool_header_layout.addStretch()
                
                pref_label = QLabel("Preference:")
                pref_label.setFont(QFont("Arial", 8))
                tool_header_layout.addWidget(pref_label)
                
                pref_dropdown = QComboBox()
                pref_dropdown.addItems(["PATH", "DIRECT"])
                pref_dropdown.setMaximumWidth(80)
                pref_dropdown.setFont(QFont("Arial", 8))
                # Dark theme styling for dropdown
                pref_dropdown.setStyleSheet("""
                    QComboBox {
                        border: 1px solid #555;
                        border-radius: 3px;
                        padding: 1px 4px 1px 3px;
                        background-color: #3a3a3a;
                        color: #ffffff;
                        selection-background-color: #4a4a4a;
                    }
                    QComboBox::drop-down {
                        width: 15px;
                        border: none;
                    }
                    QComboBox::down-arrow {
                        width: 10px;
                        height: 10px;
                    }
                    QComboBox:hover {
                        background-color: #4a4a4a;
                    }
                """)
                pref_dropdown.currentTextChanged.connect(
                    lambda value, t=tool: self.on_tool_preference_changed(t, value)
                )
                tool_header_layout.addWidget(pref_dropdown)
                
                self.tool_preference_dropdowns[tool] = pref_dropdown
            
            tool_layout.addLayout(tool_header_layout)
            
            path_label = QLabel("PATH: Checking...")
            direct_label = QLabel("DIRECT: Checking...")
            status_label = QLabel("STATUS: Checking...")
            
            tool_layout.addWidget(path_label)
            tool_layout.addWidget(direct_label)
            tool_layout.addWidget(status_label)
            
            self.tool_status_labels[tool] = {
                'path': path_label,
                'direct': direct_label,
                'status': status_label
            }
            
            tools_layout.addWidget(tool_frame)
        
        status_layout.addWidget(tools_frame)
        
        # Advanced checks section
        advanced_frame = QFrame()
        advanced_frame.setFrameStyle(QFrame.StyledPanel)
        advanced_layout = QVBoxLayout(advanced_frame)
        
        advanced_title = QLabel("Advanced Checks:")
        advanced_title.setFont(QFont("Arial", 10, QFont.Bold))
        advanced_layout.addWidget(advanced_title)
        
        self.ghdl_yosys_label = QLabel("GHDL-Yosys Plugin: Checking...")
        advanced_layout.addWidget(self.ghdl_yosys_label)
        
        status_layout.addWidget(advanced_frame)
        

        
        status_layout.addStretch()
        
        # Set up auto-refresh timer (disabled to prevent continuous background checking)
        self.status_timer = QTimer()
        self.status_timer.timeout.connect(self.refresh_toolchain_status)
        # self.status_timer.start(60000)  # Auto-refresh disabled - use manual refresh button instead
        
        return status_group
    
    def on_tool_preference_changed(self, tool_name, preference):
        """Handle tool preference dropdown changes."""
        try:
            from cc_project_manager_pkg.toolchain_manager import ToolChainManager
            tcm = ToolChainManager()
            
            # Map display names to internal tool names
            tool_map = {"GHDL": "ghdl", "Yosys": "yosys", "P&R": "p_r", "openFPGALoader": "openfpgaloader", "GTKWave": "gtkwave"}
            internal_tool_name = tool_map.get(tool_name)
            
            if internal_tool_name:
                success = tcm.set_tool_preference(internal_tool_name, preference)
                if success:
                    logging.info(f"Changed {tool_name} preference to {preference}")
                    # Refresh status to show updated configuration
                    self.refresh_toolchain_status()
                else:
                    logging.error(f"Failed to change {tool_name} preference to {preference}")
            else:
                logging.error(f"Unknown tool: {tool_name}")
                
        except Exception as e:
            logging.error(f"Error changing tool preference: {e}")
    
    def refresh_toolchain_status(self):
        """Refresh the toolchain status display."""
        # Check if status widgets exist (Configuration tab might not be created yet)
        if not hasattr(self, 'tool_status_labels'):
            return
            
        def update_status():
            try:
                from cc_project_manager_pkg.toolchain_manager import ToolChainManager
                tcm = ToolChainManager()
                
                # Initialize individual preferences if they don't exist
                tcm.initialize_individual_tool_preferences()
                
                # Update dropdown values with smart defaults and current preferences
                if hasattr(self, 'tool_preference_dropdowns'):
                    tool_map = {"GHDL": "ghdl", "Yosys": "yosys", "P&R": "p_r", "openFPGALoader": "openfpgaloader", "GTKWave": "gtkwave"}
                    for tool_name, dropdown in self.tool_preference_dropdowns.items():
                        internal_name = tool_map.get(tool_name)
                        if internal_name and tool_name != "GTKWave":  # Handle GTKWave separately below
                            # Check availability to set smart defaults
                            path_available = tcm.check_tool_version_path(internal_name)
                            direct_available = tcm.check_tool_version_direct(internal_name)
                            
                            # Always set smart default based on availability
                            # Prefer PATH if available, then DIRECT, then fallback to PATH
                            if path_available:
                                smart_default = "PATH"
                            elif direct_available:
                                smart_default = "DIRECT"
                            else:
                                smart_default = "PATH"  # Fallback
                            
                            # Get current preference
                            current_pref = tcm.get_tool_preference(internal_name)
                            
                            # Only update configuration if the smart default is different from current preference
                            if current_pref != smart_default:
                                tcm.set_tool_preference(internal_name, smart_default)
                                logging.info(f"Updated {tool_name} preference from {current_pref} to {smart_default} based on availability")
                                current_pref = smart_default
                            
                            # Update dropdown to reflect current preference
                            dropdown.blockSignals(True)
                            dropdown.setCurrentText(current_pref)
                            dropdown.blockSignals(False)
                
                # Handle GTKWave separately (uses different config system)
                if "GTKWave" in self.tool_preference_dropdowns:
                    try:
                        from cc_project_manager_pkg.simulation_manager import SimulationManager
                        sim_manager = SimulationManager()
                        
                        # Check availability
                        path_available = sim_manager.check_gtkwave_path()
                        direct_available = sim_manager.check_gtkwave_direct()
                        
                        # Always set smart default for GTKWave based on availability
                        if path_available:
                            smart_default = "PATH"
                        elif direct_available:
                            smart_default = "DIRECT"
                        else:
                            smart_default = "PATH"  # Fallback
                        
                        # Get current GTKWave preference
                        gtkwave_pref = tcm.get_tool_preference("gtkwave")
                        
                        # Only update configuration if the smart default is different from current preference
                        if gtkwave_pref != smart_default:
                            tcm.set_tool_preference("gtkwave", smart_default)
                            logging.info(f"Updated GTKWave preference from {gtkwave_pref} to {smart_default} based on availability")
                            gtkwave_pref = smart_default
                        
                        # Update GTKWave dropdown
                        gtkwave_dropdown = self.tool_preference_dropdowns["GTKWave"]
                        gtkwave_dropdown.blockSignals(True)
                        gtkwave_dropdown.setCurrentText(gtkwave_pref)
                        gtkwave_dropdown.blockSignals(False)
                        
                    except Exception as e:
                        logging.warning(f"Error handling GTKWave preferences: {e}")
                
                # Get legacy preference for display (backward compatibility)
                legacy_preference = tcm.config.get("cologne_chip_gatemate_toolchain_preference", "MIXED")
                
                # Check individual tools status
                tools_map = {"GHDL": "ghdl", "Yosys": "yosys", "P&R": "p_r", "openFPGALoader": "openfpgaloader"}
                
                for tool_name, tool_key in tools_map.items():
                    labels = self.tool_status_labels[tool_name]
                    
                    # Check PATH availability
                    path_available = tcm.check_tool_version_path(tool_key)
                    if path_available:
                        labels['path'].setText("PATH: ✅ Available")
                        labels['path'].setStyleSheet("color: #4CAF50;")
                    else:
                        labels['path'].setText("PATH: ❌ Not available")
                        labels['path'].setStyleSheet("color: #F44336;")
                    
                    # Check direct path availability
                    direct_available = tcm.check_tool_version_direct(tool_key)
                    direct_path = tcm.config.get("cologne_chip_gatemate_toolchain_paths", {}).get(tool_key, "")
                    if direct_available:
                        labels['direct'].setText("DIRECT: ✅ Available")
                        labels['direct'].setStyleSheet("color: #4CAF50;")
                        labels['direct'].setToolTip(direct_path)
                    elif direct_path:
                        labels['direct'].setText("DIRECT: ❌ Path not found")
                        labels['direct'].setStyleSheet("color: #F44336;")
                        labels['direct'].setToolTip(direct_path)
                    else:
                        labels['direct'].setText("DIRECT: ⚠️ Not configured")
                        labels['direct'].setStyleSheet("color: #FF9800;")
                        labels['direct'].setToolTip("")
                    
                    # Overall tool status based on current preference
                    current_pref = tcm.get_tool_preference(tool_key)
                    if current_pref == "PATH" and path_available:
                        labels['status'].setText("STATUS: ✅ READY (using PATH)")
                        labels['status'].setStyleSheet("color: #4CAF50;")
                    elif current_pref == "DIRECT" and direct_available:
                        labels['status'].setText("STATUS: ✅ READY (using DIRECT)")
                        labels['status'].setStyleSheet("color: #4CAF50;")
                    elif current_pref == "PATH" and not path_available and direct_available:
                        labels['status'].setText("STATUS: ⚠️ PATH not available, DIRECT ready")
                        labels['status'].setStyleSheet("color: #FF9800;")
                    elif current_pref == "DIRECT" and not direct_available and path_available:
                        labels['status'].setText("STATUS: ⚠️ DIRECT not configured, PATH available")
                        labels['status'].setStyleSheet("color: #FF9800;")
                    elif current_pref == "PATH" and not path_available:
                        labels['status'].setText("STATUS: ❌ PATH not available")
                        labels['status'].setStyleSheet("color: #F44336;")
                    elif current_pref == "DIRECT" and not direct_available:
                        labels['status'].setText("STATUS: ❌ DIRECT path not configured")
                        labels['status'].setStyleSheet("color: #F44336;")
                    else:
                        labels['status'].setText("STATUS: ❌ NOT AVAILABLE")
                        labels['status'].setStyleSheet("color: #F44336;")
                
                # Check GTKWave separately using SimulationManager
                try:
                    from cc_project_manager_pkg.simulation_manager import SimulationManager
                    sim_manager = SimulationManager()
                    gtkwave_labels = self.tool_status_labels["GTKWave"]
                    
                    # Check PATH availability
                    path_available = sim_manager.check_gtkwave_path()
                    if path_available:
                        gtkwave_labels['path'].setText("PATH: ✅ Available")
                        gtkwave_labels['path'].setStyleSheet("color: #4CAF50;")
                    else:
                        gtkwave_labels['path'].setText("PATH: ❌ Not available")
                        gtkwave_labels['path'].setStyleSheet("color: #F44336;")
                    
                    # Check direct path availability
                    direct_available = sim_manager.check_gtkwave_direct()
                    if direct_available:
                        direct_path = sim_manager.project_config.get("gtkwave_tool_path", {}).get("gtkwave", "")
                        gtkwave_labels['direct'].setText("DIRECT: ✅ Available")
                        gtkwave_labels['direct'].setStyleSheet("color: #4CAF50;")
                        gtkwave_labels['direct'].setToolTip(direct_path)
                    else:
                        gtkwave_labels['direct'].setText("DIRECT: ⚠️ Not configured")
                        gtkwave_labels['direct'].setStyleSheet("color: #FF9800;")
                        gtkwave_labels['direct'].setToolTip("")
                    
                    # Overall GTKWave status based on current preference
                    gtkwave_pref = tcm.get_tool_preference("gtkwave")
                    logging.debug(f"GTKWave preference: '{gtkwave_pref}', PATH available: {path_available}, DIRECT available: {direct_available}")
                    
                    if gtkwave_pref == "PATH" and path_available:
                        gtkwave_labels['status'].setText("STATUS: ✅ READY (using PATH)")
                        gtkwave_labels['status'].setStyleSheet("color: #4CAF50;")
                    elif gtkwave_pref == "DIRECT" and direct_available:
                        gtkwave_labels['status'].setText("STATUS: ✅ READY (using DIRECT)")
                        gtkwave_labels['status'].setStyleSheet("color: #4CAF50;")
                    elif gtkwave_pref == "PATH" and not path_available and direct_available:
                        gtkwave_labels['status'].setText("STATUS: ⚠️ PATH not available, DIRECT ready")
                        gtkwave_labels['status'].setStyleSheet("color: #FF9800;")
                    elif gtkwave_pref == "DIRECT" and not direct_available and path_available:
                        gtkwave_labels['status'].setText("STATUS: ⚠️ DIRECT not configured, PATH available")
                        gtkwave_labels['status'].setStyleSheet("color: #FF9800;")
                    elif gtkwave_pref == "PATH" and not path_available:
                        gtkwave_labels['status'].setText("STATUS: ❌ PATH not available")
                        gtkwave_labels['status'].setStyleSheet("color: #F44336;")
                    elif gtkwave_pref == "DIRECT" and not direct_available:
                        gtkwave_labels['status'].setText("STATUS: ❌ DIRECT path not configured")
                        gtkwave_labels['status'].setStyleSheet("color: #F44336;")
                    else:
                        gtkwave_labels['status'].setText("STATUS: ❌ NOT AVAILABLE")
                        gtkwave_labels['status'].setStyleSheet("color: #F44336;")
                        logging.debug(f"GTKWave fell through to NOT AVAILABLE case - pref: '{gtkwave_pref}', PATH: {path_available}, DIRECT: {direct_available}")
                        
                except Exception as e:
                    # Handle case where SimulationManager fails to initialize
                    gtkwave_labels = self.tool_status_labels["GTKWave"]
                    gtkwave_labels['path'].setText("PATH: ❌ Check failed")
                    gtkwave_labels['path'].setStyleSheet("color: #F44336;")
                    gtkwave_labels['direct'].setText("DIRECT: ❌ Check failed")
                    gtkwave_labels['direct'].setStyleSheet("color: #F44336;")
                    gtkwave_labels['status'].setText("STATUS: ❌ ERROR")
                    gtkwave_labels['status'].setStyleSheet("color: #F44336;")
                    logging.warning(f"Failed to check GTKWave status: {e}")
                
                # Check GHDL-Yosys plugin
                try:
                    ghdl_yosys_ok = tcm.check_ghdl_yosys_link()
                    if ghdl_yosys_ok:
                        self.ghdl_yosys_label.setText("GHDL-Yosys Plugin: ✅ Available")
                        self.ghdl_yosys_label.setStyleSheet("color: #4CAF50;")
                    else:
                        self.ghdl_yosys_label.setText("GHDL-Yosys Plugin: ⚠️ Not working properly")
                        self.ghdl_yosys_label.setStyleSheet("color: #FF9800;")
                except Exception:
                    self.ghdl_yosys_label.setText("GHDL-Yosys Plugin: ❌ Check failed")
                    self.ghdl_yosys_label.setStyleSheet("color: #F44336;")
                

                    
            except Exception as e:
                logging.error(f"Error updating toolchain status: {e}")
        
        # Run status update directly (no need for thread since it's just UI updates)
        try:
            update_status()
        except Exception as e:
            logging.error(f"Error updating toolchain status: {e}")
    
    def create_project_status_widget(self):
        """Create the project status display widget."""
        status_group = QGroupBox("Project Status")
        status_layout = QVBoxLayout(status_group)
        
        # Project info section
        info_frame = QFrame()
        info_frame.setFrameStyle(QFrame.StyledPanel)
        info_layout = QVBoxLayout(info_frame)
        
        self.project_name_label = QLabel("Project: Not loaded")
        self.project_name_label.setFont(QFont("Arial", 10, QFont.Bold))
        info_layout.addWidget(self.project_name_label)
        
        self.project_path_label = QLabel("Path: Unknown")
        info_layout.addWidget(self.project_path_label)
        
        # Set size policy for info frame to keep it compact at top
        info_frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        
        status_layout.addWidget(info_frame)
        
        # Files section
        files_frame = QFrame()
        files_frame.setFrameStyle(QFrame.StyledPanel)
        files_layout = QVBoxLayout(files_frame)
        
        files_title = QLabel("Project Files")
        files_title.setFont(QFont("Arial", 9, QFont.Bold))
        files_layout.addWidget(files_title)
        
        self.files_tree = QTreeWidget()
        self.files_tree.setHeaderLabels(["File", "Status"])
        
        # Configure tree widget for better display
        self.files_tree.setRootIsDecorated(False)  # Remove tree decorations
        self.files_tree.setAlternatingRowColors(False)  # Disable alternating colors
        self.files_tree.setUniformRowHeights(True)
        self.files_tree.setIndentation(15)  # Minimal indentation
        
        # Enable single selection for file removal functionality
        self.files_tree.setSelectionMode(QTreeWidget.SingleSelection)
        self.files_tree.setFocusPolicy(Qt.StrongFocus)
        
        # Remove any visual indicators that might cause white boxes
        self.files_tree.setItemsExpandable(False)
        self.files_tree.setExpandsOnDoubleClick(False)
        
        # Remove any default styling that might cause white bars
        self.files_tree.setStyleSheet("")  # Clear any inherited styles
        
        # Set size policy to anchor at top and allow controlled expansion
        self.files_tree.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.files_tree.setMinimumHeight(200)
        self.files_tree.setMaximumHeight(250)  # Slightly reduced max height
        
        # Configure column widths for proper file name display
        self.files_tree.setColumnWidth(0, 200)  # File name column - wider for full names
        self.files_tree.setColumnWidth(1, 60)   # Status column - narrow for icons
        
        # Enable column resizing
        header = self.files_tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.Interactive)  # File column resizable
        header.setSectionResizeMode(1, QHeaderView.Fixed)        # Status column fixed
        
        # Ensure header is visible but not taking extra space
        header.setVisible(True)
        header.setDefaultSectionSize(200)
        
        files_layout.addWidget(self.files_tree)
        
        # Set size policy for files frame to prevent it from expanding too much
        files_frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        
        status_layout.addWidget(files_frame)
        
        # Add stretch to push statistics and refresh button to bottom
        status_layout.addStretch()
        
        # Statistics section
        stats_frame = QFrame()
        stats_frame.setFrameStyle(QFrame.StyledPanel)
        stats_layout = QVBoxLayout(stats_frame)
        
        stats_title = QLabel("Statistics")
        stats_title.setFont(QFont("Arial", 9, QFont.Bold))
        stats_layout.addWidget(stats_title)
        
        self.stats_labels = {
            'total_files': QLabel("Total Files: 0"),
            'entities': QLabel("Entities: 0"),
            'testbenches': QLabel("Testbenches: 0"),
            'missing': QLabel("Missing: 0"),
            'implemented': QLabel("Implemented: 0"),
            'bitstreams': QLabel("Bitstreams: 0")
        }
        
        for label in self.stats_labels.values():
            stats_layout.addWidget(label)
        
        # Set size policy for stats frame to keep it compact
        stats_frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        
        status_layout.addWidget(stats_frame)
        
        # Refresh button
        refresh_btn = QPushButton("🔄 Refresh Status")
        refresh_btn.clicked.connect(self.refresh_project_status)
        refresh_btn.setMaximumWidth(200)
        refresh_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        status_layout.addWidget(refresh_btn)
        
        # Set up auto-refresh timer for project status (disabled to prevent continuous background checking)
        self.project_status_timer = QTimer()
        self.project_status_timer.timeout.connect(self.refresh_project_status)
        # self.project_status_timer.start(30000)  # Auto-refresh disabled - use manual refresh button instead
        
        return status_group
    
    def refresh_project_status(self):
        """Refresh the project status display."""
        try:
            logging.info("🔄 Refreshing project status...")
            from cc_project_manager_pkg.hierarchy_manager import HierarchyManager
            
            # Find project configuration using the same logic as add_vhdl_file
            project_config_path, project_dir = self.find_project_config()
            
            if not project_config_path:
                # No project found
                logging.warning("❌ No project configuration found")
                self.project_name_label.setText("Project: Error loading")
                self.project_name_label.setStyleSheet("color: #F44336;")
                self.project_path_label.setText("Path: Check project configuration")
                self.files_tree.clear()
                
                # Reset statistics
                self.stats_labels['total_files'].setText("Total Files: 0")
                self.stats_labels['entities'].setText("Entities: 0")
                self.stats_labels['testbenches'].setText("Testbenches: 0")
                self.stats_labels['missing'].setText("Missing: 0")
                self.stats_labels['implemented'].setText("Implemented: 0")
                self.stats_labels['bitstreams'].setText("Bitstreams: 0")
                logging.info("📊 Project status display reset to default values")
                return
            
            # Change to project directory temporarily to load hierarchy
            original_cwd = os.getcwd()
            logging.info(f"📁 Found project config at: {project_config_path}")
            logging.info(f"🔄 Temporarily changing to project directory: {project_dir}")
            os.chdir(project_dir)
            
            try:
                hierarchy = HierarchyManager()
                
                # Update project info
                if hierarchy.config:
                    project_name = hierarchy.config.get('project_name', 'Unknown')
                    project_path = hierarchy.config.get('project_path', 'Unknown')
                    logging.info(f"✅ Successfully loaded project: {project_name}")
                    logging.info(f"📍 Project path: {project_path}")
                    self.project_name_label.setText(f"Project: {project_name}")
                    self.project_name_label.setStyleSheet("color: #4CAF50;")
                    self.project_path_label.setText(f"Path: {project_path}")
                else:
                    logging.error("❌ Failed to load project configuration from HierarchyManager")
                    self.project_name_label.setText("Project: Error loading")
                    self.project_name_label.setStyleSheet("color: #F44336;")
                    self.project_path_label.setText("Path: Check project configuration")
                
                # Update files tree
                logging.info("🗂️ Updating project files tree...")
                self.files_tree.clear()
                files_info = hierarchy.get_source_files_info()
                
                # Add source files
                if files_info.get("src"):
                    src_count = len(files_info["src"])
                    logging.info(f"📄 Found {src_count} source files")
                    src_item = QTreeWidgetItem(["Source Files", ""])
                    src_item.setIcon(0, self.style().standardIcon(QStyle.SP_DirIcon))
                    # Ensure folder item has proper text color
                    src_item.setForeground(0, QColor("#ffffff"))
                    src_item.setForeground(1, QColor("#ffffff"))
                    for file_name, file_path in files_info["src"].items():
                        file_exists = os.path.exists(file_path)
                        status_icon = "✅" if file_exists else "❌"
                        status_text = "exists" if file_exists else "missing"
                        logging.info(f"  📄 {file_name} - {status_text}")
                        file_item = QTreeWidgetItem([file_name, status_icon])
                        file_item.setToolTip(0, file_path)
                        # Store file metadata for removal functionality
                        file_item.setData(0, Qt.UserRole, {"file_name": file_name, "category": "src", "file_path": file_path})
                        # Add file icon to remove white box
                        file_item.setIcon(0, self.style().standardIcon(QStyle.SP_FileIcon))
                        # Ensure file item has proper text color
                        file_item.setForeground(0, QColor("#ffffff"))
                        file_item.setForeground(1, QColor("#4CAF50" if file_exists else "#F44336"))
                        src_item.addChild(file_item)
                    self.files_tree.addTopLevelItem(src_item)
                    src_item.setExpanded(True)
                
                # Add testbench files
                if files_info.get("testbench"):
                    tb_count = len(files_info["testbench"])
                    logging.info(f"🧪 Found {tb_count} testbench files")
                    tb_item = QTreeWidgetItem(["Testbench Files", ""])
                    tb_item.setIcon(0, self.style().standardIcon(QStyle.SP_DirIcon))
                    # Ensure folder item has proper text color
                    tb_item.setForeground(0, QColor("#ffffff"))
                    tb_item.setForeground(1, QColor("#ffffff"))
                    for file_name, file_path in files_info["testbench"].items():
                        file_exists = os.path.exists(file_path)
                        status_icon = "✅" if file_exists else "❌"
                        status_text = "exists" if file_exists else "missing"
                        logging.info(f"  🧪 {file_name} - {status_text}")
                        file_item = QTreeWidgetItem([file_name, status_icon])
                        file_item.setToolTip(0, file_path)
                        # Store file metadata for removal functionality
                        file_item.setData(0, Qt.UserRole, {"file_name": file_name, "category": "testbench", "file_path": file_path})
                        # Add file icon to remove white box
                        file_item.setIcon(0, self.style().standardIcon(QStyle.SP_FileIcon))
                        # Ensure file item has proper text color
                        file_item.setForeground(0, QColor("#ffffff"))
                        file_item.setForeground(1, QColor("#4CAF50" if file_exists else "#F44336"))
                        tb_item.addChild(file_item)
                    self.files_tree.addTopLevelItem(tb_item)
                    tb_item.setExpanded(True)
                
                # Add top-level files
                if files_info.get("top"):
                    top_item = QTreeWidgetItem(["Top-Level Files", ""])
                    top_item.setIcon(0, self.style().standardIcon(QStyle.SP_DirIcon))
                    # Ensure folder item has proper text color
                    top_item.setForeground(0, QColor("#ffffff"))
                    top_item.setForeground(1, QColor("#ffffff"))
                    for file_name, file_path in files_info["top"].items():
                        file_item = QTreeWidgetItem([file_name, "✅" if os.path.exists(file_path) else "❌"])
                        file_item.setToolTip(0, file_path)
                        # Store file metadata for removal functionality
                        file_item.setData(0, Qt.UserRole, {"file_name": file_name, "category": "top", "file_path": file_path})
                        # Add file icon to remove white box
                        file_item.setIcon(0, self.style().standardIcon(QStyle.SP_FileIcon))
                        # Ensure file item has proper text color
                        file_item.setForeground(0, QColor("#ffffff"))
                        file_item.setForeground(1, QColor("#4CAF50" if os.path.exists(file_path) else "#F44336"))
                        top_item.addChild(file_item)
                    self.files_tree.addTopLevelItem(top_item)
                    top_item.setExpanded(True)
                
                # Add implementation outputs
                implementation_outputs = self._find_implementation_outputs()
                if implementation_outputs:
                    impl_count = len(implementation_outputs)
                    logging.info(f"🔧 Found {impl_count} implemented designs")
                    impl_item = QTreeWidgetItem(["Implementation Outputs", ""])
                    impl_item.setIcon(0, self.style().standardIcon(QStyle.SP_DirIcon))
                    impl_item.setForeground(0, QColor("#ffffff"))
                    impl_item.setForeground(1, QColor("#ffffff"))
                    
                    for design_name, outputs in implementation_outputs.items():
                        # Show implementation status
                        status_parts = []
                        if outputs.get('placed', False):
                            status_parts.append("P&R")
                        if outputs.get('timing_analyzed', False):
                            status_parts.append("Timing")
                        if outputs.get('bitstream_generated', False):
                            status_parts.append("Bitstream")
                        
                        status_icon = "✅" if status_parts else "⚪"
                        status_text = " + ".join(status_parts) if status_parts else "Pending"
                        
                        design_item = QTreeWidgetItem([design_name, status_icon])
                        design_item.setToolTip(0, f"Implementation Status: {status_text}")
                        design_item.setIcon(0, self.style().standardIcon(QStyle.SP_ComputerIcon))
                        design_item.setForeground(0, QColor("#ffffff"))
                        design_item.setForeground(1, QColor("#4CAF50" if status_parts else "#888888"))
                        
                        # Add individual output files as children
                        for file_path in outputs.get('files', []):
                            file_name = os.path.basename(file_path)
                            file_exists = os.path.exists(file_path)
                            file_status_icon = "✅" if file_exists else "❌"
                            
                            # Determine file type for better categorization
                            file_type = "Unknown"
                            if file_name.endswith('.bit'):
                                file_type = "Bitstream"
                            elif file_name.endswith('.cdf'):
                                file_type = "GateMate CDF"
                            elif file_name.endswith('.sdf'):
                                file_type = "Timing (SDF)"
                            elif file_name.endswith('.rpt'):
                                file_type = "Timing Report"
                            elif file_name.endswith('.ccf') or file_name.endswith('.cfg'):
                                file_type = "Implementation"
                            elif file_name.endswith('.v') or file_name.endswith('.vhd'):
                                file_type = "Post-Impl Netlist"
                            
                            file_item = QTreeWidgetItem([file_name, file_status_icon])
                            file_item.setToolTip(0, f"{file_type}: {file_path}")
                            file_item.setIcon(0, self.style().standardIcon(QStyle.SP_FileIcon))
                            file_item.setForeground(0, QColor("#ffffff"))
                            file_item.setForeground(1, QColor("#4CAF50" if file_exists else "#F44336"))
                            
                            design_item.addChild(file_item)
                        
                        impl_item.addChild(design_item)
                    
                    self.files_tree.addTopLevelItem(impl_item)
                    impl_item.setExpanded(True)
                
                # Ensure proper column sizing after adding files
                self.files_tree.resizeColumnToContents(0)  # Auto-resize file name column
                
                # But ensure minimum width for readability
                if self.files_tree.columnWidth(0) < 200:
                    self.files_tree.setColumnWidth(0, 200)
                
                # Update statistics
                stats = hierarchy.get_project_statistics()
                
                # Calculate implementation statistics
                impl_count = len(implementation_outputs) if implementation_outputs else 0
                bitstream_count = 0
                if implementation_outputs:
                    bitstream_count = sum(1 for outputs in implementation_outputs.values() 
                                        if outputs.get('bitstream_generated', False))
                
                logging.info("📊 Updating project statistics...")
                logging.info(f"  📁 Total Files: {stats['total_files']}")
                logging.info(f"  🏗️ Entities: {stats['available_entities']}")
                logging.info(f"  🧪 Testbenches: {stats['available_testbenches']}")
                logging.info(f"  ❌ Missing Files: {stats['missing_files']}")
                logging.info(f"  🔧 Implemented: {impl_count}")
                logging.info(f"  💾 Bitstreams: {bitstream_count}")
                
                self.stats_labels['total_files'].setText(f"Total Files: {stats['total_files']}")
                self.stats_labels['entities'].setText(f"Entities: {stats['available_entities']}")
                self.stats_labels['testbenches'].setText(f"Testbenches: {stats['available_testbenches']}")
                
                missing_count = stats['missing_files']
                self.stats_labels['missing'].setText(f"Missing: {missing_count}")
                if missing_count > 0:
                    self.stats_labels['missing'].setStyleSheet("color: #F44336;")
                    logging.warning(f"⚠️ {missing_count} files are missing!")
                else:
                    self.stats_labels['missing'].setStyleSheet("color: #4CAF50;")
                    logging.info("✅ All project files are present")
                
                # Update implementation statistics
                self.stats_labels['implemented'].setText(f"Implemented: {impl_count}")
                self.stats_labels['implemented'].setStyleSheet("color: #4CAF50;" if impl_count > 0 else "color: #888888;")
                
                self.stats_labels['bitstreams'].setText(f"Bitstreams: {bitstream_count}")
                self.stats_labels['bitstreams'].setStyleSheet("color: #4CAF50;" if bitstream_count > 0 else "color: #888888;")
                
                logging.info("✅ Project status refresh completed successfully")
                    
            finally:
                # Always restore the original working directory
                logging.info(f"🔄 Restoring working directory to: {original_cwd}")
                os.chdir(original_cwd)
                
        except Exception as e:
            import traceback
            error_details = traceback.format_exc()
            logging.error(f"Error refreshing project status: {e}")
            logging.error(f"Full traceback: {error_details}")
            self.project_name_label.setText("Project: Error loading")
            self.project_name_label.setStyleSheet("color: #F44336;")
            self.project_path_label.setText("Path: Check project configuration")
    
    def create_synthesis_status_widget(self):
        """Create the synthesis status widget showing entities and synthesis results."""
        status_group = QGroupBox("Synthesis Status")
        layout = QVBoxLayout(status_group)
        
        # Project info section
        info_frame = QFrame()
        info_layout = QVBoxLayout(info_frame)
        info_layout.setContentsMargins(10, 5, 10, 5)
        
        # Synthesis strategy info
        self.synth_config_label = QLabel("Synthesis Strategy: Not loaded")
        self.synth_config_label.setStyleSheet("font-weight: bold; color: #64b5f6;")
        info_layout.addWidget(self.synth_config_label)
        
        info_frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        layout.addWidget(info_frame)
        
        # Entities and synthesis results tree
        self.synthesis_tree = QTreeWidget()
        self.synthesis_tree.setHeaderLabels(["Entity / Design", "Type", "Synthesizable", "Status", "Strategy", "Synthesized"])
        
        # Configure tree widget for better display (same as project files tree)
        self.synthesis_tree.setRootIsDecorated(False)  # Remove tree decorations
        self.synthesis_tree.setAlternatingRowColors(False)  # Disable alternating colors
        self.synthesis_tree.setUniformRowHeights(True)
        self.synthesis_tree.setIndentation(15)  # Minimal indentation
        
        # Enable single selection
        self.synthesis_tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.synthesis_tree.setFocusPolicy(Qt.StrongFocus)
        
        # Remove any visual indicators that might cause white boxes
        self.synthesis_tree.setItemsExpandable(False)
        self.synthesis_tree.setExpandsOnDoubleClick(False)
        
        # Remove white boxes by clearing any inherited styles (same fix as project files tree)
        self.synthesis_tree.setStyleSheet("")  # Clear any inherited styles
        
        # Set column widths
        self.synthesis_tree.setColumnWidth(0, 200)  # Entity/Design
        self.synthesis_tree.setColumnWidth(1, 80)   # Type
        self.synthesis_tree.setColumnWidth(2, 100)  # Synthesizable
        self.synthesis_tree.setColumnWidth(3, 100)  # Status
        self.synthesis_tree.setColumnWidth(4, 100)  # Strategy
        
        layout.addWidget(self.synthesis_tree)
        
        # Statistics section
        stats_frame = QFrame()
        stats_layout = QGridLayout(stats_frame)
        stats_layout.setContentsMargins(10, 5, 10, 5)
        
        # Create statistics labels
        self.synth_stats_labels = {}
        stats_items = [
            ('available_entities', 'Available Entities:', 0, 0),
            ('synthesized_designs', 'Synthesized:', 0, 1),
            ('synthesis_errors', 'Errors:', 1, 0),
            ('last_synthesis', 'Last Synthesis:', 1, 1)
        ]
        
        for key, label_text, row, col in stats_items:
            label = QLabel(label_text)
            label.setStyleSheet("color: #888888; font-size: 11px;")
            value_label = QLabel("0")
            value_label.setStyleSheet("color: #ffffff; font-weight: bold; font-size: 11px;")
            
            stats_layout.addWidget(label, row * 2, col)
            stats_layout.addWidget(value_label, row * 2 + 1, col)
            self.synth_stats_labels[key] = value_label
        
        stats_frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        layout.addWidget(stats_frame)
        
        return status_group
    
    def create_simulation_status_widget(self):
        """Create the simulation status widget showing testbenches and simulation results."""
        status_group = QGroupBox("Simulation Status")
        layout = QVBoxLayout(status_group)
        
        # Simulation info section
        info_frame = QFrame()
        info_layout = QVBoxLayout(info_frame)
        info_layout.setContentsMargins(10, 5, 10, 5)
        
        # Simulation settings info
        self.sim_config_label = QLabel("Simulation Settings: Not loaded")
        self.sim_config_label.setStyleSheet("font-weight: bold; color: #64b5f6;")
        info_layout.addWidget(self.sim_config_label)
        
        # GTKWave status
        self.gtkwave_status_label = QLabel("GTKWave: Checking...")
        self.gtkwave_status_label.setStyleSheet("font-weight: bold; color: #FFA726;")
        info_layout.addWidget(self.gtkwave_status_label)
        
        # Selected testbench info
        self.selected_testbench_label = QLabel("Selected Testbench: None")
        self.selected_testbench_label.setStyleSheet("font-weight: bold; color: #4CAF50; margin-top: 5px;")
        info_layout.addWidget(self.selected_testbench_label)
        
        info_frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        layout.addWidget(info_frame)
        
        # Available Testbenches section
        testbench_label = QLabel("Available Testbenches:")
        testbench_label.setStyleSheet("font-weight: bold; margin-top: 10px;")
        layout.addWidget(testbench_label)
        
        self.testbench_tree = QTreeWidget()
        self.testbench_tree.setHeaderLabels(["Testbench", "File", "Entity", "Status"])
        self.testbench_tree.setAlternatingRowColors(True)
        self.testbench_tree.setRootIsDecorated(False)
        self.testbench_tree.setMaximumHeight(200)
        self.testbench_tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.testbench_tree.setFocusPolicy(Qt.StrongFocus)
        self.testbench_tree.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.testbench_tree.itemClicked.connect(self._on_testbench_tree_clicked)
        
        # Set column widths for testbench tree
        self.testbench_tree.setColumnWidth(0, 150)  # Testbench
        self.testbench_tree.setColumnWidth(1, 120)  # File
        self.testbench_tree.setColumnWidth(2, 100)  # Entity
        
        layout.addWidget(self.testbench_tree)
        
        # VCD Files section
        vcd_label = QLabel("VCD Files:")
        vcd_label.setStyleSheet("font-weight: bold; margin-top: 10px;")
        layout.addWidget(vcd_label)
        
        # Simulations tree
        self.simulation_tree = QTreeWidget()
        self.simulation_tree.setHeaderLabels(["Simulation / VCD File", "Type", "Size", "Modified", "Entity", "Duration", "Status"])
        
        # Configure tree widget for better display
        self.simulation_tree.setRootIsDecorated(False)
        self.simulation_tree.setAlternatingRowColors(False)
        self.simulation_tree.setUniformRowHeights(True)
        self.simulation_tree.setIndentation(15)
        
        # Enable single selection
        self.simulation_tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.simulation_tree.setFocusPolicy(Qt.StrongFocus)
        self.simulation_tree.setSelectionBehavior(QAbstractItemView.SelectRows)
        
        # Remove any visual indicators that might cause white boxes
        self.simulation_tree.setItemsExpandable(False)
        self.simulation_tree.setExpandsOnDoubleClick(False)
        self.simulation_tree.setStyleSheet("")
        
        # Set column widths
        self.simulation_tree.setColumnWidth(0, 200)  # Simulation/VCD File
        self.simulation_tree.setColumnWidth(1, 100)  # Type
        self.simulation_tree.setColumnWidth(2, 80)   # Size
        self.simulation_tree.setColumnWidth(3, 120)  # Modified
        self.simulation_tree.setColumnWidth(4, 100)  # Entity
        self.simulation_tree.setColumnWidth(5, 80)   # Duration
        
        # Connect single-click for highlighting and double-click to launch GTKWave
        self.simulation_tree.itemClicked.connect(self._on_simulation_tree_clicked)
        self.simulation_tree.itemDoubleClicked.connect(self._on_simulation_double_clicked)
        
        layout.addWidget(self.simulation_tree)
        
        # Statistics section
        stats_frame = QFrame()
        stats_layout = QGridLayout(stats_frame)
        stats_layout.setContentsMargins(10, 5, 10, 5)
        
        # Create statistics labels
        self.sim_stats_labels = {}
        stats_items = [
            ('behavioral_sims', 'Behavioral:', 0, 0),
            ('post_synth_sims', 'Post-Synthesis:', 0, 1),
            ('post_impl_sims', 'Post-Implementation:', 1, 0),
            ('total_vcd_files', 'Total VCD Files:', 1, 1)
        ]
        
        for key, label_text, row, col in stats_items:
            label = QLabel(label_text)
            label.setStyleSheet("color: #888888; font-size: 11px;")
            value_label = QLabel("0")
            value_label.setStyleSheet("color: #ffffff; font-weight: bold; font-size: 11px;")
            
            stats_layout.addWidget(label, row * 2, col)
            stats_layout.addWidget(value_label, row * 2 + 1, col)
            self.sim_stats_labels[key] = value_label
        
        stats_frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        layout.addWidget(stats_frame)
        
        # Refresh button
        refresh_btn = QPushButton("🔄 Refresh Status")
        refresh_btn.clicked.connect(self.refresh_simulation_status)
        refresh_btn.setMaximumWidth(200)
        layout.addWidget(refresh_btn)
        
        # Set up auto-refresh timer (disabled to prevent continuous background checking)
        self.simulation_status_timer = QTimer()
        self.simulation_status_timer.timeout.connect(self.refresh_simulation_status)
        
        # Initialize selected testbench and simulation
        self.selected_testbench = None
        self.selected_testbench_item = None
        self.selected_simulation_item = None
        # self.simulation_status_timer.start(30000)  # Auto-refresh disabled - use manual refresh button instead
        
        return status_group
    
    def create_upload_status_widget(self):
        """Create the upload status display widget."""
        status_group = QGroupBox("Upload Status")
        layout = QVBoxLayout(status_group)
        
        # Upload info section
        info_frame = QFrame()
        info_layout = QVBoxLayout(info_frame)
        info_layout.setContentsMargins(10, 5, 10, 5)
        
        # openFPGALoader status
        self.openfpgaloader_status_label = QLabel("openFPGALoader: Checking...")
        self.openfpgaloader_status_label.setStyleSheet("font-weight: bold; color: #FFA726;")
        info_layout.addWidget(self.openfpgaloader_status_label)
        
        # Device detection status
        self.device_status_label = QLabel("FPGA Device: Not detected")
        self.device_status_label.setStyleSheet("font-weight: bold; color: #888888;")
        info_layout.addWidget(self.device_status_label)
        
        # Upload activity indicator
        self.upload_activity_label = QLabel("Upload Status: Ready")
        self.upload_activity_label.setStyleSheet("font-weight: bold; color: #888888; margin-top: 5px;")
        info_layout.addWidget(self.upload_activity_label)
        
        # Upload progress bar
        self.upload_progress_bar = QProgressBar()
        self.upload_progress_bar.setVisible(False)  # Hidden by default
        self.upload_progress_bar.setMaximumHeight(20)
        self.upload_progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #555;
                border-radius: 5px;
                text-align: center;
                background-color: #2b2b2b;
            }
            QProgressBar::chunk {
                background-color: #4CAF50;
                border-radius: 4px;
            }
        """)
        info_layout.addWidget(self.upload_progress_bar)
        
        # Selected board info
        self.selected_board_status_label = QLabel("Target Board: Olimex GateMate EVB")
        self.selected_board_status_label.setStyleSheet("font-weight: bold; color: #FF9800; margin-top: 5px;")
        info_layout.addWidget(self.selected_board_status_label)
        
        # Selected bitstream info
        self.selected_bitstream_label = QLabel("Selected Bitstream: None")
        self.selected_bitstream_label.setStyleSheet("font-weight: bold; color: #4CAF50; margin-top: 5px;")
        info_layout.addWidget(self.selected_bitstream_label)
        
        info_frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        layout.addWidget(info_frame)
        
        # Available Bitstreams section
        bitstream_label = QLabel("Available Bitstreams:")
        bitstream_label.setStyleSheet("font-weight: bold; margin-top: 10px;")
        layout.addWidget(bitstream_label)
        
        self.bitstream_tree = QTreeWidget()
        self.bitstream_tree.setHeaderLabels(["Bitstream File", "Design", "Size", "Modified", "Type", "Status"])
        self.bitstream_tree.setAlternatingRowColors(True)
        self.bitstream_tree.setRootIsDecorated(False)
        self.bitstream_tree.setMaximumHeight(200)
        self.bitstream_tree.setMinimumHeight(120)
        self.bitstream_tree.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.bitstream_tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.bitstream_tree.setFocusPolicy(Qt.StrongFocus)
        self.bitstream_tree.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.bitstream_tree.itemClicked.connect(self._on_bitstream_tree_clicked)
        
        # Set column widths for bitstream tree
        self.bitstream_tree.setColumnWidth(0, 180)  # Bitstream File
        self.bitstream_tree.setColumnWidth(1, 120)  # Design
        self.bitstream_tree.setColumnWidth(2, 80)   # Size
        self.bitstream_tree.setColumnWidth(3, 120)  # Modified
        self.bitstream_tree.setColumnWidth(4, 100)  # Type
        
        layout.addWidget(self.bitstream_tree)
        
        # Add spacer to prevent bitstream tree from expanding
        layout.addStretch()
        
        # Upload Statistics section
        stats_frame = QFrame()
        stats_layout = QGridLayout(stats_frame)
        stats_layout.setContentsMargins(10, 5, 10, 5)
        
        # Create statistics labels
        self.upload_stats_labels = {}
        stats_items = [
            ('total_bitstreams', 'Total Bitstreams:', 0, 0),
            ('sram_uploads', 'SRAM Uploads:', 0, 1),
            ('flash_uploads', 'Flash Uploads:', 1, 0),
            ('last_upload', 'Last Upload:', 1, 1)
        ]
        
        for key, label_text, row, col in stats_items:
            label = QLabel(label_text)
            label.setStyleSheet("color: #888888; font-size: 11px;")
            value_label = QLabel("0" if key != 'last_upload' else "Never")
            value_label.setStyleSheet("color: #ffffff; font-weight: bold; font-size: 11px;")
            
            stats_layout.addWidget(label, row * 2, col)
            stats_layout.addWidget(value_label, row * 2 + 1, col)
            self.upload_stats_labels[key] = value_label
        
        stats_frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        layout.addWidget(stats_frame)
        
        # Refresh button
        refresh_btn = QPushButton("🔄 Refresh Status")
        refresh_btn.clicked.connect(self.refresh_upload_status)
        refresh_btn.setMaximumWidth(200)
        layout.addWidget(refresh_btn)
        
        # Set up auto-refresh timer (disabled to prevent continuous background checking)
        self.upload_status_timer = QTimer()
        self.upload_status_timer.timeout.connect(self.refresh_upload_status)
        
        # Initialize selected bitstream
        self.selected_bitstream = None
        self.selected_bitstream_item = None
        
        # Initialize upload activity indicator
        self.upload_activity_timer = QTimer()
        self.upload_activity_timer.timeout.connect(self._blink_upload_activity)
        self.upload_activity_blink_state = False
        self.upload_in_progress = False
        
        return status_group
    
    
    
    def refresh_simulation_status(self):
        """Refresh the simulation status display."""
        try:
            logging.info("🔄 Refreshing simulation status...")
            
            # Update simulation settings display
            try:
                from cc_project_manager_pkg.simulation_manager import SimulationManager
                sim_manager = SimulationManager()
                
                # Get simulation settings
                sim_settings = sim_manager.get_simulation_length()
                current_profile = sim_manager.get_current_simulation_profile()
                
                if sim_settings:
                    sim_time, time_prefix = sim_settings
                    config_text = f"Profile: {current_profile}, Duration: {sim_time}{time_prefix}"
                    self.sim_config_label.setText(f"Simulation Settings: {config_text}")
                    self.sim_config_label.setStyleSheet("font-weight: bold; color: #4CAF50;")
                else:
                    self.sim_config_label.setText("Simulation Settings: Using defaults")
                    self.sim_config_label.setStyleSheet("font-weight: bold; color: #FFA726;")
                
                # Check GTKWave status
                if sim_manager.check_gtkwave():
                    self.gtkwave_status_label.setText("GTKWave: ✅ Available")
                    self.gtkwave_status_label.setStyleSheet("font-weight: bold; color: #4CAF50;")
                else:
                    self.gtkwave_status_label.setText("GTKWave: ❌ Not available")
                    self.gtkwave_status_label.setStyleSheet("font-weight: bold; color: #F44336;")
                
            except Exception as e:
                logging.warning(f"Could not load simulation configuration: {e}")
                self.sim_config_label.setText("Simulation Settings: Error loading")
                self.sim_config_label.setStyleSheet("font-weight: bold; color: #F44336;")
                self.gtkwave_status_label.setText("GTKWave: Error checking")
                self.gtkwave_status_label.setStyleSheet("font-weight: bold; color: #F44336;")
            
            # Clear and populate testbench tree
            self.testbench_tree.clear()
            
            # Get available testbenches
            try:
                from cc_project_manager_pkg.hierarchy_manager import HierarchyManager
                hierarchy_manager = HierarchyManager()
                available_testbenches = hierarchy_manager.get_available_testbenches()
                files_info = hierarchy_manager.get_source_files_info()
                
                if available_testbenches:
                    for testbench_entity in available_testbenches:
                        # Find the corresponding file for this testbench entity
                        testbench_file = "Unknown"
                        status = "Ready"
                        
                        # Look in testbench files first
                        for file_name, file_path in files_info.get("testbench", {}).items():
                            try:
                                entity_name = hierarchy_manager.parse_entity_name_from_vhdl(file_path)
                                if entity_name == testbench_entity:
                                    testbench_file = file_name
                                    break
                            except:
                                continue
                        
                        # If not found, look in top files
                        if testbench_file == "Unknown":
                            for file_name, file_path in files_info.get("top", {}).items():
                                if '_tb' in file_name.lower():
                                    try:
                                        entity_name = hierarchy_manager.parse_entity_name_from_vhdl(file_path)
                                        if entity_name == testbench_entity:
                                            testbench_file = file_name
                                            break
                                    except:
                                        continue
                        
                        item = QTreeWidgetItem(self.testbench_tree, [
                            testbench_entity,
                            testbench_file,
                            testbench_entity,
                            status
                        ])
                        
                        # Store testbench entity name for selection
                        item.setData(0, Qt.UserRole, testbench_entity)
                        
                        # Color code based on status
                        if status == "Ready":
                            item.setForeground(3, QColor("#4CAF50"))
                        else:
                            item.setForeground(3, QColor("#FFA726"))
                    
                    logging.info(f"✅ Found {len(available_testbenches)} testbenches: {', '.join(available_testbenches)}")
                else:
                    # Add message when no testbenches found
                    no_tb_item = QTreeWidgetItem(self.testbench_tree, [
                        "No testbenches found",
                        "Add testbench files to project",
                        "",
                        "Missing"
                    ])
                    no_tb_item.setForeground(0, QColor("#FFA726"))
                    no_tb_item.setForeground(3, QColor("#F44336"))
                    logging.warning("⚠️ No testbenches found in project")
                    
            except Exception as e:
                logging.error(f"Error loading testbenches: {e}")
                error_item = QTreeWidgetItem(self.testbench_tree, [
                    "Error loading testbenches",
                    str(e),
                    "",
                    "Error"
                ])
                error_item.setForeground(0, QColor("#F44336"))
                error_item.setForeground(3, QColor("#F44336"))
            
            # Clear the tree
            self.simulation_tree.clear()
            
            # Get available simulations
            try:
                available_sims = sim_manager.get_available_simulations()
                
                # Count totals
                behavioral_count = len(available_sims.get("behavioral", []))
                post_synth_count = len(available_sims.get("post-synthesis", []))
                post_impl_count = len(available_sims.get("post-implementation", []))
                total_count = behavioral_count + post_synth_count + post_impl_count
                
                # Add behavioral simulations
                if behavioral_count > 0:
                    behavioral_item = QTreeWidgetItem(["Behavioral Simulations", f"{behavioral_count} files", "", "", "", "", ""])
                    behavioral_item.setIcon(0, self.style().standardIcon(QStyle.SP_DirIcon))
                    behavioral_item.setForeground(0, QColor("#ffffff"))
                    behavioral_item.setForeground(1, QColor("#64b5f6"))
                    
                    for sim in available_sims["behavioral"]:
                        size_mb = sim["size"] / (1024 * 1024)
                        size_text = f"{size_mb:.1f} MB" if size_mb >= 1 else f"{sim['size']} B"
                        modified_text = sim["modified"].strftime("%Y-%m-%d %H:%M")
                        
                        # Get simulation duration from simulation history
                        sim_duration = self._get_simulation_duration_for_vcd(sim["name"], "behavioral")
                        
                        sim_item = QTreeWidgetItem([
                            sim["name"], "Behavioral", size_text, modified_text, sim["entity"], sim_duration, "✅ Ready"
                        ])
                        sim_item.setIcon(0, self.style().standardIcon(QStyle.SP_FileIcon))
                        sim_item.setForeground(0, QColor("#ffffff"))
                        sim_item.setForeground(1, QColor("#64b5f6"))
                        sim_item.setForeground(2, QColor("#FFA726"))
                        sim_item.setForeground(3, QColor("#888888"))
                        sim_item.setForeground(4, QColor("#4CAF50"))
                        sim_item.setForeground(5, QColor("#81C784"))  # Duration color
                        sim_item.setForeground(6, QColor("#4CAF50"))  # Status color
                        
                        # Store simulation metadata for launching
                        sim_item.setData(0, Qt.UserRole, {"path": sim["path"], "type": "behavioral"})
                        
                        behavioral_item.addChild(sim_item)
                    
                    self.simulation_tree.addTopLevelItem(behavioral_item)
                    behavioral_item.setExpanded(True)
                
                # Add post-synthesis simulations
                if post_synth_count > 0:
                    post_synth_item = QTreeWidgetItem(["Post-Synthesis Simulations", f"{post_synth_count} files", "", "", "", "", ""])
                    post_synth_item.setIcon(0, self.style().standardIcon(QStyle.SP_DirIcon))
                    post_synth_item.setForeground(0, QColor("#ffffff"))
                    post_synth_item.setForeground(1, QColor("#FF9800"))
                    
                    for sim in available_sims["post-synthesis"]:
                        size_mb = sim["size"] / (1024 * 1024)
                        size_text = f"{size_mb:.1f} MB" if size_mb >= 1 else f"{sim['size']} B"
                        modified_text = sim["modified"].strftime("%Y-%m-%d %H:%M")
                        
                        # Get simulation duration from simulation history
                        sim_duration = self._get_simulation_duration_for_vcd(sim["name"], "post-synthesis")
                        
                        sim_item = QTreeWidgetItem([
                            sim["name"], "Post-Synthesis", size_text, modified_text, sim["entity"], sim_duration, "✅ Ready"
                        ])
                        sim_item.setIcon(0, self.style().standardIcon(QStyle.SP_FileIcon))
                        sim_item.setForeground(0, QColor("#ffffff"))
                        sim_item.setForeground(1, QColor("#FF9800"))
                        sim_item.setForeground(2, QColor("#FFA726"))
                        sim_item.setForeground(3, QColor("#888888"))
                        sim_item.setForeground(4, QColor("#4CAF50"))
                        sim_item.setForeground(5, QColor("#81C784"))  # Duration color
                        sim_item.setForeground(6, QColor("#4CAF50"))  # Status color
                        
                        # Store simulation metadata for launching
                        sim_item.setData(0, Qt.UserRole, {"path": sim["path"], "type": "post-synthesis"})
                        
                        post_synth_item.addChild(sim_item)
                    
                    self.simulation_tree.addTopLevelItem(post_synth_item)
                    post_synth_item.setExpanded(True)
                
                # Add post-implementation simulations
                if post_impl_count > 0:
                    post_impl_item = QTreeWidgetItem(["Post-Implementation Simulations", f"{post_impl_count} files", "", "", "", "", ""])
                    post_impl_item.setIcon(0, self.style().standardIcon(QStyle.SP_DirIcon))
                    post_impl_item.setForeground(0, QColor("#ffffff"))
                    post_impl_item.setForeground(1, QColor("#9C27B0"))
                    
                    for sim in available_sims["post-implementation"]:
                        size_mb = sim["size"] / (1024 * 1024)
                        size_text = f"{size_mb:.1f} MB" if size_mb >= 1 else f"{sim['size']} B"
                        modified_text = sim["modified"].strftime("%Y-%m-%d %H:%M")
                        
                        # Get simulation duration from simulation history
                        sim_duration = self._get_simulation_duration_for_vcd(sim["name"], "post-implementation")
                        
                        sim_item = QTreeWidgetItem([
                            sim["name"], "Post-Implementation", size_text, modified_text, sim["entity"], sim_duration, "✅ Ready"
                        ])
                        sim_item.setIcon(0, self.style().standardIcon(QStyle.SP_FileIcon))
                        sim_item.setForeground(0, QColor("#ffffff"))
                        sim_item.setForeground(1, QColor("#9C27B0"))
                        sim_item.setForeground(2, QColor("#FFA726"))
                        sim_item.setForeground(3, QColor("#888888"))
                        sim_item.setForeground(4, QColor("#4CAF50"))
                        sim_item.setForeground(5, QColor("#81C784"))  # Duration color
                        sim_item.setForeground(6, QColor("#4CAF50"))  # Status color
                        
                        # Store simulation metadata for launching
                        sim_item.setData(0, Qt.UserRole, {"path": sim["path"], "type": "post-implementation"})
                        
                        post_impl_item.addChild(sim_item)
                    
                    self.simulation_tree.addTopLevelItem(post_impl_item)
                    post_impl_item.setExpanded(True)
                
                # Update statistics
                self.sim_stats_labels['behavioral_sims'].setText(str(behavioral_count))
                self.sim_stats_labels['post_synth_sims'].setText(str(post_synth_count))
                self.sim_stats_labels['post_impl_sims'].setText(str(post_impl_count))
                self.sim_stats_labels['total_vcd_files'].setText(str(total_count))
                
                logging.info(f"📊 Simulation status updated: {total_count} total VCD files")
                
            except Exception as e:
                logging.error(f"Error getting simulation data: {e}")
                # Reset statistics on error
                for label in self.sim_stats_labels.values():
                    label.setText("0")
                
        except Exception as e:
            logging.error(f"Error refreshing simulation status: {e}")
    
    def _get_simulation_duration_for_vcd(self, vcd_filename, sim_type):
        """Get simulation duration for a VCD file from simulation history."""
        try:
            from cc_project_manager_pkg.simulation_manager import SimulationManager
            sim_manager = SimulationManager()
            
            # Check if simulation history exists in project config
            if hasattr(sim_manager, 'project_config') and sim_manager.project_config:
                sim_history = sim_manager.project_config.get("simulation_history", {})
                type_history = sim_history.get(sim_type, [])
                
                # Find the most recent simulation record for this VCD file
                for record in reversed(type_history):  # Start from most recent
                    if record.get("vcd_file", "").endswith(vcd_filename):
                        sim_time = record.get("simulation_time", "Unknown")
                        time_prefix = record.get("time_prefix", "")
                        if sim_time != "Unknown":
                            return f"{sim_time}{time_prefix}"
                        break
            
            # Fallback: try to get current simulation settings
            sim_settings = sim_manager.get_simulation_length()
            if sim_settings:
                sim_time, time_prefix = sim_settings
                return f"{sim_time}{time_prefix}"
            
            return "Unknown"
            
        except Exception as e:
            logging.warning(f"Could not get simulation duration for {vcd_filename}: {e}")
            return "Unknown"
    
    def _on_testbench_tree_clicked(self, item, column):
        """Handle testbench tree item clicks for selection."""
        testbench_entity = item.data(0, Qt.UserRole)
        
        if testbench_entity and testbench_entity not in ["No testbenches found", "Error loading testbenches"]:
            # Clear previous highlighting
            self._clear_testbench_highlighting()
            
            # Highlight selected testbench
            self._highlight_selected_testbench(item)
            
            # Update selected testbench label
            self.selected_testbench_label.setText(f"Selected Testbench: {testbench_entity}")
            self.selected_testbench_label.setStyleSheet("font-weight: bold; color: #4CAF50; margin-top: 5px;")
            
            # Store selected testbench for simulation operations
            self.selected_testbench = testbench_entity
            
            logging.info(f"🎯 Selected testbench: {testbench_entity}")
        else:
            # Clear selection if invalid item clicked
            self.selected_testbench_label.setText("Selected Testbench: None")
            self.selected_testbench_label.setStyleSheet("font-weight: bold; color: #888888; margin-top: 5px;")
            self.selected_testbench = None
    
    def _highlight_selected_testbench(self, item):
        """Highlight the selected testbench item row."""
        try:
            # Clear previous highlighting
            self._clear_testbench_highlighting()
            
            # Store reference to currently selected item
            self.selected_testbench_item = item
            
            # Use Qt's built-in selection mechanism first
            self.testbench_tree.setCurrentItem(item)
            
            # Apply additional custom highlighting for better visibility
            highlight_color = QColor(25, 118, 210)  # Material Design Blue 700 (RGB)
            text_color = QColor(255, 255, 255)      # White text (RGB)
            
            for column in range(self.testbench_tree.columnCount()):
                # Set background and foreground colors directly
                item.setBackground(column, highlight_color)
                item.setForeground(column, text_color)
                
                # Make the text bold for better visibility
                font = item.font(column)
                font.setBold(True)
                item.setFont(column, font)
            
            logging.info(f"✅ Highlighted testbench row: {item.text(0)} with blue background and selection")
            
        except Exception as e:
            logging.error(f"Error highlighting selected testbench: {e}")
    
    def _clear_testbench_highlighting(self):
        """Clear highlighting from all testbench item rows."""
        try:
            # Clear Qt's built-in selection
            if hasattr(self, 'testbench_tree'):
                self.testbench_tree.clearSelection()
                self.testbench_tree.setCurrentItem(None)
            
            # Clear custom highlighting from previously selected item
            if hasattr(self, 'selected_testbench_item') and self.selected_testbench_item:
                for column in range(self.testbench_tree.columnCount()):
                    # Reset to default colors (transparent background, default text)
                    default_bg = QColor(0, 0, 0, 0)  # Transparent background (RGBA)
                    
                    self.selected_testbench_item.setBackground(column, default_bg)
                    
                    # Restore original text colors
                    if column == 3:  # Status column
                        status = self.selected_testbench_item.text(3)
                        if status == "Ready":
                            self.selected_testbench_item.setForeground(column, QColor("#4CAF50"))
                        elif status == "Missing":
                            self.selected_testbench_item.setForeground(column, QColor("#F44336"))
                        else:
                            self.selected_testbench_item.setForeground(column, QColor("#FFA726"))
                    else:
                        self.selected_testbench_item.setForeground(column, QColor("#FFFFFF"))  # Default white text
                    
                    # Reset font to normal weight
                    font = self.selected_testbench_item.font(column)
                    font.setBold(False)
                    self.selected_testbench_item.setFont(column, font)
                    
                logging.info(f"🧹 Cleared highlighting and selection from: {self.selected_testbench_item.text(0)}")
                self.selected_testbench_item = None
                
        except Exception as e:
            logging.error(f"Error clearing testbench highlighting: {e}")
    
    def _on_simulation_tree_clicked(self, item, column):
        """Handle simulation tree item clicks for selection."""
        # Check if this is a VCD file item (has simulation data)
        sim_data = item.data(0, Qt.UserRole)
        if sim_data and "path" in sim_data:
            vcd_path = sim_data["path"]
            sim_type = sim_data["type"]
            vcd_name = os.path.basename(vcd_path)
            
            # Clear previous highlighting
            self._clear_simulation_highlighting()
            
            # Highlight selected simulation
            self._highlight_selected_simulation(item)
            
            logging.info(f"🎯 Selected VCD file: {vcd_name} ({sim_type})")
        else:
            # Clear selection if invalid item clicked (like category headers)
            self._clear_simulation_highlighting()
    
    def _highlight_selected_simulation(self, item):
        """Highlight the selected simulation item row."""
        try:
            # Clear previous highlighting
            self._clear_simulation_highlighting()
            
            # Store reference to currently selected item
            self.selected_simulation_item = item
            
            # Use Qt's built-in selection mechanism first
            self.simulation_tree.setCurrentItem(item)
            
            # Apply additional custom highlighting for better visibility
            highlight_color = QColor(25, 118, 210)  # Material Design Blue 700 (RGB)
            text_color = QColor(255, 255, 255)      # White text (RGB)
            
            for column in range(self.simulation_tree.columnCount()):
                # Set background and foreground colors directly
                item.setBackground(column, highlight_color)
                item.setForeground(column, text_color)
                
                # Make the text bold for better visibility
                font = item.font(column)
                font.setBold(True)
                item.setFont(column, font)
            
            logging.info(f"✅ Highlighted simulation row: {item.text(0)} with blue background and selection")
            
        except Exception as e:
            logging.error(f"Error highlighting selected simulation: {e}")
    
    def _clear_simulation_highlighting(self):
        """Clear highlighting from all simulation item rows."""
        try:
            # Clear Qt's built-in selection
            if hasattr(self, 'simulation_tree'):
                self.simulation_tree.clearSelection()
                self.simulation_tree.setCurrentItem(None)
            
            # Clear custom highlighting from previously selected item
            if hasattr(self, 'selected_simulation_item') and self.selected_simulation_item:
                for column in range(self.simulation_tree.columnCount()):
                    # Reset to default colors (transparent background, default text)
                    default_bg = QColor(0, 0, 0, 0)  # Transparent background (RGBA)
                    
                    self.selected_simulation_item.setBackground(column, default_bg)
                    
                    # Restore original text colors based on column type
                    if column == 1:  # Type column
                        sim_type = self.selected_simulation_item.text(1)
                        if sim_type == "Behavioral":
                            self.selected_simulation_item.setForeground(column, QColor("#64b5f6"))
                        elif sim_type == "Post-Synthesis":
                            self.selected_simulation_item.setForeground(column, QColor("#FF9800"))
                        elif sim_type == "Post-Implementation":
                            self.selected_simulation_item.setForeground(column, QColor("#9C27B0"))
                        else:
                            self.selected_simulation_item.setForeground(column, QColor("#FFFFFF"))
                    elif column == 2:  # Size column
                        self.selected_simulation_item.setForeground(column, QColor("#FFA726"))
                    elif column == 3:  # Modified column
                        self.selected_simulation_item.setForeground(column, QColor("#888888"))
                    elif column == 4:  # Entity column
                        self.selected_simulation_item.setForeground(column, QColor("#4CAF50"))
                    elif column == 5:  # Status column
                        self.selected_simulation_item.setForeground(column, QColor("#4CAF50"))
                    else:  # Default (Name column)
                        self.selected_simulation_item.setForeground(column, QColor("#FFFFFF"))
                    
                    # Reset font to normal weight
                    font = self.selected_simulation_item.font(column)
                    font.setBold(False)
                    self.selected_simulation_item.setFont(column, font)
                    
                logging.info(f"🧹 Cleared highlighting and selection from: {self.selected_simulation_item.text(0)}")
                self.selected_simulation_item = None
                
        except Exception as e:
            logging.error(f"Error clearing simulation highlighting: {e}")
    
    def _on_simulation_double_clicked(self, item, column):
        """Handle double-click on simulation item to launch GTKWave."""
        # Check if this is a VCD file item (has simulation data)
        sim_data = item.data(0, Qt.UserRole)
        if sim_data and "path" in sim_data:
            vcd_path = sim_data["path"]
            sim_type = sim_data["type"]
            
            logging.info(f"🌊 Launching GTKWave for {sim_type} simulation: {os.path.basename(vcd_path)}")
            
            try:
                from cc_project_manager_pkg.simulation_manager import SimulationManager
                sim_manager = SimulationManager()
                
                if sim_manager.launch_wave(vcd_path):
                    logging.info("✅ GTKWave launched successfully")
                else:
                    logging.error("❌ Failed to launch GTKWave")
                    self.show_message("Error", "Failed to launch GTKWave. Check that GTKWave is properly configured.", "error")
                    
            except Exception as e:
                logging.error(f"Error launching GTKWave: {e}")
                self.show_message("Error", f"Error launching GTKWave: {e}", "error")
    
    def refresh_synthesis_status(self):
        """Refresh the synthesis status display."""
        try:
            logging.info("🔄 Refreshing synthesis status...")
            
            # Update synthesis strategy display
            try:
                synth_config = self._get_synthesis_configuration()
                config_text = f"Strategy: {synth_config['strategy']}, VHDL: {synth_config['vhdl_standard']}, IEEE: {synth_config['ieee_library']}"
                self.synth_config_label.setText(f"Synthesis Strategy: {config_text}")
                self.synth_config_label.setStyleSheet("font-weight: bold; color: #4CAF50;")
            except Exception as e:
                logging.warning(f"Could not load synthesis configuration: {e}")
                self.synth_config_label.setText("Synthesis Strategy: Error loading")
                self.synth_config_label.setStyleSheet("font-weight: bold; color: #F44336;")
            
            # Clear the tree
            self.synthesis_tree.clear()
            
            # Find available VHDL entities
            available_entities = self._find_available_vhdl_entities()
            entity_count = len(available_entities)
            
            # Find synthesized designs
            synthesized_designs = self._find_synthesized_designs()
            synthesized_count = len(synthesized_designs)
            
            # Load synthesis results
            synthesis_results = self._load_synthesis_results()
            
            # Add available entities section
            if available_entities:
                entities_item = QTreeWidgetItem(["Available Entities", f"{entity_count} found", "", "", "", ""])
                entities_item.setIcon(0, self.style().standardIcon(QStyle.SP_DirIcon))
                entities_item.setForeground(0, QColor("#ffffff"))
                entities_item.setForeground(1, QColor("#64b5f6"))
                
                for entity, entity_type in available_entities.items():
                    # Check if this entity has been synthesized
                    is_synthesized = entity in synthesized_designs
                    status = "✅ Synthesized" if is_synthesized else "⚪ Not synthesized"
                    status_color = "#4CAF50" if is_synthesized else "#888888"
                    
                    # Set type color based on entity type
                    type_color = {
                        'Source': '#64b5f6',      # Blue for source files
                        'Top': '#FF9800',         # Orange for top modules
                        'Testbench': '#9C27B0'    # Purple for testbenches
                    }.get(entity_type, '#888888')
                    
                    # Determine if entity is synthesizable
                    is_synthesizable = entity_type in ['Source', 'Top']
                    synthesizable_icon = "✅" if is_synthesizable else "❌"
                    synthesizable_color = "#4CAF50" if is_synthesizable else "#F44336"
                    
                    # Get strategy and timestamp information
                    strategy = ""
                    timestamp = ""
                    if entity in synthesis_results:
                        strategy = synthesis_results[entity].get('strategy', '').title()
                        if synthesis_results[entity].get('use_gatemate', False):
                            strategy += " (GateMate)"
                        timestamp = synthesis_results[entity].get('timestamp', '')
                    
                    entity_item = QTreeWidgetItem([entity, entity_type, synthesizable_icon, status, strategy, timestamp])
                    entity_item.setIcon(0, self.style().standardIcon(QStyle.SP_FileIcon))
                    entity_item.setForeground(0, QColor("#ffffff"))
                    entity_item.setForeground(1, QColor(type_color))
                    entity_item.setForeground(2, QColor(synthesizable_color))
                    entity_item.setForeground(3, QColor(status_color))
                    entity_item.setForeground(4, QColor("#64b5f6" if strategy else "#888888"))
                    entity_item.setForeground(5, QColor("#FFA726" if timestamp else "#888888"))
                    
                    # Store entity metadata
                    entity_item.setData(0, Qt.UserRole, {"entity_name": entity, "is_synthesized": is_synthesized})
                    
                    entities_item.addChild(entity_item)
                
                self.synthesis_tree.addTopLevelItem(entities_item)
                entities_item.setExpanded(True)
            
            # Add synthesized designs section
            if synthesized_designs:
                synth_item = QTreeWidgetItem(["Synthesized Designs", f"{synthesized_count} designs", "", "", "", ""])
                synth_item.setIcon(0, self.style().standardIcon(QStyle.SP_DirIcon))
                synth_item.setForeground(0, QColor("#ffffff"))
                synth_item.setForeground(1, QColor("#4CAF50"))
                
                for design_name, design_info in synthesized_designs.items():
                    # Show design with file info
                    file_info = f"{len(design_info.get('files', []))} files"
                    
                    # Get strategy for this design
                    design_strategy = ""
                    design_timestamp = design_info.get('timestamp', 'Unknown')
                    
                    if design_name in synthesis_results:
                        design_strategy = synthesis_results[design_name].get('strategy', '').title()
                        if synthesis_results[design_name].get('use_gatemate', False):
                            design_strategy += " (GateMate)"
                        # Use stored timestamp if available (more accurate than file modification time)
                        stored_timestamp = synthesis_results[design_name].get('timestamp')
                        if stored_timestamp:
                            design_timestamp = stored_timestamp
                    
                    design_item = QTreeWidgetItem([design_name, "", "", file_info, design_strategy, design_timestamp])
                    design_item.setIcon(0, self.style().standardIcon(QStyle.SP_ComputerIcon))
                    design_item.setForeground(0, QColor("#ffffff"))
                    design_item.setForeground(1, QColor("#888888"))  # Empty type column
                    design_item.setForeground(2, QColor("#4CAF50"))
                    design_item.setForeground(3, QColor("#64b5f6" if design_strategy else "#888888"))
                    design_item.setForeground(4, QColor("#FFA726"))
                    
                    # Add synthesis files as children
                    for file_path in design_info.get('files', []):
                        file_name = os.path.basename(file_path)
                        file_exists = os.path.exists(file_path)
                        file_status = "✅" if file_exists else "❌"
                        
                        file_item = QTreeWidgetItem([file_name, "", file_status, "", ""])
                        file_item.setIcon(0, self.style().standardIcon(QStyle.SP_FileIcon))
                        file_item.setForeground(0, QColor("#ffffff"))
                        file_item.setForeground(1, QColor("#888888"))  # Empty type column
                        file_item.setForeground(2, QColor("#4CAF50" if file_exists else "#F44336"))
                        file_item.setToolTip(0, file_path)
                        
                        design_item.addChild(file_item)
                    
                    synth_item.addChild(design_item)
                
                self.synthesis_tree.addTopLevelItem(synth_item)
                synth_item.setExpanded(True)
            
            # Update statistics
            # Count only synthesizable entities (Source and Top, not Testbench)
            synthesizable_count = sum(1 for entity, entity_type in available_entities.items() 
                                    if entity_type in ['Source', 'Top'])
            self.synth_stats_labels['available_entities'].setText(str(synthesizable_count))
            self.synth_stats_labels['synthesized_designs'].setText(str(synthesized_count))
            
            # Count synthesis errors (placeholder for now)
            error_count = 0  # TODO: Implement error detection from logs
            self.synth_stats_labels['synthesis_errors'].setText(str(error_count))
            if error_count > 0:
                self.synth_stats_labels['synthesis_errors'].setStyleSheet("color: #F44336; font-weight: bold; font-size: 11px;")
            else:
                self.synth_stats_labels['synthesis_errors'].setStyleSheet("color: #4CAF50; font-weight: bold; font-size: 11px;")
            
            # Last synthesis time - find the most recent synthesis timestamp
            last_synthesis_time = "Never"
            if synthesis_results:
                # Get all timestamps and find the most recent one
                timestamps = []
                for entity_data in synthesis_results.values():
                    if isinstance(entity_data, dict) and 'timestamp' in entity_data:
                        timestamp_str = entity_data['timestamp']
                        if timestamp_str and timestamp_str != "Unknown":
                            try:
                                # Parse timestamp to compare
                                timestamp_obj = datetime.datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S')
                                timestamps.append((timestamp_obj, timestamp_str))
                            except:
                                pass  # Skip invalid timestamps
                
                if timestamps:
                    # Sort by timestamp and get the most recent
                    timestamps.sort(key=lambda x: x[0], reverse=True)
                    last_synthesis_time = timestamps[0][1]  # Get the string representation
            
            self.synth_stats_labels['last_synthesis'].setText(last_synthesis_time)
            
            # Resize columns
            self.synthesis_tree.resizeColumnToContents(0)
            self.synthesis_tree.resizeColumnToContents(1)
            self.synthesis_tree.resizeColumnToContents(2)
            self.synthesis_tree.resizeColumnToContents(3)
            self.synthesis_tree.resizeColumnToContents(4)
            self.synthesis_tree.resizeColumnToContents(5)
            
            # Set minimum widths for better display
            if self.synthesis_tree.columnWidth(0) < 200:
                self.synthesis_tree.setColumnWidth(0, 200)
            if self.synthesis_tree.columnWidth(4) < 150:
                self.synthesis_tree.setColumnWidth(4, 150)
            if self.synthesis_tree.columnWidth(5) < 150:
                self.synthesis_tree.setColumnWidth(5, 150)
            
            logging.info("✅ Synthesis status refresh completed successfully")
            
        except Exception as e:
            import traceback
            error_details = traceback.format_exc()
            logging.error(f"Error refreshing synthesis status: {e}")
            logging.error(f"Full traceback: {error_details}")
            self.synth_config_label.setText("Synthesis Strategy: Error loading")
            self.synth_config_label.setStyleSheet("font-weight: bold; color: #F44336;")
    
    def _find_synthesized_designs(self):
        """Find synthesized designs by looking for synthesis output files."""
        try:
            from cc_project_manager_pkg.hierarchy_manager import HierarchyManager
            
            # Find project configuration
            project_config_path, project_dir = self.find_project_config()
            if not project_config_path:
                return {}
            
            # Change to project directory temporarily
            original_cwd = os.getcwd()
            os.chdir(project_dir)
            
            try:
                hierarchy = HierarchyManager()
                if not hierarchy.config:
                    return {}
                
                # Get synthesis directory
                synth_dir = hierarchy.config.get("project_structure", {}).get("synth", [])
                if isinstance(synth_dir, list) and synth_dir:
                    synth_dir = synth_dir[0]
                
                if not synth_dir or not os.path.exists(synth_dir):
                    return {}
                
                synthesized_designs = {}
                
                # Look for synthesis output files (.v, .json)
                for file_name in os.listdir(synth_dir):
                    if file_name.endswith(('_synth.v', '_synth.json')):
                        # Extract design name
                        if file_name.endswith('_synth.v'):
                            design_name = file_name[:-8]  # Remove '_synth.v'
                        else:
                            design_name = file_name[:-11]  # Remove '_synth.json'
                        
                        if design_name not in synthesized_designs:
                            synthesized_designs[design_name] = {'files': [], 'timestamp': None}
                        
                        file_path = os.path.join(synth_dir, file_name)
                        synthesized_designs[design_name]['files'].append(file_path)
                        
                        # Get file modification time as fallback timestamp
                        if synthesized_designs[design_name]['timestamp'] is None:
                            try:
                                import time
                                mtime = os.path.getmtime(file_path)
                                synthesized_designs[design_name]['timestamp'] = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(mtime))
                            except:
                                synthesized_designs[design_name]['timestamp'] = "Unknown"
                
                return synthesized_designs
                
            finally:
                os.chdir(original_cwd)
                
        except Exception as e:
            logging.warning(f"Could not find synthesized designs: {e}")
            return {}
    
    def create_output_area(self):
        """Create the output/log area."""
        group = QGroupBox("Output / Log Messages")
        layout = QVBoxLayout(group)
        
        # Create log text widget
        self.log_widget = LogTextWidget()
        
        # Set minimum height to ensure at least 5 lines are always visible
        # Calculate based on font metrics: 5 lines + padding
        font_metrics = self.log_widget.fontMetrics()
        line_height = font_metrics.lineSpacing()
        min_height = (line_height * 5) + 20  # 5 lines + padding for scrollbar/margins
        self.log_widget.setMinimumHeight(min_height)
        
        layout.addWidget(self.log_widget)
        
        # Control buttons
        button_layout = QHBoxLayout()
        clear_btn = QPushButton("Clear")
        clear_btn.clicked.connect(self.log_widget.clear)
        
        save_btn = QPushButton("Save Log")
        save_btn.clicked.connect(self.save_log)
        
        button_layout.addWidget(clear_btn)
        button_layout.addWidget(save_btn)
        button_layout.addStretch()
        
        layout.addLayout(button_layout)
        
        return group
    
    def create_menu_bar(self):
        """Create the menu bar."""
        menubar = self.menuBar()
        
        # File menu
        file_menu = menubar.addMenu('File')
        
        new_action = QAction('New Project...', self)
        new_action.setShortcut('Ctrl+N')
        new_action.triggered.connect(self.create_new_project)
        file_menu.addAction(new_action)
        
        load_action = QAction('Load Existing Project...', self)
        load_action.setShortcut('Ctrl+O')
        load_action.triggered.connect(self.load_existing_project)
        file_menu.addAction(load_action)
        
        file_menu.addSeparator()
        
        clear_recent_action = QAction('Clear Recent Project', self)
        clear_recent_action.triggered.connect(self.clear_recent_project)
        file_menu.addAction(clear_recent_action)
        
        file_menu.addSeparator()
        
        exit_action = QAction('Exit', self)
        exit_action.setShortcut('Ctrl+Q')
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        
        # Tools menu
        tools_menu = menubar.addMenu('Tools')
        
        check_tools_action = QAction('Check Toolchain', self)
        check_tools_action.triggered.connect(self.check_toolchain_availability)
        tools_menu.addAction(check_tools_action)
        
        # Help menu
        help_menu = menubar.addMenu('Help')
        
        about_action = QAction('About', self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)
    
    def apply_stylesheet(self):
        """Apply custom dark theme stylesheet."""
        style = """
        /* Main Application Window */
        QMainWindow {
            background-color: #1e1e1e;
            color: #ffffff;
        }
        
        /* Central Widget */
        QWidget {
            background-color: #1e1e1e;
            color: #ffffff;
        }
        
        /* Group Boxes */
        QGroupBox {
            font-weight: bold;
            border: 2px solid #404040;
            border-radius: 8px;
            margin-top: 12px;
            padding-top: 12px;
            background-color: #2d2d2d;
            color: #ffffff;
        }
        
        QGroupBox::title {
            subcontrol-origin: margin;
            left: 12px;
            padding: 0 8px 0 8px;
            color: #64b5f6;
            font-size: 14px;
        }
        
        /* Push Buttons */
        QPushButton {
            background-color: #0d7377;
            border: none;
            color: #ffffff;
            padding: 12px 18px;
            text-align: center;
            font-size: 12px;
            font-weight: bold;
            margin: 3px;
            border-radius: 6px;
            min-height: 20px;
        }
        
        QPushButton:hover {
            background-color: #14a085;
        }
        
        QPushButton:pressed {
            background-color: #0a5d61;
        }
        
        QPushButton:disabled {
            background-color: #555555;
            color: #888888;
        }
        
        /* Tab Widget */
        QTabWidget::pane {
            border: 1px solid #404040;
            background-color: #2d2d2d;
            border-radius: 4px;
        }
        
        QTabBar::tab {
            background-color: #404040;
            color: #ffffff;
            padding: 12px 24px;
            margin-right: 2px;
            border-top-left-radius: 4px;
            border-top-right-radius: 4px;
            min-width: 140px;
        }
        
        QTabBar::tab:selected {
            background-color: #0d7377;
            color: #ffffff;
            font-weight: bold;
        }
        
        QTabBar::tab:hover:!selected {
            background-color: #555555;
        }
        
        /* Text Widgets */
        QTextEdit {
            background-color: #1a1a1a;
            border: 1px solid #404040;
            color: #ffffff;
            border-radius: 4px;
            padding: 5px;
            font-family: 'Consolas', 'Monaco', monospace;
        }
        
        QLineEdit {
            background-color: #2d2d2d;
            border: 2px solid #404040;
            color: #ffffff;
            border-radius: 4px;
            padding: 8px;
            font-size: 12px;
        }
        
        QLineEdit:focus {
            border-color: #0d7377;
        }
        
        /* Combo Boxes */
        QComboBox {
            background-color: #2d2d2d;
            border: 2px solid #404040;
            color: #ffffff;
            border-radius: 4px;
            padding: 8px;
            font-size: 12px;
            min-width: 120px;
        }
        
        QComboBox:focus {
            border-color: #0d7377;
        }
        
        QComboBox::drop-down {
            border: none;
            width: 20px;
        }
        
        QComboBox::down-arrow {
            image: none;
            border-left: 5px solid transparent;
            border-right: 5px solid transparent;
            border-top: 5px solid #ffffff;
        }
        
        QComboBox QAbstractItemView {
            background-color: #2d2d2d;
            border: 1px solid #404040;
            color: #ffffff;
            selection-background-color: #0d7377;
        }
        
        /* Check Boxes */
        QCheckBox {
            color: #ffffff;
            font-size: 12px;
        }
        
        QCheckBox::indicator {
            width: 16px;
            height: 16px;
            border: 2px solid #404040;
            border-radius: 3px;
            background-color: #2d2d2d;
        }
        
        QCheckBox::indicator:checked {
            background-color: #0d7377;
            border-color: #0d7377;
        }
        
        QCheckBox::indicator:checked::after {
            content: "✓";
            color: white;
            font-weight: bold;
        }
        
        /* Spin Boxes */
        QSpinBox {
            background-color: #2d2d2d;
            border: 2px solid #404040;
            color: #ffffff;
            border-radius: 4px;
            padding: 8px;
            font-size: 12px;
        }
        
        QSpinBox:focus {
            border-color: #0d7377;
        }
        
        /* Labels */
        QLabel {
            color: #ffffff;
            font-size: 12px;
        }
        
        /* Status Bar */
        QStatusBar {
            background-color: #1a1a1a;
            color: #ffffff;
            border-top: 1px solid #404040;
        }
        
        /* Menu Bar */
        QMenuBar {
            background-color: #2d2d2d;
            color: #ffffff;
            border-bottom: 1px solid #404040;
        }
        
        QMenuBar::item {
            background-color: transparent;
            padding: 8px 12px;
        }
        
        QMenuBar::item:selected {
            background-color: #0d7377;
        }
        
        QMenu {
            background-color: #2d2d2d;
            color: #ffffff;
            border: 1px solid #404040;
        }
        
        QMenu::item {
            padding: 8px 20px;
        }
        
        QMenu::item:selected {
            background-color: #0d7377;
        }
        
        /* Scroll Bars */
        QScrollBar:vertical {
            background-color: #2d2d2d;
            width: 12px;
            border-radius: 6px;
        }
        
        QScrollBar::handle:vertical {
            background-color: #555555;
            border-radius: 6px;
            min-height: 20px;
        }
        
        QScrollBar::handle:vertical:hover {
            background-color: #0d7377;
        }
        
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
            border: none;
            background: none;
        }
        
        QScrollBar:horizontal {
            background-color: #2d2d2d;
            height: 12px;
            border-radius: 6px;
        }
        
        QScrollBar::handle:horizontal {
            background-color: #555555;
            border-radius: 6px;
            min-width: 20px;
        }
        
        QScrollBar::handle:horizontal:hover {
            background-color: #0d7377;
        }
        
        /* Splitter */
        QSplitter::handle {
            background-color: #404040;
        }
        
        QSplitter::handle:horizontal {
            width: 3px;
        }
        
        QSplitter::handle:vertical {
            height: 3px;
        }
        
        /* Dialogs */
        QDialog {
            background-color: #2d2d2d;
            color: #ffffff;
        }
        
        /* Form Layout */
        QFormLayout QLabel {
            color: #ffffff;
            font-weight: bold;
        }
        
        /* Tool Tips */
        QToolTip {
            background-color: #1a1a1a;
            color: #ffffff;
            border: 1px solid #0d7377;
            padding: 5px;
            border-radius: 3px;
        }
        
        /* Tree Widget */
        QTreeWidget {
            background-color: #2d2d2d;
            border: 1px solid #404040;
            color: #ffffff;
            border-radius: 4px;
            outline: none;
            show-decoration-selected: 0;
        }
        
        QTreeWidget::item {
            background-color: transparent;
            color: #ffffff;
            padding: 4px;
            border: none;
            min-height: 20px;
        }
        
        QTreeWidget::item:selected {
            background-color: transparent;
            color: #ffffff;
        }
        
        QTreeWidget::item:hover {
            background-color: #404040;
            color: #ffffff;
        }
        
        QTreeWidget::item:alternate {
            background-color: #353535;
        }
        
        QTreeWidget::branch {
            background: transparent;
            border: none;
            width: 0px;
            margin: 0px;
            padding: 0px;
        }
        
        QTreeWidget::branch:has-children:!has-siblings:closed,
        QTreeWidget::branch:closed:has-children:has-siblings {
            background: transparent;
            border: none;
            width: 0px;
            margin: 0px;
            padding: 0px;
            border-image: none;
            image: none;
        }
        
        QTreeWidget::branch:open:has-children:!has-siblings,
        QTreeWidget::branch:open:has-children:has-siblings {
            background: transparent;
            border: none;
            width: 0px;
            margin: 0px;
            padding: 0px;
            border-image: none;
            image: none;
        }
        
        QTreeWidget::branch:has-siblings:!adjoins-item {
            background: transparent;
            border: none;
            width: 0px;
        }
        
        QTreeWidget::branch:has-siblings:adjoins-item {
            background: transparent;
            border: none;
            width: 0px;
        }
        
        QTreeWidget::branch:!has-children:!has-siblings:adjoins-item {
            background: transparent;
            border: none;
            width: 0px;
        }
        
        /* Tree Widget Header */
        QTreeWidget QHeaderView {
            background-color: #404040;
            color: #ffffff;
            border: none;
        }
        
        QTreeWidget QHeaderView::section {
            background-color: #404040;
            color: #ffffff;
            padding: 6px;
            border: none;
            border-right: 1px solid #555555;
            font-weight: bold;
        }
        
        QTreeWidget QHeaderView::section:hover {
            background-color: #555555;
        }
        """
        self.setStyleSheet(style)
    
    def setup_logging(self):
        """Setup logging to redirect to the GUI output window."""
        # Get root logger
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.INFO)
        
        # Remove existing handlers
        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)
        
        # Add GUI handler
        gui_handler = LogHandler(self.log_widget)
        gui_handler.setLevel(logging.INFO)
        root_logger.addHandler(gui_handler)
        
        # Initial message
        logging.info("GateMate Project Manager by JOCRIX GUI started")
    
    def show_message(self, title: str, message: str, msg_type: str = "info"):
        """Show a message box."""
        msg_box = QMessageBox()
        msg_box.setWindowTitle(title)
        msg_box.setText(message)
        
        if msg_type == "info":
            msg_box.setIcon(QMessageBox.Information)
        elif msg_type == "warning":
            msg_box.setIcon(QMessageBox.Warning)
        elif msg_type == "error":
            msg_box.setIcon(QMessageBox.Critical)
        elif msg_type == "question":
            msg_box.setIcon(QMessageBox.Question)
            msg_box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
            return msg_box.exec_() == QMessageBox.Yes
        
        msg_box.exec_()
        return True
    
    def run_in_thread(self, operation, *args, success_msg="Operation completed", **kwargs):
        """Run an operation in a worker thread."""
        if self.worker_thread and self.worker_thread.isRunning():
            logging.warning("Another operation is already running")
            return
        
        self.status_bar.showMessage("Running operation...")
        
        self.worker_thread = WorkerThread(operation, *args, **kwargs)
        self.worker_thread.finished.connect(self.on_operation_finished)
        self.worker_thread.start()
    
    def on_operation_finished(self, success: bool, message: str):
        """Handle completion of worker thread operation."""
        self.status_bar.showMessage("Ready")
        
        # Stop upload activity indicator if it was running
        if hasattr(self, 'upload_in_progress') and self.upload_in_progress:
            self._stop_upload_activity(success, "Complete" if success else "Failed")
        
        if success:
            logging.info(message)
            
            # Check if we need to refresh project status after project creation
            if hasattr(self, '_pending_project_refresh') and self._pending_project_refresh:
                self._pending_project_refresh = False
                QTimer.singleShot(500, self.refresh_project_status)
                # Also refresh synthesis status when project files change
                QTimer.singleShot(700, self.refresh_synthesis_status)
                QTimer.singleShot(800, self.refresh_implementation_status)
            
            # Check if we need to refresh implementation status after constraints file addition
            if hasattr(self, '_pending_implementation_refresh') and self._pending_implementation_refresh:
                self._pending_implementation_refresh = False
                QTimer.singleShot(600, self.refresh_implementation_status)
            
            # Check if this was a synthesis operation and refresh synthesis status
            if "synthesis" in message.lower() or "synthesize" in message.lower():
                QTimer.singleShot(600, self.refresh_synthesis_status)
                QTimer.singleShot(700, self.refresh_implementation_status)
            
            # Check if this was an implementation operation and refresh implementation status
            if any(keyword in message.lower() for keyword in ["place", "route", "bitstream", "implementation", "timing", "netlist", "constraints"]):
                QTimer.singleShot(1200, self.refresh_implementation_status)
            
            # Check if this was an upload operation and refresh upload status
            if any(keyword in message.lower() for keyword in ["program", "flash", "sram", "verify", "upload"]):
                # Update upload statistics if this was a successful programming operation
                if hasattr(self, 'selected_bitstream') and self.selected_bitstream:
                    design_name = self.selected_bitstream.get("design", "Unknown")
                    if "sram" in message.lower() and "program" in message.lower():
                        self._update_upload_statistics('sram', design_name)
                    elif "flash" in message.lower() and "program" in message.lower():
                        self._update_upload_statistics('flash', design_name)
                
                QTimer.singleShot(800, self.refresh_upload_status_without_device_check)
        else:
            logging.error(message)
            
            # Clear pending refresh flags on error
            if hasattr(self, '_pending_project_refresh'):
                self._pending_project_refresh = False
            if hasattr(self, '_pending_implementation_refresh'):
                self._pending_implementation_refresh = False
    
    # Project Management Methods
    def create_new_project(self):
        """Create a new project using the proper CreateStructure workflow."""
        logging.info("🆕 Opening new project creation dialog...")
        dialog = ProjectDialog(self)
        if dialog.exec_() == QDialog.Accepted:
            project_info = dialog.get_project_info()
            logging.info(f"📋 User entered project info: Name='{project_info['name']}', Path='{project_info['path']}'")
            
            if not project_info['name']:
                logging.warning("❌ Project name is empty")
                return
            
            def create_project():
                try:
                    logging.info(f"🏗️ Creating project '{project_info['name']}' at '{project_info['path']}'")
                    logging.info(f"📋 Project info received: {project_info}")
                    
                    # Validate project info
                    if not project_info.get('name'):
                        raise ValueError("Project name is empty or None")
                    if not project_info.get('path'):
                        raise ValueError("Project path is empty or None")
                    
                    # CreateStructure requires project_name and project_path in __init__
                    # This follows the proper workflow from CreateStructure class
                    logging.info("🔧 Initializing CreateStructure...")
                    creator = CreateStructure(project_info['name'], project_info['path'])
                    logging.info(f"✅ CreateStructure initialized with project_path: {creator.project_path}")
                    
                    # Step 1: Create project configuration file with directory structure
                    logging.info("📝 Step 1: Creating project configuration...")
                    creator.create_project_config()
                    logging.info("✅ Step 1 completed successfully")
                    
                    # Step 2: Create the actual directory structure based on config
                    logging.info("📁 Step 2: Creating directory structure...")
                    creator.create_dir_struct()
                    logging.info("✅ Step 2 completed successfully")
                    
                    # Step 3: Finalize by moving config and log files to proper locations
                    logging.info("🔧 Step 3: Finalizing project setup...")
                    creator.finalize()
                    logging.info("✅ Step 3 completed successfully")
                    
                    logging.info(f"🎉 Project creation completed successfully at {creator.project_path}")
                    
                    # Automatically navigate to the newly created project directory
                    os.chdir(creator.project_path)
                    logging.info(f"🔄 Automatically navigated to project directory: {creator.project_path}")
                    
                    # Save this project as the most recent
                    self.save_recent_project_path(creator.project_path)
                    self.current_project_path = creator.project_path
                    
                    return f"Project '{project_info['name']}' created successfully at {creator.project_path}"
                    
                except Exception as e:
                    import traceback
                    error_details = traceback.format_exc()
                    logging.error(f"Error creating project: {str(e)}")
                    logging.error(f"Full traceback: {error_details}")
                    raise Exception(f"Failed to create project: {str(e)}")
            
            # Store project info for post-creation refresh
            self._pending_project_refresh = True
            
            self.run_in_thread(
                create_project, 
                success_msg=f"Project '{project_info['name']}' created successfully"
            )
        else:
            logging.info("❌ User cancelled project creation dialog")
    
    def add_vhdl_file(self):
        """Add VHDL files to project (supports multiple file selection)."""
        logging.info("📁 Opening VHDL file selection dialog...")
        file_paths, _ = QFileDialog.getOpenFileNames(
            self, "Select VHDL Files", "", "VHDL Files (*.vhd *.vhdl);;All Files (*)"
        )
        
        if file_paths:
            logging.info(f"📄 User selected {len(file_paths)} VHDL file(s): {file_paths}")
            def add_files():
                try:
                    from cc_project_manager_pkg.hierarchy_manager import HierarchyManager
                    
                    # Find project configuration
                    project_config_path, project_dir = self.find_project_config()
                    
                    if not project_config_path:
                        raise Exception("No project configuration found. Please create a project first or navigate to a project directory.")
                    
                    logging.info(f"Found project configuration at: {project_config_path}")
                    logging.info(f"Project directory: {project_dir}")
                    logging.info(f"Current working directory: {os.getcwd()}")
                    
                    # Change to project directory temporarily
                    original_cwd = os.getcwd()
                    os.chdir(project_dir)
                    logging.info(f"Changed working directory to: {os.getcwd()}")
                    
                    try:
                        hierarchy = HierarchyManager()
                        
                        # Check if project is properly configured
                        if not hierarchy.config_path or not hierarchy.config:
                            raise Exception("Failed to load project configuration.")
                        
                        logging.info(f"HierarchyManager loaded project config: {hierarchy.config_path}")
                        
                        added_files = []
                        failed_files = []
                        
                        # Process each selected file
                        for file_path in file_paths:
                            try:
                                logging.info(f"Adding VHDL file: {file_path}")
                                
                                # Check if file exists
                                if not os.path.exists(file_path):
                                    raise FileNotFoundError(f"Source file does not exist: {file_path}")
                                
                                # Determine file type based on filename
                                file_name = os.path.basename(file_path)
                                if '_tb' in file_name.lower() or 'testbench' in file_name.lower():
                                    file_type = 'testbench'
                                elif '_top' in file_name.lower():
                                    file_type = 'top'
                                else:
                                    file_type = 'src'
                                
                                logging.info(f"🏷️ Detected file type: {file_type} for file: {file_name}")
                                
                                # Add file to project (copy to project)
                                logging.info(f"📋 Calling hierarchy.add_file with copy_to_project=True")
                                result_path = hierarchy.add_file(file_path, file_type, copy_to_project=True)
                                
                                logging.info(f"📁 File copied to: {result_path}")
                                
                                # Verify the file was actually copied
                                if os.path.exists(result_path):
                                    logging.info(f"✅ File successfully copied to project: {result_path}")
                                    added_files.append(f"{os.path.basename(result_path)} ({file_type})")
                                else:
                                    logging.warning(f"⚠️ File copy may have failed - destination not found: {result_path}")
                                    failed_files.append(f"{file_name} (copy failed)")
                                
                            except Exception as e:
                                logging.error(f"❌ Failed to add file {file_path}: {str(e)}")
                                failed_files.append(f"{os.path.basename(file_path)} ({str(e)})")
                        
                        # Store flag for project status refresh
                        self._pending_project_refresh = True
                        logging.info("🔄 Flagged project status for refresh after file addition")
                        
                        # Prepare result message
                        result_parts = []
                        if added_files:
                            result_parts.append(f"Successfully added {len(added_files)} file(s): {', '.join(added_files)}")
                        if failed_files:
                            result_parts.append(f"Failed to add {len(failed_files)} file(s): {', '.join(failed_files)}")
                        
                        if not added_files and failed_files:
                            raise Exception(f"Failed to add any files. Errors: {'; '.join(failed_files)}")
                        
                        return ". ".join(result_parts)
                        
                    finally:
                        # Always restore the original working directory
                        os.chdir(original_cwd)
                        logging.info(f"Restored working directory to: {os.getcwd()}")
                    
                except Exception as e:
                    import traceback
                    error_details = traceback.format_exc()
                    logging.error(f"Error adding VHDL files: {str(e)}")
                    logging.error(f"Full traceback: {error_details}")
                    raise Exception(f"Failed to add VHDL files: {str(e)}")
            
            # Update success message to reflect multiple files
            file_count = len(file_paths)
            success_msg = f"VHDL file{'s' if file_count > 1 else ''} added successfully"
            self.run_in_thread(add_files, success_msg=success_msg)
        else:
            logging.info("❌ User cancelled VHDL file selection")
    
    def remove_vhdl_file(self):
        """Remove selected VHDL file from project configuration (does not delete the source file)."""
        # Get the currently selected item from the project tree
        selected_items = self.files_tree.selectedItems()
        
        if not selected_items:
            logging.warning("❌ No file selected for removal")
            return
        
        selected_item = selected_items[0]
        
        # Check if the selected item is a file (has metadata) or a category folder
        file_data = selected_item.data(0, Qt.UserRole)
        if not file_data:
            logging.warning("❌ Selected item is not a file")
            return
        
        file_name = file_data["file_name"]
        category = file_data["category"]
        file_path = file_data["file_path"]
        
        logging.info(f"📄 User selected file for removal: {file_name} from {category} category")
        
        # Confirm removal with user
        reply = self.show_message(
            "Confirm Removal", 
            f"Remove '{file_name}' from the project?\n\n"
            f"Category: {category}\n"
            f"Path: {file_path}\n\n"
            f"Note: This will only remove the file from the project configuration.\n"
            f"The source file will NOT be deleted from disk.", 
            "question"
        )
        
        if not reply:
            logging.info("❌ User cancelled file removal")
            return
        
        def remove_file():
            try:
                logging.info(f"🗑️ Removing file '{file_name}' from project configuration...")
                
                from cc_project_manager_pkg.hierarchy_manager import HierarchyManager
                
                # Find project configuration
                project_config_path, project_dir = self.find_project_config()
                
                if not project_config_path:
                    raise Exception("No project configuration found. Please create a project first or navigate to a project directory.")
                
                logging.info(f"Found project configuration at: {project_config_path}")
                logging.info(f"Project directory: {project_dir}")
                
                # Change to project directory temporarily
                original_cwd = os.getcwd()
                os.chdir(project_dir)
                logging.info(f"Changed working directory to: {os.getcwd()}")
                
                try:
                    hierarchy = HierarchyManager()
                    
                    # Check if project is properly configured
                    if not hierarchy.config_path or not hierarchy.config:
                        raise Exception("Failed to load project configuration.")
                    
                    logging.info(f"HierarchyManager loaded project config: {hierarchy.config_path}")
                    
                    # Remove file from hierarchy (this only removes from config, not from disk)
                    result = hierarchy.remove_file_from_hierarchy(file_name)
                    
                    if result["removed"]:
                        logging.info(f"✅ Successfully removed '{file_name}' from {result['category']} category")
                        logging.info(f"📁 Source file remains at: {file_path}")
                        
                        # Store flag for project status refresh
                        self._pending_project_refresh = True
                        logging.info("🔄 Flagged project status for refresh after file removal")
                        
                        return f"File '{file_name}' removed from project {result['category']} category"
                    else:
                        logging.warning(f"⚠️ Failed to remove file: {result['message']}")
                        raise Exception(result['message'])
                        
                finally:
                    # Always restore the original working directory
                    os.chdir(original_cwd)
                    logging.info(f"Restored working directory to: {os.getcwd()}")
                
            except Exception as e:
                import traceback
                error_details = traceback.format_exc()
                logging.error(f"Error removing VHDL file: {str(e)}")
                logging.error(f"Full traceback: {error_details}")
                raise Exception(f"Failed to remove VHDL file: {str(e)}")
        
        self.run_in_thread(remove_file, success_msg=f"File '{file_name}' removed from project")
    
    def add_constraints_file(self):
        """Add constraints files to project (supports multiple file selection)."""
        logging.info("📁 Opening constraints file selection dialog...")
        file_paths, _ = QFileDialog.getOpenFileNames(
            self, "Select Constraints Files", "", "Constraints Files (*.ccf);;All Files (*)"
        )
        
        if file_paths:
            logging.info(f"📄 User selected {len(file_paths)} constraints file(s): {file_paths}")
            def add_constraints():
                try:
                    # Find project configuration
                    project_config_path, project_dir = self.find_project_config()
                    
                    if not project_config_path:
                        raise Exception("No project configuration found. Please create a project first or navigate to a project directory.")
                    
                    logging.info(f"Found project configuration at: {project_config_path}")
                    logging.info(f"Project directory: {project_dir}")
                    logging.info(f"Current working directory: {os.getcwd()}")
                    
                    # Change to project directory temporarily
                    original_cwd = os.getcwd()
                    os.chdir(project_dir)
                    logging.info(f"Changed working directory to: {os.getcwd()}")
                    
                    try:
                        from cc_project_manager_pkg.pnr_commands import PnRCommands
                        
                        # Initialize PnRCommands to get constraints directory
                        pnr = PnRCommands()
                        constraints_dir = pnr.constraints_dir
                        
                        logging.info(f"Constraints directory: {constraints_dir}")
                        
                        # Ensure constraints directory exists
                        if not os.path.exists(constraints_dir):
                            os.makedirs(constraints_dir, exist_ok=True)
                            logging.info(f"Created constraints directory: {constraints_dir}")
                        
                        added_files = []
                        failed_files = []
                        
                        # Process each selected file
                        for file_path in file_paths:
                            try:
                                logging.info(f"Adding constraints file: {file_path}")
                                
                                # Check if file exists
                                if not os.path.exists(file_path):
                                    raise FileNotFoundError(f"Source file does not exist: {file_path}")
                                
                                # Get file name
                                file_name = os.path.basename(file_path)
                                
                                # Check if it's a .ccf file
                                if not file_name.lower().endswith('.ccf'):
                                    logging.warning(f"⚠️ File {file_name} is not a .ccf file, but proceeding anyway")
                                
                                # Copy file to constraints directory
                                dest_file_path = os.path.join(constraints_dir, file_name)
                                
                                # Check if file already exists at destination
                                if os.path.exists(dest_file_path):
                                    logging.warning(f"File already exists at destination: {dest_file_path}")
                                    # For now, we'll overwrite. You can modify this behavior as needed
                                
                                import shutil
                                shutil.copy2(file_path, dest_file_path)
                                logging.info(f"📁 File copied to: {dest_file_path}")
                                
                                # Verify the file was actually copied
                                if os.path.exists(dest_file_path):
                                    logging.info(f"✅ File successfully copied to project: {dest_file_path}")
                                    added_files.append(file_name)
                                else:
                                    logging.warning(f"⚠️ File copy may have failed - destination not found: {dest_file_path}")
                                    failed_files.append(f"{file_name} (copy failed)")
                                
                            except Exception as e:
                                logging.error(f"❌ Failed to add file {file_path}: {str(e)}")
                                failed_files.append(f"{os.path.basename(file_path)} ({str(e)})")
                        
                        # Store flag for implementation status refresh
                        self._pending_implementation_refresh = True
                        logging.info("🔄 Flagged implementation status for refresh after constraints file addition")
                        
                        # Prepare result message
                        result_parts = []
                        if added_files:
                            result_parts.append(f"Successfully added {len(added_files)} constraints file(s): {', '.join(added_files)}")
                        if failed_files:
                            result_parts.append(f"Failed to add {len(failed_files)} file(s): {', '.join(failed_files)}")
                        
                        if not added_files and failed_files:
                            raise Exception(f"Failed to add any files. Errors: {'; '.join(failed_files)}")
                        
                        return ". ".join(result_parts)
                        
                    finally:
                        # Always restore the original working directory
                        os.chdir(original_cwd)
                        logging.info(f"Restored working directory to: {os.getcwd()}")
                    
                except Exception as e:
                    import traceback
                    error_details = traceback.format_exc()
                    logging.error(f"Error adding constraints files: {str(e)}")
                    logging.error(f"Full traceback: {error_details}")
                    raise Exception(f"Failed to add constraints files: {str(e)}")
            
            # Update success message to reflect multiple files
            file_count = len(file_paths)
            success_msg = f"Constraints file{'s' if file_count > 1 else ''} added successfully"
            self.run_in_thread(add_constraints, success_msg=success_msg)
        else:
            logging.info("❌ User cancelled constraints file selection")
    
    
    def remove_constraints_file(self):
        """Remove selected constraints file from project (does not delete the source file)."""
        # Get the currently selected item from the implementation tree
        selected_items = self.implementation_tree.selectedItems()
        
        if not selected_items:
            logging.warning("❌ No constraint file selected for removal")
            logging.warning("   Please select a constraints file from the 'Constraint Files' section in the Design/File container")
            return
        
        selected_item = selected_items[0]
        
        # Check if the selected item is a constraint file
        # Constraint files are children of the "Constraint Files" parent item
        parent_item = selected_item.parent()
        if not parent_item or parent_item.text(0) != "Constraint Files":
            logging.warning("❌ Selected item is not a constraints file")
            logging.warning("   Please select a constraints file from the 'Constraint Files' section in the Design/File container")
            return
        
        file_name = selected_item.text(0)
        file_type = selected_item.text(1)  # Should be "Constraint"
        file_status = selected_item.text(2)  # Status like "✅ Available"
        
        logging.info(f"📄 Starting removal of constraints file: {file_name}")
        logging.info(f"   Type: {file_type}, Status: {file_status}")
        logging.info(f"   Note: File will be moved to backup location, not deleted")
        
        def remove_constraints():
            try:
                logging.info(f"🗑️ Removing constraints file '{file_name}' from project...")
                
                from cc_project_manager_pkg.pnr_commands import PnRCommands
                
                # Find project configuration
                project_config_path, project_dir = self.find_project_config()
                
                if not project_config_path:
                    raise Exception("No project configuration found. Please create a project first or navigate to a project directory.")
                
                logging.info(f"Found project configuration at: {project_config_path}")
                logging.info(f"Project directory: {project_dir}")
                
                # Change to project directory temporarily
                original_cwd = os.getcwd()
                os.chdir(project_dir)
                logging.info(f"Changed working directory to: {os.getcwd()}")
                
                try:
                    # Initialize PnRCommands to get constraints directory
                    pnr = PnRCommands()
                    constraints_dir = pnr.constraints_dir
                    
                    logging.info(f"Constraints directory: {constraints_dir}")
                    
                    # Build full path to the constraints file
                    file_path = os.path.join(constraints_dir, file_name)
                    
                    # Check if file exists
                    if not os.path.exists(file_path):
                        raise FileNotFoundError(f"Constraints file does not exist: {file_path}")
                    
                    logging.info(f"Found constraints file at: {file_path}")
                    
                    # Create backup directory in project root
                    backup_dir = os.path.join(project_dir, "removed_constraints")
                    if not os.path.exists(backup_dir):
                        os.makedirs(backup_dir, exist_ok=True)
                        logging.info(f"Created backup directory: {backup_dir}")
                    
                    # Move file to backup location instead of deleting
                    import shutil
                    backup_file_path = os.path.join(backup_dir, file_name)
                    
                    # Handle duplicate names by adding a timestamp
                    if os.path.exists(backup_file_path):
                        import time
                        timestamp = time.strftime("%Y%m%d_%H%M%S")
                        name, ext = os.path.splitext(file_name)
                        backup_file_path = os.path.join(backup_dir, f"{name}_{timestamp}{ext}")
                    
                    shutil.move(file_path, backup_file_path)
                    logging.info(f"📁 File moved to backup: {backup_file_path}")
                    
                    # Verify the file was actually moved
                    if os.path.exists(file_path):
                        raise Exception(f"File removal may have failed - file still exists: {file_path}")
                    
                    if not os.path.exists(backup_file_path):
                        raise Exception(f"File backup may have failed - backup not found: {backup_file_path}")
                    
                    logging.info(f"✅ Successfully removed constraints file: {file_name}")
                    
                    # Store flag for implementation status refresh
                    self._pending_implementation_refresh = True
                    logging.info("🔄 Flagged implementation status for refresh after constraints file removal")
                    
                    return f"Constraints file '{file_name}' moved to backup location: {backup_file_path}"
                    
                finally:
                    # Always restore the original working directory
                    os.chdir(original_cwd)
                    logging.info(f"Restored working directory to: {os.getcwd()}")
                
            except Exception as e:
                import traceback
                error_details = traceback.format_exc()
                logging.error(f"Error removing constraints file: {str(e)}")
                logging.error(f"Full traceback: {error_details}")
                raise Exception(f"Failed to remove constraints file: {str(e)}")
        
        self.run_in_thread(remove_constraints, success_msg=f"Constraints file '{file_name}' removed from project")

    def view_project_logs(self):
        """View project manager logs."""
        logging.info("Opening project manager logs...")
        
        try:
            # Get the project manager log file path
            # The log file is typically in the project root or logs directory
            from cc_project_manager_pkg.hierarchy_manager import HierarchyManager
            hierarchy = HierarchyManager()
            
            if not hierarchy.config_path or not os.path.exists(hierarchy.config_path):
                self.show_message("Error", "No project configuration found. Please create or load a project first.", "error")
                return
            
            # Load project configuration to find log directory
            import yaml
            with open(hierarchy.config_path, 'r') as f:
                config = yaml.safe_load(f)
            
            # Look for project manager log file
            project_log_path = None
            
            # Check common log file locations
            project_root = os.path.dirname(hierarchy.config_path)
            possible_log_paths = [
                os.path.join(project_root, "logs", "project_manager.log"),
                os.path.join(project_root, "project_manager.log"),
                os.path.join(project_root, "logs", "cc_project_manager.log"),
                os.path.join(project_root, "cc_project_manager.log")
            ]
            
            # Also check logs section in config (nested structure)
            logs_section = config.get("logs", {})
            if isinstance(logs_section, dict):
                for log_category, log_files in logs_section.items():
                    if isinstance(log_files, dict) and ("project" in log_category.lower() or "manager" in log_category.lower()):
                        # Look for project manager log files in the nested structure
                        for log_filename, log_path in log_files.items():
                            if isinstance(log_path, str) and ("project" in log_filename.lower() or "manager" in log_filename.lower()):
                                if os.path.exists(log_path):
                                    possible_log_paths.insert(0, log_path)  # Prioritize config-specified paths
            
            # Find the first existing log file
            for log_path in possible_log_paths:
                if os.path.exists(log_path):
                    project_log_path = log_path
                    break
            
            if not project_log_path:
                self.show_message("Info", 
                    "No project manager logs found yet.\n\n"
                    "Project logs will be available after performing project operations.\n"
                    "The logs contain detailed output from project management including:\n"
                    "• Project creation and loading operations\n"
                    "• File addition and removal activities\n"
                    "• Configuration changes and updates\n"
                    "• Error messages and warnings\n"
                    "• Project structure modifications", "info")
                return
            
            # Create and show log viewer dialog
            self._show_project_log_dialog(project_log_path)
            
        except Exception as e:
            logging.error(f"Error accessing project logs: {e}")
            self.show_message("Error", f"Error accessing project logs: {str(e)}", "error")

    def _show_project_log_dialog(self, log_file_path):
        """Show project log viewer dialog."""
        dialog = QDialog(self)
        dialog.setWindowTitle("Project Logs - Manager Commands & Operations")
        dialog.setModal(True)
        dialog.resize(1200, 800)  # Larger window for better viewing
        
        layout = QVBoxLayout(dialog)
        
        # Header with file info and search
        header_layout = QHBoxLayout()
        
        file_info_label = QLabel(f"📄 Log File: {os.path.basename(log_file_path)}")
        file_info_label.setStyleSheet("font-weight: bold; color: #64b5f6; font-size: 12px;")
        header_layout.addWidget(file_info_label)
        
        header_layout.addStretch()
        
        # Search functionality
        search_label = QLabel("🔍 Find:")
        search_label.setStyleSheet("color: #ffffff; font-size: 11px;")
        header_layout.addWidget(search_label)
        
        search_input = QLineEdit()
        search_input.setPlaceholderText("Search for project operations, errors, etc.")
        search_input.setMaximumWidth(250)
        search_input.setStyleSheet("""
            QLineEdit {
                background-color: #2d2d2d;
                color: #ffffff;
                border: 1px solid #555;
                padding: 4px;
                border-radius: 3px;
            }
        """)
        header_layout.addWidget(search_input)
        
        # Quick search buttons
        find_commands_btn = QPushButton("Find Project Operations")
        find_commands_btn.setMinimumWidth(180)
        find_commands_btn.setMaximumWidth(180)
        find_commands_btn.setStyleSheet("background-color: #4caf50; color: #ffffff; font-weight: bold;")
        header_layout.addWidget(find_commands_btn)
        
        # Refresh button
        refresh_btn = QPushButton("🔄 Refresh")
        refresh_btn.setMinimumWidth(110)
        refresh_btn.setMaximumWidth(110)
        header_layout.addWidget(refresh_btn)
        
        # Save button
        save_btn = QPushButton("💾 Save")
        save_btn.setMinimumWidth(100)
        save_btn.setMaximumWidth(100)
        header_layout.addWidget(save_btn)
        
        # Clear log button
        clear_btn = QPushButton("🗑️ Clear Log")
        clear_btn.setMinimumWidth(120)
        clear_btn.setMaximumWidth(120)
        clear_btn.setStyleSheet("background-color: #ff4757; color: #ffffff; font-weight: bold;")
        header_layout.addWidget(clear_btn)
        
        layout.addLayout(header_layout)
        
        # Log content area
        log_text_widget = QTextEdit()
        log_text_widget.setReadOnly(True)
        log_text_widget.setFont(QFont("Consolas", 9))
        log_text_widget.setStyleSheet("""
            QTextEdit {
                background-color: #1e1e1e;
                color: #ffffff;
                border: 1px solid #555;
                selection-background-color: #3399ff;
            }
        """)
        
        # Load and display log content
        self._refresh_project_log_content(log_text_widget, log_file_path)
        
        # Connect buttons and search functionality
        refresh_btn.clicked.connect(lambda: self._refresh_project_log_content(log_text_widget, log_file_path))
        save_btn.clicked.connect(lambda: self._save_log_content(log_text_widget))
        clear_btn.clicked.connect(lambda: self._clear_project_log(log_text_widget, log_file_path))
        
        # Search functionality
        def perform_search():
            search_text = search_input.text().strip()
            if search_text:
                self._search_in_text_widget(log_text_widget, search_text)
        
        def find_project_operations():
            # Search for common project operation patterns
            patterns = ["Project", "VHDL", "Created", "Added", "Removed", "Loading"]
            for pattern in patterns:
                if self._search_in_text_widget(log_text_widget, pattern):
                    search_input.setText(pattern)
                    break
        
        search_input.returnPressed.connect(perform_search)
        find_commands_btn.clicked.connect(find_project_operations)
        
        layout.addWidget(log_text_widget)
        
        # Status bar
        status_layout = QHBoxLayout()
        
        file_size_label = QLabel()
        try:
            file_size = os.path.getsize(log_file_path)
            if file_size < 1024:
                size_str = f"{file_size} bytes"
            elif file_size < 1024 * 1024:
                size_str = f"{file_size / 1024:.1f} KB"
            else:
                size_str = f"{file_size / (1024 * 1024):.1f} MB"
            file_size_label.setText(f"📊 Size: {size_str}")
        except:
            file_size_label.setText("📊 Size: Unknown")
        
        file_size_label.setStyleSheet("color: #888; font-size: 11px;")
        status_layout.addWidget(file_size_label)
        
        status_layout.addStretch()
        
        # Close button
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(dialog.accept)
        status_layout.addWidget(close_btn)
        
        layout.addLayout(status_layout)
        
        dialog.exec_()

    def _refresh_project_log_content(self, text_widget, log_file_path):
        """Refresh project log content in the text widget."""
        try:
            # Try multiple encodings to handle project manager output
            content = None
            encodings_to_try = ['utf-8', 'latin-1', 'cp1252', 'iso-8859-1']
            
            for encoding in encodings_to_try:
                try:
                    with open(log_file_path, 'r', encoding=encoding) as f:
                        content = f.read()
                    break  # Success, stop trying other encodings
                except UnicodeDecodeError:
                    continue  # Try next encoding
            
            if content is None:
                # If all encodings fail, read as binary and decode with error handling
                with open(log_file_path, 'rb') as f:
                    raw_content = f.read()
                content = raw_content.decode('utf-8', errors='replace')
            
            # Apply syntax highlighting for better readability
            formatted_content = self._format_project_log(content)
            text_widget.setHtml(formatted_content)
            
            # Scroll to top to show commands from the beginning
            cursor = text_widget.textCursor()
            cursor.movePosition(cursor.Start)
            text_widget.setTextCursor(cursor)
            text_widget.ensureCursorVisible()
            
        except Exception as e:
            text_widget.setPlainText(f"Error reading log file: {str(e)}")

    def _format_project_log(self, content):
        """Format project log content with enhanced syntax highlighting."""
        if not content:
            return "<p style='color: #888;'>No log content available.</p>"
        
        # Show all content - no truncation to allow full scrolling
        # For very large files (>1MB), show warning but still load all content
        if len(content) > 1024 * 1024:  # 1MB limit
            content = f"WARNING: Large log file ({len(content)} bytes) - loading may be slow\n\n{content}"
        
        # Split into lines and apply formatting
        lines = content.split('\n')
        formatted_lines = []
        
        for line in lines:
            line = line.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            
            # Enhanced color coding with project operation highlighting
            if ' - ERROR - ' in line or 'ERROR:' in line:
                formatted_lines.append(f'<span style="color: #ff6b6b; font-weight: bold;">{line}</span>')
            elif ' - WARNING - ' in line or 'WARNING:' in line:
                formatted_lines.append(f'<span style="color: #ffd93d;">{line}</span>')
            elif ' - INFO - ' in line or 'INFO:' in line:
                formatted_lines.append(f'<span style="color: #6bcf7f;">{line}</span>')
            elif ' - DEBUG - ' in line or 'DEBUG:' in line:
                formatted_lines.append(f'<span style="color: #74c0fc;">{line}</span>')
            # Highlight project operations - this is what you want to see!
            elif 'Project created:' in line or 'Creating project' in line or 'New project' in line:
                formatted_lines.append(f'<span style="color: #4caf50; font-weight: bold; background-color: #1b2e1b;">{line}</span>')
            elif 'VHDL file added:' in line or 'Adding VHDL' in line or 'File added' in line:
                formatted_lines.append(f'<span style="color: #2196f3; font-weight: bold; background-color: #1a2332;">{line}</span>')
            elif 'VHDL file removed:' in line or 'Removing VHDL' in line or 'File removed' in line:
                formatted_lines.append(f'<span style="color: #ff9800; font-weight: bold; background-color: #2e1f0e;">{line}</span>')
            elif 'Project loaded:' in line or 'Loading project' in line or 'Project found' in line:
                formatted_lines.append(f'<span style="color: #9c27b0; font-weight: bold; background-color: #2a1b2e;">{line}</span>')
            elif 'successful' in line.lower() or 'completed' in line.lower():
                formatted_lines.append(f'<span style="color: #51cf66; font-weight: bold;">{line}</span>')
            elif 'failed' in line.lower() or 'error' in line.lower():
                formatted_lines.append(f'<span style="color: #ff6b6b; font-weight: bold;">{line}</span>')
            elif line.startswith('=== ') or '=' * 20 in line:
                formatted_lines.append(f'<span style="color: #ffd43b; font-weight: bold;">{line}</span>')
            # Highlight configuration changes
            elif 'config' in line.lower() and ('updated' in line.lower() or 'changed' in line.lower()):
                formatted_lines.append(f'<span style="color: #da77f2; font-weight: bold;">{line}</span>')
            # Highlight file paths and directories
            elif '.vhd' in line.lower() or '.vhdl' in line.lower():
                formatted_lines.append(f'<span style="color: #81c784;">{line}</span>')
            else:
                formatted_lines.append(f'<span style="color: #ffffff;">{line}</span>')
        
        return f'<pre style="font-family: Consolas, monospace; font-size: 9pt; line-height: 1.2;">{"<br>".join(formatted_lines)}</pre>'

    def _clear_project_log(self, text_widget, log_file_path):
        """Clear the project log file and refresh the display."""
        try:
            # Ask for confirmation before clearing
            from PyQt5.QtWidgets import QMessageBox
            reply = QMessageBox.question(
                text_widget.parent(),
                "Clear Project Log",
                "Are you sure you want to clear the project log file?\n\n"
                "This will permanently delete all project operation history.\n"
                "This action cannot be undone.",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            
            if reply == QMessageBox.Yes:
                # Clear the log file by writing empty content
                with open(log_file_path, 'w', encoding='utf-8') as f:
                    f.write("")
                
                # Clear the text widget display
                text_widget.clear()
                text_widget.setPlainText("Project log has been cleared.\n\nNew project operations will be logged here.")
                
                # Log the action
                logging.info("🗑️ Project log file cleared successfully")
                
        except Exception as e:
            logging.error(f"❌ Error clearing project log: {e}")
            # Show error message
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.critical(
                text_widget.parent(),
                "Error Clearing Log",
                f"Failed to clear the project log file:\n\n{str(e)}"
            )

    def view_project_status(self):
        """View project status."""
        logging.info("Refreshing project status display...")
        self.refresh_project_status()
    
    def find_project_config(self, search_dir=None):
        """Find project configuration file in the given directory or current working directory.
        
        Args:
            search_dir: Directory to search in (default: current working directory)
            
        Returns:
            tuple: (project_config_path, project_dir) or (None, None) if not found
        """
        if search_dir is None:
            search_dir = os.getcwd()
        
        # Check root directory first
        try:
            for file in os.listdir(search_dir):
                if file.endswith('_project_config.yml'):
                    return os.path.join(search_dir, file), search_dir
        except OSError:
            pass
        
        # Check config subdirectory
        config_subdir = os.path.join(search_dir, 'config')
        if os.path.exists(config_subdir):
            try:
                for file in os.listdir(config_subdir):
                    if file.endswith('_project_config.yml'):
                        return os.path.join(config_subdir, file), search_dir
            except OSError:
                pass
        
        # Walk subdirectories as last resort
        try:
            for root, dirs, files in os.walk(search_dir):
                for file in files:
                    if file.endswith('_project_config.yml'):
                        if os.path.basename(root) == 'config':
                            return os.path.join(root, file), os.path.dirname(root)
                        else:
                            return os.path.join(root, file), root
        except OSError:
            pass
        
        return None, None

    def load_existing_project(self):
        """Load an existing project from a directory."""
        logging.info("📁 Opening project directory selection dialog to load existing project...")
        project_dir = QFileDialog.getExistingDirectory(
            self, "Select Existing Project Directory", "", QFileDialog.ShowDirsOnly
        )
        
        if project_dir:
            logging.info(f"📂 User selected project directory: {project_dir}")
            # Use helper function to find project config
            project_config_path, found_project_dir = self.find_project_config(project_dir)
            
            # Also check if this looks like a project directory by checking for typical project structure
            project_indicators = ['src', 'testbench', 'build', 'logs', 'constraints']
            has_project_structure = any(os.path.exists(os.path.join(project_dir, indicator)) for indicator in project_indicators)
            
            if project_config_path or has_project_structure:
                logging.info(f"✅ Valid project found - loading project: {os.path.basename(project_dir)}")
                os.chdir(project_dir)
                logging.info(f"🔄 Working directory changed to: {project_dir}")
                
                # Save this project as the most recent
                self.save_recent_project_path(project_dir)
                self.current_project_path = project_dir
                
                logging.info("🔄 Refreshing all tab statuses after loading project...")
                
                # Refresh all tabs to ensure they recognize the new project
                self.refresh_project_status()
                QTimer.singleShot(300, self.refresh_synthesis_status)
                QTimer.singleShot(400, self.refresh_implementation_status)
                QTimer.singleShot(500, self.refresh_simulation_status)
                
                if project_config_path:
                    logging.info(f"✅ Project successfully loaded: {os.path.basename(project_dir)}")
                else:
                    logging.info(f"✅ Project loaded (detected by structure): {os.path.basename(project_dir)}")
            else:
                logging.warning(f"❌ No valid project found in: {project_dir}")
        else:
            logging.info("❌ User cancelled project loading")
    
    def detect_manual_files(self):
        """Detect manually added files."""
        def detect_files():
            logging.info("Detecting manually added files...")
            from cc_project_manager_pkg.hierarchy_manager import HierarchyManager
            hierarchy = HierarchyManager()
            detected_files = hierarchy.detect_manual_files()
            
            # Count total detected files
            total_detected = sum(len(files) for files in detected_files.values())
            
            if total_detected == 0:
                return "No untracked files found - all VHDL files are already tracked"
            
            # Add detected files automatically
            added_summary = hierarchy.add_detected_files(detected_files, ["src", "testbench", "top"])
            
            # Store flag for project status refresh (will be handled by on_operation_finished)
            self._pending_project_refresh = True
            logging.info("🔄 Flagged project status for refresh after file detection")
            
            return f"Detected and added {added_summary['total']} files: {added_summary['src']} source, {added_summary['testbench']} testbench, {added_summary['top']} top-level"
        
        self.run_in_thread(detect_files, success_msg="File detection completed")
    
    # Synthesis Methods
    def run_synthesis(self):
        """Run synthesis on the selected entity from the synthesis tree."""
        # Check if an entity is selected in the synthesis tree
        selected_items = self.synthesis_tree.selectedItems()
        if not selected_items:
            logging.warning("No entity selected for synthesis")
            self.show_message("Selection Required", 
                            "Please select an entity from the Entity/Design tree to synthesize.", 
                            "warning")
            return
        
        selected_item = selected_items[0]
        
        # Check if it's an entity (not a parent category)
        if not selected_item.parent():
            logging.warning("Please select a specific entity, not a category")
            self.show_message("Invalid Selection", 
                            "Please select a specific entity from the tree, not a category.", 
                            "warning")
            return
        
        entity_name = selected_item.text(0)
        logging.info(f"🔄 Opening synthesis dialog for entity: {entity_name}")
        
        # Get current synthesis configuration
        try:
            synth_config = self._get_synthesis_configuration()
        except Exception:
            synth_config = {}
        
        # Create synthesis strategy dialog
        dialog = SynthesisStrategyDialog(self, entity_name, synth_config)
        if dialog.exec_() == QDialog.Accepted:
            synthesis_params = dialog.get_synthesis_params()
            
            def synthesis_operation():
                try:
                    # Enhanced logging with comprehensive synthesis information
                    logging.info("=" * 80)
                    logging.info("🔄 SYNTHESIS OPERATION STARTED")
                    logging.info("=" * 80)
                    
                    # Find source file for the entity
                    source_file = self._find_entity_source_file(entity_name)
                    if source_file:
                        logging.info(f"📁 Entity: {entity_name}")
                        logging.info(f"📄 Source File: {source_file}")
                    else:
                        logging.warning(f"⚠️  Entity: {entity_name} (source file not found)")
                    
                    # Get VHDL standard, IEEE library, and custom options from current config
                    try:
                        synth_config = self._get_synthesis_configuration()
                        vhdl_standard = synth_config.get('vhdl_standard', 'VHDL-2008')
                        ieee_library = synth_config.get('ieee_library', 'synopsys')
                        custom_yosys_options = synth_config.get('custom_yosys_options', [])
                    except Exception:
                        vhdl_standard = 'VHDL-2008'
                        ieee_library = 'synopsys'
                        custom_yosys_options = []
                    
                    # Get custom strategy options if using a custom strategy
                    strategy_custom_options = self._get_custom_strategy_options(synthesis_params['strategy'])
                    if strategy_custom_options:
                        custom_yosys_options.extend(strategy_custom_options)
                        logging.info(f"   • Custom Strategy Options: {' '.join(strategy_custom_options)}")
                    
                    # Log synthesis settings
                    logging.info("⚙️  SYNTHESIS SETTINGS:")
                    logging.info(f"   • Strategy: {synthesis_params['strategy'].upper()}")
                    logging.info(f"   • Target: {'GateMate FPGA' if synthesis_params['use_gatemate'] else 'Generic FPGA'}")
                    logging.info(f"   • VHDL Standard: {vhdl_standard}")
                    logging.info(f"   • IEEE Library: {ieee_library}")
                    if custom_yosys_options:
                        logging.info(f"   • Custom Yosys Options: {' '.join(custom_yosys_options)}")
                    else:
                        logging.info("   • Custom Yosys Options: None")
                    
                    # Get all VHDL files for logging
                    vhdl_files = self._get_project_vhdl_files()
                    if vhdl_files:
                        logging.info(f"📚 VHDL Files in Project ({len(vhdl_files)} files):")
                        for i, vhdl_file in enumerate(vhdl_files, 1):
                            file_name = os.path.basename(vhdl_file)
                            logging.info(f"   {i}. {file_name}")
                    
                    logging.info("-" * 80)
                    logging.info("🛠️  INITIALIZING YOSYS SYNTHESIZER...")
                    
                    from cc_project_manager_pkg.yosys_commands import YosysCommands
                    yosys = YosysCommands(
                        strategy=synthesis_params['strategy'],
                        vhdl_std=vhdl_standard,
                        ieee_lib=ieee_library
                    )
                    
                    # Log the exact command that will be executed
                    logging.info("🔧 YOSYS COMMAND PREPARATION:")
                    try:
                        # Get the command that would be executed
                        command_info = self._get_yosys_command_preview(yosys, entity_name, synthesis_params['use_gatemate'], custom_yosys_options)
                        logging.info(f"   Command: {command_info['command']}")
                        logging.info(f"   Working Directory: {command_info['work_dir']}")
                        logging.info(f"   Output Files:")
                        for output_file in command_info['output_files']:
                            logging.info(f"     • {output_file}")
                    except Exception as e:
                        logging.warning(f"Could not preview command: {e}")
                    
                    logging.info("-" * 80)
                    logging.info("🚀 EXECUTING SYNTHESIS...")
                    
                    if synthesis_params['use_gatemate']:
                        logging.info("   Using GateMate-specific synthesis flow")
                        success = yosys.synthesize_gatemate(entity_name, options=custom_yosys_options)
                    else:
                        logging.info("   Using generic synthesis flow")
                        success = yosys.synthesize(entity_name, options=custom_yosys_options)
                    
                    if success:
                        logging.info("✅ SYNTHESIS COMPLETED SUCCESSFULLY!")
                        logging.info(f"   Entity '{entity_name}' synthesized with '{synthesis_params['strategy']}' strategy")
                        
                        # Store synthesis info for the entity
                        self._store_synthesis_result(entity_name, synthesis_params['strategy'], 
                                                   synthesis_params['use_gatemate'])
                        
                        # Log output files
                        output_files = self._check_synthesis_outputs(entity_name, synthesis_params['use_gatemate'])
                        if output_files:
                            logging.info("📁 Generated Output Files:")
                            for output_file in output_files:
                                if os.path.exists(output_file):
                                    file_size = os.path.getsize(output_file)
                                    logging.info(f"   ✅ {os.path.basename(output_file)} ({file_size} bytes)")
                                else:
                                    logging.warning(f"   ❌ {os.path.basename(output_file)} (not found)")
                        
                        logging.info("=" * 80)
                        return f"✅ Successfully synthesized {entity_name} with {synthesis_params['strategy']} strategy!"
                    else:
                        logging.error("❌ SYNTHESIS FAILED!")
                        logging.error(f"   Entity '{entity_name}' synthesis unsuccessful")
                        
                        # Check for path-related issues in the logs
                        try:
                            # Get logs directory from project configuration
                            logs_dir = yosys.config["project_structure"]["logs"][0] if isinstance(yosys.config["project_structure"]["logs"], list) else yosys.config["project_structure"]["logs"]
                            yosys_log_path = os.path.join(logs_dir, "yosys_commands.log")
                            if os.path.exists(yosys_log_path):
                                # Read the last 100 lines of the Yosys log to get the error details
                                with open(yosys_log_path, 'r', encoding='utf-8', errors='ignore') as f:
                                    lines = f.readlines()
                                    recent_lines = lines[-100:] if len(lines) > 100 else lines
                                    recent_log = ''.join(recent_lines)
                                    
                                    # Check for path with spaces error
                                    if "PATH WITH SPACES DETECTED" in recent_log:
                                        path_error_msg = "❌ PATH WITH SPACES DETECTED\n\n"
                                        path_error_msg += "Synthesis failed because your project path contains spaces.\n"
                                        path_error_msg += "GHDL/Yosys has issues with file paths that contain spaces.\n\n"
                                        path_error_msg += "SOLUTIONS:\n"
                                        path_error_msg += "1. Move your project to a path without spaces\n"
                                        path_error_msg += "   Example: C:\\Projects\\MyProject instead of C:\\My Projects\\MyProject\n"
                                        path_error_msg += "2. Rename directories to remove spaces\n"
                                        path_error_msg += "   Example: 'New folder' → 'NewFolder' or 'New_folder'\n"
                                        path_error_msg += "3. Use underscores or hyphens instead of spaces\n"
                                        path_error_msg += "4. Avoid placing projects in Desktop or Documents folders with spaces\n\n"
                                        path_error_msg += "RECOMMENDED PROJECT LOCATIONS:\n"
                                        path_error_msg += "• C:\\Projects\\\n"
                                        path_error_msg += "• C:\\FPGA_Projects\\\n"
                                        path_error_msg += "• C:\\Development\\\n"
                                        path_error_msg += "• D:\\Projects\\ (if you have a D: drive)"
                                        
                                        logging.error(path_error_msg)
                                        raise Exception(path_error_msg)
                                    elif "unexpected extension for file" in recent_log.lower() or "cannot find entity" in recent_log.lower():
                                        # Generic path issue
                                        path_error_msg = "❌ FILE PATH ISSUE DETECTED\n\n"
                                        path_error_msg += "Synthesis failed due to file path issues.\n"
                                        path_error_msg += "This commonly occurs with paths containing spaces or special characters.\n\n"
                                        path_error_msg += "SOLUTIONS:\n"
                                        path_error_msg += "1. Check that all VHDL files exist and are readable\n"
                                        path_error_msg += "2. Avoid file paths with spaces or special characters\n"
                                        path_error_msg += "3. Move project to a simpler path (e.g., C:\\Projects\\)\n"
                                        path_error_msg += "4. Check file permissions\n\n"
                                        path_error_msg += "Check the Synthesis Logs tab for detailed error information."
                                        
                                        logging.error(path_error_msg)
                                        raise Exception(path_error_msg)
                        except Exception as log_error:
                            if "PATH WITH SPACES" in str(log_error) or "FILE PATH ISSUE" in str(log_error):
                                raise  # Re-raise path-related errors
                            else:
                                logging.warning(f"Could not read Yosys logs for detailed error: {log_error}")
                        
                        logging.error("   Check Yosys logs for detailed error information")
                        logging.info("=" * 80)
                        raise Exception(f"Failed to synthesize {entity_name}. Check synthesis logs for details.")
                        
                except Exception as e:
                    logging.error("💥 SYNTHESIS OPERATION FAILED!")
                    logging.error(f"   Error: {e}")
                    logging.info("=" * 80)
                    raise e
            
            self.run_in_thread(synthesis_operation, success_msg="Synthesis completed successfully")
    
    def _store_synthesis_result(self, entity_name, strategy, use_gatemate):
        """Store synthesis result information for display in the tree."""
        try:
            # Get or create synthesis results file
            from cc_project_manager_pkg.toolchain_manager import ToolChainManager
            tcm = ToolChainManager()
            config_dir = tcm.config["project_structure"]["config"][0] if isinstance(tcm.config["project_structure"]["config"], list) else tcm.config["project_structure"]["config"]
            
            synthesis_results_path = os.path.join(config_dir, "synthesis_results.yml")
            
            # Load existing results or create new
            synthesis_results = {}
            if os.path.exists(synthesis_results_path):
                import yaml
                with open(synthesis_results_path, 'r') as f:
                    synthesis_results = yaml.safe_load(f) or {}
            
            # Store the result
            synthesis_results[entity_name] = {
                'strategy': strategy,
                'use_gatemate': use_gatemate,
                'timestamp': time.strftime('%Y-%m-%d %H:%M:%S')
            }
            
            # Save results
            import yaml
            with open(synthesis_results_path, 'w') as f:
                yaml.dump(synthesis_results, f, default_flow_style=False)
                
            logging.info(f"Stored synthesis result for {entity_name}: {strategy} strategy")
            
        except Exception as e:
            logging.warning(f"Failed to store synthesis result: {e}")
    
    def _load_synthesis_results(self):
        """Load synthesis results from the results file."""
        try:
            from cc_project_manager_pkg.toolchain_manager import ToolChainManager
            tcm = ToolChainManager()
            config_dir = tcm.config["project_structure"]["config"][0] if isinstance(tcm.config["project_structure"]["config"], list) else tcm.config["project_structure"]["config"]
            
            synthesis_results_path = os.path.join(config_dir, "synthesis_results.yml")
            
            if os.path.exists(synthesis_results_path):
                import yaml
                with open(synthesis_results_path, 'r') as f:
                    return yaml.safe_load(f) or {}
            
            return {}
            
        except Exception as e:
            logging.warning(f"Failed to load synthesis results: {e}")
            return {}
    
    def configure_synthesis(self):
        """Configure synthesis settings."""
        # Load current config
        try:
            current_config = self._get_synthesis_configuration()
        except Exception as e:
            logging.error(f"Failed to load synthesis configuration: {e}")
            current_config = {
                "strategy": "balanced",
                "vhdl_standard": "VHDL-2008",
                "ieee_library": "synopsys",
                "default_target": "GateMate FPGA"
            }
        
        dialog = SynthesisConfigDialog(self, current_config)
        if dialog.exec_() == QDialog.Accepted:
            config = dialog.get_config()
            # Save the configuration
            if self._save_synthesis_configuration(config):
                logging.info(f"✅ Synthesis configuration updated: {config}")
            else:
                logging.error("❌ Failed to save synthesis configuration")
    
    def configure_custom_strategy(self):
        """Configure custom synthesis strategy."""
        try:
            dialog = CustomStrategyDialog(self)
            if dialog.exec_() == QDialog.Accepted:
                strategy_name, strategy_data = dialog.get_strategy_data()
                
                if strategy_name and strategy_data:
                    # Save the custom strategy to synthesis_options.yml
                    if self._save_custom_strategy(strategy_name, strategy_data):
                        logging.info(f"✅ Custom strategy '{strategy_name}' saved successfully")
                        self.show_message("Success", f"Custom strategy '{strategy_name}' has been saved and is now available in Run Synthesis.", "info")
                    else:
                        logging.error(f"❌ Failed to save custom strategy '{strategy_name}'")
                        self.show_message("Error", f"Failed to save custom strategy '{strategy_name}'", "error")
                    
        except Exception as e:
            logging.error(f"Error configuring custom strategy: {e}")
            self.show_message("Error", f"Error configuring custom strategy: {e}", "error")
    
    def _save_custom_strategy(self, strategy_name, strategy_data):
        """Save a custom strategy to synthesis_options.yml file.
        
        Args:
            strategy_name: Name of the custom strategy
            strategy_data: Dictionary containing strategy configuration
            
        Returns:
            bool: True if saved successfully, False otherwise
        """
        try:
            from cc_project_manager_pkg.toolchain_manager import ToolChainManager
            import yaml
            
            tcm = ToolChainManager()
            
            # Get synthesis options file path
            setup_files = tcm.config.get("setup_files_initial", {})
            if "synthesis_options_file" in setup_files:
                synthesis_options_path = setup_files["synthesis_options_file"][0]
            else:
                # Fallback to config directory
                config_dir = tcm.config.get("project_structure", {}).get("config", [])
                if isinstance(config_dir, list) and config_dir:
                    synthesis_options_path = os.path.join(config_dir[0], "synthesis_options.yml")
                else:
                    synthesis_options_path = os.path.join(config_dir, "synthesis_options.yml")
            
            # Load existing synthesis options
            if os.path.exists(synthesis_options_path):
                with open(synthesis_options_path, 'r') as f:
                    synthesis_options = yaml.safe_load(f)
            else:
                # Create basic structure if file doesn't exist
                synthesis_options = {
                    'synthesis_defaults': {
                        'strategy': 'balanced',
                        'vhdl_standard': 'VHDL-2008',
                        'ieee_library': 'synopsys'
                    },
                    'synthesis_strategies': {}
                }
            
            # Ensure synthesis_strategies section exists
            if 'synthesis_strategies' not in synthesis_options:
                synthesis_options['synthesis_strategies'] = {}
            
            # Check if strategy already exists
            if strategy_name in synthesis_options['synthesis_strategies']:
                # Ask user if they want to overwrite
                from PyQt5.QtWidgets import QMessageBox
                reply = QMessageBox.question(
                    self, 
                    "Strategy Exists", 
                    f"Strategy '{strategy_name}' already exists. Do you want to overwrite it?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No
                )
                if reply != QMessageBox.Yes:
                    return False
            
            # Add the custom strategy
            synthesis_options['synthesis_strategies'][strategy_name] = strategy_data
            
            # Write back to file
            with open(synthesis_options_path, 'w') as f:
                # Add header comment
                f.write("# Default Synthesis Options Configuration\n")
                f.write("# This file defines the default synthesis options for the Cologne Chip Project Manager\n")
                f.write("# Auto-generated by yosys_commands.py during instantiation\n")
                f.write("# These settings will be used as fallback values when no custom configuration is set\n\n")
                
                # Write YAML content
                yaml.safe_dump(synthesis_options, f, default_flow_style=False, sort_keys=False)
            
            logging.info(f"✅ Custom strategy '{strategy_name}' saved to {synthesis_options_path}")
            return True
            
        except Exception as e:
            logging.error(f"❌ Error saving custom strategy: {e}")
            return False
    
    def _get_custom_strategy_options(self, strategy_name):
        """Get custom command-line options for a specific strategy.
        
        Args:
            strategy_name: Name of the strategy to get options for
            
        Returns:
            list: List of custom command-line options for the strategy, or empty list
        """
        try:
            from cc_project_manager_pkg.toolchain_manager import ToolChainManager
            import yaml
            
            tcm = ToolChainManager()
            
            # Get synthesis options file path
            setup_files = tcm.config.get("setup_files_initial", {})
            if "synthesis_options_file" in setup_files:
                synthesis_options_path = setup_files["synthesis_options_file"][0]
            else:
                # Fallback to config directory
                config_dir = tcm.config.get("project_structure", {}).get("config", [])
                if isinstance(config_dir, list) and config_dir:
                    synthesis_options_path = os.path.join(config_dir[0], "synthesis_options.yml")
                else:
                    synthesis_options_path = os.path.join(config_dir, "synthesis_options.yml")
            
            # Load synthesis options
            if os.path.exists(synthesis_options_path):
                with open(synthesis_options_path, 'r') as f:
                    synthesis_options = yaml.safe_load(f)
                
                if (synthesis_options and 
                    'synthesis_strategies' in synthesis_options and 
                    strategy_name in synthesis_options['synthesis_strategies']):
                    
                    strategy_config = synthesis_options['synthesis_strategies'][strategy_name]
                    return strategy_config.get('command_line_options', [])
            
            return []
            
        except Exception as e:
            logging.error(f"Error loading custom strategy options for {strategy_name}: {e}")
            return []
    
    def view_synthesis_logs(self):
        """View synthesis logs."""
        logging.info("Opening synthesis logs...")
        
        try:
            # Get the synthesis log file path from project configuration
            from cc_project_manager_pkg.hierarchy_manager import HierarchyManager
            hierarchy = HierarchyManager()
            
            if not hierarchy.config_path or not os.path.exists(hierarchy.config_path):
                self.show_message("Error", "No project configuration found. Please create or load a project first.", "error")
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
                self.show_message("Info", 
                    "No synthesis logs found yet.\n\n"
                    "Synthesis logs will be available after running synthesis operations.\n"
                    "The logs contain detailed output from Yosys including:\n"
                    "• Analysis and elaboration results\n"
                    "• Synthesis strategy execution\n"
                    "• Resource utilization reports\n"
                    "• Error messages and warnings", "info")
                return
            
            # Create and show log viewer dialog
            self._show_synthesis_log_dialog(yosys_log_path)
            
        except Exception as e:
            logging.error(f"Error opening synthesis logs: {e}")
            self.show_message("Error", f"Failed to open synthesis logs: {str(e)}", "error")
    
    def _show_synthesis_log_dialog(self, log_file_path):
        """Show synthesis log in a dialog window."""
        dialog = QDialog(self)
        dialog.setWindowTitle("Synthesis Logs - Yosys Commands & Output")
        dialog.setModal(True)
        dialog.resize(1200, 800)  # Larger window for better viewing
        
        layout = QVBoxLayout(dialog)
        
        # Header with file info and search
        header_layout = QHBoxLayout()
        
        file_info_label = QLabel(f"📄 Log File: {os.path.basename(log_file_path)}")
        file_info_label.setStyleSheet("font-weight: bold; color: #64b5f6; font-size: 12px;")
        header_layout.addWidget(file_info_label)
        
        header_layout.addStretch()
        
        # Search functionality
        search_label = QLabel("🔍 Find:")
        search_label.setStyleSheet("color: #ffffff; font-size: 11px;")
        header_layout.addWidget(search_label)
        
        search_input = QLineEdit()
        search_input.setPlaceholderText("Search for Yosys commands, errors, etc.")
        search_input.setMaximumWidth(250)
        search_input.setStyleSheet("""
            QLineEdit {
                background-color: #2d2d2d;
                color: #ffffff;
                border: 1px solid #555;
                padding: 4px;
                border-radius: 3px;
            }
        """)
        header_layout.addWidget(search_input)
        
        # Quick search buttons
        find_commands_btn = QPushButton("Find Yosys Commands")
        find_commands_btn.setMinimumWidth(180)
        find_commands_btn.setMaximumWidth(180)
        find_commands_btn.setStyleSheet("background-color: #42a5f5; color: #ffffff; font-weight: bold;")
        header_layout.addWidget(find_commands_btn)
        
        # Refresh button
        refresh_btn = QPushButton("🔄 Refresh")
        refresh_btn.setMinimumWidth(110)
        refresh_btn.setMaximumWidth(110)
        header_layout.addWidget(refresh_btn)
        
        # Save button
        save_btn = QPushButton("💾 Save")
        save_btn.setMinimumWidth(100)
        save_btn.setMaximumWidth(100)
        header_layout.addWidget(save_btn)
        
        # Clear log button
        clear_btn = QPushButton("🗑️ Clear Log")
        clear_btn.setMinimumWidth(120)
        clear_btn.setMaximumWidth(120)
        clear_btn.setStyleSheet("background-color: #ff4757; color: #ffffff; font-weight: bold;")
        header_layout.addWidget(clear_btn)
        
        layout.addLayout(header_layout)
        
        # Log content area
        log_text_widget = QTextEdit()
        log_text_widget.setReadOnly(True)
        log_text_widget.setFont(QFont("Consolas", 9))
        log_text_widget.setStyleSheet("""
            QTextEdit {
                background-color: #1e1e1e;
                color: #ffffff;
                border: 1px solid #555;
                selection-background-color: #3399ff;
            }
        """)
        
        # Load and display log content
        self._refresh_synthesis_log_content(log_text_widget, log_file_path)
        
        # Connect buttons and search functionality
        refresh_btn.clicked.connect(lambda: self._refresh_synthesis_log_content(log_text_widget, log_file_path))
        save_btn.clicked.connect(lambda: self._save_log_content(log_text_widget))
        clear_btn.clicked.connect(lambda: self._clear_synthesis_log(log_text_widget, log_file_path))
        
        # Search functionality
        def perform_search():
            search_text = search_input.text().strip()
            if search_text:
                self._search_in_text_widget(log_text_widget, search_text)
        
        def find_yosys_commands():
            # Search for common Yosys command patterns
            patterns = ["yosys ", "Yosys Command:", "DEBUG - yosys", "synthesis"]
            for pattern in patterns:
                if self._search_in_text_widget(log_text_widget, pattern):
                    search_input.setText(pattern)
                    break
        
        search_input.returnPressed.connect(perform_search)
        find_commands_btn.clicked.connect(find_yosys_commands)
        
        layout.addWidget(log_text_widget)
        
        # Status bar
        status_layout = QHBoxLayout()
        
        file_size_label = QLabel()
        try:
            file_size = os.path.getsize(log_file_path)
            if file_size < 1024:
                size_str = f"{file_size} bytes"
            elif file_size < 1024 * 1024:
                size_str = f"{file_size / 1024:.1f} KB"
            else:
                size_str = f"{file_size / (1024 * 1024):.1f} MB"
            file_size_label.setText(f"📊 Size: {size_str}")
        except:
            file_size_label.setText("📊 Size: Unknown")
        
        file_size_label.setStyleSheet("color: #888; font-size: 11px;")
        status_layout.addWidget(file_size_label)
        
        status_layout.addStretch()
        
        # Close button
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(dialog.accept)
        status_layout.addWidget(close_btn)
        
        layout.addLayout(status_layout)
        
        dialog.exec_()
    
    def _refresh_synthesis_log_content(self, text_widget, log_file_path):
        """Refresh synthesis log content in the text widget."""
        try:
            # Try multiple encodings to handle Yosys tool output
            content = None
            encodings_to_try = ['utf-8', 'latin-1', 'cp1252', 'iso-8859-1']
            
            for encoding in encodings_to_try:
                try:
                    with open(log_file_path, 'r', encoding=encoding) as f:
                        content = f.read()
                    break  # Success, stop trying other encodings
                except UnicodeDecodeError:
                    continue  # Try next encoding
            
            if content is None:
                # If all encodings fail, read as binary and decode with error handling
                with open(log_file_path, 'rb') as f:
                    raw_content = f.read()
                content = raw_content.decode('utf-8', errors='replace')
            
            # Apply syntax highlighting for better readability
            formatted_content = self._format_synthesis_log(content)
            text_widget.setHtml(formatted_content)
            
            # Scroll to top to show commands from the beginning
            cursor = text_widget.textCursor()
            cursor.movePosition(cursor.Start)
            text_widget.setTextCursor(cursor)
            text_widget.ensureCursorVisible()
            
        except Exception as e:
            text_widget.setPlainText(f"Error reading log file: {str(e)}")
    
    def _format_synthesis_log(self, content):
        """Format synthesis log content with enhanced syntax highlighting."""
        if not content:
            return "<p style='color: #888;'>No log content available.</p>"
        
        # Show all content - no truncation to allow full scrolling
        # For very large files (>1MB), show warning but still load all content
        if len(content) > 1024 * 1024:  # 1MB limit
            content = f"WARNING: Large log file ({len(content)} bytes) - loading may be slow\n\n{content}"
        
        # Split into lines and apply formatting
        lines = content.split('\n')
        formatted_lines = []
        
        for line in lines:
            line = line.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            
            # Enhanced color coding with Yosys command highlighting
            if ' - ERROR - ' in line or 'ERROR:' in line:
                formatted_lines.append(f'<span style="color: #ff6b6b; font-weight: bold;">{line}</span>')
            elif ' - WARNING - ' in line or 'WARNING:' in line:
                formatted_lines.append(f'<span style="color: #ffd93d;">{line}</span>')
            elif ' - INFO - ' in line or 'INFO:' in line:
                formatted_lines.append(f'<span style="color: #6bcf7f;">{line}</span>')
            elif ' - DEBUG - ' in line or 'DEBUG:' in line:
                formatted_lines.append(f'<span style="color: #74c0fc;">{line}</span>')
            # Highlight Yosys commands - this is what you want to see!
            elif 'Yosys Command:' in line or 'DEBUG - yosys ' in line or line.strip().startswith('yosys '):
                formatted_lines.append(f'<span style="color: #42a5f5; font-weight: bold; background-color: #1a2332;">{line}</span>')
            elif line.strip().startswith('Yosys ') and ('version' in line.lower() or 'build' in line.lower()):
                formatted_lines.append(f'<span style="color: #42a5f5; font-weight: bold;">{line}</span>')
            elif 'synthesis' in line.lower() and ('successful' in line.lower() or 'completed' in line.lower()):
                formatted_lines.append(f'<span style="color: #51cf66; font-weight: bold;">{line}</span>')
            elif 'failed' in line.lower() or 'error' in line.lower():
                formatted_lines.append(f'<span style="color: #ff6b6b; font-weight: bold;">{line}</span>')
            elif line.startswith('=== ') or '=' * 20 in line:
                formatted_lines.append(f'<span style="color: #ffd43b; font-weight: bold;">{line}</span>')
            # Highlight synthesis strategy and options
            elif 'strategy:' in line.lower() or 'using strategy' in line.lower():
                formatted_lines.append(f'<span style="color: #da77f2; font-weight: bold;">{line}</span>')
            # Highlight entity/module information
            elif 'entity:' in line.lower() or 'module:' in line.lower() or 'top module' in line.lower():
                formatted_lines.append(f'<span style="color: #51cf66;">{line}</span>')
            else:
                formatted_lines.append(f'<span style="color: #ffffff;">{line}</span>')
        
        return f'<pre style="font-family: Consolas, monospace; font-size: 9pt; line-height: 1.2;">{"<br>".join(formatted_lines)}</pre>'
    
    def _clear_synthesis_log(self, text_widget, log_file_path):
        """Clear the synthesis log file and refresh the display."""
        try:
            # Ask for confirmation before clearing
            from PyQt5.QtWidgets import QMessageBox
            reply = QMessageBox.question(
                text_widget.parent(),
                "Clear Synthesis Log",
                "Are you sure you want to clear the synthesis log file?\n\n"
                "This will permanently delete all Yosys command history and output.\n"
                "This action cannot be undone.",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            
            if reply == QMessageBox.Yes:
                # Clear the log file by writing empty content
                with open(log_file_path, 'w', encoding='utf-8') as f:
                    f.write("")
                
                # Clear the text widget display
                text_widget.clear()
                text_widget.setPlainText("Synthesis log has been cleared.\n\nNew synthesis operations will be logged here.")
                
                # Log the action
                logging.info("🗑️ Synthesis log file cleared successfully")
                
        except Exception as e:
            logging.error(f"❌ Error clearing synthesis log: {e}")
            # Show error message
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.critical(
                text_widget.parent(),
                "Error Clearing Log",
                f"Failed to clear the synthesis log file:\n\n{str(e)}"
            )
    
    def _save_log_content(self, text_widget):
        """Save log content to a file."""
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save Synthesis Log", "synthesis_log.txt", "Text Files (*.txt);;All Files (*)"
        )
        
        if file_path:
            try:
                # Get plain text content (without HTML formatting)
                content = text_widget.toPlainText()
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(content)
                logging.info(f"Synthesis log saved to {file_path}")
                self.show_message("Success", f"Log saved successfully to:\n{file_path}", "info")
            except Exception as e:
                logging.error(f"Failed to save log: {str(e)}")
                self.show_message("Error", f"Failed to save log: {str(e)}", "error")
    
    # Implementation Methods
    def run_place_and_route(self):
        """Run place and route using PnRCommands with strategy selection."""
        try:
            logging.info("🔄 Starting place and route operation...")
            
            # Get available synthesized designs
            synthesized_designs = self._find_synthesized_designs()
            
            if not synthesized_designs:
                logging.warning("❌ No synthesized designs found for place and route")
                self.show_message("Warning", 
                    "No synthesized designs found.\n\n"
                    "Please run synthesis first before attempting place and route.", "warning")
                return
            
            logging.info(f"📋 Found {len(synthesized_designs)} synthesized designs: {list(synthesized_designs.keys())}")
            
            # Use the selected design from the tree, or fall back to first available
            design_name = None
            if hasattr(self, 'selected_design') and self.selected_design and self.selected_design in synthesized_designs:
                design_name = self.selected_design
                logging.info(f"🎯 Using selected design from tree: {design_name}")
            else:
                design_name = list(synthesized_designs.keys())[0]
                logging.info(f"🎯 No design selected, using first available: {design_name}")
                
            logging.info(f"📁 Design for implementation: {design_name}")
            
            # Show implementation strategy dialog
            dialog = ImplementationStrategyDialog(self, design_name)
            if dialog.exec_() != QDialog.Accepted:
                logging.info("❌ Implementation cancelled by user")
                return
            
            impl_params = dialog.get_implementation_params()
            logging.info(f"🔧 Implementation parameters: {impl_params}")
            
            # Store constraint file mapping for this design
            constraint_file = impl_params['constraint_file']
            if constraint_file and constraint_file != "default" and constraint_file != "none":
                self.design_constraint_mapping[design_name] = constraint_file
            else:
                # Try to determine the default constraint file that will be used
                # Ensure we're in the correct project directory
                project_config_path, project_dir = self.find_project_config()
                if project_dir and os.getcwd() != project_dir:
                    logging.info(f"🔄 Changing working directory to project directory: {project_dir}")
                    os.chdir(project_dir)
                
                from cc_project_manager_pkg.pnr_commands import PnRCommands
                pnr_temp = PnRCommands()
                default_constraint = pnr_temp.get_default_constraint_file_path()
                if os.path.exists(default_constraint):
                    self.design_constraint_mapping[design_name] = os.path.basename(default_constraint)
                else:
                    self.design_constraint_mapping[design_name] = "None"
            
            def pnr_operation():
                try:
                    logging.info("=" * 80)
                    logging.info("🔄 IMPLEMENTATION OPERATION STARTED")
                    logging.info("=" * 80)
                    logging.info(f"📁 Design: {design_name}")
                    logging.info(f"🎯 Strategy: {impl_params['strategy']}")
                    logging.info(f"📄 Constraint File: {impl_params['constraint_file']}")
                    logging.info(f"💾 Generate Bitstream: {impl_params['generate_bitstream']}")
                    logging.info(f"⏱️  Run Timing Analysis: {impl_params['run_timing_analysis']}")
                    logging.info(f"📄 Generate Netlist: {impl_params['generate_sim_netlist']}")
                    
                    # Ensure we're in the correct project directory
                    project_config_path, project_dir = self.find_project_config()
                    if project_dir and os.getcwd() != project_dir:
                        logging.info(f"🔄 Changing working directory to project directory: {project_dir}")
                        os.chdir(project_dir)
                    
                    from cc_project_manager_pkg.pnr_commands import PnRCommands
                    pnr = PnRCommands(strategy=impl_params['strategy'])
                    
                    # Set constraint file if specified
                    constraint_file = impl_params['constraint_file']
                    if constraint_file and constraint_file != "default" and constraint_file != "none":
                        logging.info(f"🔗 Using specified constraint file: {constraint_file}")
                        # The constraint file selection will be passed to the PnR tool
                    else:
                        logging.info("🔗 Using default constraint file detection")
                    
                    if impl_params['generate_bitstream'] and impl_params['run_timing_analysis'] and impl_params['generate_sim_netlist']:
                        # Run full implementation flow
                        logging.info("🚀 Running full implementation flow...")
                        
                        # Determine constraint file to use
                        constraint_file_param = None
                        if constraint_file and constraint_file != "default" and constraint_file != "none":
                            constraint_file_param = os.path.join(pnr.constraints_dir, constraint_file)
                            logging.info(f"🔗 Using specified constraint file: {constraint_file}")
                        elif constraint_file == "default":
                            logging.info("🔍 Using auto-detection for constraint file (will use default or first available .ccf)")
                        # If constraint_file is "default", leave constraint_file_param as None to enable auto-detection
                        
                        success = pnr.full_implementation_flow(
                            design_name,
                            constraint_file=constraint_file_param,
                            generate_bitstream=impl_params['generate_bitstream'],
                            run_timing_analysis=impl_params['run_timing_analysis'],
                            generate_sim_netlist=impl_params['generate_sim_netlist'],
                            sim_netlist_format="vhdl"
                        )
                        
                        if success:
                            logging.info("✅ Full implementation flow completed successfully")
                            return f"Full implementation completed successfully for {design_name}"
                        else:
                            raise Exception(f"Full implementation flow failed for {design_name}")
                    else:
                        # Run place and route only
                        logging.info("🔧 Running place and route only...")
                        
                        # Determine constraint file to use
                        constraint_file_param = None
                        if constraint_file and constraint_file != "default" and constraint_file != "none":
                            constraint_file_param = os.path.join(pnr.constraints_dir, constraint_file)
                            logging.info(f"🔗 Using specified constraint file: {constraint_file}")
                        elif constraint_file == "default":
                            logging.info("🔍 Using auto-detection for constraint file (will use default or first available .ccf)")
                        # If constraint_file is "default", leave constraint_file_param as None to enable auto-detection
                        
                        logging.info(f"🔄 Calling pnr.place_and_route(design_name='{design_name}', constraint_file={constraint_file_param})")
                        success = pnr.place_and_route(design_name, constraint_file=constraint_file_param)
                        logging.info(f"🔍 DEBUG - place_and_route returned: {success}")
                        
                        if success:
                            logging.info("✅ Place and route completed successfully")
                            return f"Place and route completed successfully for {design_name}"
                        else:
                            logging.error(f"❌ place_and_route returned False for {design_name}")
                            
                            # Check if it's a constraint file issue by looking at recent PnR logs
                            try:
                                pnr_log_path = os.path.join(pnr.impl_logs_dir, "pnr_commands.log")
                                if os.path.exists(pnr_log_path):
                                    # Read the last 50 lines of the PnR log to get the error details
                                    with open(pnr_log_path, 'r', encoding='utf-8', errors='ignore') as f:
                                        lines = f.readlines()
                                        recent_lines = lines[-50:] if len(lines) > 50 else lines
                                        recent_log = ''.join(recent_lines)
                                        
                                        # Check for constraint file error
                                        if "CONSTRAINT FILE REQUIRED" in recent_log:
                                            constraint_error_msg = "❌ CONSTRAINT FILE REQUIRED\n\n"
                                            constraint_error_msg += "Place and Route failed because no constraint file was specified.\n\n"
                                            constraint_error_msg += "SOLUTIONS:\n"
                                            constraint_error_msg += "1. Go to Implementation tab → Place & Route\n"
                                            constraint_error_msg += "2. Select a constraint file from the dropdown\n"
                                            constraint_error_msg += "3. Or create a default constraint file first\n\n"
                                            constraint_error_msg += "Constraint files define pin assignments and timing constraints\n"
                                            constraint_error_msg += "which are typically required for FPGA implementation."
                                            
                                            logging.error(constraint_error_msg)
                                            raise Exception(constraint_error_msg)
                                        elif "Specified constraint file not found" in recent_log:
                                            file_error_msg = "❌ CONSTRAINT FILE NOT FOUND\n\n"
                                            file_error_msg += "The specified constraint file could not be found.\n\n"
                                            file_error_msg += "SOLUTIONS:\n"
                                            file_error_msg += "1. Check that the constraint file exists\n"
                                            file_error_msg += "2. Verify the file path is correct\n"
                                            file_error_msg += "3. Select a different constraint file\n"
                                            file_error_msg += "4. Create a new constraint file"
                                            
                                            logging.error(file_error_msg)
                                            raise Exception(file_error_msg)
                                        elif "SYNTHESIS NETLIST REQUIRED" in recent_log:
                                            netlist_error_msg = "❌ SYNTHESIS NETLIST REQUIRED\n\n"
                                            netlist_error_msg += "Place and Route failed because no synthesis netlist was found.\n\n"
                                            netlist_error_msg += "SOLUTIONS:\n"
                                            netlist_error_msg += "1. Go to Synthesis tab and run Synthesis first\n"
                                            netlist_error_msg += "2. Check that Synthesis completed successfully\n"
                                            netlist_error_msg += "3. Verify the design name matches your project\n"
                                            netlist_error_msg += "4. Check synthesis output files in synth directory\n\n"
                                            netlist_error_msg += "Place and Route requires a synthesized netlist as input."
                                            
                                            logging.error(netlist_error_msg)
                                            raise Exception(netlist_error_msg)
                            except Exception as log_error:
                                if "CONSTRAINT FILE" in str(log_error) or "SYNTHESIS NETLIST" in str(log_error):
                                    raise  # Re-raise constraint file and netlist errors
                                else:
                                    logging.warning(f"Could not read PnR logs for detailed error: {log_error}")
                            
                            # Generic error message if we can't determine the specific cause
                            generic_error_msg = f"❌ Place and route failed for {design_name}\n\n"
                            generic_error_msg += "Common causes:\n"
                            generic_error_msg += "• Missing or invalid constraint file\n"
                            generic_error_msg += "• Synthesis netlist not found\n"
                            generic_error_msg += "• P&R tool configuration issues\n\n"
                            generic_error_msg += "Check the Implementation Logs for detailed error information."
                            
                            logging.error(generic_error_msg)
                            raise Exception(generic_error_msg)
                            
                except Exception as e:
                    logging.error(f"❌ Implementation operation failed: {e}")
                    raise
            
            self.run_in_thread(pnr_operation, success_msg="Implementation completed successfully")
            # Refresh implementation status after P&R
            QTimer.singleShot(500, self.refresh_implementation_status)
            
        except Exception as e:
            logging.error(f"❌ Error in place and route: {e}")
            self.show_message("Error", f"Error in place and route: {str(e)}", "error")
    
    def generate_bitstream(self):
        """Generate bitstream from already placed and routed designs."""
        try:
            logging.info("🔄 Starting bitstream generation...")
            
            # Get available placed designs (not synthesized designs)
            # Ensure we're in the correct project directory
            project_config_path, project_dir = self.find_project_config()
            if project_dir and os.getcwd() != project_dir:
                logging.info(f"🔄 Changing working directory to project directory: {project_dir}")
                os.chdir(project_dir)
            
            from cc_project_manager_pkg.pnr_commands import PnRCommands
            pnr = PnRCommands()
            placed_designs = pnr.get_available_placed_designs()
            
            if not placed_designs:
                logging.warning("❌ No placed and routed designs found for bitstream generation")
                self.show_message("Warning", 
                    "No placed and routed designs found.\n\n"
                    "Please run Place & Route first before generating bitstream.", "warning")
                return
            
            logging.info(f"📋 Found {len(placed_designs)} placed designs: {placed_designs}")
            
            # Use the selected design from the tree, or fall back to first available
            design_name = None
            if hasattr(self, 'selected_design') and self.selected_design and self.selected_design in placed_designs:
                design_name = self.selected_design
                logging.info(f"🎯 Using selected design from tree: {design_name}")
            else:
                design_name = placed_designs[0]
                logging.info(f"🎯 No design selected, using first available: {design_name}")
                
            logging.info(f"📁 Design for bitstream generation: {design_name}")
            
            def bitstream_operation():
                try:
                    logging.info("=" * 60)
                    logging.info("🔄 BITSTREAM GENERATION STARTED")
                    logging.info("=" * 60)
                    logging.info(f"📁 Design: {design_name}")
                    
                    success = pnr.generate_bitstream(design_name)
                    
                    if success:
                        logging.info("✅ Bitstream generation completed successfully")
                        return f"Bitstream generated successfully for {design_name}"
                    else:
                        raise Exception(f"Bitstream generation failed for {design_name}")
                        
                except Exception as e:
                    logging.error(f"❌ Bitstream generation operation failed: {e}")
                    raise
            
            self.run_in_thread(bitstream_operation, success_msg="Bitstream generated successfully")
            # Refresh implementation status after bitstream generation
            QTimer.singleShot(1000, self.refresh_implementation_status)
            
        except Exception as e:
            logging.error(f"❌ Error in bitstream generation: {e}")
            self.show_message("Error", f"Error in bitstream generation: {str(e)}", "error")
    
    def run_timing_analysis(self):
        """Run timing analysis using PnRCommands."""
        try:
            logging.info("🔄 Starting timing analysis...")
            
            # Get available placed designs
            # Ensure we're in the correct project directory
            project_config_path, project_dir = self.find_project_config()
            if project_dir and os.getcwd() != project_dir:
                logging.info(f"🔄 Changing working directory to project directory: {project_dir}")
                os.chdir(project_dir)
            
            from cc_project_manager_pkg.pnr_commands import PnRCommands
            pnr = PnRCommands()
            placed_designs = pnr.get_available_placed_designs()
            
            if not placed_designs:
                logging.warning("❌ No placed and routed designs found for timing analysis")
                self.show_message("Warning", 
                    "No placed and routed designs found.\n\n"
                    "Please run place and route first before timing analysis.", "warning")
                return
            
            logging.info(f"📋 Found {len(placed_designs)} placed designs: {placed_designs}")
            
            # Use the selected design from the tree, or fall back to first available
            design_name = None
            if hasattr(self, 'selected_design') and self.selected_design and self.selected_design in placed_designs:
                design_name = self.selected_design
                logging.info(f"🎯 Using selected design from tree: {design_name}")
            else:
                design_name = placed_designs[0]
                logging.info(f"🎯 No design selected, using first available: {design_name}")
                
            logging.info(f"📁 Design for timing analysis: {design_name}")
            
            def timing_operation():
                try:
                    logging.info("=" * 60)
                    logging.info("🔄 TIMING ANALYSIS STARTED")
                    logging.info("=" * 60)
                    logging.info(f"📁 Design: {design_name}")
                    
                    success = pnr.timing_analysis(design_name)
                    
                    if success:
                        logging.info("✅ Timing analysis completed successfully")
                        return f"Timing analysis completed successfully for {design_name}"
                    else:
                        raise Exception(f"Timing analysis failed for {design_name}")
                        
                except Exception as e:
                    logging.error(f"❌ Timing analysis operation failed: {e}")
                    raise
            
            self.run_in_thread(timing_operation, success_msg="Timing analysis completed successfully")
            # Refresh implementation status after timing analysis
            QTimer.singleShot(500, self.refresh_implementation_status)
            
        except Exception as e:
            logging.error(f"❌ Error in timing analysis: {e}")
            self.show_message("Error", f"Error in timing analysis: {str(e)}", "error")
    
    def generate_post_impl_netlist(self):
        """Generate post-implementation netlist using PnRCommands."""
        try:
            logging.info("🔄 Starting post-implementation netlist generation...")
            
            # Get available placed designs
            # Ensure we're in the correct project directory
            project_config_path, project_dir = self.find_project_config()
            if project_dir and os.getcwd() != project_dir:
                logging.info(f"🔄 Changing working directory to project directory: {project_dir}")
                os.chdir(project_dir)
            
            from cc_project_manager_pkg.pnr_commands import PnRCommands
            pnr = PnRCommands()
            placed_designs = pnr.get_available_placed_designs()
            
            if not placed_designs:
                logging.warning("❌ No placed and routed designs found for netlist generation")
                self.show_message("Warning", 
                    "No placed and routed designs found.\n\n"
                    "Please run place and route first before generating post-implementation netlist.", "warning")
                return
            
            logging.info(f"📋 Found {len(placed_designs)} placed designs: {placed_designs}")
            
            # Use the selected design from the tree, or fall back to first available
            design_name = None
            if hasattr(self, 'selected_design') and self.selected_design and self.selected_design in placed_designs:
                design_name = self.selected_design
                logging.info(f"🎯 Using selected design from tree: {design_name}")
            else:
                design_name = placed_designs[0]
                logging.info(f"🎯 No design selected, using first available: {design_name}")
                
            logging.info(f"📁 Design for netlist generation: {design_name}")
            
            def netlist_operation():
                try:
                    logging.info("=" * 70)
                    logging.info("🔄 POST-IMPLEMENTATION NETLIST GENERATION STARTED")
                    logging.info("=" * 70)
                    logging.info(f"📁 Design: {design_name}")
                    logging.info(f"📄 Format: VHDL")
                    
                    success = pnr.generate_post_impl_netlist(design_name, netlist_format="vhdl")
                    
                    if success:
                        logging.info("✅ Post-implementation netlist generation completed successfully")
                        return f"Post-implementation netlist generated successfully for {design_name}"
                    else:
                        raise Exception(f"Post-implementation netlist generation failed for {design_name}")
                        
                except Exception as e:
                    logging.error(f"❌ Netlist generation operation failed: {e}")
                    raise
            
            self.run_in_thread(netlist_operation, success_msg="Post-implementation netlist generated successfully")
            # Refresh implementation status after netlist generation (with longer delay)
            QTimer.singleShot(1000, self.refresh_implementation_status)
            
        except Exception as e:
            logging.error(f"❌ Error in post-implementation netlist generation: {e}")
            self.show_message("Error", f"Error in post-implementation netlist generation: {str(e)}", "error")
    
    def run_full_implementation(self):
        """Run full implementation flow using PnRCommands with strategy selection."""
        try:
            logging.info("🔄 Starting full implementation flow...")
            
            # Get available synthesized designs
            synthesized_designs = self._find_synthesized_designs()
            
            if not synthesized_designs:
                logging.warning("❌ No synthesized designs found for full implementation")
                self.show_message("Warning", 
                    "No synthesized designs found.\n\n"
                    "Please run synthesis first before attempting full implementation.", "warning")
                return
            
            logging.info(f"📋 Found {len(synthesized_designs)} synthesized designs: {list(synthesized_designs.keys())}")
            
            # Use the selected design from the tree, or fall back to first available
            design_name = None
            if hasattr(self, 'selected_design') and self.selected_design and self.selected_design in synthesized_designs:
                design_name = self.selected_design
                logging.info(f"🎯 Using selected design from tree: {design_name}")
            else:
                design_name = list(synthesized_designs.keys())[0]
                logging.info(f"🎯 No design selected, using first available: {design_name}")
                
            logging.info(f"📁 Design for full implementation: {design_name}")
            
            # Show implementation strategy dialog
            dialog = ImplementationStrategyDialog(self, design_name)
            if dialog.exec_() != QDialog.Accepted:
                logging.info("❌ Full implementation cancelled by user")
                return
            
            impl_params = dialog.get_implementation_params()
            logging.info(f"🔧 Full implementation parameters: {impl_params}")
            
            # Store constraint file mapping for this design
            constraint_file = impl_params['constraint_file']
            if constraint_file and constraint_file != "default" and constraint_file != "none":
                self.design_constraint_mapping[design_name] = constraint_file
            else:
                # Try to determine the default constraint file that will be used
                # Ensure we're in the correct project directory
                project_config_path, project_dir = self.find_project_config()
                if project_dir and os.getcwd() != project_dir:
                    logging.info(f"🔄 Changing working directory to project directory: {project_dir}")
                    os.chdir(project_dir)
                
                from cc_project_manager_pkg.pnr_commands import PnRCommands
                pnr_temp = PnRCommands()
                default_constraint = pnr_temp.get_default_constraint_file_path()
                if os.path.exists(default_constraint):
                    self.design_constraint_mapping[design_name] = os.path.basename(default_constraint)
                else:
                    self.design_constraint_mapping[design_name] = "None"
            
            def full_impl_operation():
                try:
                    logging.info("=" * 80)
                    logging.info("🔄 FULL IMPLEMENTATION FLOW STARTED")
                    logging.info("=" * 80)
                    logging.info(f"📁 Design: {design_name}")
                    logging.info(f"🎯 Strategy: {impl_params['strategy']}")
                    logging.info(f"💾 Generate Bitstream: {impl_params['generate_bitstream']}")
                    logging.info(f"⏱️  Run Timing Analysis: {impl_params['run_timing_analysis']}")
                    logging.info(f"📄 Generate Netlist: {impl_params['generate_sim_netlist']}")
                    
                    # Ensure we're in the correct project directory
                    project_config_path, project_dir = self.find_project_config()
                    if project_dir and os.getcwd() != project_dir:
                        logging.info(f"🔄 Changing working directory to project directory: {project_dir}")
                        os.chdir(project_dir)
                    
                    from cc_project_manager_pkg.pnr_commands import PnRCommands
                    pnr = PnRCommands(strategy=impl_params['strategy'])
                    
                    # Determine constraint file to use
                    constraint_file_param = None
                    if constraint_file and constraint_file != "default" and constraint_file != "none":
                        constraint_file_param = os.path.join(pnr.constraints_dir, constraint_file)
                        logging.info(f"🔗 Using specified constraint file: {constraint_file}")
                    elif constraint_file == "default":
                        logging.info("🔍 Using auto-detection for constraint file (will use default or first available .ccf)")
                    # If constraint_file is "default", leave constraint_file_param as None to enable auto-detection
                    
                    success = pnr.full_implementation_flow(
                        design_name,
                        constraint_file=constraint_file_param,
                        generate_bitstream=impl_params['generate_bitstream'],
                        run_timing_analysis=impl_params['run_timing_analysis'],
                        generate_sim_netlist=impl_params['generate_sim_netlist'],
                        sim_netlist_format="vhdl"
                    )
                    
                    if success:
                        logging.info("✅ Full implementation flow completed successfully")
                        return f"Full implementation flow completed successfully for {design_name}"
                    else:
                        raise Exception(f"Full implementation flow failed for {design_name}")
                        
                except Exception as e:
                    logging.error(f"❌ Full implementation operation failed: {e}")
                    raise
            
            self.run_in_thread(full_impl_operation, success_msg="Full implementation completed successfully")
            # Refresh implementation status after full implementation
            QTimer.singleShot(500, self.refresh_implementation_status)
            
        except Exception as e:
            logging.error(f"❌ Error in full implementation: {e}")
            self.show_message("Error", f"Error in full implementation: {str(e)}", "error")
    
    def view_implementation_logs(self):
        """View implementation logs."""
        logging.info("Opening implementation logs...")
        
        try:
            # Get the implementation log file path from project configuration
            from cc_project_manager_pkg.hierarchy_manager import HierarchyManager
            hierarchy = HierarchyManager()
            
            if not hierarchy.config_path or not os.path.exists(hierarchy.config_path):
                self.show_message("Error", "No project configuration found. Please create or load a project first.", "error")
                return
            
            # Load project configuration
            import yaml
            with open(hierarchy.config_path, 'r') as f:
                config = yaml.safe_load(f)
            
            # Get pnr log file path
            pnr_log_path = None
            logs_section = config.get("logs", {})
            pnr_commands = logs_section.get("pnr_commands", {})
            
            if isinstance(pnr_commands, dict):
                pnr_log_path = pnr_commands.get("pnr_commands.log")
            
            if not pnr_log_path or not os.path.exists(pnr_log_path):
                self.show_message("Info", 
                    "No implementation logs found yet.\n\n"
                    "Implementation logs will be available after running P&R operations.\n"
                    "The logs contain detailed output from the P&R tool including:\n"
                    "• Place and route execution details\n"
                    "• Implementation strategy results\n"
                    "• Resource utilization reports\n"
                    "• Timing analysis results\n"
                    "• Bitstream generation output\n"
                    "• Error messages and warnings", "info")
                return
            
            # Create and show log viewer dialog
            self._show_implementation_log_dialog(pnr_log_path)
            
        except Exception as e:
            logging.error(f"Error accessing implementation logs: {e}")
            self.show_message("Error", f"Error accessing implementation logs: {str(e)}", "error")
    
    def _show_implementation_log_dialog(self, log_file_path):
        """Show implementation log viewer dialog."""
        dialog = QDialog(self)
        dialog.setWindowTitle("Implementation Logs - PNR Commands & Output")
        dialog.setModal(True)
        dialog.resize(1200, 800)  # Larger window for better viewing
        
        layout = QVBoxLayout(dialog)
        
        # Header with file info and search
        header_layout = QHBoxLayout()
        
        file_info_label = QLabel(f"📄 Log File: {os.path.basename(log_file_path)}")
        file_info_label.setStyleSheet("font-weight: bold; color: #64b5f6; font-size: 12px;")
        header_layout.addWidget(file_info_label)
        
        header_layout.addStretch()
        
        # Search functionality
        search_label = QLabel("🔍 Find:")
        search_label.setStyleSheet("color: #ffffff; font-size: 11px;")
        header_layout.addWidget(search_label)
        
        search_input = QLineEdit()
        search_input.setPlaceholderText("Search for PNR commands, errors, etc.")
        search_input.setMaximumWidth(250)
        search_input.setStyleSheet("""
            QLineEdit {
                background-color: #2d2d2d;
                color: #ffffff;
                border: 1px solid #555;
                padding: 4px;
                border-radius: 3px;
            }
        """)
        header_layout.addWidget(search_input)
        
        # Quick search buttons
        find_commands_btn = QPushButton("Find P&R Commands")
        find_commands_btn.setMinimumWidth(180)  # Increased significantly to 180
        find_commands_btn.setMaximumWidth(180)
        find_commands_btn.setStyleSheet("background-color: #ff9f40; color: #000000; font-weight: bold;")
        header_layout.addWidget(find_commands_btn)
        
        # Refresh button
        refresh_btn = QPushButton("🔄 Refresh")
        refresh_btn.setMinimumWidth(110)  # Increased to 110 for full text
        refresh_btn.setMaximumWidth(110)
        header_layout.addWidget(refresh_btn)
        
        # Save button
        save_btn = QPushButton("💾 Save")
        save_btn.setMinimumWidth(100)  # Increased to 100 for full text
        save_btn.setMaximumWidth(100)
        header_layout.addWidget(save_btn)
        
        # Clear log button
        clear_btn = QPushButton("🗑️ Clear Log")
        clear_btn.setMinimumWidth(120)
        clear_btn.setMaximumWidth(120)
        clear_btn.setStyleSheet("background-color: #ff4757; color: #ffffff; font-weight: bold;")
        header_layout.addWidget(clear_btn)
        
        layout.addLayout(header_layout)
        
        # Log content area
        log_text_widget = QTextEdit()
        log_text_widget.setReadOnly(True)
        log_text_widget.setFont(QFont("Consolas", 9))
        log_text_widget.setStyleSheet("""
            QTextEdit {
                background-color: #1e1e1e;
                color: #ffffff;
                border: 1px solid #555;
                selection-background-color: #3399ff;
            }
        """)
        
        # Load initial content
        self._refresh_implementation_log_content(log_text_widget, log_file_path)
        
        # Connect buttons and search functionality
        refresh_btn.clicked.connect(lambda: self._refresh_implementation_log_content(log_text_widget, log_file_path))
        save_btn.clicked.connect(lambda: self._save_log_content(log_text_widget))
        clear_btn.clicked.connect(lambda: self._clear_implementation_log(log_text_widget, log_file_path))
        
        # Search functionality
        def perform_search():
            search_text = search_input.text().strip()
            if search_text:
                self._search_in_text_widget(log_text_widget, search_text)
        
        def find_pnr_commands():
            # Search for common PNR command patterns
            patterns = ["p_r ", "P&R Command:", "DEBUG - p_r", "place and route"]
            for pattern in patterns:
                if self._search_in_text_widget(log_text_widget, pattern):
                    search_input.setText(pattern)
                    break
        
        search_input.returnPressed.connect(perform_search)
        find_commands_btn.clicked.connect(find_pnr_commands)
        
        layout.addWidget(log_text_widget)
        
        # Status bar
        status_layout = QHBoxLayout()
        
        file_size_label = QLabel()
        try:
            file_size = os.path.getsize(log_file_path)
            if file_size < 1024:
                size_str = f"{file_size} bytes"
            elif file_size < 1024 * 1024:
                size_str = f"{file_size / 1024:.1f} KB"
            else:
                size_str = f"{file_size / (1024 * 1024):.1f} MB"
            file_size_label.setText(f"📊 Size: {size_str}")
        except:
            file_size_label.setText("📊 Size: Unknown")
        
        file_size_label.setStyleSheet("color: #888; font-size: 11px;")
        status_layout.addWidget(file_size_label)
        
        status_layout.addStretch()
        
        # Close button
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(dialog.accept)
        status_layout.addWidget(close_btn)
        
        layout.addLayout(status_layout)
        
        dialog.exec_()
    
    def _refresh_implementation_log_content(self, text_widget, log_file_path):
        """Refresh implementation log content in the text widget."""
        try:
            # Try multiple encodings to handle P&R tool output
            content = None
            encodings_to_try = ['utf-8', 'latin-1', 'cp1252', 'iso-8859-1']
            
            for encoding in encodings_to_try:
                try:
                    with open(log_file_path, 'r', encoding=encoding) as f:
                        content = f.read()
                    break  # Success, stop trying other encodings
                except UnicodeDecodeError:
                    continue  # Try next encoding
            
            if content is None:
                # If all encodings fail, read as binary and decode with error handling
                with open(log_file_path, 'rb') as f:
                    raw_content = f.read()
                content = raw_content.decode('utf-8', errors='replace')
            
            # Apply syntax highlighting for better readability
            formatted_content = self._format_implementation_log(content)
            text_widget.setHtml(formatted_content)
            
            # Scroll to top to show commands from the beginning
            cursor = text_widget.textCursor()
            cursor.movePosition(cursor.Start)
            text_widget.setTextCursor(cursor)
            text_widget.ensureCursorVisible()
            
        except Exception as e:
            text_widget.setPlainText(f"Error reading log file: {str(e)}")
    
    def _format_implementation_log(self, content):
        """Format implementation log content with syntax highlighting."""
        if not content:
            return "<p style='color: #888;'>No log content available.</p>"
        
        # Show all content - no truncation to allow full scrolling
        # For very large files (>1MB), show warning but still load all content
        if len(content) > 1024 * 1024:  # 1MB limit
            content = f"WARNING: Large log file ({len(content)} bytes) - loading may be slow\n\n{content}"
        
        # Split into lines and apply formatting
        lines = content.split('\n')
        formatted_lines = []
        
        for line in lines:
            line = line.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            
            # Enhanced color coding with PNR command highlighting
            if ' - ERROR - ' in line or 'ERROR:' in line:
                formatted_lines.append(f'<span style="color: #ff6b6b; font-weight: bold;">{line}</span>')
            elif ' - WARNING - ' in line or 'WARNING:' in line:
                formatted_lines.append(f'<span style="color: #ffd93d;">{line}</span>')
            elif ' - INFO - ' in line or 'INFO:' in line:
                formatted_lines.append(f'<span style="color: #6bcf7f;">{line}</span>')
            elif ' - DEBUG - ' in line or 'DEBUG:' in line:
                formatted_lines.append(f'<span style="color: #74c0fc;">{line}</span>')
            # Highlight PNR commands - this is what you want to see!
            elif 'P&R Command:' in line or 'DEBUG - p_r ' in line or line.strip().startswith('p_r '):
                formatted_lines.append(f'<span style="color: #ff9f40; font-weight: bold; background-color: #2d1b0e;">{line}</span>')
            elif 'place and route' in line.lower() and ('successful' in line.lower() or 'completed' in line.lower()):
                formatted_lines.append(f'<span style="color: #51cf66; font-weight: bold;">{line}</span>')
            elif 'bitstream' in line.lower() and ('generated' in line.lower() or 'successful' in line.lower()):
                formatted_lines.append(f'<span style="color: #51cf66; font-weight: bold;">{line}</span>')
            elif 'failed' in line.lower() or 'error' in line.lower():
                formatted_lines.append(f'<span style="color: #ff6b6b; font-weight: bold;">{line}</span>')
            elif line.startswith('=== ') or '=' * 20 in line:
                formatted_lines.append(f'<span style="color: #ffd43b; font-weight: bold;">{line}</span>')
            # Highlight constraint file usage
            elif 'constraint file:' in line.lower() or 'using constraint' in line.lower():
                formatted_lines.append(f'<span style="color: #da77f2; font-weight: bold;">{line}</span>')
            else:
                formatted_lines.append(f'<span style="color: #ffffff;">{line}</span>')
        
        return f'<pre style="font-family: Consolas, monospace; font-size: 9pt; line-height: 1.2;">{"<br>".join(formatted_lines)}</pre>'
    
    def _search_in_text_widget(self, text_widget, search_text):
        """Search for text in the text widget and highlight the first match."""
        try:
            # Get the document
            document = text_widget.document()
            
            # Clear previous search highlights
            cursor = text_widget.textCursor()
            cursor.select(cursor.Document)
            
            # Search for the text
            found = document.find(search_text)
            if found.isNull():
                # Try case-insensitive search
                found = document.find(search_text, 0, document.FindCaseInsensitively)
            
            if not found.isNull():
                # Highlight and scroll to the found text
                text_widget.setTextCursor(found)
                text_widget.ensureCursorVisible()
                
                # Optionally highlight the found text
                selection = QTextEdit.ExtraSelection()
                selection.cursor = found
                selection.format.setBackground(QColor(255, 255, 0, 100))  # Yellow highlight
                text_widget.setExtraSelections([selection])
                
                return True
            else:
                # Text not found - show message in status or similar
                logging.info(f"🔍 Text '{search_text}' not found in log")
                return False
                
        except Exception as e:
            logging.error(f"Error searching in text widget: {e}")
            return False
    
    def _clear_implementation_log(self, text_widget, log_file_path):
        """Clear the implementation log file and refresh the display."""
        try:
            # Ask for confirmation before clearing
            from PyQt5.QtWidgets import QMessageBox
            reply = QMessageBox.question(
                text_widget.parent(),
                "Clear Implementation Log",
                "Are you sure you want to clear the implementation log file?\n\n"
                "This will permanently delete all PNR command history and output.\n"
                "This action cannot be undone.",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            
            if reply == QMessageBox.Yes:
                # Clear the log file by writing empty content
                with open(log_file_path, 'w', encoding='utf-8') as f:
                    f.write("")
                
                # Clear the text widget display
                text_widget.clear()
                text_widget.setPlainText("Implementation log has been cleared.\n\nNew PNR operations will be logged here.")
                
                # Log the action
                logging.info("🗑️ Implementation log file cleared successfully")
                
        except Exception as e:
            logging.error(f"❌ Error clearing implementation log: {e}")
            # Show error message
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.critical(
                text_widget.parent(),
                "Error Clearing Log",
                f"Failed to clear the implementation log file:\n\n{str(e)}"
            )
    
    # Implementation Analysis Methods
    def view_timing_report(self):
        """View detailed timing analysis report for the selected design."""
        if not self.selected_design:
            logging.warning("⚠️ No design selected for timing analysis")
            self.selected_design_status.setText("Please click on an implemented design in the Design/File container above")
            self.selected_design_status.setStyleSheet("color: #FF9800; font-size: 11px; margin-top: 5px;")
            return
            
        try:
            from cc_project_manager_pkg.pnr_commands import PnRCommands
            pnr = PnRCommands()
            
            # Check if design has timing analysis
            status = pnr.get_implementation_status(self.selected_design)
            if not status.get('timing_analyzed', False):
                self.show_message("No Timing Data", 
                                f"Design '{self.selected_design}' has no timing analysis.\n\n" +
                                "Run Timing Analysis or Full Implementation first.", "warning")
                return
            
            # Look for design-specific timing files first
            timing_files = []
            
            # Check for SDF files (Standard Delay Format)
            sdf_patterns = [
                os.path.join(pnr.timing_dir, f"{self.selected_design}.sdf"),
                os.path.join(pnr.timing_dir, f"{self.selected_design}_impl_00.sdf"),
                os.path.join(pnr.work_dir, f"{self.selected_design}_impl_00.sdf")
            ]
            
            for sdf_file in sdf_patterns:
                if os.path.exists(sdf_file):
                    timing_files.append(sdf_file)
                    break
            
            # Look for timing analysis in the main log file
            log_file = os.path.join(pnr.impl_logs_dir, "pnr_commands.log")
            if os.path.exists(log_file):
                timing_files.append(log_file)
            
            if timing_files:
                # Extract timing analysis content
                timing_content = self._extract_timing_analysis_for_design(timing_files, self.selected_design)
                if timing_content:
                    title = f"Timing Analysis Report - {self.selected_design}"
                    self._show_analysis_dialog(title, timing_content, "timing")
                else:
                    self.show_message("No Timing Data", 
                                    f"No timing analysis found for design '{self.selected_design}'.\n\n" +
                                    "The timing analysis may not have completed successfully.", "warning")
            else:
                self.show_message("No Implementation Data", 
                                f"No timing files found for design '{self.selected_design}'.\n\n" +
                                "Run Timing Analysis first to generate timing data.", "warning")
                
        except Exception as e:
            logging.error(f"Error viewing timing report: {str(e)}")
            self.show_message("Error", f"Failed to view timing report:\n{str(e)}", "error")
    
    def view_utilization_report(self):
        """View resource utilization report for the selected design."""
        if not self.selected_design:
            logging.warning("⚠️ No design selected for utilization analysis")
            self.selected_design_status.setText("Please click on an implemented design in the Design/File container above")
            self.selected_design_status.setStyleSheet("color: #FF9800; font-size: 11px; margin-top: 5px;")
            return
            
        try:
            from cc_project_manager_pkg.pnr_commands import PnRCommands
            pnr = PnRCommands()
            
            # Check if design has been implemented
            status = pnr.get_implementation_status(self.selected_design)
            if not status.get('placed', False):
                self.show_message("No Implementation Data", 
                                f"Design '{self.selected_design}' has not been implemented.\n\n" +
                                "Run Place & Route first to generate utilization data.", "warning")
                return
            
            # Look for design-specific utilization files
            utilization_files = []
            
            # Check for design-specific .used files
            if os.path.exists(pnr.work_dir):
                for file in os.listdir(pnr.work_dir):
                    if file.startswith(self.selected_design) and file.endswith('.used'):
                        utilization_files.append(os.path.join(pnr.work_dir, file))
            
            # Check for generic LUT report (this may contain multiple designs)
            lut_report = os.path.join(pnr.work_dir, "lut_report.txt")
            if os.path.exists(lut_report):
                utilization_files.append(lut_report)
            
            # Check for design-specific LUT report
            design_lut_report = os.path.join(pnr.work_dir, f"{self.selected_design}_lut_report.txt")
            if os.path.exists(design_lut_report):
                utilization_files.append(design_lut_report)
            
            if utilization_files:
                # Combine all utilization data
                utilization_content = self._combine_utilization_reports_for_design(utilization_files, self.selected_design)
                title = f"Resource Utilization Report - {self.selected_design}"
                self._show_analysis_dialog(title, utilization_content, "utilization")
            else:
                self.show_message("No Utilization Data", 
                                f"No utilization reports found for design '{self.selected_design}'.\n\n" +
                                "The utilization data may not have been generated properly.", "warning")
                
        except Exception as e:
            logging.error(f"Error viewing utilization report: {str(e)}")
            self.show_message("Error", f"Failed to view utilization report:\n{str(e)}", "error")
    
    def view_placement_report(self):
        """View placement and routing details for the selected design."""
        if not self.selected_design:
            logging.warning("⚠️ No design selected for placement analysis")
            self.selected_design_status.setText("Please click on an implemented design in the Design/File container above")
            self.selected_design_status.setStyleSheet("color: #FF9800; font-size: 11px; margin-top: 5px;")
            return
            
        try:
            from cc_project_manager_pkg.pnr_commands import PnRCommands
            pnr = PnRCommands()
            
            # Check if design has been implemented
            status = pnr.get_implementation_status(self.selected_design)
            if not status.get('placed', False):
                self.show_message("No Implementation Data", 
                                f"Design '{self.selected_design}' has not been implemented.\n\n" +
                                "Run Place & Route first to generate placement data.", "warning")
                return
            
            # Look for design-specific placement files
            placement_files = []
            
            if os.path.exists(pnr.work_dir):
                for file in os.listdir(pnr.work_dir):
                    # Look for design-specific placement files
                    if (file.startswith(self.selected_design) and 
                        file.endswith(('.place', '.pin', '.pos', '.route'))):
                        placement_files.append(os.path.join(pnr.work_dir, file))
            
            if placement_files:
                # Combine placement data
                placement_content = self._combine_placement_reports_for_design(placement_files, self.selected_design)
                title = f"Placement & Routing Report - {self.selected_design}"
                self._show_analysis_dialog(title, placement_content, "placement")
            else:
                self.show_message("No Placement Data", 
                                f"No placement reports found for design '{self.selected_design}'.\n\n" +
                                "The placement data may not have been generated properly.", "warning")
                
        except Exception as e:
            logging.error(f"Error viewing placement report: {str(e)}")
            self.show_message("Error", f"Failed to view placement report:\n{str(e)}", "error")
    
    def view_power_analysis(self):
        """View power analysis information."""
        self.show_message("Power Analysis Not Available", 
                        "Power analysis is not currently supported.\n\n" +
                        "The PnR tool (p_r) does not generate dedicated power analysis reports. " +
                        "While the tool has power reduction options (--pwr_red, --fpga_mode lowpower), " +
                        "it does not output detailed power consumption data.\n\n" +
                        "For power analysis, you would need:\n" +
                        "• A dedicated power analysis tool\n" +
                        "• Post-implementation simulation with power-aware models\n" +
                        "• Manual calculation based on device specifications", "info")
    
    # Simulation Methods
    def behavioral_simulation(self):
        """Run behavioral simulation with configuration dialog."""
        logging.info("🧪 Opening behavioral simulation configuration...")
        
        # Show simulation configuration dialog
        dialog = SimulationRunDialog(self, simulation_type="behavioral")
        if dialog.exec_() != QDialog.Accepted:
            logging.info("Behavioral simulation cancelled by user")
            return
        
        # Get simulation settings from dialog
        settings = dialog.get_simulation_settings()
        simulation_time = settings['simulation_time']
        time_prefix = settings['time_prefix']
        save_settings = settings['save_settings']
        
        logging.info(f"🎯 Running behavioral simulation with {simulation_time}{time_prefix}")
        
        def sim_operation():
            try:
                from cc_project_manager_pkg.simulation_manager import SimulationManager
                
                # SimulationManager now automatically reads simulation configuration
                # and passes the correct VHDL standard and IEEE library to GHDLCommands
                sim_manager = SimulationManager()
                
                # Save settings if requested
                if save_settings:
                    try:
                        sim_manager.set_simulation_length(simulation_time, time_prefix)
                        logging.info(f"✅ Saved simulation settings: {simulation_time}{time_prefix}")
                    except Exception as e:
                        logging.warning(f"Failed to save simulation settings: {e}")
                
                # Check if a testbench is selected
                if hasattr(self, 'selected_testbench') and self.selected_testbench:
                    testbench_entity = self.selected_testbench
                    logging.info(f"🎯 Using selected testbench: {testbench_entity}")
                    
                    # Prepare the specific testbench for simulation
                    success = sim_manager.prepare_testbench_for_simulation(testbench_entity)
                    if not success:
                        logging.error(f"❌ Failed to prepare testbench '{testbench_entity}' for simulation")
                        return f"Failed to prepare testbench '{testbench_entity}' for simulation"
                    
                    # Run behavioral simulation for the specific testbench
                    success = sim_manager.behavioral_simulation(
                        testbench_entity, 
                        options=None,
                        run_options=[f"--stop-time={simulation_time}{time_prefix}"]
                    )
                    
                    if success:
                        logging.info(f"✅ Behavioral simulation completed successfully for {testbench_entity}!")
                        # Refresh simulation status to show new VCD files
                        QTimer.singleShot(1000, self.refresh_simulation_status)
                        return f"Behavioral simulation completed successfully for {testbench_entity} ({simulation_time}{time_prefix})"
                    else:
                        logging.error(f"❌ Behavioral simulation failed for {testbench_entity}")
                        return f"Behavioral simulation failed for {testbench_entity} - check logs for details"
                else:
                    # No testbench selected, use default behavior
                    logging.info("🔄 No testbench selected, using default simulation")
                    success = sim_manager.behavioral_simulate()
                    
                    if success:
                        logging.info("✅ Behavioral simulation completed successfully!")
                        # Refresh simulation status to show new VCD files
                        QTimer.singleShot(1000, self.refresh_simulation_status)
                        return f"Behavioral simulation completed successfully ({simulation_time}{time_prefix})"
                    else:
                        logging.error("❌ Behavioral simulation failed")
                        return "Behavioral simulation failed - check logs for details"
                    
            except Exception as e:
                logging.error(f"❌ Behavioral simulation error: {e}")
                return f"Behavioral simulation error: {e}"
        
        self.run_in_thread(sim_operation, success_msg="Behavioral simulation completed successfully")
    
    def post_synthesis_simulation(self):
        """Run post-synthesis simulation with configuration dialog."""
        logging.info("🔬 Opening post-synthesis simulation configuration...")
        
        # Show simulation configuration dialog
        dialog = SimulationRunDialog(self, simulation_type="post-synthesis")
        if dialog.exec_() != QDialog.Accepted:
            logging.info("Post-synthesis simulation cancelled by user")
            return
        
        # Get simulation settings from dialog
        settings = dialog.get_simulation_settings()
        simulation_time = settings['simulation_time']
        time_prefix = settings['time_prefix']
        save_settings = settings['save_settings']
        
        logging.info(f"🎯 Running post-synthesis simulation with {simulation_time}{time_prefix}")
        
        def post_sim_operation():
            try:
                from cc_project_manager_pkg.simulation_manager import SimulationManager
                
                # SimulationManager now automatically reads simulation configuration
                # and passes the correct VHDL standard and IEEE library to GHDLCommands
                sim_manager = SimulationManager()
                
                # Save settings if requested
                if save_settings:
                    try:
                        sim_manager.set_simulation_length(simulation_time, time_prefix)
                        logging.info(f"✅ Saved simulation settings: {simulation_time}{time_prefix}")
                    except Exception as e:
                        logging.warning(f"Failed to save simulation settings: {e}")
                
                # Check if a testbench is selected
                if hasattr(self, 'selected_testbench') and self.selected_testbench:
                    testbench_entity = self.selected_testbench
                    logging.info(f"🎯 Using selected testbench: {testbench_entity}")
                    
                    # For post-synthesis simulation, we need to find the synthesized entity
                    # This is typically the entity that was synthesized, not the testbench
                    # We'll need to determine which entity to simulate based on synthesis results
                    
                    # For now, we'll use the default post-synthesis simulation
                    # TODO: Enhance this to use specific entity based on testbench selection
                    success = sim_manager.post_synthesis_simulate()
                    
                    if success:
                        logging.info(f"✅ Post-synthesis simulation completed successfully for {testbench_entity}!")
                        # Refresh simulation status to show new VCD files
                        QTimer.singleShot(1000, self.refresh_simulation_status)
                        return f"Post-synthesis simulation completed successfully for {testbench_entity} ({simulation_time}{time_prefix})"
                    else:
                        logging.error(f"❌ Post-synthesis simulation failed for {testbench_entity}")
                        return f"Post-synthesis simulation failed for {testbench_entity} - check logs for details"
                else:
                    # No testbench selected, use default behavior
                    logging.info("🔄 No testbench selected, using default post-synthesis simulation")
                    success = sim_manager.post_synthesis_simulate()
                    
                    if success:
                        logging.info("✅ Post-synthesis simulation completed successfully!")
                        # Refresh simulation status to show new VCD files
                        QTimer.singleShot(1000, self.refresh_simulation_status)
                        return f"Post-synthesis simulation completed successfully ({simulation_time}{time_prefix})"
                    else:
                        logging.error("❌ Post-synthesis simulation failed")
                        return "Post-synthesis simulation failed - check logs for details"
                    
            except Exception as e:
                logging.error(f"❌ Post-synthesis simulation error: {e}")
                return f"Post-synthesis simulation error: {e}"
        
        self.run_in_thread(post_sim_operation, success_msg="Post-synthesis simulation completed successfully")
    


    
    def launch_waveform_viewer(self):
        """Launch waveform viewer."""
        def launch_operation():
            logging.info("🌊 Launching waveform viewer...")
            
            try:
                from cc_project_manager_pkg.simulation_manager import SimulationManager
                sim_manager = SimulationManager()
                
                # Check if GTKWave is available
                if not sim_manager.check_gtkwave():
                    logging.error("❌ GTKWave is not available")
                    return "GTKWave is not available - please configure GTKWave path in Configuration tab"
                
                # Launch GTKWave with latest simulation
                success = sim_manager.launch_wave()
                
                if success:
                    logging.info("✅ GTKWave launched successfully")
                    return "GTKWave launched successfully"
                else:
                    logging.warning("⚠️ No simulation VCD files found")
                    return "No simulation VCD files found - run a simulation first"
                    
            except Exception as e:
                logging.error(f"❌ Waveform viewer launch error: {e}")
                return f"Waveform viewer launch error: {e}"
        
        self.run_in_thread(launch_operation, success_msg="Waveform viewer launched")

    def configure_simulation(self):
        """Configure simulation settings."""
        logging.info("Opening simulation configuration...")
        
        # Load current config
        try:
            current_config = self._get_simulation_configuration()
        except Exception as e:
            logging.error(f"Failed to load simulation configuration: {e}")
            current_config = {
                "vhdl_standard": "VHDL-2008",
                "ieee_library": "synopsys",
                "simulation_time": 1000,
                "time_prefix": "ns",
                "verbose": False,
                "save_waveforms": True
            }
        
        dialog = SimulationConfigDialog(self, current_config)
        if dialog.exec_() == QDialog.Accepted:
            config = dialog.get_config()
            # Save the configuration
            if self._save_simulation_configuration(config):
                logging.info(f"✅ Simulation configuration updated: {config}")
                # Refresh simulation status to show updated settings
                self.refresh_simulation_status()
            else:
                logging.error("❌ Failed to save simulation configuration")
    
    def view_simulation_logs(self):
        """View comprehensive simulation logs including GHDL commands, parameters, and simulation history."""
        logging.info("📋 Opening simulation logs...")
        
        try:
            # Find project configuration using the same logic as the GUI
            project_config_path, project_dir = self.find_project_config()
            
            if not project_config_path:
                logging.warning("❌ No project configuration found. Please create or load a project first.")
                logging.info("💡 Use 'File > New Project' or 'File > Load Existing Project' to set up a project.")
                return
            
            # Change to project directory temporarily to ensure correct context
            original_cwd = os.getcwd()
            os.chdir(project_dir)
            
            try:
                from cc_project_manager_pkg.simulation_manager import SimulationManager
                sim_manager = SimulationManager()
                
                # Find GHDL commands log file
                ghdl_log_path = None
                project_config = sim_manager.project_config
                
                # Check if GHDL log is in project config
                if "logs" in project_config and "ghdl_commands" in project_config["logs"]:
                    ghdl_log_path = project_config["logs"]["ghdl_commands"].get("ghdl_commands.log")
                
                # Fallback: look in logs directory
                if not ghdl_log_path or not os.path.exists(ghdl_log_path):
                    logs_dir = project_config.get("project_structure", {}).get("logs", [])
                    if logs_dir:
                        potential_path = os.path.join(logs_dir[0], "ghdl_commands.log")
                        if os.path.exists(potential_path):
                            ghdl_log_path = potential_path
                
                if not ghdl_log_path or not os.path.exists(ghdl_log_path):
                    logging.warning("❌ No simulation logs found. Run a simulation first to generate logs.")
                    logging.info("💡 Simulation logs will be created automatically when you run behavioral or post-synthesis simulations.")
                    logging.info(f"📁 Expected log location: {os.path.join(project_dir, 'logs', 'ghdl_commands.log')}")
                    return
                
                self._show_simulation_log_dialog(ghdl_log_path, sim_manager)
                
            finally:
                # Always restore the original working directory
                os.chdir(original_cwd)
            
        except Exception as e:
            logging.error(f"❌ Error opening simulation logs: {e}")
            logging.error("💡 Make sure you have run at least one simulation to generate log files.")
    
    def _show_simulation_log_dialog(self, ghdl_log_path, sim_manager):
        """Show comprehensive simulation log dialog with GHDL commands, parameters, and history."""
        dialog = QDialog(self)
        dialog.setWindowTitle("Simulation Logs & History")
        dialog.setModal(True)
        dialog.resize(1000, 700)
        
        layout = QVBoxLayout(dialog)
        
        # Create tab widget for different log views
        tab_widget = QTabWidget()
        
        # Tab 1: GHDL Commands Log
        ghdl_tab = QWidget()
        ghdl_layout = QVBoxLayout(ghdl_tab)
        
        # GHDL log header
        ghdl_header = QLabel(f"GHDL Commands Log: {os.path.basename(ghdl_log_path)}")
        ghdl_header.setStyleSheet("font-weight: bold; font-size: 14px; color: #4CAF50; margin-bottom: 10px;")
        ghdl_layout.addWidget(ghdl_header)
        
        # GHDL log content
        ghdl_text = LogTextWidget()
        ghdl_layout.addWidget(ghdl_text)
        
        # GHDL log controls
        ghdl_controls = QHBoxLayout()
        
        ghdl_refresh_btn = QPushButton("🔄 Refresh")
        ghdl_refresh_btn.clicked.connect(lambda: self._refresh_simulation_log_content(ghdl_text, ghdl_log_path))
        ghdl_controls.addWidget(ghdl_refresh_btn)
        
        ghdl_clear_btn = QPushButton("🗑️ Clear Log File")
        ghdl_clear_btn.clicked.connect(lambda: self._clear_simulation_log(ghdl_text, ghdl_log_path))
        ghdl_controls.addWidget(ghdl_clear_btn)
        
        ghdl_save_btn = QPushButton("💾 Save Log")
        ghdl_save_btn.clicked.connect(lambda: self._save_log_content(ghdl_text))
        ghdl_controls.addWidget(ghdl_save_btn)
        
        ghdl_controls.addStretch()
        
        # Search functionality for GHDL logs
        search_layout = QHBoxLayout()
        search_label = QLabel("Search:")
        search_input = QLineEdit()
        search_input.setPlaceholderText("Enter search term (e.g., 'GHDL Command', 'simulation', 'error')...")
        search_btn = QPushButton("🔍 Search")
        
        def perform_ghdl_search():
            search_text = search_input.text().strip()
            if search_text:
                self._search_in_text_widget(ghdl_text, search_text)
        
        search_btn.clicked.connect(perform_ghdl_search)
        search_input.returnPressed.connect(perform_ghdl_search)
        
        search_layout.addWidget(search_label)
        search_layout.addWidget(search_input)
        search_layout.addWidget(search_btn)
        
        ghdl_layout.addLayout(search_layout)
        ghdl_layout.addLayout(ghdl_controls)
        
        tab_widget.addTab(ghdl_tab, "GHDL Commands")
        
        # Tab 2: Simulation History & Parameters
        history_tab = QWidget()
        history_layout = QVBoxLayout(history_tab)
        
        # Current simulation settings
        settings_header = QLabel("Current Simulation Settings")
        settings_header.setStyleSheet("font-weight: bold; font-size: 14px; color: #2196F3; margin-bottom: 10px;")
        history_layout.addWidget(settings_header)
        
        settings_text = QTextEdit()
        settings_text.setMaximumHeight(150)
        settings_text.setReadOnly(True)
        
        # Get current simulation settings
        try:
            sim_settings = sim_manager.get_simulation_length()
            current_profile = sim_manager.get_current_simulation_profile()
            
            settings_info = f"""Current Simulation Configuration:
• Profile: {current_profile}
• Duration: {sim_settings[0]}{sim_settings[1]} (if settings available)
• Supported Time Prefixes: {', '.join(sim_manager.supported_time_prefixes)}
• Simulation Types: {', '.join(sim_manager.simulation_types)}

GHDL Parameters Used:
• VHDL Standard: {getattr(sim_manager, 'vhdl_std', '--std=08')}
• IEEE Library: {getattr(sim_manager, 'ieee_lib', '--ieee=synopsys')}
• Work Library: {getattr(sim_manager, 'work_lib_name', 'work')}
• Build Directory: {sim_manager.project_config.get('project_structure', {}).get('build', ['Not set'])[0]}

GTKWave Configuration:
• Status: {'Available' if sim_manager.check_gtkwave() else 'Not Available'}
• Preference: {sim_manager.project_config.get('gtkwave_preference', 'PATH')}
"""
            
            if sim_settings:
                settings_info = settings_info.replace(f"{sim_settings[0]}{sim_settings[1]} (if settings available)", f"{sim_settings[0]}{sim_settings[1]}")
            
        except Exception as e:
            settings_info = f"Error loading simulation settings: {e}"
        
        settings_text.setPlainText(settings_info)
        history_layout.addWidget(settings_text)
        
        # Simulation history
        history_header = QLabel("Simulation History")
        history_header.setStyleSheet("font-weight: bold; font-size: 14px; color: #FF9800; margin-top: 15px; margin-bottom: 10px;")
        history_layout.addWidget(history_header)
        
        history_text = QTextEdit()
        history_text.setReadOnly(True)
        
        # Get simulation history
        try:
            sim_history = sim_manager.project_config.get("simulation_history", {})
            history_content = "Simulation Run History:\n\n"
            
            for sim_type, records in sim_history.items():
                history_content += f"=== {sim_type.upper()} SIMULATIONS ===\n"
                
                if records:
                    for i, record in enumerate(reversed(records[-10:])):  # Show last 10 records
                        timestamp = record.get("timestamp", "Unknown")
                        entity = record.get("entity_name", "Unknown")
                        success = "✅ SUCCESS" if record.get("success", False) else "❌ FAILED"
                        sim_time = record.get("simulation_time", "Unknown")
                        time_prefix = record.get("time_prefix", "")
                        vcd_file = record.get("vcd_file", "Unknown")
                        
                        history_content += f"\n{i+1}. {timestamp}\n"
                        history_content += f"   Entity: {entity}\n"
                        history_content += f"   Status: {success}\n"
                        history_content += f"   Duration: {sim_time}{time_prefix}\n"
                        history_content += f"   VCD File: {os.path.basename(vcd_file) if vcd_file != 'Unknown' else 'Unknown'}\n"
                else:
                    history_content += "   No simulation records found.\n"
                
                history_content += "\n"
            
            if not sim_history:
                history_content += "No simulation history available. Run simulations to populate this section.\n"
                
        except Exception as e:
            history_content = f"Error loading simulation history: {e}\n"
        
        history_text.setPlainText(history_content)
        history_layout.addWidget(history_text)
        
        tab_widget.addTab(history_tab, "Settings & History")
        
        # Tab 3: GHDL Command Examples
        examples_tab = QWidget()
        examples_layout = QVBoxLayout(examples_tab)
        
        examples_header = QLabel("GHDL Command Examples & Documentation")
        examples_header.setStyleSheet("font-weight: bold; font-size: 14px; color: #9C27B0; margin-bottom: 10px;")
        examples_layout.addWidget(examples_header)
        
        examples_text = QTextEdit()
        examples_text.setReadOnly(True)
        
        examples_content = """GHDL Command Structure & Examples:

=== ANALYSIS PHASE ===
Command: ghdl analyze [options] file.vhd
Example: ghdl analyze --std=08 --ieee=synopsys --workdir=build --work=work src/entity.vhd

Options Used:
• --std=08: VHDL-2008 standard
• --ieee=synopsys: Synopsys IEEE library variant
• --workdir=build: Working directory for compiled files
• --work=work: Work library name

=== ELABORATION PHASE ===
Command: ghdl elaborate [options] entity_name
Example: ghdl elaborate --std=08 --ieee=synopsys --work=work --workdir=build testbench_entity

=== SIMULATION PHASE ===
Command: ghdl run [options] entity_name [simulation_options]
Example: ghdl run --std=08 --ieee=synopsys --workdir=build --work=work testbench_entity --vcd=output.vcd --stop-time=1000ns

Simulation Options:
• --vcd=file.vcd: Generate VCD waveform file
• --stop-time=1000ns: Stop simulation after specified time
• --wave=file.ghw: Generate GHW waveform file (GHDL native format)

=== TYPICAL SIMULATION WORKFLOW ===
1. Analyze all source files (dependencies first)
2. Analyze testbench files
3. Elaborate the testbench entity
4. Run simulation with waveform generation

=== TIME UNITS SUPPORTED ===
• fs (femtoseconds)
• ps (picoseconds)  
• ns (nanoseconds)
• us (microseconds)
• ms (milliseconds)
• sec (seconds)

=== COMMON GHDL FLAGS ===
• --version: Show GHDL version
• --help: Show help information
• --verbose: Enable verbose output
• --warn-error: Treat warnings as errors
• --ieee-asserts=disable: Disable IEEE assertion warnings

=== TROUBLESHOOTING ===
• Check entity names match between files
• Ensure all dependencies are analyzed before elaboration
• Verify VHDL standard compatibility
• Check file paths and working directory permissions
"""
        
        examples_text.setPlainText(examples_content)
        examples_layout.addWidget(examples_text)
        
        tab_widget.addTab(examples_tab, "GHDL Reference")
        
        layout.addWidget(tab_widget)
        
        # Dialog buttons
        button_layout = QHBoxLayout()
        
        refresh_all_btn = QPushButton("🔄 Refresh All")
        refresh_all_btn.clicked.connect(lambda: self._refresh_simulation_log_content(ghdl_text, ghdl_log_path))
        button_layout.addWidget(refresh_all_btn)
        
        button_layout.addStretch()
        
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(dialog.accept)
        button_layout.addWidget(close_btn)
        
        layout.addLayout(button_layout)
        
        # Load initial content
        self._refresh_simulation_log_content(ghdl_text, ghdl_log_path)
        
        dialog.exec_()
    
    def _refresh_simulation_log_content(self, text_widget, log_file_path):
        """Refresh simulation log content with formatting."""
        try:
            if os.path.exists(log_file_path):
                with open(log_file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                
                # Format the content for better readability
                formatted_content = self._format_simulation_log(content)
                text_widget.setPlainText(formatted_content)
                
                # Scroll to bottom to show latest entries
                cursor = text_widget.textCursor()
                cursor.movePosition(cursor.End)
                text_widget.setTextCursor(cursor)
                
                logging.info(f"✅ Refreshed simulation log content from {log_file_path}")
            else:
                text_widget.setPlainText(f"Log file not found: {log_file_path}")
                logging.warning(f"Simulation log file not found: {log_file_path}")
                
        except Exception as e:
            error_msg = f"Error reading simulation log file: {e}"
            text_widget.setPlainText(error_msg)
            logging.error(f"Error refreshing simulation log content: {e}")
    
    def _format_simulation_log(self, content):
        """Format simulation log content for better readability."""
        lines = content.split('\n')
        formatted_lines = []
        
        for line in lines:
            # Highlight important log levels
            if ' - ERROR - ' in line:
                formatted_lines.append(f"🔴 {line}")
            elif ' - WARNING - ' in line:
                formatted_lines.append(f"🟡 {line}")
            elif ' - INFO - ' in line and any(keyword in line.lower() for keyword in ['ghdl command', 'simulation', 'analyze', 'elaborate']):
                formatted_lines.append(f"🔵 {line}")
            elif 'GHDL Command:' in line:
                formatted_lines.append(f"⚡ {line}")
            elif 'Successfully' in line:
                formatted_lines.append(f"✅ {line}")
            elif 'Failed' in line or 'failed' in line:
                formatted_lines.append(f"❌ {line}")
            else:
                formatted_lines.append(line)
        
        return '\n'.join(formatted_lines)
    
    def _clear_simulation_log(self, text_widget, log_file_path):
        """Clear simulation log file and display."""
        reply = QMessageBox.question(
            self, 
            "Clear GHDL Log File", 
            f"This will permanently delete the GHDL commands log file:\n\n{log_file_path}\n\nThis action cannot be undone. Are you sure?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            try:
                # Clear the log file by truncating it
                if os.path.exists(log_file_path):
                    with open(log_file_path, 'w') as f:
                        f.truncate(0)  # Clear the file content
                    logging.info(f"✅ Cleared GHDL log file: {log_file_path}")
                    
                    # Also clear the display
                    text_widget.clear()
                    text_widget.append("📝 GHDL log file has been cleared.")
                    text_widget.append("🔄 Run a simulation to generate new log entries.")
                    
                    # Log to the main application log
                    logging.info("GHDL commands log file cleared by user")
                else:
                    logging.warning(f"GHDL log file not found: {log_file_path}")
                    text_widget.clear()
                    text_widget.append("⚠️ GHDL log file not found.")
                    
            except Exception as e:
                logging.error(f"Failed to clear GHDL log file: {e}")
                QMessageBox.critical(
                    self,
                    "Error",
                    f"Failed to clear GHDL log file:\n\n{str(e)}"
                )
    
    def on_tab_changed(self, index):
        """Handle tab change events to automatically refresh tab content."""
        try:
            # Get the tab text to identify which tab was selected
            tab_text = self.tab_widget.tabText(index)
            
            # Auto-refresh Upload tab when it's selected
            if tab_text == "Upload":
                logging.info("🔄 Upload tab selected - automatically refreshing bitstream files...")
                # Use a small delay to ensure the tab is fully loaded
                QTimer.singleShot(100, self.refresh_upload_status_without_device_check)
                
        except Exception as e:
            logging.error(f"Error handling tab change: {e}")
    
    # Upload Methods
    def refresh_upload_status(self):
        """Refresh the upload status display."""
        try:
            logging.info("🔄 Refreshing upload status...")
            
            # Check openFPGALoader availability
            try:
                from cc_project_manager_pkg.openfpgaloader_manager import OpenFPGALoaderManager
                upload_manager = OpenFPGALoaderManager()
                
                # Check if openFPGALoader is available using toolchain manager
                from cc_project_manager_pkg.toolchain_manager import ToolChainManager
                tcm = ToolChainManager()
                if tcm.check_tool_version("openfpgaloader"):
                    self.openfpgaloader_status_label.setText("openFPGALoader: ✅ Available")
                    self.openfpgaloader_status_label.setStyleSheet("font-weight: bold; color: #4CAF50;")
                else:
                    self.openfpgaloader_status_label.setText("openFPGALoader: ❌ Not available")
                    self.openfpgaloader_status_label.setStyleSheet("font-weight: bold; color: #F44336;")
                
                # Try to detect devices
                try:
                    device_detected = upload_manager.detect_devices()
                    if device_detected:
                        self.device_status_label.setText("FPGA Device: ✅ Detected")
                        self.device_status_label.setStyleSheet("font-weight: bold; color: #4CAF50;")
                    else:
                        self.device_status_label.setText("FPGA Device: ⚠️ Not detected")
                        self.device_status_label.setStyleSheet("font-weight: bold; color: #FFA726;")
                except Exception as e:
                    self.device_status_label.setText("FPGA Device: ❌ Detection failed")
                    self.device_status_label.setStyleSheet("font-weight: bold; color: #F44336;")
                    logging.warning(f"Device detection failed: {e}")
                
            except Exception as e:
                logging.warning(f"Could not load openFPGALoader manager: {e}")
                self.openfpgaloader_status_label.setText("openFPGALoader: ❌ Error loading")
                self.openfpgaloader_status_label.setStyleSheet("font-weight: bold; color: #F44336;")
                self.device_status_label.setText("FPGA Device: ❌ Cannot check")
                self.device_status_label.setStyleSheet("font-weight: bold; color: #F44336;")
            
            # Clear and populate bitstream tree
            self.bitstream_tree.clear()
            
            # Get available bitstreams
            try:
                bitstream_files = self._find_bitstream_files()
                
                if bitstream_files:
                    for bitstream in bitstream_files:
                        size_mb = bitstream["size"] / (1024 * 1024)
                        size_text = f"{size_mb:.1f} MB" if size_mb >= 1 else f"{bitstream['size']} B"
                        modified_text = bitstream["modified"].strftime("%Y-%m-%d %H:%M")
                        
                        item = QTreeWidgetItem(self.bitstream_tree, [
                            bitstream["name"],
                            bitstream["design"],
                            size_text,
                            modified_text,
                            bitstream["type"],
                            "✅ Ready"
                        ])
                        
                        # Store bitstream metadata
                        item.setData(0, Qt.UserRole, {"path": bitstream["path"], "design": bitstream["design"]})
                        
                        # Color code the items
                        item.setForeground(0, QColor("#ffffff"))
                        item.setForeground(1, QColor("#4CAF50"))
                        item.setForeground(2, QColor("#FFA726"))
                        item.setForeground(3, QColor("#888888"))
                        item.setForeground(4, QColor("#64b5f6"))
                        item.setForeground(5, QColor("#4CAF50"))
                    
                    logging.info(f"✅ Found {len(bitstream_files)} bitstream files")
                else:
                    # Add message when no bitstreams found
                    no_bitstream_item = QTreeWidgetItem(self.bitstream_tree, [
                        "No bitstreams found",
                        "Run implementation to generate bitstreams",
                        "",
                        "",
                        "",
                        "Missing"
                    ])
                    no_bitstream_item.setForeground(0, QColor("#FFA726"))
                    no_bitstream_item.setForeground(5, QColor("#F44336"))
                    logging.warning("⚠️ No bitstream files found in project")
                
                # Update statistics
                self.upload_stats_labels['total_bitstreams'].setText(str(len(bitstream_files)))
                
                # Load upload history statistics from JSON file
                self._load_upload_statistics()
                
            except Exception as e:
                logging.error(f"Error loading bitstream files: {e}")
                error_item = QTreeWidgetItem(self.bitstream_tree, [
                    "Error loading bitstreams",
                    str(e),
                    "",
                    "",
                    "",
                    "Error"
                ])
                error_item.setForeground(0, QColor("#F44336"))
                error_item.setForeground(5, QColor("#F44336"))
            
        except Exception as e:
            logging.error(f"Error refreshing upload status: {e}")
    
    def refresh_upload_status_without_device_check(self):
        """Refresh upload status without running device detection (device status already updated)."""
        try:
            logging.info("🔄 Refreshing upload status (skipping device check)...")
            
            # Check openFPGALoader availability
            try:
                from cc_project_manager_pkg.openfpgaloader_manager import OpenFPGALoaderManager
                upload_manager = OpenFPGALoaderManager()
                
                # Check if openFPGALoader is available using toolchain manager
                from cc_project_manager_pkg.toolchain_manager import ToolChainManager
                tcm = ToolChainManager()
                if tcm.check_tool_version("openfpgaloader"):
                    self.openfpgaloader_status_label.setText("openFPGALoader: ✅ Available")
                    self.openfpgaloader_status_label.setStyleSheet("font-weight: bold; color: #4CAF50;")
                else:
                    self.openfpgaloader_status_label.setText("openFPGALoader: ❌ Not available")
                    self.openfpgaloader_status_label.setStyleSheet("font-weight: bold; color: #F44336;")
                
                # Skip device detection - device status already updated by dialog
                
            except Exception as e:
                logging.warning(f"Could not load openFPGALoader manager: {e}")
                self.openfpgaloader_status_label.setText("openFPGALoader: ❌ Error loading")
                self.openfpgaloader_status_label.setStyleSheet("font-weight: bold; color: #F44336;")
            
            # Clear and populate bitstream tree
            self.bitstream_tree.clear()
            
            # Get available bitstreams
            try:
                bitstream_files = self._find_bitstream_files()
                
                if bitstream_files:
                    for bitstream in bitstream_files:
                        size_mb = bitstream["size"] / (1024 * 1024)
                        size_text = f"{size_mb:.1f} MB" if size_mb >= 1 else f"{bitstream['size']} B"
                        modified_text = bitstream["modified"].strftime("%Y-%m-%d %H:%M")
                        
                        item = QTreeWidgetItem(self.bitstream_tree, [
                            bitstream["name"],
                            bitstream["design"],
                            size_text,
                            modified_text,
                            bitstream["type"],
                            "✅ Ready"
                        ])
                        
                        # Store bitstream metadata
                        item.setData(0, Qt.UserRole, {"path": bitstream["path"], "design": bitstream["design"]})
                        
                        # Color code the items
                        item.setForeground(0, QColor("#ffffff"))
                        item.setForeground(1, QColor("#4CAF50"))
                        item.setForeground(2, QColor("#FFA726"))
                        item.setForeground(3, QColor("#888888"))
                        item.setForeground(4, QColor("#64b5f6"))
                        item.setForeground(5, QColor("#4CAF50"))
                    
                    logging.info(f"✅ Found {len(bitstream_files)} bitstream files")
                else:
                    # Add message when no bitstreams found
                    no_bitstream_item = QTreeWidgetItem(self.bitstream_tree, [
                        "No bitstreams found",
                        "Run implementation to generate bitstreams",
                        "",
                        "",
                        "",
                        "Missing"
                    ])
                    no_bitstream_item.setForeground(0, QColor("#FFA726"))
                    no_bitstream_item.setForeground(5, QColor("#F44336"))
                    logging.warning("⚠️ No bitstream files found in project")
                
                # Update statistics
                self.upload_stats_labels['total_bitstreams'].setText(str(len(bitstream_files)))
                
                # Load upload history statistics from JSON file
                self._load_upload_statistics()
                
            except Exception as e:
                logging.error(f"Error loading bitstream files: {e}")
                error_item = QTreeWidgetItem(self.bitstream_tree, [
                    "Error loading bitstreams",
                    str(e),
                    "",
                    "",
                    "",
                    "Error"
                ])
                error_item.setForeground(0, QColor("#F44336"))
                error_item.setForeground(5, QColor("#F44336"))
            
        except Exception as e:
            logging.error(f"Error refreshing upload status (without device check): {e}")
    
    def _load_upload_statistics(self):
        """Load upload statistics from JSON file."""
        try:
            # Find the upload stats file
            from cc_project_manager_pkg.hierarchy_manager import HierarchyManager
            hierarchy = HierarchyManager()
            
            # Get log file path from project structure
            if hierarchy.config and 'project_structure' in hierarchy.config:
                logs_dir = hierarchy.config['project_structure']['logs'][0]
                stats_file_path = os.path.join(logs_dir, 'upload_stats.json')
            else:
                # Fallback to current directory logs
                stats_file_path = os.path.join(os.getcwd(), 'logs', 'upload_stats.json')
            
            # Load statistics from file
            if os.path.exists(stats_file_path):
                import json
                with open(stats_file_path, 'r') as f:
                    stats_data = json.load(f)
                
                # Update UI with loaded statistics
                self.upload_stats_labels['sram_uploads'].setText(str(stats_data.get('sram_uploads', 0)))
                self.upload_stats_labels['flash_uploads'].setText(str(stats_data.get('flash_uploads', 0)))
                
                # Calculate total uploads
                if 'last_upload' in self.upload_stats_labels:
                    self.upload_stats_labels['last_upload'].setText(stats_data.get('last_upload', 'Never'))
                
                logging.info(f"📊 Loaded upload statistics: SRAM={stats_data.get('sram_uploads', 0)}, Flash={stats_data.get('flash_uploads', 0)}, Last={stats_data.get('last_upload', 'Never')}")
            else:
                # Create empty stats file if it doesn't exist
                import json
                os.makedirs(os.path.dirname(stats_file_path), exist_ok=True)
                default_stats = {
                    "sram_uploads": 0,
                    "flash_uploads": 0,
                    "total_uploads": 0,
                    "last_upload": "Never",
                    "last_upload_time": None
                }
                with open(stats_file_path, 'w') as f:
                    json.dump(default_stats, f, indent=2)
                
                # Set default values in UI
                self.upload_stats_labels['sram_uploads'].setText("0")
                self.upload_stats_labels['flash_uploads'].setText("0")
                if 'last_upload' in self.upload_stats_labels:
                    self.upload_stats_labels['last_upload'].setText("Never")
                
                logging.info("📊 Created new upload statistics file with default values")
                
        except Exception as e:
            logging.error(f"Error loading upload statistics: {e}")
            # Set default values on error
            self.upload_stats_labels['sram_uploads'].setText("0")
            self.upload_stats_labels['flash_uploads'].setText("0")
            if 'last_upload' in self.upload_stats_labels:
                self.upload_stats_labels['last_upload'].setText("Never")
    
    def _update_upload_statistics(self, upload_type, design_name):
        """Update upload statistics and save to JSON file.
        
        Args:
            upload_type: 'sram' or 'flash'
            design_name: Name of the design that was uploaded
        """
        try:
            # Find the upload stats file
            from cc_project_manager_pkg.hierarchy_manager import HierarchyManager
            hierarchy = HierarchyManager()
            
            # Get log file path from project structure
            if hierarchy.config and 'project_structure' in hierarchy.config:
                logs_dir = hierarchy.config['project_structure']['logs'][0]
                stats_file_path = os.path.join(logs_dir, 'upload_stats.json')
            else:
                # Fallback to current directory logs
                stats_file_path = os.path.join(os.getcwd(), 'logs', 'upload_stats.json')
            
            # Load existing statistics
            import json
            if os.path.exists(stats_file_path):
                with open(stats_file_path, 'r') as f:
                    stats_data = json.load(f)
            else:
                stats_data = {
                    "sram_uploads": 0,
                    "flash_uploads": 0,
                    "total_uploads": 0,
                    "last_upload": "Never",
                    "last_upload_time": None
                }
            
            # Update statistics
            if upload_type == 'sram':
                stats_data['sram_uploads'] = stats_data.get('sram_uploads', 0) + 1
            elif upload_type == 'flash':
                stats_data['flash_uploads'] = stats_data.get('flash_uploads', 0) + 1
            
            # Update total uploads
            stats_data['total_uploads'] = stats_data.get('sram_uploads', 0) + stats_data.get('flash_uploads', 0)
            
            # Update last upload info
            from datetime import datetime
            now = datetime.now()
            upload_type_display = upload_type.upper()
            stats_data['last_upload'] = f"{design_name} ({upload_type_display}) - {now.strftime('%H:%M:%S')}"
            stats_data['last_upload_time'] = now.isoformat()
            
            # Save updated statistics
            os.makedirs(os.path.dirname(stats_file_path), exist_ok=True)
            with open(stats_file_path, 'w') as f:
                json.dump(stats_data, f, indent=2)
            
            logging.info(f"📊 Updated upload statistics: {upload_type_display} upload count incremented, last upload: {stats_data['last_upload']}")
            
            # Refresh the UI to show updated statistics
            self._load_upload_statistics()
            
        except Exception as e:
            logging.error(f"Error updating upload statistics: {e}")
    
    def _blink_upload_activity(self):
        """Blink the upload activity indicator."""
        if not self.upload_in_progress:
            return
            
        self.upload_activity_blink_state = not self.upload_activity_blink_state
        
        if self.upload_activity_blink_state:
            self.upload_activity_label.setText("Upload Status: 🔄 Programming...")
            self.upload_activity_label.setStyleSheet("font-weight: bold; color: #FFA726; margin-top: 5px;")
        else:
            self.upload_activity_label.setText("Upload Status: ⚡ Programming...")
            self.upload_activity_label.setStyleSheet("font-weight: bold; color: #FF9800; margin-top: 5px;")
    
    def _start_upload_activity(self, operation_name="Programming"):
        """Start the upload activity indicator."""
        self.upload_in_progress = True
        self.upload_activity_label.setText(f"Upload Status: 🔄 {operation_name}...")
        self.upload_activity_label.setStyleSheet("font-weight: bold; color: #FFA726; margin-top: 5px;")
        self.upload_progress_bar.setVisible(True)
        self.upload_progress_bar.setRange(0, 0)  # Indeterminate progress
        self.upload_activity_timer.start(500)  # Blink every 500ms
        
    def _stop_upload_activity(self, success=True, message="Complete"):
        """Stop the upload activity indicator."""
        self.upload_in_progress = False
        self.upload_activity_timer.stop()
        self.upload_progress_bar.setVisible(False)
        
        if success:
            self.upload_activity_label.setText(f"Upload Status: ✅ {message}")
            self.upload_activity_label.setStyleSheet("font-weight: bold; color: #4CAF50; margin-top: 5px;")
        else:
            self.upload_activity_label.setText(f"Upload Status: ❌ {message}")
            self.upload_activity_label.setStyleSheet("font-weight: bold; color: #F44336; margin-top: 5px;")
        
        # Reset to ready after 3 seconds
        QTimer.singleShot(3000, self._reset_upload_activity)
    
    def _reset_upload_activity(self):
        """Reset upload activity indicator to ready state."""
        if not self.upload_in_progress:  # Only reset if no operation is running
            self.upload_activity_label.setText("Upload Status: Ready")
            self.upload_activity_label.setStyleSheet("font-weight: bold; color: #888888; margin-top: 5px;")
    
    def _update_upload_progress(self, progress_text):
        """Update upload progress based on openFPGALoader output."""
        try:
            # Look for percentage indicators in the output
            import re
            
            # Common progress patterns from openFPGALoader
            percentage_match = re.search(r'(\d+)%', progress_text)
            if percentage_match:
                percentage = int(percentage_match.group(1))
                self.upload_progress_bar.setRange(0, 100)
                self.upload_progress_bar.setValue(percentage)
                self.upload_activity_label.setText(f"Upload Status: 📤 Programming {percentage}%")
                return
            
            # Look for specific operation indicators
            if "Erasing" in progress_text or "erase" in progress_text.lower():
                self.upload_activity_label.setText("Upload Status: 🗑️ Erasing...")
            elif "Writing" in progress_text or "write" in progress_text.lower():
                self.upload_activity_label.setText("Upload Status: 📝 Writing...")
            elif "Verifying" in progress_text or "verify" in progress_text.lower():
                self.upload_activity_label.setText("Upload Status: ✅ Verifying...")
            elif "Done" in progress_text or "done" in progress_text.lower():
                self.upload_activity_label.setText("Upload Status: ✅ Complete")
            
        except Exception as e:
            logging.debug(f"Error parsing upload progress: {e}")
    
    def _find_bitstream_files(self):
        """Find available bitstream files in the project."""
        bitstream_files = []
        
        try:
            # Look for bitstream files in the bitstream directory
            from cc_project_manager_pkg.hierarchy_manager import HierarchyManager
            hierarchy = HierarchyManager()
            
            # Get project structure from config
            if hierarchy.config and 'project_structure' in hierarchy.config:
                project_structure = hierarchy.config['project_structure']
                
                if 'impl' in project_structure and 'bitstream' in project_structure['impl']:
                    bitstream_dir = project_structure['impl']['bitstream'][0]
                    
                    if os.path.exists(bitstream_dir):
                        for file_name in os.listdir(bitstream_dir):
                            if file_name.endswith('.bit') or file_name.endswith('.cfg') or file_name.endswith('.cdf'):
                                file_path = os.path.join(bitstream_dir, file_name)
                                file_stat = os.stat(file_path)
                                
                                # Extract design name from filename
                                design_name = file_name.split('.')[0]
                                if file_name.endswith('.bit'):
                                    file_type = "Bitstream"
                                elif file_name.endswith('.cdf'):
                                    file_type = "GateMate CDF"
                                else:
                                    file_type = "Configuration"
                                
                                bitstream_files.append({
                                    "name": file_name,
                                    "path": file_path,
                                    "design": design_name,
                                    "size": file_stat.st_size,
                                    "modified": datetime.datetime.fromtimestamp(file_stat.st_mtime),
                                    "type": file_type
                                })
                    else:
                        logging.warning(f"Bitstream directory does not exist: {bitstream_dir}")
                else:
                    logging.warning("No bitstream directory found in project structure")
            else:
                logging.warning("No project structure found in configuration")
            
        except Exception as e:
            logging.error(f"Error finding bitstream files: {e}")
        
        return bitstream_files
    
    def _on_bitstream_tree_clicked(self, item, column):
        """Handle bitstream tree item click."""
        if item and item.data(0, Qt.UserRole):
            bitstream_data = item.data(0, Qt.UserRole)
            bitstream_name = item.text(0)
            design_name = bitstream_data.get("design", "Unknown")
            
            # Update selected bitstream label
            self.selected_bitstream_label.setText(f"Selected Bitstream: {bitstream_name} ({design_name})")
            self.selected_bitstream_label.setStyleSheet("font-weight: bold; color: #4CAF50;")
            
            # Store selection
            self.selected_bitstream = bitstream_data
            self.selected_bitstream_item = item
            
            # Highlight selected item
            self._highlight_selected_bitstream(item)
            
            logging.info(f"Selected bitstream: {bitstream_name} for design {design_name}")
    
    def _highlight_selected_bitstream(self, item):
        """Highlight the selected bitstream item."""
        # Clear previous highlighting
        self._clear_bitstream_highlighting()
        
        # Highlight selected item
        for col in range(self.bitstream_tree.columnCount()):
            item.setBackground(col, QColor("#2E3440"))
            item.setForeground(col, QColor("#88C0D0"))
    
    def _clear_bitstream_highlighting(self):
        """Clear bitstream highlighting."""
        for i in range(self.bitstream_tree.topLevelItemCount()):
            item = self.bitstream_tree.topLevelItem(i)
            for col in range(self.bitstream_tree.columnCount()):
                item.setBackground(col, QColor())
                # Restore original colors
                if col == 0:
                    item.setForeground(col, QColor("#ffffff"))
                elif col == 1:
                    item.setForeground(col, QColor("#4CAF50"))
                elif col == 2:
                    item.setForeground(col, QColor("#FFA726"))
                elif col == 3:
                    item.setForeground(col, QColor("#888888"))
                elif col == 4:
                    item.setForeground(col, QColor("#64b5f6"))
                elif col == 5:
                    item.setForeground(col, QColor("#4CAF50"))
    
    def open_board_selection_dialog(self):
        """Open the FPGA board selection dialog."""
        try:
            # Get current board configuration
            current_board = getattr(self, 'selected_board', {'name': 'Olimex GateMate EVB', 'identifier': 'olimex_gatemateevb'})
            
            # Open the dialog
            dialog = FPGABoardSelectionDialog(self, current_board)
            
            if dialog.exec_() == QDialog.Accepted:
                # Update the selected board
                self.selected_board = dialog.get_selected_board()
                
                # Check if connection test was successful
                connection_successful = dialog.was_connection_successful()
                
                # Update the device status based on connection test result
                if connection_successful:
                    self.device_status_label.setText("FPGA Device: ✅ Detected")
                    self.device_status_label.setStyleSheet("font-weight: bold; color: #4CAF50;")
                    logging.info(f"✅ FPGA Device status updated to 'Detected' after successful connection test")
                else:
                    # Still update the board selection but keep device status as not detected
                    self.device_status_label.setText("FPGA Device: ⚠️ Not detected")
                    self.device_status_label.setStyleSheet("font-weight: bold; color: #FFA726;")
                    logging.warning(f"⚠️ FPGA Device status remains 'Not detected' after failed connection test")
                
                # Update other upload status elements (but don't run full device detection again)
                self.refresh_upload_status_without_device_check()
                
                logging.info(f"✅ Board selection updated: {self.selected_board['name']} ({self.selected_board['identifier']})")
                
                # Show confirmation message with connection status
                connection_msg = "✅ Connection verified" if connection_successful else "⚠️ Connection not verified"
                QMessageBox.information(self, "Board Selection Updated", 
                                      f"Selected board: {self.selected_board['name']}\n"
                                      f"Identifier: {self.selected_board['identifier']}\n"
                                      f"Status: {connection_msg}\n\n"
                                      f"All upload operations will now use this board configuration.")
            
        except Exception as e:
            logging.error(f"Error opening board selection dialog: {e}")
            QMessageBox.critical(self, "Error", f"Failed to open board selection dialog:\n\n{str(e)}")
    
    def program_sram(self):
        """Program bitstream to FPGA SRAM (volatile)."""
        if not self.selected_bitstream:
            QMessageBox.warning(self, "No Bitstream Selected", 
                              "Please select a bitstream file from the list first.")
            return
        
        # Start activity indicator
        self._start_upload_activity("SRAM Programming")
        
        def sram_program_operation():
            logging.info("Starting SRAM programming...")
            from cc_project_manager_pkg.openfpgaloader_manager import OpenFPGALoaderManager
            
            # Use selected board for programming
            board_identifier = self.selected_board['identifier']
            board_name = self.selected_board['name']
            upload_manager = OpenFPGALoaderManager(device=board_identifier)
            
            bitstream_path = self.selected_bitstream["path"]
            design_name = self.selected_bitstream["design"]
            
            logging.info(f"Programming {design_name} to SRAM on {board_name}: {bitstream_path}")
            
            # Program SRAM with board specification and verbose output for progress tracking
            board_options = ["-b", board_identifier, "--verbose"]
            result = upload_manager.program_sram(bitstream_path, options=board_options)
            
            if result:
                logging.info(f"✅ Successfully programmed {design_name} to {board_name} SRAM")
                return f"Successfully programmed {design_name} to {board_name} SRAM"
            else:
                logging.error(f"❌ Failed to program {design_name} to {board_name} SRAM")
                raise Exception(f"Failed to program {design_name} to {board_name} SRAM")
        
        self.run_in_thread(sram_program_operation, success_msg="SRAM programming completed")
    
    def program_flash(self):
        """Program bitstream to FPGA Flash (non-volatile)."""
        if not self.selected_bitstream:
            QMessageBox.warning(self, "No Bitstream Selected", 
                              "Please select a bitstream file from the list first.")
            return
        
        # Start activity indicator
        self._start_upload_activity("Flash Programming")
        
        def flash_program_operation():
            logging.info("Starting Flash programming...")
            from cc_project_manager_pkg.openfpgaloader_manager import OpenFPGALoaderManager
            
            # Use selected board for programming
            board_identifier = self.selected_board['identifier']
            board_name = self.selected_board['name']
            upload_manager = OpenFPGALoaderManager(device=board_identifier)
            
            bitstream_path = self.selected_bitstream["path"]
            design_name = self.selected_bitstream["design"]
            
            logging.info(f"Programming {design_name} to Flash on {board_name}: {bitstream_path}")
            
            # Program Flash with board specification and verbose output for progress tracking
            board_options = ["-b", board_identifier, "--verbose"]
            result = upload_manager.program_flash(bitstream_path, options=board_options)
            
            if result:
                logging.info(f"✅ Successfully programmed {design_name} to {board_name} Flash")
                return f"Successfully programmed {design_name} to {board_name} Flash"
            else:
                logging.error(f"❌ Failed to program {design_name} to {board_name} Flash")
                raise Exception(f"Failed to program {design_name} to {board_name} Flash")
        
        self.run_in_thread(flash_program_operation, success_msg="Flash programming completed")
    
    def detect_fpga_devices(self):
        """Detect connected FPGA devices and cables."""
        def detect_operation():
            logging.info("Detecting FPGA devices...")
            from cc_project_manager_pkg.openfpgaloader_manager import OpenFPGALoaderManager
            
            # Use selected board for device detection
            board_identifier = self.selected_board['identifier']
            board_name = self.selected_board['name']
            upload_manager = OpenFPGALoaderManager(device=board_identifier)
            
            logging.info(f"Detecting devices for {board_name}...")
            
            # Detect devices (returns bool)
            device_detected = upload_manager.detect_devices()
            
            if device_detected:
                result = f"{board_name} device detected successfully. Check logs for details."
                logging.info(f"✅ {result}")
                return result
            else:
                logging.warning(f"⚠️ No {board_name} devices detected")
                return f"No {board_name} devices detected. Check connections and drivers."
        
        self.run_in_thread(detect_operation, success_msg="Device detection completed")
    
    def verify_bitstream(self):
        """Verify programmed bitstream against file."""
        if not self.selected_bitstream:
            QMessageBox.warning(self, "No Bitstream Selected", 
                              "Please select a bitstream file from the list first.")
            return
        
        # Start activity indicator
        self._start_upload_activity("Verification")
        
        def verify_operation():
            logging.info("Starting bitstream verification...")
            from cc_project_manager_pkg.openfpgaloader_manager import OpenFPGALoaderManager
            
            # Use selected board for verification
            board_identifier = self.selected_board['identifier']
            board_name = self.selected_board['name']
            upload_manager = OpenFPGALoaderManager(device=board_identifier)
            
            bitstream_path = self.selected_bitstream["path"]
            design_name = self.selected_bitstream["design"]
            
            logging.info(f"Verifying {design_name} on {board_name}: {bitstream_path}")
            
            # Verify bitstream with board specification and verbose output for progress tracking
            board_options = ["-b", board_identifier, "--verbose"]
            result = upload_manager.verify_bitstream(bitstream_path, options=board_options)
            
            if result:
                logging.info(f"✅ Successfully verified {design_name} on {board_name}")
                return f"Successfully verified {design_name} bitstream on {board_name}"
            else:
                logging.error(f"❌ Failed to verify {design_name} on {board_name}")
                raise Exception(f"Failed to verify {design_name} bitstream on {board_name}")
        
        self.run_in_thread(verify_operation, success_msg="Bitstream verification completed")
    
    def view_upload_logs(self):
        """View openFPGALoader log files and programming history."""
        try:
            # Find the openFPGALoader log file
            from cc_project_manager_pkg.hierarchy_manager import HierarchyManager
            hierarchy = HierarchyManager()
            
            # Get log file path from project structure
            if hierarchy.config and 'project_structure' in hierarchy.config:
                logs_dir = hierarchy.config['project_structure']['logs'][0]
                log_file_path = os.path.join(logs_dir, 'openfpgaloader.log')
            else:
                # Fallback to current directory logs
                log_file_path = os.path.join(os.getcwd(), 'logs', 'openfpgaloader.log')
            
            if not os.path.exists(log_file_path):
                # Create empty log file if it doesn't exist
                os.makedirs(os.path.dirname(log_file_path), exist_ok=True)
                with open(log_file_path, 'w') as f:
                    f.write("# openFPGALoader Log File\\n")
                    f.write("# This file contains all openFPGALoader operations and output\\n\\n")
            
            self._show_upload_log_dialog(log_file_path)
            
        except Exception as e:
            logging.error(f"Error opening upload logs: {e}")
            QMessageBox.critical(self, "Error", f"Failed to open upload logs:\\n\\n{str(e)}")
    
    def _show_upload_log_dialog(self, log_file_path):
        """Show upload log dialog with search and management features."""
        dialog = QDialog(self)
        dialog.setWindowTitle("Upload Logs - openFPGALoader")
        dialog.setModal(True)
        dialog.resize(1000, 700)
        
        layout = QVBoxLayout(dialog)
        
        # Header with file info
        header_layout = QHBoxLayout()
        
        file_info = QLabel(f"📁 Log File: {log_file_path}")
        file_info.setStyleSheet("font-weight: bold; color: #64b5f6; margin: 5px;")
        header_layout.addWidget(file_info)
        
        header_layout.addStretch()
        
        # File size info
        try:
            file_size = os.path.getsize(log_file_path)
            size_text = f"{file_size / 1024:.1f} KB" if file_size > 1024 else f"{file_size} B"
            size_label = QLabel(f"📊 Size: {size_text}")
            size_label.setStyleSheet("color: #888888; margin: 5px;")
            header_layout.addWidget(size_label)
        except:
            pass
        
        layout.addLayout(header_layout)
        
        # Search section
        search_layout = QHBoxLayout()
        
        search_label = QLabel("🔍 Search:")
        search_layout.addWidget(search_label)
        
        search_input = QLineEdit()
        search_input.setPlaceholderText("Enter search term (e.g., 'error', 'program', 'device')...")
        search_layout.addWidget(search_input)
        
        search_btn = QPushButton("Search")
        search_layout.addWidget(search_btn)
        
        layout.addLayout(search_layout)
        
        # Log content area
        upload_text = LogTextWidget()
        upload_text.setFont(QFont("Consolas", 10))
        layout.addWidget(upload_text)
        
        # Button layout
        button_layout = QHBoxLayout()
        
        refresh_btn = QPushButton("🔄 Refresh")
        refresh_btn.clicked.connect(lambda: self._refresh_upload_log_content(upload_text, log_file_path))
        button_layout.addWidget(refresh_btn)
        
        clear_btn = QPushButton("🗑️ Clear Log")
        clear_btn.clicked.connect(lambda: self._clear_upload_log(upload_text, log_file_path))
        button_layout.addWidget(clear_btn)
        
        save_btn = QPushButton("💾 Save As...")
        save_btn.clicked.connect(lambda: self._save_log_content(upload_text))
        button_layout.addWidget(save_btn)
        
        # Search functionality
        def perform_search():
            search_term = search_input.text().strip()
            if search_term:
                self._search_in_text_widget(upload_text, search_term)
        
        def find_upload_commands():
            # Search for common openFPGALoader command patterns
            patterns = [
                "openFPGALoader",
                "Programming",
                "Device detected",
                "SRAM",
                "Flash",
                "Verify",
                "ERROR",
                "WARNING"
            ]
            
            content = upload_text.toPlainText()
            matches = []
            
            for pattern in patterns:
                lines = [line for line in content.split('\\n') if pattern.lower() in line.lower()]
                if lines:
                    matches.extend([f"=== {pattern} ===" + "\\n" + "\\n".join(lines[:5])])
            
            if matches:
                result_text = "\\n\\n".join(matches)
                upload_text.setPlainText(result_text)
            else:
                upload_text.setPlainText("No openFPGALoader commands found in log file.")
        
        search_btn.clicked.connect(perform_search)
        search_input.returnPressed.connect(perform_search)
        
        # Quick search buttons
        quick_search_layout = QHBoxLayout()
        quick_buttons = [
            ("🔧 Commands", find_upload_commands),
            ("❌ Errors", lambda: self._search_in_text_widget(upload_text, "ERROR")),
            ("⚠️ Warnings", lambda: self._search_in_text_widget(upload_text, "WARNING")),
            ("📡 Programming", lambda: self._search_in_text_widget(upload_text, "Programming")),
            ("🔍 Device", lambda: self._search_in_text_widget(upload_text, "Device"))
        ]
        
        for btn_text, btn_callback in quick_buttons:
            btn = QPushButton(btn_text)
            btn.clicked.connect(btn_callback)
            btn.setMaximumWidth(120)
            quick_search_layout.addWidget(btn)
        
        button_layout.addLayout(quick_search_layout)
        
        button_layout.addStretch()
        
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(dialog.accept)
        button_layout.addWidget(close_btn)
        
        layout.addLayout(button_layout)
        
        # Load initial content
        self._refresh_upload_log_content(upload_text, log_file_path)
        
        dialog.exec_()
    
    def _refresh_upload_log_content(self, text_widget, log_file_path):
        """Refresh upload log content with formatting."""
        try:
            if os.path.exists(log_file_path):
                with open(log_file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                
                # Format the content for better readability
                formatted_content = self._format_upload_log(content)
                text_widget.setPlainText(formatted_content)
                
                # Scroll to bottom to show latest entries
                cursor = text_widget.textCursor()
                cursor.movePosition(cursor.End)
                text_widget.setTextCursor(cursor)
                
                logging.info(f"✅ Refreshed upload log content from {log_file_path}")
            else:
                text_widget.setPlainText(f"Log file not found: {log_file_path}")
                logging.warning(f"Upload log file not found: {log_file_path}")
                
        except Exception as e:
            error_msg = f"Error reading upload log file: {e}"
            text_widget.setPlainText(error_msg)
            logging.error(f"Error refreshing upload log content: {e}")
    
    def _format_upload_log(self, content):
        """Format upload log content for better readability."""
        lines = content.split('\\n')
        formatted_lines = []
        
        for line in lines:
            # Highlight important log levels and openFPGALoader operations
            if ' - ERROR - ' in line:
                formatted_lines.append(f"🔴 {line}")
            elif ' - WARNING - ' in line:
                formatted_lines.append(f"🟡 {line}")
            elif ' - INFO - ' in line and any(keyword in line.lower() for keyword in ['openfpgaloader', 'programming', 'device', 'sram', 'flash']):
                formatted_lines.append(f"🔵 {line}")
            elif 'openFPGALoader' in line:
                formatted_lines.append(f"⚡ {line}")
            elif 'Programming' in line or 'programming' in line:
                formatted_lines.append(f"📡 {line}")
            elif 'Device detected' in line or 'device detected' in line:
                formatted_lines.append(f"🔍 {line}")
            elif 'Successfully' in line or 'successfully' in line:
                formatted_lines.append(f"✅ {line}")
            elif 'Failed' in line or 'failed' in line or 'Error' in line:
                formatted_lines.append(f"❌ {line}")
            else:
                formatted_lines.append(line)
        
        return '\\n'.join(formatted_lines)
    
    def _clear_upload_log(self, text_widget, log_file_path):
        """Clear upload log file and display."""
        reply = QMessageBox.question(
            self, 
            "Clear Upload Log File", 
            f"This will permanently delete the openFPGALoader log file:\\n\\n{log_file_path}\\n\\nThis action cannot be undone. Are you sure?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            try:
                # Clear the log file by truncating it
                if os.path.exists(log_file_path):
                    with open(log_file_path, 'w') as f:
                        f.truncate(0)  # Clear the file content
                    logging.info(f"✅ Cleared upload log file: {log_file_path}")
                    
                    # Also clear the display
                    text_widget.clear()
                    text_widget.append("📝 openFPGALoader log file has been cleared.")
                    text_widget.append("🔄 Run an upload operation to generate new log entries.")
                    
                    # Log to the main application log
                    logging.info("openFPGALoader log file cleared by user")
                else:
                    logging.warning(f"Upload log file not found: {log_file_path}")
                    text_widget.clear()
                    text_widget.append("⚠️ Upload log file not found.")
                    
            except Exception as e:
                logging.error(f"Failed to clear upload log file: {e}")
                QMessageBox.critical(
                    self,
                    "Error",
                    f"Failed to clear upload log file:\\n\\n{str(e)}"
                )

    # Configuration Methods
    def check_toolchain_availability(self):
        """Check toolchain availability."""
        def check_tools():
            logging.info("Checking toolchain availability...")
            from cc_project_manager_pkg.toolchain_manager import ToolChainManager
            tcm = ToolChainManager()
            overall_status = tcm.check_toolchain()
            
            # Also refresh the status display
            self.refresh_toolchain_status()
            
            if overall_status:
                logging.info("Toolchain check completed - All tools are available")
                return "Toolchain check completed - All tools are available"
            else:
                logging.warning("Toolchain check completed - Some tools are missing or not configured")
                return "Toolchain check completed - Some tools are missing or not configured"
        
        # Run directly without showing success popup
        try:
            result = check_tools()
            self.status_bar.showMessage("Toolchain check completed")
        except Exception as e:
            logging.error(f"Error checking toolchain: {e}")
    
    def edit_toolchain_paths(self):
        """Edit toolchain paths."""
        logging.info("Opening toolchain path editor...")
        dialog = ToolchainPathDialog(self)
        if dialog.exec_() == QDialog.Accepted:
            # Refresh the status display in the Configuration tab
            self.refresh_toolchain_status()
            logging.info("Toolchain paths updated successfully")
    
    def configure_gtkwave(self):
        """Configure GTKWave settings."""
        logging.info("Opening GTKWave configuration...")
        dialog = GTKWaveConfigDialog(self)
        if dialog.exec_() == QDialog.Accepted:
            # Refresh the status display in the Configuration tab
            self.refresh_toolchain_status()
            logging.info("GTKWave configuration updated successfully")
    
    def check_project_configuration(self):
        """Check project configuration."""
        def check_config():
            logging.info("Checking project configuration...")
            from cc_project_manager_pkg.hierarchy_manager import HierarchyManager
            hierarchy = HierarchyManager()
            
            issues = []
            
            # Check if project configuration exists
            if not hierarchy.config_path or not os.path.exists(hierarchy.config_path):
                issues.append("No project configuration file found")
                return "❌ No project configuration file found. Create a new project to generate proper configuration."
            
            # Check project hierarchy
            project_hierarchy = hierarchy.get_hierarchy()
            if project_hierarchy is True:
                issues.append("No project hierarchy found in configuration")
            
            # Check file paths
            files_info = hierarchy.get_source_files_info()
            missing_files = 0
            total_files = 0
            
            for category, files in files_info.items():
                for file_name, file_path in files.items():
                    total_files += 1
                    if not os.path.exists(file_path):
                        missing_files += 1
                        issues.append(f"Missing file: {file_name} ({file_path})")
            
            # Generate report
            if not issues:
                return f"✅ Project configuration is valid. {total_files} files tracked, all present."
            else:
                issue_summary = f"⚠️ Found {len(issues)} configuration issues:\n" + "\n".join(f"• {issue}" for issue in issues[:5])
                if len(issues) > 5:
                    issue_summary += f"\n... and {len(issues) - 5} more issues"
                return issue_summary
        
        self.run_in_thread(check_config, success_msg="Configuration check completed")
    
    # Utility Methods
    def save_log(self):
        """Save log to file."""
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save Log", "project_log.txt", "Text Files (*.txt);;All Files (*)"
        )
        
        if file_path:
            try:
                with open(file_path, 'w') as f:
                    f.write(self.log_widget.toPlainText())
                logging.info(f"Log saved to {file_path}")
            except Exception as e:
                logging.error(f"Failed to save log: {str(e)}")
    
    def show_about(self):
        """Show about dialog."""
        QMessageBox.about(
            self, 
            "About", 
            "GateMate Project Manager by JOCRIX v0.1\n\n"
            "A modern GUI for managing GateMate FPGA projects\n"
            "using Yosys, GHDL, and other open-source tools.\n\n"
            "Created by JOCRIX"
        )
    
    def closeEvent(self, event):
        """Handle application close event."""
        if self.worker_thread and self.worker_thread.isRunning():
            reply = self.show_message(
                "Confirm Exit", 
                "An operation is currently running. Are you sure you want to exit?", 
                "question"
            )
            if not reply:
                event.ignore()
                return
            
            self.worker_thread.terminate()
        
        event.accept()
    
    # Helper methods for synthesis functionality
    def _get_synthesis_configuration(self):
        """Get the current synthesis configuration from project config."""
        try:
            from cc_project_manager_pkg.toolchain_manager import ToolChainManager
            tcm = ToolChainManager()
            config = tcm.config
            
            # Get default configuration
            default_config = self._load_synthesis_defaults()
            
            # Check if synthesis configuration exists
            if "synthesis_configuration" not in config:
                # No configuration exists, save defaults automatically
                self._save_synthesis_configuration(default_config)
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
                    self._save_synthesis_configuration(synth_config)
                    
            return synth_config
            
        except Exception as e:
            logging.warning(f"Could not read synthesis configuration: {e}")
            # Return hardcoded defaults if config can't be read
            return self._load_synthesis_defaults()
    
    def _load_synthesis_defaults(self):
        """Load synthesis defaults from synthesis_options.yml or return hardcoded defaults."""
        try:
            from cc_project_manager_pkg.toolchain_manager import ToolChainManager
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
                    
        except Exception:
            # If anything fails, continue to hardcoded defaults
            pass
            
        # Hardcoded fallback defaults
        return {
            "strategy": "balanced",
            "vhdl_standard": "VHDL-2008",
            "ieee_library": "synopsys",
            "default_target": "GateMate FPGA",
            "custom_yosys_options": []
        }
    
    def _save_synthesis_configuration(self, config_dict):
        """Save synthesis configuration to project config."""
        try:
            from cc_project_manager_pkg.toolchain_manager import ToolChainManager
            tcm = ToolChainManager()
            
            # Update the synthesis configuration section
            tcm.config["synthesis_configuration"] = config_dict
            
            # Write back to config file
            import yaml
            with open(tcm.config_path, "w") as config_file:
                yaml.safe_dump(tcm.config, config_file)
                
            return True
            
        except Exception as e:
            logging.error(f"Error saving synthesis configuration: {e}")
            return False

    def _get_simulation_configuration(self):
        """Get the current simulation configuration from project config."""
        try:
            from cc_project_manager_pkg.toolchain_manager import ToolChainManager
            tcm = ToolChainManager()
            config = tcm.config
            
            # Get default configuration
            default_config = self._load_simulation_defaults()
            
            # Check if simulation configuration exists
            if "simulation_configuration" not in config:
                # No configuration exists, save defaults automatically
                self._save_simulation_configuration(default_config)
                sim_config = default_config.copy()
            else:
                # Get existing simulation configuration
                sim_config = config["simulation_configuration"]
                
                # Ensure all required keys exist, add missing ones
                updated = False
                for key, default_value in default_config.items():
                    if key not in sim_config:
                        sim_config[key] = default_value
                        updated = True
                
                # Save updated configuration if we added missing keys
                if updated:
                    self._save_simulation_configuration(sim_config)
            
            return sim_config
            
        except Exception as e:
            logging.warning(f"Could not read simulation configuration: {e}")
            # Return hardcoded defaults if config can't be read
            return self._load_simulation_defaults()
    
    def _load_simulation_defaults(self):
        """Load simulation defaults or return hardcoded defaults."""
        try:
            from cc_project_manager_pkg.toolchain_manager import ToolChainManager
            tcm = ToolChainManager()
            
            # Check if simulation_config.yml exists
            config_dir = tcm.config.get("project_structure", {}).get("config", [])
            if isinstance(config_dir, list) and config_dir:
                simulation_config_path = os.path.join(config_dir[0], "simulation_config.yml")
            else:
                simulation_config_path = os.path.join(config_dir, "simulation_config.yml")
            
            if os.path.exists(simulation_config_path):
                import yaml
                with open(simulation_config_path, 'r') as f:
                    sim_config_file = yaml.safe_load(f)
                
                if sim_config_file and "default_simulation_settings" in sim_config_file:
                    defaults = sim_config_file["default_simulation_settings"]
                    return {
                        "vhdl_standard": "VHDL-2008",
                        "ieee_library": "synopsys",
                        "simulation_time": defaults.get("simulation_time", 1000),
                        "time_prefix": defaults.get("time_prefix", "ns"),
                        "verbose": False,
                        "save_waveforms": True
                    }
        except Exception:
            # If anything fails, continue to hardcoded defaults
            pass
            
        # Hardcoded fallback defaults
        return {
            "vhdl_standard": "VHDL-2008",
            "ieee_library": "synopsys",
            "simulation_time": 1000,
            "time_prefix": "ns",
            "verbose": False,
            "save_waveforms": True
        }
    
    def _save_simulation_configuration(self, config_dict):
        """Save simulation configuration to project config."""
        try:
            from cc_project_manager_pkg.toolchain_manager import ToolChainManager
            tcm = ToolChainManager()
            
            # Update the simulation configuration section
            tcm.config["simulation_configuration"] = config_dict
            
            # Also update the existing simulation_settings section for backward compatibility
            tcm.config["simulation_settings"] = {
                "simulation_time": config_dict["simulation_time"],
                "time_prefix": config_dict["time_prefix"]
            }
            
            # Write back to config file
            import yaml
            with open(tcm.config_path, "w") as config_file:
                yaml.safe_dump(tcm.config, config_file)
                
            return True
            
        except Exception as e:
            logging.error(f"Error saving simulation configuration: {e}")
            return False

    def _find_available_vhdl_entities(self):
        """Find available VHDL entities in the project with their type information."""
        try:
            from cc_project_manager_pkg.hierarchy_manager import HierarchyManager
            hierarchy = HierarchyManager()
            
            # Get all VHDL files from the project
            files_info = hierarchy.get_source_files_info()
            entities_with_type = {}
            
            # Parse each VHDL file to find entities
            for category, files in files_info.items():
                for file_name, file_path in files.items():
                    if os.path.exists(file_path) and file_path.lower().endswith(('.vhd', '.vhdl')):
                        try:
                            with open(file_path, 'r', encoding='utf-8') as f:
                                content = f.read()
                                
                            # Simple regex to find entity declarations (case-insensitive but preserve original case)
                            import re
                            entity_matches = re.findall(r'entity\s+(\w+)\s+is', content, re.IGNORECASE)
                            
                            # Map category to display type
                            display_type = {
                                'src': 'Source',
                                'top': 'Top',
                                'testbench': 'Testbench'
                            }.get(category, 'Unknown')
                            
                            for entity in entity_matches:
                                # If entity already exists, prefer non-testbench types
                                if entity in entities_with_type:
                                    if category != 'testbench' and entities_with_type[entity] == 'Testbench':
                                        entities_with_type[entity] = display_type
                                else:
                                    entities_with_type[entity] = display_type
                            
                        except Exception as e:
                            logging.warning(f"Could not parse {file_path}: {e}")
                            continue
            
            return entities_with_type
            
        except Exception as e:
            logging.warning(f"Could not find VHDL entities: {e}")
            return {}
    
    def _find_entity_source_file(self, entity_name):
        """Find the source file containing the specified entity."""
        try:
            from cc_project_manager_pkg.hierarchy_manager import HierarchyManager
            hierarchy = HierarchyManager()
            
            # Get all VHDL files from the project
            files_info = hierarchy.get_source_files_info()
            
            # Parse each VHDL file to find the entity
            for category, files in files_info.items():
                for file_name, file_path in files.items():
                    if os.path.exists(file_path) and file_path.lower().endswith(('.vhd', '.vhdl')):
                        try:
                            with open(file_path, 'r', encoding='utf-8') as f:
                                content = f.read()
                                
                            # Simple regex to find entity declarations (case-insensitive)
                            import re
                            entity_matches = re.findall(r'entity\s+(\w+)\s+is', content, re.IGNORECASE)
                            if entity_name.lower() in [match.lower() for match in entity_matches]:
                                return os.path.relpath(file_path)
                                
                        except Exception as e:
                            logging.warning(f"Could not parse {file_path}: {e}")
                            continue
            
            return None
            
        except Exception as e:
            logging.error(f"Error finding entity source file: {e}")
            return None
    
    def _get_project_vhdl_files(self):
        """Get all VHDL files in the project."""
        vhdl_files = []
        try:
            from cc_project_manager_pkg.hierarchy_manager import HierarchyManager
            hierarchy = HierarchyManager()
            
            # Get all VHDL files from the project
            files_info = hierarchy.get_source_files_info()
            
            # Collect all VHDL files
            for category, files in files_info.items():
                for file_name, file_path in files.items():
                    if os.path.exists(file_path) and file_path.lower().endswith(('.vhd', '.vhdl')):
                        vhdl_files.append(file_path)
            
            return sorted(vhdl_files)
            
        except Exception as e:
            logging.error(f"Error getting VHDL files: {e}")
            return []
    
    def _get_yosys_command_preview(self, yosys_instance, entity_name, use_gatemate, custom_options=None):
        """Get a preview of the Yosys command that will be executed."""
        try:
            # Get working directory
            work_dir = os.getcwd()
            
            # Get VHDL files for the command
            vhdl_files = self._get_project_vhdl_files()
            vhdl_file_names = [os.path.basename(f) for f in vhdl_files]
            
            # Construct basic command info based on YosysCommands structure
            if use_gatemate:
                # GateMate synthesis command
                command_parts = [
                    "yosys",
                    "-p",
                    f"'ghdl --std={yosys_instance.vhdl_std} --ieee={yosys_instance.ieee_lib} {' '.join(vhdl_file_names)} -e {entity_name}; synth_gatemate -top {entity_name}; write_json {entity_name}_gatemate.json; write_verilog {entity_name}_gatemate.v'"
                ]
                output_files = [f"{entity_name}_gatemate.json", f"{entity_name}_gatemate.v"]
            else:
                # Generic synthesis command
                command_parts = [
                    "yosys",
                    "-p", 
                    f"'ghdl --std={yosys_instance.vhdl_std} --ieee={yosys_instance.ieee_lib} {' '.join(vhdl_file_names)} -e {entity_name}; synth -top {entity_name}; write_json {entity_name}.json; write_verilog {entity_name}.v'"
                ]
                output_files = [f"{entity_name}.json", f"{entity_name}.v"]
            
            # Add custom options if provided
            if custom_options:
                command_parts.extend(custom_options)
            
            command = " ".join(command_parts)
            
            return {
                'command': command,
                'work_dir': work_dir,
                'output_files': output_files
            }
            
        except Exception as e:
            logging.warning(f"Could not generate command preview: {e}")
            return {
                'command': 'Command preview not available',
                'work_dir': os.getcwd(),
                'output_files': []
            }
    
    def _check_synthesis_outputs(self, entity_name, use_gatemate):
        """Check for synthesis output files."""
        output_files = []
        try:
            from cc_project_manager_pkg.toolchain_manager import ToolChainManager
            tcm = ToolChainManager()
            synth_dir = tcm.config["project_structure"]["synth"][0] if isinstance(tcm.config["project_structure"]["synth"], list) else tcm.config["project_structure"]["synth"]
            
            # Common output file patterns
            if use_gatemate:
                patterns = [
                    f"{entity_name}_gatemate.json",
                    f"{entity_name}_gatemate.v",
                    f"{entity_name}.v"
                ]
            else:
                patterns = [
                    f"{entity_name}.json",
                    f"{entity_name}.v",
                    f"{entity_name}_synth.v"
                ]
            
            # Check in synthesis directory
            if os.path.exists(synth_dir):
                for pattern in patterns:
                    file_path = os.path.join(synth_dir, pattern)
                    if os.path.exists(file_path):
                        output_files.append(file_path)
            
            # Also check current directory
            for pattern in patterns:
                if os.path.exists(pattern):
                    output_files.append(os.path.abspath(pattern))
            
            return output_files
            
        except Exception as e:
            logging.warning(f"Could not check synthesis outputs: {e}")
            return []
    
    def create_implementation_status_widget(self):
        """Create the implementation status widget showing synthesized designs and implementation results."""
        status_group = QGroupBox("Implementation Status")
        layout = QVBoxLayout(status_group)
        
        # Project info section
        info_frame = QFrame()
        info_layout = QVBoxLayout(info_frame)
        info_layout.setContentsMargins(10, 5, 10, 5)
        
        # Header with strategy info and refresh button
        header_layout = QHBoxLayout()
        
        # Implementation strategy info
        self.impl_config_label = QLabel("Implementation Strategy: Not loaded")
        self.impl_config_label.setStyleSheet("font-weight: bold; color: #64b5f6;")
        header_layout.addWidget(self.impl_config_label)
        
        header_layout.addStretch()
        
        # Refresh button
        refresh_btn = QPushButton("🔄 Refresh")
        refresh_btn.setMaximumWidth(100)
        refresh_btn.setToolTip("Refresh implementation status display")
        refresh_btn.clicked.connect(self.refresh_implementation_status)
        refresh_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 5px 10px;
                font-size: 11px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
            QPushButton:pressed {
                background-color: #3d8b40;
            }
        """)
        header_layout.addWidget(refresh_btn)
        
        info_layout.addLayout(header_layout)
        
        info_frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        layout.addWidget(info_frame)
        
        # Implementation tree
        self.implementation_tree = QTreeWidget()
        self.implementation_tree.setHeaderLabels(["Design / File", "Type", "Status", "Constraint File", "Size", "Modified"])
        
        # Configure tree widget for better display
        self.implementation_tree.setRootIsDecorated(False)
        self.implementation_tree.setAlternatingRowColors(False)
        self.implementation_tree.setUniformRowHeights(True)
        self.implementation_tree.setIndentation(15)
        
        # Enable single selection
        self.implementation_tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.implementation_tree.setFocusPolicy(Qt.StrongFocus)
        
        # Remove visual indicators
        self.implementation_tree.setItemsExpandable(False)
        self.implementation_tree.setExpandsOnDoubleClick(False)
        self.implementation_tree.setStyleSheet("")
        
        # Set column widths
        self.implementation_tree.setColumnWidth(0, 200)  # Design/File
        self.implementation_tree.setColumnWidth(1, 100)  # Type
        self.implementation_tree.setColumnWidth(2, 100)  # Status
        self.implementation_tree.setColumnWidth(3, 80)   # Size
        
        # Connect click handler for design selection
        self.implementation_tree.itemClicked.connect(self._on_implementation_tree_clicked)
        
        # Enable single selection mode for better highlighting support
        self.implementation_tree.setSelectionMode(QAbstractItemView.SingleSelection)
        
        layout.addWidget(self.implementation_tree)
        
        # Statistics section
        stats_frame = QFrame()
        stats_layout = QGridLayout(stats_frame)
        stats_layout.setContentsMargins(10, 5, 10, 5)
        
        # Create statistics labels
        self.impl_stats_labels = {}
        stats_items = [
            ('synthesized_designs', 'Synthesized Designs:', 0, 0),
            ('constraint_files', 'Constraint Files:', 0, 1),
            ('implemented_designs', 'Implemented:', 1, 0),
            ('bitstreams_generated', 'Bitstreams:', 1, 1)
        ]
        
        for key, label_text, row, col in stats_items:
            label = QLabel(label_text)
            label.setStyleSheet("color: #888888; font-size: 11px;")
            value_label = QLabel("0")
            value_label.setStyleSheet("color: #ffffff; font-weight: bold; font-size: 11px;")
            
            stats_layout.addWidget(label, row * 2, col)
            stats_layout.addWidget(value_label, row * 2 + 1, col)
            self.impl_stats_labels[key] = value_label
        
        stats_frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        layout.addWidget(stats_frame)
        
        return status_group
    
    def refresh_implementation_status(self):
        """Refresh the implementation status display."""
        try:
            logging.info("🔄 Refreshing implementation status...")
            
            # Update implementation strategy display
            self.impl_config_label.setText("Implementation Strategy: Balanced (Default)")
            self.impl_config_label.setStyleSheet("font-weight: bold; color: #4CAF50;")
            
            # Store current selection before clearing
            current_selection = getattr(self, 'selected_design', None)
            
            # Clear the tree and highlighting
            self.implementation_tree.clear()
            self.selected_tree_item = None
            
            # Find synthesized designs ready for implementation
            synthesized_designs = self._find_synthesized_designs()
            synthesized_count = len(synthesized_designs)
            
            # Find constraint files
            constraint_files = self._find_constraint_files()
            constraint_count = len(constraint_files)
            
            # Find implementation outputs
            implementation_outputs = self._find_implementation_outputs()
            implemented_count = len(implementation_outputs)
            
            # Count bitstreams
            bitstream_count = sum(1 for outputs in implementation_outputs.values() 
                                if outputs.get('bitstream_generated', False))
            
            # Add synthesized designs section
            if synthesized_designs:
                synth_item = QTreeWidgetItem(["Synthesized Designs", f"{synthesized_count} ready", "", "", ""])
                synth_item.setIcon(0, self.style().standardIcon(QStyle.SP_DirIcon))
                synth_item.setForeground(0, QColor("#ffffff"))
                synth_item.setForeground(1, QColor("#64b5f6"))
                
                for design_name, design_info in synthesized_designs.items():
                    # Check implementation status
                    impl_status = implementation_outputs.get(design_name, {})
                    if impl_status.get('placed', False):
                        status = "✅ Implemented"
                        status_color = "#4CAF50"
                    else:
                        status = "⚪ Ready for P&R"
                        status_color = "#888888"
                    
                    # Get file info
                    file_count = len(design_info.get('files', []))
                    file_info = f"{file_count} files"
                    
                    # Get timestamp
                    timestamp = design_info.get('timestamp', 'Unknown')
                    
                    design_item = QTreeWidgetItem([design_name, "Synthesis", status, file_info, timestamp])
                    design_item.setIcon(0, self.style().standardIcon(QStyle.SP_ComputerIcon))
                    design_item.setForeground(0, QColor("#ffffff"))
                    design_item.setForeground(1, QColor("#FF9800"))
                    design_item.setForeground(2, QColor(status_color))
                    design_item.setForeground(3, QColor("#64b5f6"))
                    design_item.setForeground(4, QColor("#FFA726"))
                    
                    synth_item.addChild(design_item)
                
                self.implementation_tree.addTopLevelItem(synth_item)
                synth_item.setExpanded(True)
            
            # Add constraint files section
            if constraint_files:
                const_item = QTreeWidgetItem(["Constraint Files", f"{constraint_count} available", "", "", ""])
                const_item.setIcon(0, self.style().standardIcon(QStyle.SP_DirIcon))
                const_item.setForeground(0, QColor("#ffffff"))
                const_item.setForeground(1, QColor("#9C27B0"))
                
                for file_name, file_info in constraint_files.items():
                    file_size = file_info.get('size', 0)
                    if file_size < 1024:
                        size_str = f"{file_size}B"
                    else:
                        size_str = f"{file_size/1024:.1f}KB"
                    
                    file_exists = file_info.get('exists', False)
                    status = "✅ Available" if file_exists else "❌ Missing"
                    status_color = "#4CAF50" if file_exists else "#F44336"
                    
                    timestamp = file_info.get('modified', 'Unknown')
                    
                    file_item = QTreeWidgetItem([file_name, "Constraint", status, size_str, timestamp])
                    file_item.setIcon(0, self.style().standardIcon(QStyle.SP_FileIcon))
                    file_item.setForeground(0, QColor("#ffffff"))
                    file_item.setForeground(1, QColor("#9C27B0"))
                    file_item.setForeground(2, QColor(status_color))
                    file_item.setForeground(3, QColor("#64b5f6"))
                    file_item.setForeground(4, QColor("#FFA726"))
                    
                    const_item.addChild(file_item)
                
                self.implementation_tree.addTopLevelItem(const_item)
                const_item.setExpanded(True)
            
            # Add implementation outputs section
            if implementation_outputs:
                impl_item = QTreeWidgetItem(["Implementation Outputs", f"{implemented_count} designs", "", "", ""])
                impl_item.setIcon(0, self.style().standardIcon(QStyle.SP_DirIcon))
                impl_item.setForeground(0, QColor("#ffffff"))
                impl_item.setForeground(1, QColor("#4CAF50"))
                
                for design_name, outputs in implementation_outputs.items():
                    # Show implementation status
                    status_parts = []
                    if outputs.get('placed', False):
                        status_parts.append("P&R")
                    if outputs.get('timing_analyzed', False):
                        status_parts.append("Timing")
                    if outputs.get('bitstream_generated', False):
                        status_parts.append("Bitstream")
                    if outputs.get('post_impl_netlist', False):
                        status_parts.append("Netlist")
                    
                    status = " + ".join(status_parts) if status_parts else "Pending"
                    
                    # Get file count
                    file_count = len(outputs.get('files', []))
                    file_info = f"{file_count} files"
                    
                    # Get latest timestamp
                    timestamp = outputs.get('timestamp', 'Unknown')
                    
                    # Get constraint file
                    constraint_file = outputs.get('constraint_file', 'Unknown')
                    
                    output_item = QTreeWidgetItem([design_name, "Implementation", status, constraint_file, file_info, timestamp])
                    output_item.setIcon(0, self.style().standardIcon(QStyle.SP_ComputerIcon))
                    output_item.setForeground(0, QColor("#ffffff"))
                    output_item.setForeground(1, QColor("#4CAF50"))
                    output_item.setForeground(2, QColor("#64b5f6"))
                    output_item.setForeground(3, QColor("#FF9800"))  # Constraint file - orange
                    output_item.setForeground(4, QColor("#64b5f6"))
                    output_item.setForeground(5, QColor("#FFA726"))
                    
                    # Add individual output files as children
                    output_files = outputs.get('files', [])
                    if output_files:
                        # Group files by type for better organization
                        file_groups = {
                            'Implementation': [],
                            'Bitstream': [],
                            'Timing': [],
                            'Netlist': [],
                            'Other': []
                        }
                        
                        for file_path in output_files:
                            file_name = os.path.basename(file_path)
                            file_ext = os.path.splitext(file_name)[1].lower()
                            
                            # Categorize files by type
                            if file_name.endswith('.cfg'):
                                file_groups['Implementation'].append(file_path)
                            elif file_ext in ['.bit']:
                                file_groups['Bitstream'].append(file_path)
                            elif file_ext in ['.sdf', '.rpt'] or 'timing' in file_name.lower():
                                file_groups['Timing'].append(file_path)
                            elif file_ext in ['.v', '.vhd', '.json', '.blif']:
                                file_groups['Netlist'].append(file_path)
                            else:
                                file_groups['Other'].append(file_path)
                        
                        # Add file groups as children
                        for group_name, group_files in file_groups.items():
                            if group_files:
                                # Create group header
                                group_item = QTreeWidgetItem([f"{group_name} Files", f"{len(group_files)} files", "", "", "", ""])
                                group_item.setIcon(0, self.style().standardIcon(QStyle.SP_DirIcon))
                                group_item.setForeground(0, QColor("#ffffff"))
                                group_item.setForeground(1, QColor("#9C27B0"))
                                
                                # Add individual files
                                for file_path in sorted(group_files):
                                    file_name = os.path.basename(file_path)
                                    
                                    # Get file info
                                    try:
                                        file_stat = os.stat(file_path)
                                        file_size = file_stat.st_size
                                        if file_size < 1024:
                                            size_str = f"{file_size}B"
                                        elif file_size < 1024 * 1024:
                                            size_str = f"{file_size/1024:.1f}KB"
                                        else:
                                            size_str = f"{file_size/(1024*1024):.1f}MB"
                                        
                                        file_time = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(file_stat.st_mtime))
                                    except:
                                        size_str = "Unknown"
                                        file_time = "Unknown"
                                    
                                    # Determine file type and icon
                                    file_ext = os.path.splitext(file_name)[1].lower()
                                    if file_ext == '.cfg':
                                        file_type = "Config"
                                        file_icon = QStyle.SP_FileDialogDetailedView
                                    elif file_ext == '.bit':
                                        file_type = "Bitstream"
                                        file_icon = QStyle.SP_DriveHDIcon
                                    elif file_ext in ['.sdf', '.rpt']:
                                        file_type = "Timing"
                                        file_icon = QStyle.SP_FileDialogListView
                                    elif file_ext in ['.v', '.vhd']:
                                        file_type = "Netlist"
                                        file_icon = QStyle.SP_FileIcon
                                    elif file_ext in ['.json', '.blif']:
                                        file_type = "Netlist"
                                        file_icon = QStyle.SP_FileIcon
                                    else:
                                        file_type = "File"
                                        file_icon = QStyle.SP_FileIcon
                                    
                                    file_item = QTreeWidgetItem([file_name, file_type, "✅ Available", "", size_str, file_time])
                                    file_item.setIcon(0, self.style().standardIcon(file_icon))
                                    file_item.setForeground(0, QColor("#ffffff"))
                                    file_item.setForeground(1, QColor("#64b5f6"))
                                    file_item.setForeground(2, QColor("#4CAF50"))
                                    file_item.setForeground(3, QColor("#888888"))  # Empty constraint file column
                                    file_item.setForeground(4, QColor("#64b5f6"))
                                    file_item.setForeground(5, QColor("#FFA726"))
                                    
                                    # Store file path for potential future use
                                    file_item.setData(0, Qt.UserRole, file_path)
                                    
                                    group_item.addChild(file_item)
                                
                                output_item.addChild(group_item)
                                group_item.setExpanded(True)
                    
                    impl_item.addChild(output_item)
                
                self.implementation_tree.addTopLevelItem(impl_item)
                impl_item.setExpanded(True)
            
            # Update statistics
            self.impl_stats_labels['synthesized_designs'].setText(str(synthesized_count))
            self.impl_stats_labels['constraint_files'].setText(str(constraint_count))
            self.impl_stats_labels['implemented_designs'].setText(str(implemented_count))
            self.impl_stats_labels['bitstreams_generated'].setText(str(bitstream_count))
            
            # Note: Design selection is now handled via Design/File container clicks
            
            # Resize columns
            self.implementation_tree.resizeColumnToContents(0)
            self.implementation_tree.resizeColumnToContents(1)
            self.implementation_tree.resizeColumnToContents(2)
            self.implementation_tree.resizeColumnToContents(3)
            self.implementation_tree.resizeColumnToContents(4)
            self.implementation_tree.resizeColumnToContents(5)
            
            # Set minimum widths for better display
            if self.implementation_tree.columnWidth(0) < 200:
                self.implementation_tree.setColumnWidth(0, 200)
            if self.implementation_tree.columnWidth(3) < 120:  # Constraint file column
                self.implementation_tree.setColumnWidth(3, 120)
            if self.implementation_tree.columnWidth(5) < 150:  # Modified column
                self.implementation_tree.setColumnWidth(5, 150)
            
            # Restore previous selection if it still exists
            if current_selection:
                self._restore_tree_selection(current_selection)
            
            logging.info("✅ Implementation status refresh completed successfully")
            
        except Exception as e:
            import traceback
            error_details = traceback.format_exc()
            logging.error(f"Error refreshing implementation status: {e}")
            logging.error(f"Full traceback: {error_details}")
            self.impl_config_label.setText("Implementation Strategy: Error loading")
            self.impl_config_label.setStyleSheet("font-weight: bold; color: #F44336;")
    
    def _find_constraint_files(self):
        """Find available constraint files for implementation."""
        try:
            from cc_project_manager_pkg.pnr_commands import PnRCommands
            pnr = PnRCommands()
            
            constraint_files = {}
            
            # Get constraint files from the constraints directory
            if os.path.exists(pnr.constraints_dir):
                for file_name in os.listdir(pnr.constraints_dir):
                    if file_name.endswith('.ccf'):
                        file_path = os.path.join(pnr.constraints_dir, file_name)
                        file_exists = os.path.exists(file_path)
                        
                        file_info = {
                            'exists': file_exists,
                            'path': file_path
                        }
                        
                        if file_exists:
                            try:
                                file_info['size'] = os.path.getsize(file_path)
                                file_info['modified'] = time.strftime('%Y-%m-%d %H:%M:%S', 
                                                                   time.localtime(os.path.getmtime(file_path)))
                            except:
                                file_info['size'] = 0
                                file_info['modified'] = 'Unknown'
                        else:
                            file_info['size'] = 0
                            file_info['modified'] = 'Unknown'
                        
                        constraint_files[file_name] = file_info
            
            return constraint_files
            
        except Exception as e:
            logging.error(f"Error finding constraint files: {e}")
            return {}
    
    def _get_constraint_file_for_design(self, design_name):
        """Get the constraint file that was used for a specific design implementation."""
        try:
            # Check if we have stored constraint file information for this design
            if hasattr(self, 'design_constraint_mapping') and design_name in self.design_constraint_mapping:
                return self.design_constraint_mapping[design_name]
            
            # Try to determine from log files or implementation files
            from cc_project_manager_pkg.pnr_commands import PnRCommands
            pnr = PnRCommands()
            
            # Check PnR log files for constraint file usage
            log_file = os.path.join(pnr.impl_logs_dir, "pnr_commands.log")
            if os.path.exists(log_file):
                try:
                    with open(log_file, 'r', encoding='utf-8', errors='replace') as f:
                        log_content = f.read()
                    
                    # Look for constraint file usage in logs for this design
                    lines = log_content.split('\n')
                    for line in reversed(lines):  # Start from most recent
                        if design_name in line and "constraint file" in line.lower():
                            # Extract constraint file name from log line
                            if "Using constraint file:" in line:
                                constraint_path = line.split("Using constraint file:")[-1].strip()
                                return os.path.basename(constraint_path)
                            elif "Using default constraint file:" in line:
                                constraint_path = line.split("Using default constraint file:")[-1].strip()
                                return os.path.basename(constraint_path)
                except Exception as e:
                    logging.debug(f"Error reading PnR log for constraint file info: {e}")
            
            # Fallback: check if there's a default constraint file
            default_constraint = pnr.get_default_constraint_file_path()
            if os.path.exists(default_constraint):
                return os.path.basename(default_constraint)
            
            return "Unknown"
            
        except Exception as e:
            logging.debug(f"Error getting constraint file for design {design_name}: {e}")
            return "Unknown"
    
    def _find_implementation_outputs(self):
        """Find implementation output files and their status."""
        try:
            from cc_project_manager_pkg.pnr_commands import PnRCommands
            pnr = PnRCommands()
            
            implementation_outputs = {}
            
            # Get list of designs that have been placed and routed
            placed_designs = pnr.get_available_placed_designs()
            
            for design_name in placed_designs:
                # Get implementation status for this design
                status = pnr.get_implementation_status(design_name)
                
                # Collect all output files for this design
                output_files = []
                
                # Implementation files (check both patterns)
                impl_patterns = [
                    os.path.join(pnr.work_dir, f"{design_name}_impl.cfg"),
                    os.path.join(pnr.work_dir, f"{design_name}_impl_00.cfg")
                ]
                
                for impl_file in impl_patterns:
                    if os.path.exists(impl_file):
                        output_files.append(impl_file)
                
                # Bitstream files (check both patterns)
                bitstream_patterns = [
                    os.path.join(pnr.bitstream_dir, f"{design_name}.bit"),
                    os.path.join(pnr.bitstream_dir, f"{design_name}_impl_00.cfg.bit")
                ]
                
                for bitstream_file in bitstream_patterns:
                    if os.path.exists(bitstream_file):
                        output_files.append(bitstream_file)
                
                # Timing files (check multiple patterns)
                timing_patterns = [
                    os.path.join(pnr.timing_dir, f"{design_name}_timing.rpt"),
                    os.path.join(pnr.timing_dir, f"{design_name}.sdf"),
                    os.path.join(pnr.timing_dir, f"{design_name}_impl_00.sdf")
                ]
                
                for timing_file in timing_patterns:
                    if os.path.exists(timing_file):
                        output_files.append(timing_file)
                
                # Post-implementation netlists (check both patterns)
                for fmt, ext in pnr.NETLIST_FORMATS.items():
                    netlist_patterns = [
                        os.path.join(pnr.netlist_dir, f"{design_name}_impl{ext}"),
                        os.path.join(pnr.netlist_dir, f"{design_name}_impl_00{ext}")
                    ]
                    
                    for netlist_file in netlist_patterns:
                        if os.path.exists(netlist_file):
                            output_files.append(netlist_file)
                
                # Get the most recent timestamp from output files
                latest_timestamp = "Unknown"
                if output_files:
                    try:
                        timestamps = []
                        for file_path in output_files:
                            if os.path.exists(file_path):
                                timestamps.append(os.path.getmtime(file_path))
                        
                        if timestamps:
                            latest_time = max(timestamps)
                            latest_timestamp = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(latest_time))
                    except:
                        pass
                
                implementation_outputs[design_name] = {
                    **status,  # Include all status flags
                    'files': output_files,
                    'timestamp': latest_timestamp,
                    'constraint_file': self._get_constraint_file_for_design(design_name)
                }
            
            return implementation_outputs
            
        except Exception as e:
            logging.error(f"Error finding implementation outputs: {e}")
            return {}
    
    # Helper methods for analysis reports
    def _show_analysis_dialog(self, title, content, analysis_type):
        """Show analysis report in a dialog."""
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.setModal(True)
        dialog.resize(1000, 700)
        
        layout = QVBoxLayout(dialog)
        
        # Header with analysis type info
        header_layout = QHBoxLayout()
        
        type_icons = {
            "timing": "⏱️",
            "utilization": "📊", 
            "placement": "📍",
            "power": "⚡"
        }
        
        icon = type_icons.get(analysis_type, "📋")
        header_label = QLabel(f"{icon} {title}")
        header_label.setStyleSheet("font-weight: bold; color: #64b5f6; font-size: 14px;")
        header_layout.addWidget(header_label)
        
        header_layout.addStretch()
        
        # Save button
        save_btn = QPushButton("💾 Save Report")
        save_btn.setMaximumWidth(120)
        header_layout.addWidget(save_btn)
        
        layout.addLayout(header_layout)
        
        # Content area
        content_widget = QTextEdit()
        content_widget.setReadOnly(True)
        content_widget.setFont(QFont("Consolas", 9))
        content_widget.setStyleSheet("""
            QTextEdit {
                background-color: #1e1e1e;
                color: #ffffff;
                border: 1px solid #555;
                selection-background-color: #3399ff;
            }
        """)
        
        # Set content with formatting
        if analysis_type == "timing":
            formatted_content = self._format_timing_content(content)
        elif analysis_type == "utilization":
            formatted_content = self._format_utilization_content(content)
        elif analysis_type == "placement":
            formatted_content = self._format_placement_content(content)
        elif analysis_type == "power":
            formatted_content = self._format_power_content(content)
        else:
            formatted_content = f"<pre>{content}</pre>"
        
        content_widget.setHtml(formatted_content)
        
        # Connect save button
        save_btn.clicked.connect(lambda: self._save_analysis_report(content, title))
        
        layout.addWidget(content_widget)
        
        # Close button
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(dialog.accept)
        layout.addWidget(close_btn)
        
        dialog.exec_()
    
    def _extract_timing_analysis(self, log_file):
        """Extract timing analysis from log file."""
        try:
            with open(log_file, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()
            
            # Look for timing analysis sections
            timing_sections = []
            lines = content.split('\n')
            
            in_timing_section = False
            current_section = []
            
            for line in lines:
                # Start of timing analysis
                if any(keyword in line.lower() for keyword in ['timing analysis', 'static timing', 'critical path', 'max frequency']):
                    in_timing_section = True
                    current_section = [line]
                elif in_timing_section:
                    current_section.append(line)
                    # End of timing section (empty line or new major section)
                    if not line.strip() and len(current_section) > 5:
                        timing_sections.append('\n'.join(current_section))
                        current_section = []
                        in_timing_section = False
            
            # Add any remaining section
            if current_section and len(current_section) > 3:
                timing_sections.append('\n'.join(current_section))
            
            return '\n\n'.join(timing_sections) if timing_sections else None
            
        except Exception as e:
            logging.error(f"Error extracting timing analysis: {e}")
            return None
    
    def _extract_timing_analysis_for_design(self, timing_files, design_name):
        """Extract timing analysis for a specific design from multiple files."""
        try:
            all_content = []
            
            for file_path in timing_files:
                if file_path.endswith('.sdf'):
                    # Parse SDF file
                    sdf_content = self._parse_sdf_file(file_path, design_name)
                    if sdf_content:
                        all_content.append(f"=== SDF Timing Data ({os.path.basename(file_path)}) ===")
                        all_content.append(sdf_content)
                        all_content.append("")
                else:
                    # Parse log file for design-specific timing
                    log_content = self._extract_design_timing_from_log(file_path, design_name)
                    if log_content:
                        all_content.append(f"=== Timing Analysis Log ({os.path.basename(file_path)}) ===")
                        all_content.append(log_content)
                        all_content.append("")
            
            return '\n'.join(all_content) if all_content else None
            
        except Exception as e:
            logging.error(f"Error extracting timing analysis for design {design_name}: {e}")
            return None
    
    def _parse_sdf_file(self, sdf_file, design_name):
        """Parse SDF file for timing information."""
        try:
            content = []
            with open(sdf_file, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()
            
            # Extract key timing information from SDF
            for i, line in enumerate(lines):
                line = line.strip()
                if any(keyword in line.upper() for keyword in [
                    'DELAY', 'SETUP', 'HOLD', 'TIMINGCHECK', 'CELL'
                ]):
                    content.append(line)
                    # Add a few context lines
                    for j in range(1, 3):
                        if i + j < len(lines):
                            next_line = lines[i + j].strip()
                            if next_line and not next_line.startswith('//'):
                                content.append(f"  {next_line}")
            
            if content:
                summary = [
                    f"SDF Timing File: {os.path.basename(sdf_file)}",
                    f"Design: {design_name}",
                    f"Total timing entries: {len(content)}",
                    "",
                    "Key Timing Information:",
                    "=" * 40
                ]
                return '\n'.join(summary + content[:50])  # Limit to first 50 entries
            
            return None
            
        except Exception as e:
            logging.error(f"Error parsing SDF file {sdf_file}: {e}")
            return None
    
    def _extract_design_timing_from_log(self, log_file, design_name):
        """Extract design-specific timing information from log file."""
        try:
            content = []
            with open(log_file, 'r', encoding='utf-8', errors='replace') as f:
                lines = f.readlines()
            
            # Look for design-specific timing sections
            in_design_section = False
            for line in lines:
                line_lower = line.lower()
                
                # Check if this line mentions our design
                if design_name.lower() in line_lower:
                    in_design_section = True
                    content.append(line.strip())
                elif in_design_section:
                    # Continue collecting timing-related lines
                    if any(keyword in line_lower for keyword in [
                        'timing', 'frequency', 'slack', 'delay', 'setup', 'hold',
                        'critical', 'path', 'clock', 'constraint'
                    ]):
                        content.append(line.strip())
                    elif line.strip() == "" or line.startswith("---"):
                        # Potential end of section
                        if len(content) > 10:  # We have enough content
                            break
                    elif not any(char.isalnum() for char in line):
                        # Skip separator lines
                        continue
                    else:
                        # If we encounter unrelated content, stop
                        if len(content) > 5:
                            break
            
            return '\n'.join(content) if content else None
            
        except Exception as e:
            logging.error(f"Error extracting design timing from log: {e}")
            return None
    
    def _combine_utilization_reports(self, file_list):
        """Combine multiple utilization report files."""
        combined_content = []
        
        for file_path in file_list:
            try:
                with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                    content = f.read()
                
                filename = os.path.basename(file_path)
                combined_content.append(f"=== {filename} ===\n{content}\n")
                
            except Exception as e:
                combined_content.append(f"=== {os.path.basename(file_path)} ===\nError reading file: {e}\n")
        
        return '\n'.join(combined_content)
    
    def _combine_utilization_reports_for_design(self, file_list, design_name):
        """Combine multiple utilization report files for a specific design."""
        combined_content = []
        
        for file_path in file_list:
            try:
                with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                    content = f.read()
                
                filename = os.path.basename(file_path)
                
                # Filter content for the specific design if it's a generic report
                if filename == "lut_report.txt":
                    # Extract design-specific content from generic LUT report
                    design_content = self._extract_design_utilization(content, design_name)
                    if design_content:
                        combined_content.append(f"=== {filename} (filtered for {design_name}) ===\n{design_content}\n")
                    else:
                        combined_content.append(f"=== {filename} ===\nNo data found for design '{design_name}'\n")
                else:
                    # Design-specific file, include all content
                    combined_content.append(f"=== {filename} ===\n{content}\n")
                
            except Exception as e:
                combined_content.append(f"=== {os.path.basename(file_path)} ===\nError reading file: {e}\n")
        
        return '\n'.join(combined_content)
    
    def _extract_design_utilization(self, content, design_name):
        """Extract utilization data for a specific design from generic reports."""
        try:
            lines = content.split('\n')
            design_lines = []
            in_design_section = False
            
            for line in lines:
                line_lower = line.lower()
                
                # Check if this line mentions our design
                if design_name.lower() in line_lower:
                    in_design_section = True
                    design_lines.append(line)
                elif in_design_section:
                    # Continue collecting utilization-related lines
                    if any(keyword in line_lower for keyword in [
                        'lut', 'cpe', 'resource', 'utilization', 'used', 'available',
                        'logic', 'routing', 'memory', 'dsp', 'io'
                    ]):
                        design_lines.append(line)
                    elif line.strip() == "":
                        # Empty line might indicate end of section
                        if len(design_lines) > 5:
                            break
                    elif not any(char.isalnum() for char in line):
                        # Skip separator lines
                        continue
                    else:
                        # If we encounter unrelated content, stop
                        if len(design_lines) > 3:
                            break
            
            return '\n'.join(design_lines) if design_lines else None
            
        except Exception as e:
            logging.error(f"Error extracting design utilization: {e}")
            return None
    
    def _combine_placement_reports(self, file_list):
        """Combine multiple placement report files."""
        combined_content = []
        
        for file_path in file_list:
            try:
                with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                    content = f.read()
                
                filename = os.path.basename(file_path)
                combined_content.append(f"=== {filename} ===\n{content}\n")
                
            except Exception as e:
                combined_content.append(f"=== {os.path.basename(file_path)} ===\nError reading file: {e}\n")
        
        return '\n'.join(combined_content)
    
    def _combine_placement_reports_for_design(self, file_list, design_name):
        """Combine multiple placement report files for a specific design."""
        combined_content = []
        
        for file_path in file_list:
            try:
                with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                    content = f.read()
                
                filename = os.path.basename(file_path)
                
                # Add file header with design context
                combined_content.append(f"=== {filename} (Design: {design_name}) ===")
                
                # For placement files, add summary information
                if filename.endswith('.place'):
                    lines = content.split('\n')
                    placement_count = len([line for line in lines if line.strip() and not line.startswith('#')])
                    combined_content.append(f"Total placements: {placement_count}")
                    combined_content.append("")
                elif filename.endswith('.pin'):
                    lines = content.split('\n')
                    pin_count = len([line for line in lines if line.strip() and not line.startswith('#')])
                    combined_content.append(f"Total pin assignments: {pin_count}")
                    combined_content.append("")
                
                # Add the actual content (limit to reasonable size)
                lines = content.split('\n')
                if len(lines) > 100:
                    combined_content.append('\n'.join(lines[:100]))
                    combined_content.append(f"\n... (showing first 100 lines of {len(lines)} total)")
                else:
                    combined_content.append(content)
                
                combined_content.append("")
                
            except Exception as e:
                combined_content.append(f"=== {os.path.basename(file_path)} ===\nError reading file: {e}\n")
        
        return '\n'.join(combined_content)
    
    def _extract_power_analysis(self, log_file):
        """Extract power analysis from log file."""
        try:
            with open(log_file, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()
            
            # Look for power analysis sections
            power_sections = []
            lines = content.split('\n')
            
            in_power_section = False
            current_section = []
            
            for line in lines:
                # Start of power analysis
                if any(keyword in line.lower() for keyword in ['power analysis', 'power consumption', 'power estimate', 'dynamic power', 'static power']):
                    in_power_section = True
                    current_section = [line]
                elif in_power_section:
                    current_section.append(line)
                    # End of power section
                    if not line.strip() and len(current_section) > 3:
                        power_sections.append('\n'.join(current_section))
                        current_section = []
                        in_power_section = False
            
            # Add any remaining section
            if current_section and len(current_section) > 2:
                power_sections.append('\n'.join(current_section))
            
            return '\n\n'.join(power_sections) if power_sections else None
            
        except Exception as e:
            logging.error(f"Error extracting power analysis: {e}")
            return None
    
    def _extract_power_analysis_for_design(self, log_file, design_name):
        """Extract power analysis for a specific design from log file."""
        try:
            with open(log_file, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()
            
            # Look for design-specific power analysis sections
            power_sections = []
            lines = content.split('\n')
            
            in_power_section = False
            current_section = []
            
            for line in lines:
                line_lower = line.lower()
                
                # Check if this line mentions our design and power
                if (design_name.lower() in line_lower and 
                    any(keyword in line_lower for keyword in ['power', 'consumption', 'estimate'])):
                    in_power_section = True
                    current_section = [line]
                elif in_power_section:
                    # Continue collecting power-related lines
                    if any(keyword in line_lower for keyword in [
                        'power', 'consumption', 'dynamic', 'static', 'total',
                        'mw', 'uw', 'watt', 'current', 'voltage'
                    ]):
                        current_section.append(line)
                    elif line.strip() == "" or line.startswith("---"):
                        # Potential end of section
                        if len(current_section) > 3:
                            power_sections.append('\n'.join(current_section))
                            current_section = []
                            in_power_section = False
                    elif not any(char.isalnum() for char in line):
                        # Skip separator lines
                        continue
                    else:
                        # If we encounter unrelated content, stop
                        if len(current_section) > 2:
                            power_sections.append('\n'.join(current_section))
                            break
            
            # Add any remaining section
            if current_section and len(current_section) > 2:
                power_sections.append('\n'.join(current_section))
            
            return '\n\n'.join(power_sections) if power_sections else None
            
        except Exception as e:
            logging.error(f"Error extracting power analysis for design {design_name}: {e}")
            return None
    
    def _generate_power_estimate(self):
        """Generate power estimate based on utilization data."""
        try:
            from cc_project_manager_pkg.pnr_commands import PnRCommands
            pnr = PnRCommands()
            
            # Look for utilization data
            lut_report = os.path.join(pnr.work_dir, "lut_report.txt")
            if not os.path.exists(lut_report):
                return None
            
            with open(lut_report, 'r') as f:
                lut_content = f.read()
            
            # Count LUTs
            lut_count = len([line for line in lut_content.split('\n') if 'LUT' in line])
            
            # Rough power estimation (very basic)
            estimated_dynamic_power = lut_count * 0.1  # mW per LUT (rough estimate)
            estimated_static_power = lut_count * 0.05   # mW per LUT (rough estimate)
            total_power = estimated_dynamic_power + estimated_static_power
            
            power_report = f"""
=== Power Analysis Estimate ===

Note: This is a rough estimation based on resource utilization.
For accurate power analysis, use dedicated power analysis tools.

Resource Utilization:
• LUTs Used: {lut_count}

Power Estimation:
• Dynamic Power: ~{estimated_dynamic_power:.2f} mW
• Static Power: ~{estimated_static_power:.2f} mW
• Total Power: ~{total_power:.2f} mW

Assumptions:
• ~0.1 mW dynamic power per LUT
• ~0.05 mW static power per LUT
• Clock frequency: 100 MHz (assumed)
• Switching activity: 25% (assumed)

For more accurate power analysis:
1. Use vendor-specific power analysis tools
2. Provide actual clock frequencies
3. Include switching activity data
4. Consider I/O power consumption
"""
            return power_report
            
        except Exception as e:
            logging.error(f"Error generating power estimate: {e}")
            return None
    
    def _generate_power_estimate_for_design(self, design_name):
        """Generate power estimate for a specific design based on utilization data."""
        try:
            from cc_project_manager_pkg.pnr_commands import PnRCommands
            pnr = PnRCommands()
            
            # Look for design-specific utilization data
            design_used_file = os.path.join(pnr.work_dir, f"{design_name}_impl_00.used")
            lut_report = os.path.join(pnr.work_dir, "lut_report.txt")
            
            lut_count = 0
            cpe_count = 0
            io_count = 0
            
            # Try to get utilization from design-specific .used file
            if os.path.exists(design_used_file):
                with open(design_used_file, 'r') as f:
                    used_content = f.read()
                
                # Parse utilization data
                for line in used_content.split('\n'):
                    line_lower = line.lower()
                    if 'lut' in line_lower:
                        # Extract LUT count
                        numbers = [int(s) for s in line.split() if s.isdigit()]
                        if numbers:
                            lut_count += numbers[0]
                    elif 'cpe' in line_lower:
                        # Extract CPE count
                        numbers = [int(s) for s in line.split() if s.isdigit()]
                        if numbers:
                            cpe_count += numbers[0]
                    elif 'io' in line_lower:
                        # Extract I/O count
                        numbers = [int(s) for s in line.split() if s.isdigit()]
                        if numbers:
                            io_count += numbers[0]
            
            # Fallback to generic LUT report if design-specific data not available
            elif os.path.exists(lut_report):
                with open(lut_report, 'r') as f:
                    lut_content = f.read()
                
                # Try to extract design-specific data from generic report
                design_lines = []
                for line in lut_content.split('\n'):
                    if design_name.lower() in line.lower():
                        design_lines.append(line)
                
                if design_lines:
                    # Count LUTs mentioned in design-specific lines
                    for line in design_lines:
                        if 'lut' in line.lower():
                            numbers = [int(s) for s in line.split() if s.isdigit()]
                            if numbers:
                                lut_count += numbers[0]
                else:
                    # Rough estimate based on all LUTs (assume single design)
                    lut_count = len([line for line in lut_content.split('\n') if 'LUT' in line])
            
            if lut_count == 0:
                return None
            
            # Enhanced power estimation with design-specific context
            estimated_dynamic_power = lut_count * 0.12  # mW per LUT (slightly higher estimate)
            estimated_static_power = lut_count * 0.06   # mW per LUT (leakage)
            estimated_io_power = io_count * 0.5         # mW per I/O pin
            total_power = estimated_dynamic_power + estimated_static_power + estimated_io_power
            
            power_report = f"""
=== Power Analysis Estimate for {design_name} ===

Note: This is a rough estimation based on resource utilization.
For accurate power analysis, use dedicated power analysis tools.

Resource Utilization:
• LUTs Used: {lut_count}
• CPEs Used: {cpe_count}
• I/O Pins: {io_count}

Power Estimation:
• Dynamic Power: ~{estimated_dynamic_power:.2f} mW
• Static Power: ~{estimated_static_power:.2f} mW
• I/O Power: ~{estimated_io_power:.2f} mW
• Total Power: ~{total_power:.2f} mW

Power Breakdown by Component:
• Logic (LUTs): {(estimated_dynamic_power + estimated_static_power):.2f} mW ({((estimated_dynamic_power + estimated_static_power)/total_power*100):.1f}%)
• I/O: {estimated_io_power:.2f} mW ({(estimated_io_power/total_power*100):.1f}%)

Assumptions:
• ~0.12 mW dynamic power per LUT
• ~0.06 mW static power per LUT
• ~0.5 mW per I/O pin
• Clock frequency: 100 MHz (assumed)
• Switching activity: 25% (assumed)
• Core voltage: 1.2V (typical)

Power Optimization Recommendations:
1. Reduce clock frequency if timing allows
2. Use clock gating for unused logic
3. Minimize I/O switching activity
4. Consider power-optimized synthesis strategies

For more accurate power analysis:
1. Use vendor-specific power analysis tools
2. Provide actual clock frequencies and switching activity
3. Include temperature and voltage variations
4. Consider dynamic power management features
"""
            return power_report
            
        except Exception as e:
            logging.error(f"Error generating power estimate for design {design_name}: {e}")
            return None
    

    

    
    def _format_timing_content(self, content):
        """Format timing analysis content with syntax highlighting."""
        if not content:
            return "<p style='color: #888;'>No timing data available.</p>"
        
        lines = content.split('\n')
        formatted_lines = []
        
        for line in lines:
            line = line.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            
            if 'critical path' in line.lower() or 'worst slack' in line.lower():
                formatted_lines.append(f'<span style="color: #ff6b6b; font-weight: bold;">{line}</span>')
            elif 'max frequency' in line.lower() or 'fmax' in line.lower():
                formatted_lines.append(f'<span style="color: #51cf66; font-weight: bold;">{line}</span>')
            elif 'setup' in line.lower() or 'hold' in line.lower():
                formatted_lines.append(f'<span style="color: #ffd43b;">{line}</span>')
            elif line.startswith('==='):
                formatted_lines.append(f'<span style="color: #74c0fc; font-weight: bold;">{line}</span>')
            else:
                formatted_lines.append(f'<span style="color: #ffffff;">{line}</span>')
        
        return f'<pre style="font-family: Consolas, monospace; font-size: 9pt; line-height: 1.3;">{"<br>".join(formatted_lines)}</pre>'
    
    def _format_utilization_content(self, content):
        """Format utilization content with syntax highlighting."""
        if not content:
            return "<p style='color: #888;'>No utilization data available.</p>"
        
        lines = content.split('\n')
        formatted_lines = []
        
        for line in lines:
            line = line.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            
            if 'LUT' in line:
                formatted_lines.append(f'<span style="color: #51cf66;">{line}</span>')
            elif 'cpe' in line.lower():
                formatted_lines.append(f'<span style="color: #ffd43b;">{line}</span>')
            elif line.startswith('==='):
                formatted_lines.append(f'<span style="color: #74c0fc; font-weight: bold;">{line}</span>')
            else:
                formatted_lines.append(f'<span style="color: #ffffff;">{line}</span>')
        
        return f'<pre style="font-family: Consolas, monospace; font-size: 9pt; line-height: 1.3;">{"<br>".join(formatted_lines)}</pre>'
    
    def _format_placement_content(self, content):
        """Format placement content with syntax highlighting."""
        if not content:
            return "<p style='color: #888;'>No placement data available.</p>"
        
        lines = content.split('\n')
        formatted_lines = []
        
        for line in lines:
            line = line.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            
            if any(coord in line for coord in ['X:', 'Y:', 'LOC']):
                formatted_lines.append(f'<span style="color: #51cf66;">{line}</span>')
            elif line.startswith('==='):
                formatted_lines.append(f'<span style="color: #74c0fc; font-weight: bold;">{line}</span>')
            else:
                formatted_lines.append(f'<span style="color: #ffffff;">{line}</span>')
        
        return f'<pre style="font-family: Consolas, monospace; font-size: 9pt; line-height: 1.3;">{"<br>".join(formatted_lines)}</pre>'
    
    def _format_power_content(self, content):
        """Format power analysis content with syntax highlighting."""
        if not content:
            return "<p style='color: #888;'>No power data available.</p>"
        
        lines = content.split('\n')
        formatted_lines = []
        
        for line in lines:
            line = line.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
            
            if 'mW' in line or 'power' in line.lower():
                formatted_lines.append(f'<span style="color: #ffd43b; font-weight: bold;">{line}</span>')
            elif 'total' in line.lower():
                formatted_lines.append(f'<span style="color: #51cf66; font-weight: bold;">{line}</span>')
            elif line.startswith('==='):
                formatted_lines.append(f'<span style="color: #74c0fc; font-weight: bold;">{line}</span>')
            else:
                formatted_lines.append(f'<span style="color: #ffffff;">{line}</span>')
        
        return f'<pre style="font-family: Consolas, monospace; font-size: 9pt; line-height: 1.3;">{"<br>".join(formatted_lines)}</pre>'
    
    def _save_analysis_report(self, content, title):
        """Save analysis report to file."""
        filename = title.lower().replace(' ', '_').replace('&', 'and') + '.txt'
        file_path, _ = QFileDialog.getSaveFileName(
            self, f"Save {title}", filename, "Text Files (*.txt);;All Files (*)"
        )
        
        if file_path:
            try:
                with open(file_path, 'w') as f:
                    f.write(f"{title}\n")
                    f.write("=" * len(title) + "\n\n")
                    f.write(content)
                logging.info(f"Analysis report saved to {file_path}")
                self.show_message("Success", f"Report saved to:\n{file_path}", "info")
            except Exception as e:
                logging.error(f"Failed to save analysis report: {str(e)}")
                self.show_message("Error", f"Failed to save report:\n{str(e)}", "error")
    
    def _on_implementation_tree_clicked(self, item, column):
        """Handle clicks on the implementation tree for design selection and constraint file selection."""
        try:
            # Get the design name from the clicked item
            design_name = None
            selected_item = None
            constraint_file = None
            
            # Check if this is a design item (not a category or file)
            if item.parent() is not None:
                # This is a child item
                parent_text = item.parent().text(0)
                item_type = item.text(1)
                
                # Check if it's an implemented design
                if parent_text == "Implementation Outputs" and item_type == "Implementation":
                    design_name = item.text(0)
                    selected_item = item
                # Or a synthesized design that might be implemented
                elif parent_text == "Synthesized Designs" and item_type == "Synthesis":
                    # Check if this design has implementation outputs
                    potential_design = item.text(0)
                    from cc_project_manager_pkg.pnr_commands import PnRCommands
                    pnr = PnRCommands()
                    placed_designs = pnr.get_available_placed_designs()
                    if potential_design in placed_designs:
                        design_name = potential_design
                        selected_item = item
                # Check if it's a constraint file
                elif parent_text == "Constraint Files" and item_type == "Constraint":
                    constraint_file = item.text(0)
                    selected_item = item
            
            # Update selection and highlighting
            if design_name and selected_item:
                self._highlight_selected_item(selected_item)
                self._on_design_selection_changed(design_name)
                logging.info(f"🎯 Selected design for analysis: {design_name}")
            elif constraint_file and selected_item:
                self._highlight_selected_item(selected_item)
                self._on_design_selection_changed(None)  # Clear design selection
                logging.info(f"📄 Selected constraint file: {constraint_file}")
            else:
                # Clear selection if not a valid design or constraint file
                self._clear_item_highlighting()
                self._on_design_selection_changed(None)
                
        except Exception as e:
            logging.error(f"Error handling tree click: {e}")
    
    def _highlight_selected_item(self, item):
        """Highlight the selected item row in the implementation tree."""
        try:
            # Clear previous highlighting
            self._clear_item_highlighting()
            
            # Store reference to currently selected item
            self.selected_tree_item = item
            
            # Use Qt's built-in selection mechanism first
            self.implementation_tree.setCurrentItem(item)
            
            # Apply additional custom highlighting for better visibility
            highlight_color = QColor(25, 118, 210)  # Material Design Blue 700 (RGB)
            text_color = QColor(255, 255, 255)      # White text (RGB)
            
            for column in range(self.implementation_tree.columnCount()):
                # Set background and foreground colors directly
                item.setBackground(column, highlight_color)
                item.setForeground(column, text_color)
                
                # Make the text bold for better visibility
                font = item.font(column)
                font.setBold(True)
                item.setFont(column, font)
            
            logging.info(f"✅ Highlighted item row: {item.text(0)} with blue background and selection")
            
        except Exception as e:
            logging.error(f"Error highlighting selected item: {e}")
    
    def _clear_item_highlighting(self):
        """Clear highlighting from all item rows in the implementation tree."""
        try:
            # Clear Qt's built-in selection
            if hasattr(self, 'implementation_tree'):
                self.implementation_tree.clearSelection()
                self.implementation_tree.setCurrentItem(None)
            
            # Clear custom highlighting from previously selected item
            if hasattr(self, 'selected_tree_item') and self.selected_tree_item:
                for column in range(self.implementation_tree.columnCount()):
                    # Reset to default colors (transparent background, default text)
                    default_bg = QColor(0, 0, 0, 0)  # Transparent background (RGBA)
                    default_fg = QColor(255, 255, 255)  # White text (RGB)
                    
                    self.selected_tree_item.setBackground(column, default_bg)
                    self.selected_tree_item.setForeground(column, default_fg)
                    
                    # Reset font to normal weight
                    font = self.selected_tree_item.font(column)
                    font.setBold(False)
                    self.selected_tree_item.setFont(column, font)
                    
                logging.info(f"🧹 Cleared highlighting and selection from: {self.selected_tree_item.text(0)}")
                self.selected_tree_item = None
                
        except Exception as e:
            logging.error(f"Error clearing item highlighting: {e}")
    
    def _on_design_selection_changed(self, design_name):
        """Handle design selection change from Design/File container."""
        if design_name:
            self.selected_design = design_name
            self._update_design_status(design_name)
        else:
            self.selected_design = None
            self.selected_design_status.setText("No design selected")
    
    def _restore_tree_selection(self, design_name):
        """Restore tree selection after refresh."""
        try:
            # Find the design item in the tree
            for i in range(self.implementation_tree.topLevelItemCount()):
                top_item = self.implementation_tree.topLevelItem(i)
                
                # Check if this is a category with children
                for j in range(top_item.childCount()):
                    child_item = top_item.child(j)
                    if child_item.text(0) == design_name:
                        # Found the design, restore selection
                        self._highlight_selected_item(child_item)
                        self._on_design_selection_changed(design_name)
                        logging.info(f"🔄 Restored selection for design: {design_name}")
                        return
            
            # If we get here, the design wasn't found (maybe it was removed)
            logging.info(f"⚠️ Could not restore selection for design '{design_name}' - design not found in tree")
            self._on_design_selection_changed(None)  # Clear selection
            
        except Exception as e:
            logging.error(f"Error restoring tree selection: {e}")
            self._on_design_selection_changed(None)  # Clear selection on error
    
    def _update_design_status(self, design_name):
        """Update the status label for the selected design."""
        try:
            from cc_project_manager_pkg.pnr_commands import PnRCommands
            pnr = PnRCommands()
            status = pnr.get_implementation_status(design_name)
            
            status_parts = []
            if status.get('placed', False):
                status_parts.append("P&R")
            if status.get('timing_analyzed', False):
                status_parts.append("Timing")
            if status.get('bitstream_generated', False):
                status_parts.append("Bitstream")
            
            if status_parts:
                self.selected_design_status.setText(f"Status: {' + '.join(status_parts)}")
                self.selected_design_status.setStyleSheet("color: #4CAF50; font-size: 11px; margin-top: 5px;")
            else:
                self.selected_design_status.setText("Status: Not implemented")
                self.selected_design_status.setStyleSheet("color: #888888; font-size: 11px; margin-top: 5px;")
                
        except Exception as e:
            logging.error(f"Error updating design status: {e}")
            self.selected_design_status.setText("Status: Error")


class FPGABoardSelectionDialog(QDialog):
    """Dialog for FPGA board selection and configuration."""
    
    def __init__(self, parent=None, current_board=None):
        super().__init__(parent)
        self.setWindowTitle("FPGA Board Selection")
        self.setModal(True)
        self.resize(550, 500)  # Increased height to accommodate larger results area
        self.current_board = current_board or {'name': 'Olimex GateMate EVB', 'identifier': 'olimex_gatemateevb'}
        self.selected_board = self.current_board.copy()
        self.init_ui()
    
    def init_ui(self):
        layout = QVBoxLayout(self)
        
        # Title and description
        title = QLabel("FPGA Board Selection")
        title.setFont(QFont("Arial", 14, QFont.Bold))
        title.setStyleSheet("color: #4CAF50; margin-bottom: 10px;")
        layout.addWidget(title)
        
        description = QLabel("Select your FPGA board and test connectivity before programming operations.")
        description.setWordWrap(True)
        description.setStyleSheet("color: #888888; margin-bottom: 15px;")
        layout.addWidget(description)
        
        # Board selection section
        board_group = QGroupBox("Board Selection")
        board_layout = QVBoxLayout(board_group)
        
        # Board dropdown
        board_select_layout = QHBoxLayout()
        board_label = QLabel("Board:")
        board_label.setMinimumWidth(80)
        board_select_layout.addWidget(board_label)
        
        self.board_combo = QComboBox()
        self.board_combo.addItem("Olimex GateMate EVB", "olimex_gatemateevb")
        self.board_combo.setCurrentIndex(0)
        self.board_combo.currentTextChanged.connect(self._on_board_changed)
        board_select_layout.addWidget(self.board_combo)
        
        board_layout.addLayout(board_select_layout)
        
        # Board info
        self.board_info_label = QLabel(f"Selected: {self.current_board['name']}")
        self.board_info_label.setStyleSheet("font-weight: bold; color: #4CAF50; margin: 5px 0px;")
        board_layout.addWidget(self.board_info_label)
        
        layout.addWidget(board_group)
        
        # Connection testing section
        connection_group = QGroupBox("Connection Testing")
        connection_layout = QVBoxLayout(connection_group)
        
        # Connection status
        self.connection_status_label = QLabel("Connection: Not tested")
        self.connection_status_label.setStyleSheet("font-weight: bold; color: #888888; margin: 5px 0px;")
        self.connection_status_label.setMaximumHeight(25)  # Constrain height
        self.connection_status_label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        connection_layout.addWidget(self.connection_status_label)
        
        # Test buttons
        test_buttons_layout = QHBoxLayout()
        
        self.test_connection_btn = QPushButton("🔗 Test Connection")
        self.test_connection_btn.setToolTip("Test connection to the selected FPGA board")
        self.test_connection_btn.clicked.connect(self.test_board_connection)
        test_buttons_layout.addWidget(self.test_connection_btn)
        
        self.scan_usb_btn = QPushButton("🔍 Scan USB")
        self.scan_usb_btn.setToolTip("Scan for USB devices and programming interfaces")
        self.scan_usb_btn.clicked.connect(self.scan_usb_devices)
        test_buttons_layout.addWidget(self.scan_usb_btn)
        
        connection_layout.addLayout(test_buttons_layout)
        
        # Results area
        self.results_text = QTextEdit()
        self.results_text.setMinimumHeight(200)  # Ensure adequate height
        self.results_text.setMaximumHeight(300)  # Allow more space but still constrain
        self.results_text.setReadOnly(True)
        self.results_text.setFont(QFont("Consolas", 9))
        self.results_text.setStyleSheet("""
            QTextEdit {
                background-color: #1e1e1e;
                color: #ffffff;
                border: 1px solid #555;
            }
        """)
        self.results_text.setPlaceholderText("Test results will appear here...")
        connection_layout.addWidget(self.results_text)
        
        layout.addWidget(connection_group)
        
        # Dialog buttons
        button_layout = QHBoxLayout()
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)
        
        button_layout.addStretch()
        
        apply_btn = QPushButton("Apply Selection")
        apply_btn.clicked.connect(self.apply_selection)
        apply_btn.setDefault(True)
        apply_btn.setStyleSheet("background-color: #4CAF50; color: white; font-weight: bold;")
        button_layout.addWidget(apply_btn)
        
        layout.addLayout(button_layout)
    
    def _on_board_changed(self, board_name):
        """Handle board selection change."""
        board_data = self.board_combo.currentData()
        self.selected_board = {
            'name': board_name,
            'identifier': board_data
        }
        self.board_info_label.setText(f"Selected: {board_name}")
        
        # Reset connection status
        self.connection_status_label.setText("Connection: Not tested")
        self.connection_status_label.setStyleSheet("font-weight: bold; color: #888888; margin: 5px 0px;")
        self.results_text.clear()
    
    def test_board_connection(self):
        """Test connection to the selected board."""
        try:
            board_name = self.selected_board['name']
            board_identifier = self.selected_board['identifier']
            
            self.connection_status_label.setText("Connection: Testing...")
            self.connection_status_label.setStyleSheet("font-weight: bold; color: #FFA726; margin: 5px 0px;")
            self.test_connection_btn.setEnabled(False)
            self.results_text.clear()
            
            # Import here to avoid circular imports
            from cc_project_manager_pkg.openfpgaloader_manager import OpenFPGALoaderManager
            upload_manager = OpenFPGALoaderManager()
            
            # Build the detect command
            detect_cmd = [upload_manager.loader_access, "--detect", "-b", board_identifier]
            
            import subprocess
            import logging
            
            logging.info(f"🔍 Testing board connection: {' '.join(detect_cmd)}")
            self.results_text.append(f"Running: {' '.join(detect_cmd)}\n")
            
            try:
                result = subprocess.run(detect_cmd, check=True, capture_output=True, text=True, timeout=30)
                
                # Success
                self.connection_status_label.setText("Connection: ✅ Connected")
                self.connection_status_label.setStyleSheet("font-weight: bold; color: #4CAF50; margin: 5px 0px;")
                
                output_text = "✅ Board connection successful!\n\n"
                if result.stdout:
                    output_text += f"Output:\n{result.stdout}\n"
                if result.stderr:
                    output_text += f"Stderr:\n{result.stderr}\n"
                
                self.results_text.append(output_text)
                logging.info(f"✅ Board connection test successful for {board_name}")
                
            except subprocess.TimeoutExpired:
                self.connection_status_label.setText("Connection: ❌ Timeout")
                self.connection_status_label.setStyleSheet("font-weight: bold; color: #F44336; margin: 5px 0px;")
                self.results_text.append("❌ Connection test timed out (30 seconds)")
                logging.error(f"❌ Board connection test timed out for {board_name}")
                
            except subprocess.CalledProcessError as e:
                self.connection_status_label.setText("Connection: ❌ Failed")
                self.connection_status_label.setStyleSheet("font-weight: bold; color: #F44336; margin: 5px 0px;")
                
                error_text = f"❌ Connection test failed (exit code {e.returncode})\n\n"
                if e.stdout:
                    error_text += f"Output:\n{e.stdout}\n"
                if e.stderr:
                    error_text += f"Error:\n{e.stderr}\n"
                
                self.results_text.append(error_text)
                logging.error(f"❌ Board connection test failed for {board_name}: {e}")
                
        except Exception as e:
            self.connection_status_label.setText("Connection: ❌ Error")
            self.connection_status_label.setStyleSheet("font-weight: bold; color: #F44336; margin: 5px 0px;")
            self.results_text.append(f"❌ Error during connection test: {str(e)}")
            logging.error(f"❌ Error in board connection test: {e}")
        
        finally:
            self.test_connection_btn.setEnabled(True)
    
    def scan_usb_devices(self):
        """Scan for USB devices."""
        try:
            self.scan_usb_btn.setEnabled(False)
            self.scan_usb_btn.setText("🔍 Scanning...")
            
            # Import here to avoid circular imports
            from cc_project_manager_pkg.openfpgaloader_manager import OpenFPGALoaderManager
            upload_manager = OpenFPGALoaderManager()
            
            # Build the scan command
            scan_cmd = [upload_manager.loader_access, "--scan-usb"]
            
            import subprocess
            import logging
            
            logging.info(f"🔍 Scanning USB devices: {' '.join(scan_cmd)}")
            self.results_text.append(f"\nRunning: {' '.join(scan_cmd)}\n")
            
            try:
                result = subprocess.run(scan_cmd, check=True, capture_output=True, text=True, timeout=30)
                
                # Count devices
                device_count = result.stdout.count("Device") if result.stdout else 0
                
                output_text = f"📋 USB scan completed - found {device_count} devices\n\n"
                if result.stdout:
                    output_text += f"Results:\n{result.stdout}\n"
                if result.stderr:
                    output_text += f"Stderr:\n{result.stderr}\n"
                
                self.results_text.append(output_text)
                logging.info(f"✅ USB scan completed - found {device_count} devices")
                
            except subprocess.TimeoutExpired:
                self.results_text.append("❌ USB scan timed out (30 seconds)")
                logging.error("❌ USB scan timed out")
                
            except subprocess.CalledProcessError as e:
                error_text = f"❌ USB scan failed (exit code {e.returncode})\n\n"
                if e.stdout:
                    error_text += f"Output:\n{e.stdout}\n"
                if e.stderr:
                    error_text += f"Error:\n{e.stderr}\n"
                
                self.results_text.append(error_text)
                logging.error(f"❌ USB scan failed: {e}")
                
        except Exception as e:
            self.results_text.append(f"❌ Error during USB scan: {str(e)}")
            logging.error(f"❌ Error in USB scan: {e}")
        
        finally:
            self.scan_usb_btn.setEnabled(True)
            self.scan_usb_btn.setText("🔍 Scan USB")
    
    def apply_selection(self):
        """Apply the board selection and test connection automatically."""
        try:
            # First test the connection
            self.results_text.clear()
            self.results_text.append("🔄 Testing connection before applying selection...\n")
            
            board_name = self.selected_board['name']
            board_identifier = self.selected_board['identifier']
            
            self.connection_status_label.setText("Connection: Testing...")
            self.connection_status_label.setStyleSheet("font-weight: bold; color: #FFA726; margin: 5px 0px;")
            
            # Import here to avoid circular imports
            from cc_project_manager_pkg.openfpgaloader_manager import OpenFPGALoaderManager
            upload_manager = OpenFPGALoaderManager()
            
            # Build the detect command
            detect_cmd = [upload_manager.loader_access, "--detect", "-b", board_identifier]
            
            import subprocess
            import logging
            
            logging.info(f"🔍 Auto-testing board connection during apply: {' '.join(detect_cmd)}")
            self.results_text.append(f"Running: {' '.join(detect_cmd)}\n")
            
            try:
                result = subprocess.run(detect_cmd, check=True, capture_output=True, text=True, timeout=30)
                
                # Success - board detected
                self.connection_status_label.setText("Connection: ✅ Connected")
                self.connection_status_label.setStyleSheet("font-weight: bold; color: #4CAF50; margin: 5px 0px;")
                
                output_text = "✅ Board connection successful!\n\n"
                if result.stdout:
                    output_text += f"Output:\n{result.stdout}\n"
                if result.stderr:
                    output_text += f"Stderr:\n{result.stderr}\n"
                
                self.results_text.append(output_text)
                self.results_text.append("✅ Board selection applied successfully!")
                
                logging.info(f"✅ Board connection test successful during apply for {board_name}")
                
                # Store the connection success for the parent window
                self.connection_successful = True
                
                # Accept the dialog
                self.accept()
                
            except subprocess.TimeoutExpired:
                self.connection_status_label.setText("Connection: ❌ Timeout")
                self.connection_status_label.setStyleSheet("font-weight: bold; color: #F44336; margin: 5px 0px;")
                self.results_text.append("❌ Connection test timed out (30 seconds)")
                logging.error(f"❌ Board connection test timed out during apply for {board_name}")
                
                # Ask user if they want to proceed anyway
                reply = QMessageBox.question(self, "Connection Failed", 
                                           f"Connection test failed for {board_name}.\n\n"
                                           f"Do you want to apply the selection anyway?",
                                           QMessageBox.Yes | QMessageBox.No,
                                           QMessageBox.No)
                
                if reply == QMessageBox.Yes:
                    self.connection_successful = False
                    self.accept()
                
            except subprocess.CalledProcessError as e:
                self.connection_status_label.setText("Connection: ❌ Failed")
                self.connection_status_label.setStyleSheet("font-weight: bold; color: #F44336; margin: 5px 0px;")
                
                error_text = f"❌ Connection test failed (exit code {e.returncode})\n\n"
                if e.stdout:
                    error_text += f"Output:\n{e.stdout}\n"
                if e.stderr:
                    error_text += f"Error:\n{e.stderr}\n"
                
                self.results_text.append(error_text)
                logging.error(f"❌ Board connection test failed during apply for {board_name}: {e}")
                
                # Ask user if they want to proceed anyway
                reply = QMessageBox.question(self, "Connection Failed", 
                                           f"Connection test failed for {board_name}.\n\n"
                                           f"Do you want to apply the selection anyway?",
                                           QMessageBox.Yes | QMessageBox.No,
                                           QMessageBox.No)
                
                if reply == QMessageBox.Yes:
                    self.connection_successful = False
                    self.accept()
                
        except Exception as e:
            self.connection_status_label.setText("Connection: ❌ Error")
            self.connection_status_label.setStyleSheet("font-weight: bold; color: #F44336; margin: 5px 0px;")
            self.results_text.append(f"❌ Error during connection test: {str(e)}")
            logging.error(f"❌ Error in board connection test during apply: {e}")
            
            # Ask user if they want to proceed anyway
            reply = QMessageBox.question(self, "Connection Error", 
                                       f"Error testing connection to {self.selected_board['name']}.\n\n"
                                       f"Do you want to apply the selection anyway?",
                                       QMessageBox.Yes | QMessageBox.No,
                                       QMessageBox.No)
            
            if reply == QMessageBox.Yes:
                self.connection_successful = False
                self.accept()
    
    def get_selected_board(self):
        """Get the selected board configuration."""
        return self.selected_board
    
    def was_connection_successful(self):
        """Check if the connection test was successful."""
        return getattr(self, 'connection_successful', False)


class ImplementationStrategyDialog(QDialog):
    """Dialog for selecting implementation strategy for place and route."""
    
    def __init__(self, parent=None, design_name=None):
        super().__init__(parent)
        self.design_name = design_name
        self.setWindowTitle(f"Run Implementation - {design_name}")
        self.setModal(True)
        self.setFixedSize(520, 500)
        self.init_ui()
    
    def init_ui(self):
        """Initialize the dialog UI."""
        layout = QVBoxLayout(self)
        
        # Design info
        design_frame = QFrame()
        design_frame.setFrameStyle(QFrame.StyledPanel)
        design_layout = QVBoxLayout(design_frame)
        
        design_label = QLabel(f"Implementing Design: {self.design_name}")
        design_label.setStyleSheet("font-weight: bold; font-size: 14px; color: #4CAF50;")
        design_layout.addWidget(design_label)
        
        layout.addWidget(design_frame)
        
        # Strategy selection
        strategy_group = QGroupBox("Implementation Strategy")
        strategy_layout = QVBoxLayout(strategy_group)
        
        # Load available strategies from PnRCommands
        self.strategies = self._load_implementation_strategies()
        
        self.strategy_combo = QComboBox()
        for strategy, description in self.strategies.items():
            self.strategy_combo.addItem(f"{strategy.title()} - {description}", strategy)
        
        # Set default to balanced
        balanced_index = self.strategy_combo.findData("balanced")
        if balanced_index >= 0:
            self.strategy_combo.setCurrentIndex(balanced_index)
        
        strategy_layout.addWidget(QLabel("Select Strategy:"))
        strategy_layout.addWidget(self.strategy_combo)
        
        # Strategy description
        self.description_label = QLabel()
        self.description_label.setWordWrap(True)
        self.description_label.setStyleSheet("color: #888888; font-style: italic; padding: 10px;")
        self.update_description()
        
        # Connect signal to update description
        self.strategy_combo.currentTextChanged.connect(self.update_description)
        
        strategy_layout.addWidget(self.description_label)
        
        layout.addWidget(strategy_group)
        
        # Constraint file selection
        constraints_group = QGroupBox("Constraint File")
        constraints_layout = QVBoxLayout(constraints_group)
        
        # Load available constraint files
        self.available_constraints = self._load_available_constraints()
        
        constraints_layout.addWidget(QLabel("Select Constraint File:"))
        
        self.constraints_combo = QComboBox()
        
        # Get auto-detection preview
        auto_detect_preview = self._get_auto_detect_preview()
        auto_detect_text = f"Use Default (Auto-detect: {auto_detect_preview})"
        self.constraints_combo.addItem(auto_detect_text, "default")
        
        if self.available_constraints:
            for constraint_file in self.available_constraints:
                display_name = constraint_file
                self.constraints_combo.addItem(display_name, constraint_file)
        else:
            self.constraints_combo.addItem("No constraint files found", "none")
            self.constraints_combo.setEnabled(False)
        
        constraints_layout.addWidget(self.constraints_combo)
        
        # Add info label with more detailed information
        info_label = QLabel(f"Auto-detect will use: {auto_detect_preview}")
        info_label.setStyleSheet("color: #4CAF50; font-weight: bold; font-size: 10px;")
        info_label.setWordWrap(True)
        constraints_layout.addWidget(info_label)
        
        layout.addWidget(constraints_group)
        
        # Implementation options
        options_group = QGroupBox("Implementation Options")
        options_layout = QVBoxLayout(options_group)
        
        # Note: Bitstream generation is automatic during P&R, no checkbox needed
        
        self.run_timing_analysis_checkbox = QCheckBox("Run timing analysis")
        self.run_timing_analysis_checkbox.setChecked(False)
        self.run_timing_analysis_checkbox.setToolTip("Generate timing reports and SDF files")
        
        self.generate_netlist_checkbox = QCheckBox("Generate post-implementation netlist")
        self.generate_netlist_checkbox.setChecked(False)
        self.generate_netlist_checkbox.setToolTip("Generate VHDL netlist for post-implementation simulation")
        
        options_layout.addWidget(self.run_timing_analysis_checkbox)
        options_layout.addWidget(self.generate_netlist_checkbox)
        
        layout.addWidget(options_group)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        
        explain_btn = QPushButton("Explain Strategy")
        explain_btn.clicked.connect(self.show_strategy_explanation)
        explain_btn.setStyleSheet("QPushButton { background-color: #2196F3; color: white; font-weight: bold; }")
        
        self.run_btn = QPushButton("Run Implementation")
        self.run_btn.clicked.connect(self.accept)
        self.run_btn.setDefault(True)
        self.run_btn.setStyleSheet("QPushButton { background-color: #4CAF50; color: white; font-weight: bold; }")
        
        button_layout.addWidget(cancel_btn)
        button_layout.addWidget(explain_btn)
        button_layout.addWidget(self.run_btn)
        
        layout.addLayout(button_layout)
    
    def update_description(self):
        """Update the strategy description based on selection."""
        current_strategy = self.strategy_combo.currentData()
        if current_strategy in self.strategies:
            description = self.strategies[current_strategy]
            self.description_label.setText(f"Description: {description}")
    
    def _load_available_constraints(self):
        """Load available constraint files from the project.
        
        Returns:
            list: List of available constraint file names
        """
        try:
            from cc_project_manager_pkg.pnr_commands import PnRCommands
            pnr = PnRCommands()
            constraint_files = pnr.list_available_constraint_files()
            return constraint_files
        except Exception as e:
            logging.error(f"Error loading constraint files: {e}")
            return []

    def _get_auto_detect_preview(self):
        """Get a preview of which constraint file auto-detection will use.
        
        Returns:
            str: Name of the constraint file that will be auto-detected
        """
        try:
            from cc_project_manager_pkg.pnr_commands import PnRCommands
            pnr = PnRCommands()
            
            # Simulate the enhanced auto-detection logic
            default_constraint_file = pnr.get_default_constraint_file_path()
            available_constraints = pnr.list_available_constraint_files()
            
            # First, check if default constraint file exists and has active constraints
            if os.path.exists(default_constraint_file) and pnr.has_active_constraints(default_constraint_file):
                return f"{os.path.basename(default_constraint_file)} (default with active pins)"
            elif available_constraints:
                # Look for the first constraint file with active pin assignments
                for constraint_name in available_constraints:
                    constraint_path = pnr.get_constraint_file_path(constraint_name)
                    if pnr.has_active_constraints(constraint_path):
                        return f"{constraint_name} (first with active pins)"
                
                # If no constraint file has active assignments, use the first available as fallback
                if available_constraints:
                    return f"{available_constraints[0]} (template only - may fail)"
            
            return "No constraint files found"
            
        except Exception as e:
            logging.debug(f"Error getting auto-detect preview: {e}")
            return "Error detecting constraint files"
    
    def _load_implementation_strategies(self):
        """Load implementation strategies from PnRCommands.
        
        Returns:
            dict: Dictionary of strategy_name -> description
        """
        try:
            from cc_project_manager_pkg.pnr_commands import PnRCommands
            
            # Get strategy descriptions from PnRCommands
            strategies = {}
            for strategy_name, strategy_config in PnRCommands.IMPLEMENTATION_STRATEGIES.items():
                if strategy_name == "speed":
                    description = "Optimize for maximum clock frequency and performance"
                elif strategy_name == "area":
                    description = "Optimize for minimal resource usage"
                elif strategy_name == "balanced":
                    description = "Standard optimization balancing area and speed (default)"
                elif strategy_name == "power":
                    description = "Optimize for minimal power consumption"
                elif strategy_name == "congestion":
                    description = "Optimize for routing congestion relief"
                elif strategy_name == "custom":
                    description = "User-defined strategy with custom parameters"
                else:
                    description = "Implementation strategy"
                
                strategies[strategy_name] = description
            
            return strategies
            
        except Exception as e:
            logging.error(f"Error loading implementation strategies: {e}")
            # Fallback to hardcoded strategies
            return {
                "speed": "Optimize for maximum clock frequency and performance",
                "area": "Optimize for minimal resource usage", 
                "balanced": "Standard optimization balancing area and speed (default)",
                "power": "Optimize for minimal power consumption",
                "congestion": "Optimize for routing congestion relief",
                "custom": "User-defined strategy with custom parameters"
            }
    
    def show_strategy_explanation(self):
        """Show the strategy explanation dialog."""
        current_strategy = self.strategy_combo.currentData()
        dialog = ImplementationStrategyExplanationDialog(self, current_strategy)
        dialog.exec_()
    
    def get_implementation_params(self):
        """Get the implementation parameters from the dialog."""
        return {
            "strategy": self.strategy_combo.currentData(),
            "design_name": self.design_name,
            "constraint_file": self.constraints_combo.currentData(),
            "generate_bitstream": True,  # Always True since bitstream is generated automatically
            "run_timing_analysis": self.run_timing_analysis_checkbox.isChecked(),
            "generate_sim_netlist": self.generate_netlist_checkbox.isChecked()
        }


class ImplementationStrategyExplanationDialog(QDialog):
    """Dialog for explaining implementation strategies."""
    
    def __init__(self, parent=None, strategy_name="balanced"):
        super().__init__(parent)
        self.strategy_name = strategy_name
        self.setWindowTitle(f"Implementation Strategy - {strategy_name.title()}")
        self.setModal(True)
        self.resize(700, 500)
        self.init_ui()
    
    def init_ui(self):
        """Initialize the dialog UI."""
        layout = QVBoxLayout(self)
        
        # Title
        title = QLabel(f"Implementation Strategy: {self.strategy_name.title()}")
        title.setFont(QFont("Arial", 16, QFont.Bold))
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("color: #2196F3; margin: 10px;")
        layout.addWidget(title)
        
        # Strategy description
        description_view = QTextEdit()
        description_view.setHtml(self._get_strategy_description())
        description_view.setReadOnly(True)
        description_view.setMinimumHeight(300)
        layout.addWidget(description_view)
        
        # Close button
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        close_btn.setDefault(True)
        button_layout.addWidget(close_btn)
        
        layout.addLayout(button_layout)
    
    def _get_strategy_description(self):
        """Get detailed description for the strategy."""
        descriptions = {
            "speed": """
                <h3>Speed-Optimized Strategy</h3>
                <p><strong>Goal:</strong> Maximize clock frequency and performance</p>
                <p><strong>Key Features:</strong></p>
                <ul>
                    <li><strong>High effort levels:</strong> Uses maximum placement and routing effort</li>
                    <li><strong>Timing-driven:</strong> Prioritizes meeting timing constraints</li>
                    <li><strong>Performance focus:</strong> May use more resources for better speed</li>
                </ul>
                <p><strong>P&R Settings:</strong></p>
                <ul>
                    <li>Effort: High</li>
                    <li>Place effort: High</li>
                    <li>Route effort: High</li>
                    <li>Timing-driven: Enabled</li>
                    <li>Congestion-driven: Disabled</li>
                </ul>
                <p><strong>Best for:</strong> High-performance designs where timing is critical</p>
                <p><strong>Trade-offs:</strong> Longer implementation time, higher resource usage</p>
            """,
            "area": """
                <h3>Area-Optimized Strategy</h3>
                <p><strong>Goal:</strong> Minimize resource usage and area</p>
                <p><strong>Key Features:</strong></p>
                <ul>
                    <li><strong>Resource efficiency:</strong> Focuses on using minimal LUTs and logic</li>
                    <li><strong>Congestion-aware:</strong> Helps with routing in dense designs</li>
                    <li><strong>Compact placement:</strong> Tries to place logic close together</li>
                </ul>
                <p><strong>P&R Settings:</strong></p>
                <ul>
                    <li>Effort: Medium</li>
                    <li>Place effort: Medium</li>
                    <li>Route effort: Medium</li>
                    <li>Timing-driven: Disabled</li>
                    <li>Congestion-driven: Enabled</li>
                </ul>
                <p><strong>Best for:</strong> Designs with tight area constraints or fitting in smaller FPGAs</p>
                <p><strong>Trade-offs:</strong> May sacrifice performance for area savings</p>
            """,
            "balanced": """
                <h3>Balanced Strategy (Default)</h3>
                <p><strong>Goal:</strong> Balance area and speed optimization</p>
                <p><strong>Key Features:</strong></p>
                <ul>
                    <li><strong>Compromise approach:</strong> Good balance between area and performance</li>
                    <li><strong>Moderate effort:</strong> Reasonable implementation time</li>
                    <li><strong>Both optimizations:</strong> Considers timing and congestion</li>
                </ul>
                <p><strong>P&R Settings:</strong></p>
                <ul>
                    <li>Effort: Medium</li>
                    <li>Place effort: Medium</li>
                    <li>Route effort: Medium</li>
                    <li>Timing-driven: Enabled</li>
                    <li>Congestion-driven: Enabled</li>
                </ul>
                <p><strong>Best for:</strong> General-purpose designs with no extreme constraints</p>
                <p><strong>Trade-offs:</strong> Good compromise between area and speed</p>
            """,
            "power": """
                <h3>Power-Optimized Strategy</h3>
                <p><strong>Goal:</strong> Minimize power consumption</p>
                <p><strong>Key Features:</strong></p>
                <ul>
                    <li><strong>Low-power placement:</strong> Reduces switching activity</li>
                    <li><strong>Conservative routing:</strong> Minimizes dynamic power</li>
                    <li><strong>Clock optimization:</strong> Reduces clock tree power</li>
                </ul>
                <p><strong>P&R Settings:</strong></p>
                <ul>
                    <li>Effort: Medium</li>
                    <li>Place effort: Low</li>
                    <li>Route effort: Medium</li>
                    <li>Timing-driven: Disabled</li>
                    <li>Congestion-driven: Disabled</li>
                </ul>
                <p><strong>Best for:</strong> Battery-powered or low-power applications</p>
                <p><strong>Trade-offs:</strong> May sacrifice performance for power savings</p>
            """,
            "congestion": """
                <h3>Congestion-Optimized Strategy</h3>
                <p><strong>Goal:</strong> Optimize for routing congestion relief</p>
                <p><strong>Key Features:</strong></p>
                <ul>
                    <li><strong>Congestion analysis:</strong> Identifies and resolves routing bottlenecks</li>
                    <li><strong>Spread placement:</strong> Distributes logic to reduce congestion</li>
                    <li><strong>High effort routing:</strong> Tries harder to complete routing</li>
                </ul>
                <p><strong>P&R Settings:</strong></p>
                <ul>
                    <li>Effort: High</li>
                    <li>Place effort: High</li>
                    <li>Route effort: High</li>
                    <li>Timing-driven: Disabled</li>
                    <li>Congestion-driven: Enabled</li>
                </ul>
                <p><strong>Best for:</strong> Dense designs with routing challenges</p>
                <p><strong>Trade-offs:</strong> Longer implementation time, may impact timing</p>
            """,
            "custom": """
                <h3>Custom Strategy</h3>
                <p><strong>Goal:</strong> User-defined strategy with custom parameters</p>
                <p><strong>Key Features:</strong></p>
                <ul>
                    <li><strong>Flexible configuration:</strong> Allows custom P&R settings</li>
                    <li><strong>Advanced control:</strong> Fine-tune implementation parameters</li>
                    <li><strong>Expert mode:</strong> For experienced users</li>
                </ul>
                <p><strong>P&R Settings:</strong></p>
                <ul>
                    <li>Effort: Medium (default)</li>
                    <li>Place effort: Medium (default)</li>
                    <li>Route effort: Medium (default)</li>
                    <li>Timing-driven: Enabled (default)</li>
                    <li>Congestion-driven: Enabled (default)</li>
                </ul>
                <p><strong>Best for:</strong> Advanced users who need precise control over implementation</p>
                <p><strong>Trade-offs:</strong> Requires knowledge of P&R tool parameters</p>
            """
        }
        
        return descriptions.get(self.strategy_name, f"<p>Description for {self.strategy_name} strategy not available.</p>")


def main():
    """Main application entry point."""
    try:
        app = QApplication(sys.argv)
        app.setApplicationName("GateMate Project Manager by JOCRIX")
        app.setOrganizationName("JOCRIX")
        
        # Enable dark mode styling for the title bar and application
        app.setStyle('Fusion')  # Use Fusion style for better dark mode support
        
        # Apply dark mode palette
        dark_palette = QPalette()
        
        # Window colors
        dark_palette.setColor(QPalette.Window, QColor(53, 53, 53))
        dark_palette.setColor(QPalette.WindowText, QColor(255, 255, 255))
        
        # Base colors (for input fields)
        dark_palette.setColor(QPalette.Base, QColor(25, 25, 25))
        dark_palette.setColor(QPalette.AlternateBase, QColor(53, 53, 53))
        
        # Tooltip colors
        dark_palette.setColor(QPalette.ToolTipBase, QColor(0, 0, 0))
        dark_palette.setColor(QPalette.ToolTipText, QColor(255, 255, 255))
        
        # Text colors
        dark_palette.setColor(QPalette.Text, QColor(255, 255, 255))
        dark_palette.setColor(QPalette.Button, QColor(53, 53, 53))
        dark_palette.setColor(QPalette.ButtonText, QColor(255, 255, 255))
        
        # Highlight colors
        dark_palette.setColor(QPalette.Highlight, QColor(42, 130, 218))
        dark_palette.setColor(QPalette.HighlightedText, QColor(0, 0, 0))
        
        app.setPalette(dark_palette)
        
        # Platform-specific dark mode for title bar
        if sys.platform == "win32":
            try:
                # Windows-specific dark mode title bar
                import ctypes
                from ctypes import wintypes
                
                # Set dark mode for the application
                ctypes.windll.dwmapi.DwmSetWindowAttribute.argtypes = [
                    wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD
                ]
                
                def set_dark_title_bar(hwnd):
                    DWMWA_USE_IMMERSIVE_DARK_MODE = 20
                    set_dark = ctypes.c_int(1)
                    ctypes.windll.dwmapi.DwmSetWindowAttribute(
                        hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, 
                        ctypes.byref(set_dark), ctypes.sizeof(set_dark)
                    )
                
            except ImportError:
                # ctypes not available, skip Windows-specific styling
                pass
        
        # Set application icon if available
        # app.setWindowIcon(QIcon('icon.png'))
        
        window = MainWindow()
        
        # Apply dark title bar to main window (Windows)
        if sys.platform == "win32":
            try:
                # Get the window handle after showing
                window.show()
                hwnd = int(window.winId())
                set_dark_title_bar(hwnd)
            except:
                # If it fails, just show normally
                window.show()
        else:
            window.show()
        
        sys.exit(app.exec_())
        
    except Exception as e:
        print(f"❌ Unexpected Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main() 