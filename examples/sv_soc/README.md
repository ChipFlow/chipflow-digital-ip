# SystemVerilog SoC Example

This example demonstrates integrating SystemVerilog/Verilog components into a
ChipFlow SoC design using `VerilogWrapper`.

## Overview

The example creates a minimal SoC with:

- **Minerva RISC-V CPU** - 32-bit processor
- **QSPI Flash** - Code and data storage
- **SRAM** - 1KB working memory
- **GPIO** - 8-bit LED control
- **UART** - Serial output at 115200 baud
- **SystemVerilog Timer** - Programmable timer loaded via VerilogWrapper

The timer peripheral (`wb_timer`) is written in SystemVerilog and integrated
using the TOML-based `VerilogWrapper` configuration system.

## Directory Structure

```
sv_soc/
├── chipflow.toml          # ChipFlow project configuration
├── design/
│   ├── design.py          # SoC top-level design
│   ├── rtl/               # SystemVerilog source files
│   │   ├── wb_timer.sv    # Timer peripheral implementation
│   │   ├── wb_timer.toml  # VerilogWrapper configuration
│   │   └── drivers/
│   │       └── wb_timer.h # C driver header
│   ├── steps/
│   │   └── board.py       # FPGA board build step
│   ├── software/
│   │   └── main.c         # Firmware demonstrating timer usage
│   └── tests/
│       └── test_timer_sim.py  # CXXRTL simulation test
└── README.md
```

## Timer Peripheral

The `wb_timer` is a 32-bit programmable timer with:

- **Wishbone B4 interface** - Standard bus protocol
- **Prescaler** - 16-bit clock divider
- **Compare match** - Interrupt when counter reaches compare value
- **Auto-reload** - Continuous operation mode

### Registers

| Offset | Name    | Description                                    |
|--------|---------|------------------------------------------------|
| 0x00   | CTRL    | Control: [31:16] prescaler, [1] irq_en, [0] en |
| 0x04   | COMPARE | Compare value for match interrupt              |
| 0x08   | COUNTER | Current count (read) / Reload value (write)    |
| 0x0C   | STATUS  | Status: [1] match, [0] irq_pending (W1C)       |

## VerilogWrapper Configuration

The timer is configured via `wb_timer.toml`:

```toml
name = 'wb_timer'

[files]
path = '.'

[generate]
generator = 'yosys_slang'

[generate.yosys_slang]
top_module = 'wb_timer'

[clocks]
sys = 'clk'

[resets]
sys = 'rst_n'

# Wishbone bus interface (auto-mapped from signal patterns)
[ports.bus]
interface = 'amaranth_soc.wishbone.Signature'
direction = 'in'

[ports.bus.params]
addr_width = 4
data_width = 32
granularity = 8

# IRQ output pin
[pins.irq]
interface = 'amaranth.lib.wiring.Out(1)'
map = 'o_irq'
```

## Usage

### Prerequisites

- Python 3.12+
- chipflow-lib with simulation support
- yowasp-yosys with slang plugin (or native yosys+slang)

### Running the Simulation Test

```bash
cd examples/sv_soc

# Run the CXXRTL simulation test
python design/tests/test_timer_sim.py
```

Expected output:

```
SystemVerilog Timer CXXRTL Simulation Test
==================================================

1. Loading timer from: .../rtl/wb_timer.toml
   Module: wb_timer
   Source files: ['wb_timer.sv']

2. Building CXXRTL simulator in: .../build/timer_sim
   Simulator ready!

3. Test: Reset and read initial values
   CTRL:    0x00000000 (expected: 0x00000000)
   COUNTER: 0x00000000 (expected: 0x00000000)
   STATUS:  0x00000000 (expected: 0x00000000)
   PASS!

...

==================================================
All tests passed!
==================================================
```

### Building for FPGA

```bash
cd examples/sv_soc

# Build for ULX3S board
chipflow build board
```

### Using in Your Own Design

```python
from chipflow_digital_ip.io import load_wrapper_from_toml

# Load the timer
timer = load_wrapper_from_toml(
    "path/to/wb_timer.toml",
    generate_dest="build/timer_gen"
)

# Add to Wishbone decoder
wb_decoder.add(timer.bus, name="timer", addr=TIMER_BASE)

# Add to module
m.submodules.timer = timer

# Access IRQ signal
m.d.comb += cpu_irq.eq(timer.irq.o)
```

## Key Concepts

### VerilogWrapper

`VerilogWrapper` bridges Verilog/SystemVerilog modules into Amaranth designs:

1. **TOML Configuration** - Describes the module interface
2. **Auto-mapping** - Automatically maps bus signals (cyc, stb, ack, etc.)
3. **Code Generation** - Converts SystemVerilog to Verilog via yosys+slang
4. **Simulation** - Builds CXXRTL simulators for fast testing

### CXXRTL Simulation

The `build_simulator()` method compiles the RTL to a shared library:

```python
# Build simulator
sim = wrapper.build_simulator("build/sim")

# Control signals
sim.set("i_clk", 1)
sim.step()

# Read outputs
data = sim.get("o_wb_dat")
```

## Memory Map

| Address      | Peripheral    | Size   |
|--------------|---------------|--------|
| 0x00000000   | SPI Flash     | 16MB   |
| 0x10000000   | SRAM          | 1KB    |
| 0xB0000000   | Flash CSRs    | 4KB    |
| 0xB1000000   | GPIO          | 4KB    |
| 0xB2000000   | UART          | 4KB    |
| 0xB3000000   | Timer (SV)    | 4KB    |
| 0xB4000000   | SoC ID        | 4KB    |

## License

BSD-2-Clause
