# Yosys-Slang RTLIL Output

This directory contains RTLIL (Yosys intermediate representation) files
converted from SystemVerilog using [yosys-slang](https://github.com/povik/yosys-slang).

RTLIL preserves the RTL structure for downstream synthesis tools.

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

From the parent directory (`chipflow_digital_ip/processors/_openhw/`):

```bash
# Convert CV32E40P core
./convert_cv32e40p_yosys_slang.sh

# Convert Debug Module wrapper
./convert_dm_wrap_yosys_slang.sh
```

## Output Files

- `cv32e40p_yosys_slang.il` - CV32E40P RISC-V core in RTLIL format
- `dm_wrap_yosys_slang.il` - Debug Module wrapper in RTLIL format

## Comparison with sv2v

This experiment provides an alternative to the existing sv2v-based conversion:

| Feature | sv2v | yosys-slang |
|---------|------|-------------|
| Approach | Standalone converter | Yosys plugin |
| Output | Source-level Verilog | RTLIL (Yosys IR) |
| SV Support | IEEE 1800-2012 | IEEE 1800-2017/2023 |
| Integration | External tool | Native Yosys flow |

The yosys-slang approach outputs RTLIL which can be directly loaded into Yosys
for synthesis, while sv2v produces human-readable Verilog source code.

## Loading RTLIL in Yosys

To use the generated RTLIL files in a Yosys synthesis flow:

```tcl
read_rtlil cv32e40p_yosys_slang.il
# ... continue with synthesis passes
```
