#!/usr/bin/env python3
"""Setup script for GateMate Project Manager by JOCRIX."""

from setuptools import setup, find_packages
import os

# Read the README file for long description
def read_readme():
    with open("README.md", "r", encoding="utf-8") as fh:
        return fh.read()

# Read requirements from requirements.txt in the package
def read_requirements():
    requirements_path = os.path.join("cc_project_manager_pkg", "requirements.txt")
    with open(requirements_path, "r", encoding="utf-8") as fh:
        return [line.strip() for line in fh if line.strip() and not line.startswith("#")]

setup(
    name="cc-project-manager",
    version="0.3.1",
    author="JOCRIX",
    author_email="",  # Add email if desired
    description="A comprehensive GateMate FPGA project management tool with GUI and CLI interfaces for GHDL, Yosys, and PnR workflows",
    long_description=read_readme(),
    long_description_content_type="text/markdown",
    url="",  # Add repository URL if available
    packages=find_packages(),
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "Topic :: Software Development :: Build Tools",
        "Topic :: Scientific/Engineering :: Electronic Design Automation (EDA)",
        "License :: OSI Approved :: MIT License",  # Change as needed
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Operating System :: OS Independent",
    ],
    python_requires=">=3.8",
    install_requires=read_requirements(),
    entry_points={
        "console_scripts": [
            # Main entry points
            "gmpm=cc_project_manager_pkg.gui:main",
            "gatemate-project-manager=cc_project_manager_pkg.gui:main",
            # Alternative entry points
            "ccpm=cc_project_manager_pkg.gui:main",
            "cc-project-manager=cc_project_manager_pkg.gui:main",
        ],
        "gui_scripts": [
            # GUI-specific entry (no console window on Windows)
            "gmpm-gui=cc_project_manager_pkg.gui:main",
            "ccpm-gui=cc_project_manager_pkg.gui:main",
        ],
    },
    include_package_data=True,
    package_data={
        "cc_project_manager_pkg": ["*.yml", "*.yaml"],
    },
    keywords="fpga vhdl synthesis simulation gatemate ghdl yosys gui pyqt5 jocrix",
    project_urls={
        "Bug Reports": "",  # Add if available
        "Source": "",       # Add if available
        "Documentation": "", # Add if available
    },
) 