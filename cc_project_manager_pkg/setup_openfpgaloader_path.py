#!/usr/bin/env python3
"""
Setup script for openFPGALoader path configuration.

This script helps configure openFPGALoader for the cc_project_manager by:
1. Detecting the openFPGALoader installation
2. Adding the direct path to project configuration
3. Providing instructions for adding to Windows PATH
"""

import sys
import os
import subprocess

def main():
    print("=" * 70)
    print("openFPGALoader Path Configuration Setup")
    print("=" * 70)
    
    # Common openFPGALoader paths to check
    common_paths = [
        r"F:\GateMate_toolchain\cc-toolchain-win\bin\openFPGALoader\openFPGALoader.exe",
        r"C:\GateMate_toolchain\cc-toolchain-win\bin\openFPGALoader\openFPGALoader.exe",
        r"D:\GateMate_toolchain\cc-toolchain-win\bin\openFPGALoader\openFPGALoader.exe"
    ]
    
    found_path = None
    
    print(f"\n1. Searching for openFPGALoader installation...")
    for path in common_paths:
        print(f"   Checking: {path}")
        if os.path.exists(path):
            print("   ✅ openFPGALoader.exe found!")
            found_path = path
            break
        else:
            print("   ❌ Not found")
    
    if found_path:
        # Test if it works
        print(f"\n2. Testing openFPGALoader functionality...")
        print(f"   Using: {found_path}")
        try:
            result = subprocess.run([found_path, "--Version"], 
                                  capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                print("   ✅ openFPGALoader is working correctly")
                print(f"   Version: {result.stdout.strip()}")
            else:
                print("   ⚠️  openFPGALoader responded but with error")
                print(f"   Error: {result.stderr}")
        except Exception as e:
            print(f"   ❌ Error testing openFPGALoader: {e}")
            
        # Provide configuration instructions
        print("\n3. Configuration Instructions...")
        print(f"""
To use this openFPGALoader installation with cc_project_manager:

Option 1 - Direct Path Configuration (Recommended):
   The application can automatically use openFPGALoader from:
   {found_path}
   
   This will be configured automatically when you create or load a project.

Option 2 - Add to Windows PATH (System-wide access):
   Follow the PATH setup instructions below.
""")
                
    else:
        print("   ❌ openFPGALoader.exe not found at common locations")
        print("\n   Please check your GateMate toolchain installation.")
        print("   Common installation locations:")
        for path in common_paths:
            print(f"   - {path}")
        print("\n   If installed elsewhere, please note the installation path.")
    
    # Provide PATH setup instructions
    print("\n" + "=" * 70)
    print("Windows PATH Configuration Instructions")
    print("=" * 70)
    
    if found_path:
        path_to_add = os.path.dirname(found_path)
        print(f"""
To add openFPGALoader to your Windows PATH for system-wide access:

1. Press Win + R, type 'sysdm.cpl' and press Enter
2. Click 'Environment Variables...' button
3. In 'User variables' or 'System variables', find and select 'Path'
4. Click 'Edit...'
5. Click 'New' and add this path:
   {path_to_add}
6. Click 'OK' on all dialogs
7. Restart your command prompt/PowerShell

Alternative method using PowerShell (run as Administrator):
   $env:PATH += ";{path_to_add}"
   [Environment]::SetEnvironmentVariable("PATH", $env:PATH, "User")
""")
    else:
        print("""
To add openFPGALoader to your Windows PATH:

1. Locate your openFPGALoader installation directory
2. Copy the path to the directory containing openFPGALoader.exe
3. Press Win + R, type 'sysdm.cpl' and press Enter
4. Click 'Environment Variables...' button
5. In 'User variables' or 'System variables', find and select 'Path'
6. Click 'Edit...'
7. Click 'New' and add the copied path
8. Click 'OK' on all dialogs
9. Restart your command prompt/PowerShell
""")
    
    # Test current PATH
    print("\n4. Testing current PATH configuration...")
    try:
        result = subprocess.run(["openFPGALoader.exe", "--Version"], 
                              capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            print("   ✅ openFPGALoader.exe is already accessible via PATH!")
            print(f"   Version: {result.stdout.strip()}")
        else:
            print("   ❌ openFPGALoader.exe found in PATH but returned error")
            print(f"   Error: {result.stderr}")
    except FileNotFoundError:
        print("   ❌ openFPGALoader.exe not found in PATH")
        if found_path:
            print("   You can still use the direct path configuration in cc_project_manager")
        else:
            print("   Please install GateMate toolchain and follow setup instructions")
    except Exception as e:
        print(f"   ❌ Error testing PATH: {e}")
    
    print("\n" + "=" * 70)
    print("Setup Complete!")
    print("=" * 70)
    print("""
Summary:
- Direct path configuration allows projects to work without PATH setup
- Adding to PATH makes openFPGALoader available system-wide
- Both methods are supported by cc_project_manager

Next steps:
1. Run 'gmpm' to start the GUI application
2. Create or load a project to test the configuration
3. Check the Configuration tab for toolchain status
4. Use the Upload tab to program your FPGA

For detailed usage instructions, see:
- README.md
- GUI_QUICKSTART.md
""")
    
    return found_path is not None

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1) 