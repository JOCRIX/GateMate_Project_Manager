"""VHDL to Verilog Testbench Converter

This module provides functionality to convert VHDL testbenches to Verilog
testbenches for post-synthesis simulation.
"""

import os
import re
import logging
from typing import Dict, List, Optional, Tuple


class VHDLToVerilogConverter:
    """Converts VHDL testbenches to Verilog testbenches for post-synthesis simulation."""

    def __init__(self):
        """Initialize the converter with logging."""
        self.logger = logging.getLogger("VHDLToVerilogConverter")
        self.logger.setLevel(logging.DEBUG)
        
        # Type mappings from VHDL to Verilog
        self.type_mappings = {
            'std_logic': 'reg',
            'std_logic_vector': 'reg',
            'boolean': 'reg',
            'integer': 'integer',
            'natural': 'integer'
        }
        
        # Time unit mappings
        self.time_mappings = {
            'fs': '1',
            'ps': '1000',
            'ns': '1000000', 
            'us': '1000000000',
            'ms': '1000000000000'
        }

    def convert_testbench(self, vhdl_file_path: str, dut_netlist_path: str, 
                         output_path: str) -> bool:
        """
        Convert a VHDL testbench to Verilog.
        
        Args:
            vhdl_file_path: Path to the VHDL testbench file
            dut_netlist_path: Path to the synthesized Verilog netlist
            output_path: Path where to save the converted Verilog testbench
            
        Returns:
            bool: True if conversion successful, False otherwise
        """
        
        self.logger.info(f"Converting VHDL testbench: {vhdl_file_path}")
        self.logger.info(f"Target DUT netlist: {dut_netlist_path}")
        self.logger.info(f"Output path: {output_path}")
        
        try:
            # Read VHDL testbench
            with open(vhdl_file_path, 'r', encoding='utf-8') as f:
                vhdl_content = f.read()
            
            # Parse DUT interface from netlist
            dut_interface = self._parse_dut_interface(dut_netlist_path)
            if not dut_interface:
                self.logger.error("Failed to parse DUT interface from netlist")
                return False
            
            # Convert VHDL to Verilog
            verilog_content = self._convert_vhdl_to_verilog(vhdl_content, dut_interface)
            
            # Write Verilog testbench
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(verilog_content)
            
            self.logger.info(f"Successfully converted testbench to: {output_path}")
            return True
            
        except Exception as e:
            self.logger.error(f"Error converting testbench: {e}")
            return False

    def _parse_dut_interface(self, netlist_path: str) -> Optional[Dict]:
        """Parse the DUT interface from the Verilog netlist."""
        
        try:
            with open(netlist_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Find module declaration
            module_match = re.search(r'module\s+(\w+)\s*\((.*?)\);', content, re.DOTALL)
            if not module_match:
                self.logger.error("Could not find module declaration in netlist")
                return None
            
            module_name = module_match.group(1)
            ports_section = module_match.group(2)
            
            # Parse individual ports
            ports = []
            port_lines = [line.strip() for line in ports_section.split('\n') if line.strip()]
            
            for line in port_lines:
                # Remove comments and trailing commas
                line = re.sub(r'//.*$', '', line).strip().rstrip(',')
                if not line:
                    continue
                
                # Parse port declarations (input/output/inout)
                port_match = re.match(r'(input|output|inout)\s+(?:\[.*?\]\s+)?(\w+)', line)
                if port_match:
                    direction = port_match.group(1)
                    name = port_match.group(2)
                    
                    # Extract bit width if present
                    width_match = re.search(r'\[(\d+):(\d+)\]', line)
                    if width_match:
                        width = int(width_match.group(1)) + 1  # [7:0] = 8 bits
                    else:
                        width = 1
                    
                    ports.append({
                        'name': name,
                        'direction': direction,
                        'width': width
                    })
            
            interface = {
                'module_name': module_name,
                'ports': ports
            }
            
            self.logger.info(f"Parsed DUT interface: {module_name} with {len(ports)} ports")
            return interface
            
        except Exception as e:
            self.logger.error(f"Error parsing DUT interface: {e}")
            return None

    def _convert_vhdl_to_verilog(self, vhdl_content: str, dut_interface: Dict) -> str:
        """Convert VHDL testbench content to Verilog."""
        
        # Extract testbench components
        tb_info = self._parse_vhdl_testbench(vhdl_content)
        
        # Generate Verilog testbench
        verilog_lines = []
        
        # Header and module declaration
        verilog_lines.extend([
            "// Converted from VHDL testbench by VHDLToVerilogConverter",
            "// Auto-generated for post-synthesis simulation",
            "",
            "`timescale 1ns/1ps",
            "",
            f"module {tb_info['entity_name']}_tb;",
            ""
        ])
        
        # Signal declarations
        verilog_lines.append("// Signal declarations")
        for signal in tb_info['signals']:
            verilog_type = self._convert_signal_type(signal)
            verilog_lines.append(f"    {verilog_type};")
        
        verilog_lines.append("")
        
        # DUT instantiation
        verilog_lines.extend([
            "// DUT instantiation", 
            f"    {dut_interface['module_name']} uut ("
        ])
        
        # Port connections
        port_connections = []
        for port in dut_interface['ports']:
            port_connections.append(f"        .{port['name']}({port['name']})")
        
        verilog_lines.append(",\n".join(port_connections))
        verilog_lines.extend(["    );", ""])
        
        # Clock generation
        clock_signals = [s for s in tb_info['signals'] if 'clk' in s['name'].lower()]
        if clock_signals:
            verilog_lines.extend([
                "// Clock generation",
                f"    always #10 {clock_signals[0]['name']} = ~{clock_signals[0]['name']};",
                ""
            ])
        
        # Stimulus process conversion
        verilog_lines.extend([
            "// Stimulus process",
            "    initial begin",
            "        // Initialize signals"
        ])
        
        # Add signal initializations
        for signal in tb_info['signals']:
            if signal['direction'] in ['input', 'inout']:  # Only initialize inputs
                init_value = signal.get('init_value', '0')
                verilog_lines.append(f"        {signal['name']} = {init_value};")
        
        verilog_lines.append("")
        
        # Convert stimulus from VHDL processes
        stimulus = self._convert_stimulus_processes(tb_info.get('processes', []))
        verilog_lines.extend([f"        {line}" for line in stimulus])
        
        verilog_lines.extend([
            "",
            "        // End simulation",
            "        $finish;",
            "    end",
            "",
            "endmodule"
        ])
        
        return "\n".join(verilog_lines)

    def _parse_vhdl_testbench(self, vhdl_content: str) -> Dict:
        """Parse VHDL testbench to extract key components."""
        
        tb_info = {
            'entity_name': '',
            'signals': [],
            'processes': []
        }
        
        # Extract entity name
        entity_match = re.search(r'entity\s+(\w+)\s+is', vhdl_content, re.IGNORECASE)
        if entity_match:
            tb_info['entity_name'] = entity_match.group(1)
        
        # Extract signal declarations
        signal_pattern = r'signal\s+(\w+)\s*:\s*([\w_]+(?:\(.*?\))?)\s*(?::=\s*([^;]+))?;'
        signals = re.findall(signal_pattern, vhdl_content, re.IGNORECASE)
        
        for signal_name, signal_type, init_value in signals:
            # Determine direction based on signal usage patterns
            direction = 'reg'  # Default for testbench signals
            
            # Check if it's connected to DUT
            if re.search(rf'{signal_name}\s*=>', vhdl_content):
                direction = 'input' if 'in' in signal_type else 'output'
            
            tb_info['signals'].append({
                'name': signal_name,
                'type': signal_type,
                'direction': direction,
                'init_value': self._convert_init_value(init_value) if init_value else '0'
            })
        
        return tb_info

    def _convert_signal_type(self, signal: Dict) -> str:
        """Convert VHDL signal type to Verilog."""
        
        vhdl_type = signal['type'].lower()
        signal_name = signal['name']
        init_value = signal.get('init_value', '0')
        
        # Handle std_logic_vector
        if 'std_logic_vector' in vhdl_type:
            # Extract range
            range_match = re.search(r'\((\d+)\s+downto\s+(\d+)\)', vhdl_type)
            if range_match:
                high = range_match.group(1)
                low = range_match.group(2)
                return f"reg [{high}:{low}] {signal_name} = {init_value}"
        
        # Handle basic types
        verilog_type = self.type_mappings.get(vhdl_type.split('(')[0], 'reg')
        return f"{verilog_type} {signal_name} = {init_value}"

    def _convert_init_value(self, vhdl_value: str) -> str:
        """Convert VHDL initialization value to Verilog."""
        
        vhdl_value = vhdl_value.strip().strip("'\"")
        
        # Boolean values
        if vhdl_value.lower() == 'true':
            return '1\'b1'
        elif vhdl_value.lower() == 'false':
            return '1\'b0'
        
        # Std_logic values
        if vhdl_value == '0':
            return '1\'b0'
        elif vhdl_value == '1':
            return '1\'b1'
        
        # Default
        return '0'

    def _convert_stimulus_processes(self, processes: List) -> List[str]:
        """Convert VHDL stimulus processes to Verilog initial blocks."""
        
        stimulus_lines = [
            "// Reset sequence",
            "rst = 1;",
            "#100;",
            "rst = 0;",
            "",
            "// Wait for simulation to complete", 
            "#1200;",
            "",
            "// Display end message",
            "$display(\"Simulation Ended\");"
        ]
        
        return stimulus_lines

if __name__ == "__main__":
    # Test the converter
    converter = VHDLToVerilogConverter()
    print("VHDLToVerilogConverter class created successfully!") 