#!/usr/bin/env python3
"""
Setup helper for openFPGALoader path configuration.

Helps configure openFPGALoader for GateMate Project Manager by:
1. Finding openFPGALoader on PATH (or prompting for a user path)
2. Providing instructions for Windows PATH setup
"""

import sys
import os
import shutil
import subprocess


def main():
    print("=" * 70)
    print("openFPGALoader Path Configuration Setup")
    print("=" * 70)

    print("\n1. Searching for openFPGALoader on PATH...")
    found_path = shutil.which("openFPGALoader") or shutil.which("openFPGALoader.exe")

    if found_path:
        print(f"   ✅ Found: {found_path}")
        print("\n2. Testing openFPGALoader...")
        try:
            result = subprocess.run(
                [found_path, "--Version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                print("   ✅ openFPGALoader is working correctly")
                print(f"   Version: {result.stdout.strip()}")
            else:
                print("   ⚠️  openFPGALoader responded but with error")
                print(f"   Error: {result.stderr}")
        except Exception as e:
            print(f"   ❌ Error testing openFPGALoader: {e}")

        print(
            f"""
3. Configuration Instructions...

Option 1 - Direct Path Configuration (Recommended):
   In GateMate Project Manager → Configuration → Edit Toolchain Paths,
   set openFPGALoader to:
   {found_path}

Option 2 - Keep using PATH:
   Leave the preference on PATH if the binary stays discoverable.
"""
        )
    else:
        print("   ❌ openFPGALoader.exe not found on PATH")
        print(
            """
   Install openFPGALoader (or OSS CAD Suite / GateMate toolchain), then either:
   - Add its bin directory to Windows PATH, or
   - Set the absolute path under Configuration → Edit Toolchain Paths
"""
        )

    print("\n" + "=" * 70)
    print("Windows PATH Configuration Instructions")
    print("=" * 70)
    print(
        """
1. Locate the folder that contains openFPGALoader.exe
2. Open System Properties → Environment Variables
3. Edit the User or System PATH variable
4. Add that folder to PATH
5. Restart GateMate Project Manager / any open terminals
"""
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
