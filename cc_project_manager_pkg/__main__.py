#!/usr/bin/env python3
"""Launcher for the Cologne Chip Project Manager.

This script allows users to choose between CLI and GUI modes.
"""

import sys
import argparse
import os


def main():
    """Main launcher function."""
    parser = argparse.ArgumentParser(
        description="GateMate Project Manager by JOCRIX - FPGA Development Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --gui          # Launch GUI interface (default)
  %(prog)s --cli          # Launch CLI interface  
  %(prog)s --help         # Show this help message

The GUI interface provides a modern graphical user interface with all
functionality accessible through buttons and menus. The CLI interface
provides the traditional command-line menu system using WASD navigation.
        """
    )
    
    interface_group = parser.add_mutually_exclusive_group()
    interface_group.add_argument(
        '--gui', 
        action='store_true', 
        help='Launch GUI interface (default)'
    )
    interface_group.add_argument(
        '--cli', 
        action='store_true', 
        help='Launch CLI interface'
    )
    
    args = parser.parse_args()
    
    # Default to GUI if no option specified
    if not args.cli and not args.gui:
        args.gui = True
    
    try:
        if args.gui:
            print("🚀 Launching GateMate Project Manager by JOCRIX GUI...")
            
            # Check PyQt5 availability
            try:
                import PyQt5
            except ImportError:
                print("❌ Error: PyQt5 is required for GUI mode but not installed.")
                print("📦 Install it with: pip install PyQt5")
                print("💡 Alternatively, use --cli for command-line interface")
                sys.exit(1)
            
            # Import and run GUI
            from .gui import main as gui_main
            gui_main()
            
        elif args.cli:
            print("🚀 Launching GateMate Project Manager by JOCRIX CLI...")
            
            # Import and run CLI
            from .cli import MenuSystem
            menu = MenuSystem()
            menu.run()
            
    except KeyboardInterrupt:
        print("\n🛑 Operation cancelled by user")
        sys.exit(0)
    except ImportError as e:
        print(f"❌ Import Error: {e}")
        print("🔧 Please ensure all dependencies are installed:")
        print("   pip install -r requirements.txt")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Unexpected Error: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main() 