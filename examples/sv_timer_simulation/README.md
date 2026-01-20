# SystemVerilog Timer Simulation Example

This example demonstrates the complete workflow for integrating and simulating
a SystemVerilog IP module using the ChipFlow VerilogWrapper system with CXXRTL
compiled simulation.

## Overview

The `wb_timer` is a simple 32-bit programmable timer with a Wishbone B4 bus
interface. This example shows how to:

1. Define a TOML configuration for the SystemVerilog module
2. Load the wrapper and create an Amaranth component
3. Simulate the design using CXXRTL compiled simulation
4. Write testbenches that verify the hardware behavior

## Files

- `wb_timer.sv` - The SystemVerilog timer implementation
- `wb_timer.toml` - TOML configuration for VerilogWrapper
- `simulate_timer.py` - Example simulation script
- `drivers/wb_timer.h` - C driver header for software integration

## Prerequisites

```bash
# Install chipflow-digital-ip with simulation support
pip install chipflow-digital-ip

# yowasp-yosys is included as a dependency and provides SystemVerilog support
```

## Quick Start

```python
from pathlib import Path
from chipflow_digital_ip.io import load_wrapper_from_toml

# Load the wrapper from TOML configuration
toml_path = Path(__file__).parent / "wb_timer.toml"
wrapper = load_wrapper_from_toml(toml_path, generate_dest=Path("build"))

# Build CXXRTL simulator
sim = wrapper.build_simulator("build/sim")

# Reset the design
sim.set("i_rst_n", 0)
sim.set("i_clk", 0)
for _ in range(4):  # A few clock cycles in reset
    sim.set("i_clk", 0)
    sim.step()
    sim.set("i_clk", 1)
    sim.step()
sim.set("i_rst_n", 1)

# Now interact with the timer via Wishbone bus
# ... (see simulate_timer.py for complete example)

sim.close()
```

## TOML Configuration Explained

```toml
# Module name - must match the Verilog module name
name = 'wb_timer'

[files]
# Source files location (relative to this TOML file)
path = '.'

[generate]
# Use yosys with slang plugin for SystemVerilog support
generator = 'yosys_slang'

[generate.yosys_slang]
top_module = 'wb_timer'

[clocks]
# Map clock domains to Verilog signals
sys = 'clk'  # System clock -> i_clk

[resets]
# Map reset domains to Verilog signals (active-low)
sys = 'rst_n'  # System reset -> i_rst_n

[ports.bus]
# Wishbone bus interface - auto-mapped from signal patterns
interface = 'amaranth_soc.wishbone.Signature'
direction = 'in'

[ports.bus.params]
addr_width = 4
data_width = 32
granularity = 8

[pins.irq]
# Simple output signal - requires explicit mapping
interface = 'amaranth.lib.wiring.Out(1)'
map = 'o_irq'

[driver]
# Software driver configuration
regs_struct = 'wb_timer_regs_t'
h_files = ['drivers/wb_timer.h']
```

## Register Map

| Address | Name    | Description                                      |
|---------|---------|--------------------------------------------------|
| 0x0     | CTRL    | [31:16] prescaler, [1] irq_en, [0] enable       |
| 0x1     | COMPARE | Compare value for timer match                    |
| 0x2     | COUNTER | Current counter (read) / Reload value (write)   |
| 0x3     | STATUS  | [1] match, [0] irq_pending (write 1 to clear)   |

## Running the Example

```bash
# Run the simulation script
python simulate_timer.py

# Or run the tests
pytest test_timer.py -v
```

## Signal Names in Simulation

When using `CxxrtlSimulator`, signals are accessed by their Verilog names:

| Amaranth Path  | Verilog Signal |
|----------------|----------------|
| `bus.cyc`      | `i_wb_cyc`     |
| `bus.stb`      | `i_wb_stb`     |
| `bus.we`       | `i_wb_we`      |
| `bus.adr`      | `i_wb_adr`     |
| `bus.dat_w`    | `i_wb_dat`     |
| `bus.dat_r`    | `o_wb_dat`     |
| `bus.ack`      | `o_wb_ack`     |
| `bus.sel`      | `i_wb_sel`     |
| `irq`          | `o_irq`        |
| (clock)        | `i_clk`        |
| (reset)        | `i_rst_n`      |

## Next Steps

- See the [VerilogWrapper documentation](../../docs/verilog_wrapper.rst) for
  complete API reference
- Check `tests/test_wb_timer.py` for comprehensive test examples
- Explore `usb_ohci.toml` for a more complex SpinalHDL-based example
