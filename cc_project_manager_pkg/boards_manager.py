"""
Board Configuration Manager

This module manages FPGA board configurations for openFPGALoader integration.
It handles loading, saving, and maintaining board definitions in a YAML configuration file.
"""

import os
import yaml
import logging
from typing import Dict, List, Optional, Any

class BoardsManager:
    """
    Manages global FPGA board configurations for all projects.
    
    This class handles:
    - Loading and saving board configurations from ~/.cc_project_manager/
    - Managing default board definitions
    - Providing board information to the GUI across all projects
    - Maintaining the global boards_configuration.yaml file
    
    The boards configuration is stored globally so that boards are available
    to all projects without needing to be configured per-project.
    """
    
    def __init__(self):
        """Initialize the BoardsManager and ensure configuration file exists."""
        
        # Set up logging
        self.boards_logger = logging.getLogger("BoardsManager")
        self.boards_logger.setLevel(logging.DEBUG)
        self.boards_logger.propagate = False
        
        # Remove existing handlers
        for handler in self.boards_logger.handlers[:]:
            self.boards_logger.removeHandler(handler)
        
        # Get application data directory (same as GUI settings)
        self.app_data_dir = self._get_app_data_directory()
        
        # Set up logging to application data directory
        log_path = os.path.join(self.app_data_dir, "boards_manager.log")
        file_handler = logging.FileHandler(log_path)
        formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
        file_handler.setFormatter(formatter)
        self.boards_logger.addHandler(file_handler)
        
        # Set configuration file path in application data directory
        self.config_file_path = os.path.join(self.app_data_dir, "boards_configuration.yaml")
        
        # Initialize configuration
        self.boards_config = {}
        self._initialize_configuration()
        
        self.boards_logger.info("BoardsManager initialized successfully")
    
    def _initialize_configuration(self):
        """Initialize the boards configuration file with defaults if it doesn't exist."""
        if not os.path.exists(self.config_file_path):
            self.boards_logger.info("Creating new boards_configuration.yaml with default boards")
            self._create_default_configuration()
        else:
            self.boards_logger.info("Loading existing boards_configuration.yaml")
            self._load_configuration()
            
        # Ensure we have default boards (in case file was corrupted or incomplete)
        self._ensure_default_boards()
    
    def _create_default_configuration(self):
        """Create the default boards configuration."""
        default_config = {
            'boards_configuration': {
                'version': '1.0.0',
                'description': 'FPGA Board Configuration for openFPGALoader integration',
                'created_by': 'Cologne Chip Project Manager',
                'boards': self._get_default_boards()
            }
        }
        
        self.boards_config = default_config
        self._save_configuration()
    
    def _get_default_boards(self) -> Dict[str, Dict[str, Any]]:
        """Get the default board configurations."""
        return {
            'olimex_gatemateevb': {
                'name': 'Olimex GateMate EVB',
                'description': 'Olimex GateMate Evaluation Board',
                'manufacturer': 'Olimex',
                'fpga_family': 'GateMate',
                'openFPGALoader_identifier': 'olimex_gatemateevb',
                'supported_interfaces': ['jtag', 'spi'],
                'default_interface': 'auto',
                'programming_modes': ['sram', 'flash'],
                'verified': True,
                'notes': 'Default board - well tested and supported'
            },
            'gatemate_evb_jtag': {
                'name': 'Cologne Chip GateMate EVB (JTAG)',
                'description': 'Cologne Chip GateMate FPGA Evaluation Board (JTAG mode)',
                'manufacturer': 'Cologne Chip',
                'fpga_family': 'GateMate',
                'openFPGALoader_identifier': 'gatemate_evb_jtag',
                'supported_interfaces': ['jtag'],
                'default_interface': 'jtag',
                'programming_modes': ['sram', 'flash'],
                'verified': True,
                'notes': 'Official Cologne Chip evaluation board - JTAG interface'
            },
            'gatemate_evb_spi': {
                'name': 'Cologne Chip GateMate EVB (SPI)',
                'description': 'Cologne Chip GateMate FPGA Evaluation Board (SPI mode)',
                'manufacturer': 'Cologne Chip',
                'fpga_family': 'GateMate',
                'openFPGALoader_identifier': 'gatemate_evb_spi',
                'supported_interfaces': ['spi'],
                'default_interface': 'spi',
                'programming_modes': ['sram', 'flash'],
                'verified': True,
                'notes': 'Official Cologne Chip evaluation board - SPI interface'
            },
            'gatemate_pgm_spi': {
                'name': 'Cologne Chip GateMate Programmer (SPI)',
                'description': 'Cologne Chip GateMate FPGA Programmer (SPI mode)',
                'manufacturer': 'Cologne Chip',
                'fpga_family': 'GateMate',
                'openFPGALoader_identifier': 'gatemate_pgm_spi',
                'supported_interfaces': ['spi'],
                'default_interface': 'spi',
                'programming_modes': ['sram', 'flash'],
                'verified': True,
                'notes': 'Official Cologne Chip FPGA programmer - SPI interface'
            },
            'example_sram_only': {
                'name': 'Example SRAM-Only Board',
                'description': 'Example board that only supports SRAM programming',
                'manufacturer': 'Example Corp',
                'fpga_family': 'GateMate',
                'openFPGALoader_identifier': 'example_sram_only',
                'supported_interfaces': ['jtag'],
                'default_interface': 'jtag',
                'programming_modes': ['sram'],
                'verified': False,
                'notes': 'Test board to demonstrate dynamic button states - Flash programming not supported'
            }
        }
    
    def _load_configuration(self):
        """Load the boards configuration from YAML file."""
        try:
            with open(self.config_file_path, 'r') as f:
                self.boards_config = yaml.safe_load(f) or {}
            self.boards_logger.info(f"Loaded boards configuration from {self.config_file_path}")
        except Exception as e:
            self.boards_logger.error(f"Failed to load boards configuration: {e}")
            self.boards_logger.info("Creating new configuration with defaults")
            self._create_default_configuration()
    
    def _save_configuration(self):
        """Save the current boards configuration to YAML file."""
        try:
            with open(self.config_file_path, 'w') as f:
                yaml.safe_dump(self.boards_config, f, default_flow_style=False, indent=2)
            self.boards_logger.info(f"Saved boards configuration to {self.config_file_path}")
        except Exception as e:
            self.boards_logger.error(f"Failed to save boards configuration: {e}")
    
    def _ensure_default_boards(self):
        """Ensure all default boards are present in the configuration."""
        if 'boards_configuration' not in self.boards_config:
            self.boards_config['boards_configuration'] = {}
        if 'boards' not in self.boards_config['boards_configuration']:
            self.boards_config['boards_configuration']['boards'] = {}
        
        default_boards = self._get_default_boards()
        current_boards = self.boards_config['boards_configuration']['boards']
        
        updated = False
        for board_id, board_config in default_boards.items():
            if board_id not in current_boards:
                current_boards[board_id] = board_config
                updated = True
                self.boards_logger.info(f"Added default board: {board_config['name']}")
        
        if updated:
            self._save_configuration()
    
    def _get_app_data_directory(self) -> str:
        """Get the application data directory (same as GUI settings directory)."""
        home_dir = os.path.expanduser("~")
        app_data_dir = os.path.join(home_dir, ".cc_project_manager")
        os.makedirs(app_data_dir, exist_ok=True)
        return app_data_dir
    
    def get_available_boards(self) -> Dict[str, Dict[str, Any]]:
        """
        Get all available boards from the configuration.
        
        Returns:
            Dict containing board_id -> board_config mappings
        """
        return self.boards_config.get('boards_configuration', {}).get('boards', {})
    
    def get_board_by_id(self, board_id: str) -> Optional[Dict[str, Any]]:
        """
        Get a specific board configuration by its ID.
        
        Args:
            board_id: The board identifier
            
        Returns:
            Board configuration dict or None if not found
        """
        boards = self.get_available_boards()
        return boards.get(board_id)
    
    def get_board_display_info(self) -> List[Dict[str, str]]:
        """
        Get board information formatted for GUI display.
        
        Returns:
            List of dicts with 'name', 'identifier', and 'description' keys
        """
        boards = self.get_available_boards()
        display_info = []
        
        for board_id, board_config in boards.items():
            display_info.append({
                'name': board_config.get('name', board_id),
                'identifier': board_id,
                'description': board_config.get('description', 'No description available'),
                'manufacturer': board_config.get('manufacturer', 'Unknown'),
                'verified': board_config.get('verified', False)
            })
        
        # Sort by name for consistent display
        display_info.sort(key=lambda x: x['name'])
        return display_info
    
    def add_board(self, board_id: str, board_config: Dict[str, Any]) -> bool:
        """
        Add a new board to the configuration.
        
        Args:
            board_id: Unique identifier for the board
            board_config: Board configuration dictionary
            
        Returns:
            True if added successfully, False otherwise
        """
        try:
            boards = self.boards_config.get('boards_configuration', {}).get('boards', {})
            
            if board_id in boards:
                self.boards_logger.warning(f"Board {board_id} already exists, use update_board instead")
                return False
            
            boards[board_id] = board_config
            self._save_configuration()
            self.boards_logger.info(f"Added new board: {board_config.get('name', board_id)}")
            return True
            
        except Exception as e:
            self.boards_logger.error(f"Failed to add board {board_id}: {e}")
            return False
    
    def update_board(self, board_id: str, board_config: Dict[str, Any]) -> bool:
        """
        Update an existing board configuration.
        
        Args:
            board_id: Board identifier to update
            board_config: New board configuration
            
        Returns:
            True if updated successfully, False otherwise
        """
        try:
            boards = self.boards_config.get('boards_configuration', {}).get('boards', {})
            
            if board_id not in boards:
                self.boards_logger.warning(f"Board {board_id} not found, use add_board instead")
                return False
            
            boards[board_id] = board_config
            self._save_configuration()
            self.boards_logger.info(f"Updated board: {board_config.get('name', board_id)}")
            return True
            
        except Exception as e:
            self.boards_logger.error(f"Failed to update board {board_id}: {e}")
            return False
    
    def remove_board(self, board_id: str) -> bool:
        """
        Remove a board from the configuration.
        
        Args:
            board_id: Board identifier to remove
            
        Returns:
            True if removed successfully, False otherwise
        """
        try:
            boards = self.boards_config.get('boards_configuration', {}).get('boards', {})
            
            if board_id not in boards:
                self.boards_logger.warning(f"Board {board_id} not found")
                return False
            
            board_name = boards[board_id].get('name', board_id)
            del boards[board_id]
            self._save_configuration()
            self.boards_logger.info(f"Removed board: {board_name}")
            return True
            
        except Exception as e:
            self.boards_logger.error(f"Failed to remove board {board_id}: {e}")
            return False
    
    def get_default_board(self) -> Optional[Dict[str, str]]:
        """
        Get the default board (currently Olimex).
        
        Returns:
            Dict with 'name' and 'identifier' keys for the default board
        """
        boards = self.get_board_display_info()
        
        # Look for Olimex board first (current default)
        for board in boards:
            if board['identifier'] == 'olimex_gatemateevb':
                return board
        
        # If no Olimex board, return the first available board
        if boards:
            return boards[0]
        
        return None
    
    def get_board_details(self, board_identifier: str) -> Optional[Dict[str, Any]]:
        """
        Get detailed configuration for a specific board.
        
        Args:
            board_identifier: The board identifier (e.g., 'olimex_gatemateevb')
            
        Returns:
            dict: Complete board configuration or None if board not found
        """
        try:
            boards = self.boards_config.get('boards_configuration', {}).get('boards', {})
            
            if board_identifier in boards:
                board_config = boards[board_identifier].copy()
                # Add the identifier to the returned config for convenience
                board_config["identifier"] = board_identifier
                return board_config
            else:
                self.boards_logger.warning(f"Board '{board_identifier}' not found in configuration")
                return None
                
        except Exception as e:
            self.boards_logger.error(f"Error getting board details for '{board_identifier}': {e}")
            return None
    
    def validate_board_config(self, board_config: Dict[str, Any]) -> List[str]:
        """
        Validate a board configuration.
        
        Args:
            board_config: Board configuration to validate
            
        Returns:
            List of validation errors (empty if valid)
        """
        errors = []
        
        required_fields = ['name', 'openFPGALoader_identifier']
        for field in required_fields:
            if field not in board_config:
                errors.append(f"Missing required field: {field}")
        
        # Validate supported interfaces
        if 'supported_interfaces' in board_config:
            valid_interfaces = ['jtag', 'spi', 'auto']
            for interface in board_config['supported_interfaces']:
                if interface not in valid_interfaces:
                    errors.append(f"Invalid interface: {interface}")
        
        # Validate programming modes
        if 'programming_modes' in board_config:
            valid_modes = ['sram', 'flash']
            for mode in board_config['programming_modes']:
                if mode not in valid_modes:
                    errors.append(f"Invalid programming mode: {mode}")
        
        return errors 