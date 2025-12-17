# Yosys-Slang Converted Verilog

This directory contains Verilog files converted from SystemVerilog using
[yosys-slang](https://github.com/povik/yosys-slang).

## Prerequisites

1. Install Yosys (version 0.44 to 0.58):
   ```bash
   # On Ubuntu/Debian
   apt-get install yosys

   # Or build from source
   git clone https://github.com/YosysHQ/yosys
   cd yosys && make -j$(nproc) && sudo make install
   ```

2. Build and install yosys-slang:
   ```bash
   git clone --recursive https://github.com/povik/yosys-slang
   cd yosys-slang
   make -j$(nproc)
   sudo make install
   ```

## Usage

From this directory (`chipflow_digital_ip/processors/_openhw/`):

```bash
# Convert CV32E40P core
./convert_cv32e40p_yosys_slang.sh

# Convert Debug Module wrapper
./convert_dm_wrap_yosys_slang.sh
```

## Output Files

- `cv32e40p_conv_yosys_slang.v` - Converted CV32E40P RISC-V core
- `dm_wrap_conv_yosys_slang.v` - Converted Debug Module wrapper

## Comparison with sv2v

This experiment provides an alternative to the existing sv2v-based conversion:

| Feature | sv2v | yosys-slang |
|---------|------|-------------|
| Approach | Standalone converter | Yosys plugin |
| Output | Source-level Verilog | Synthesized netlist |
| SV Support | IEEE 1800-2012 | IEEE 1800-2017/2023 |
| Integration | External tool | Native Yosys flow |

The yosys-slang approach integrates directly into Yosys synthesis flows, while
sv2v produces more readable source-level Verilog output.
