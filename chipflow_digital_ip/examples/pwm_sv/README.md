# PWM Peripheral Example (SystemVerilog with TOML Binding)

This example demonstrates a SystemVerilog peripheral with pad ring connections,
wrapped for Amaranth SoC integration using the TOML binding system and
yosys-slang for RTLIL generation.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Amaranth SoC                                               │
│                                                             │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  VerilogWrapper (generated from pwm_peripheral.toml)  │  │
│  │                                                        │  │
│  │  ┌──────────────────────────────────────────────────┐ │  │
│  │  │  pwm_peripheral.sv (via yosys-slang → RTLIL)     │ │  │
│  │  └──────────────────────────────────────────────────┘ │  │
│  │                                                        │  │
│  │  CSR Bus ◄─────────────────────────► SoC Bus          │  │
│  │  PWM outputs ──────────────────────► Pad Ring         │  │
│  │  Capture inputs ◄────────────────── Pad Ring          │  │
│  │  GPIO ◄────────────────────────────► Pad Ring         │  │
│  └───────────────────────────────────────────────────────┘  │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

## Files

| File | Description |
|------|-------------|
| `pwm_peripheral.sv` | SystemVerilog RTL implementation |
| `pwm_peripheral.toml` | TOML binding for Amaranth wrapper generation |
| `pwm_tb.sv` | SystemVerilog testbench for RTL verification |
| `test_pwm.py` | Cocotb tests for RTL simulation |
| `Makefile` | Build/simulation automation |
| `convert_yosys_slang.sh` | Standalone RTLIL conversion script |

## TOML Binding

The `pwm_peripheral.toml` defines how the SystemVerilog module is wrapped:

```toml
name = 'pwm_peripheral'

[files]
path = 'examples/pwm_sv'

[generate]
generator = 'yosys_slang'

[generate.yosys_slang]
top_module = 'pwm_peripheral'

[clocks]
sys = 'clk_i'

[resets]
sys = 'rst_ni'

[ports.csr]
interface = 'amaranth_soc.csr.Signature'
# ... port mappings

[pins.pwm]
interface = 'chipflow.platform.GPIOSignature'
# ... pin mappings
```

## Usage in an SoC

```python
from chipflow_digital_ip.io import load_wrapper_from_toml

# Load the wrapper from TOML
pwm = load_wrapper_from_toml('examples/pwm_sv/pwm_peripheral.toml')

# Use in your SoC
class MySoC(Elaboratable):
    def elaborate(self, platform):
        m = Module()
        m.submodules.pwm = pwm
        # Connect CSR bus, pad ring pins, etc.
        return m
```

## Pad Ring Interface

The peripheral exposes signals that connect to the chip's pad ring:

### PWM Outputs (Active Drive)
```
pwm.o[3:0]    - PWM output signals
pwm.oe[3:0]   - Output enable (active high)
```

### Input Capture
```
capture[3:0] - External signals for input capture
```

### GPIO (Bidirectional)
```
gpio.i[7:0]   - Input from pads
gpio.o[7:0]   - Output to pads
gpio.oe[7:0]  - Output enable for pads
```

## Register Map

| Offset | Name       | Description |
|--------|------------|-------------|
| 0x00   | Control    | Enable bits [3:0], prescaler [15:8] |
| 0x04   | Status     | Capture event flags |
| 0x10   | Duty0      | PWM channel 0 duty cycle |
| 0x14   | Duty1      | PWM channel 1 duty cycle |
| 0x18   | Duty2      | PWM channel 2 duty cycle |
| 0x1C   | Duty3      | PWM channel 3 duty cycle |
| 0x20   | Period0    | PWM channel 0 period |
| 0x24   | Period1    | PWM channel 1 period |
| 0x28   | Period2    | PWM channel 2 period |
| 0x2C   | Period3    | PWM channel 3 period |
| 0x30   | Capture0   | Input capture value channel 0 |
| 0x34   | Capture1   | Input capture value channel 1 |
| 0x38   | Capture2   | Input capture value channel 2 |
| 0x3C   | Capture3   | Input capture value channel 3 |
| 0x40   | GPIO_OUT   | GPIO output register |
| 0x44   | GPIO_OE    | GPIO output enable |
| 0x48   | GPIO_IN    | GPIO input (read-only) |

## Simulation

### Prerequisites

```bash
# Icarus Verilog
apt-get install iverilog

# Verilator
apt-get install verilator

# Cocotb (for Python testbenches)
pip install cocotb
```

### Pure SystemVerilog Testbench

```bash
make sim-sv          # Icarus Verilog
make sim-sv-verilator  # Verilator
make waves           # View in GTKWave
```

### Cocotb Python Tests

```bash
make              # Icarus Verilog (default)
make SIM=verilator
```

### Test Coverage

- Reset behavior
- PWM channel enable/disable
- PWM output generation with duty cycle
- GPIO output and output enable
- GPIO input reading
- Input capture on rising edges
- Multiple channel operation

## Standalone RTLIL Conversion

For manual conversion without the TOML wrapper:

```bash
./convert_yosys_slang.sh
# Produces: rtlil/pwm_peripheral.il
```

## Parameters

| Parameter      | Default | Description |
|----------------|---------|-------------|
| NUM_CHANNELS   | 4       | Number of PWM/capture channels |
| COUNTER_WIDTH  | 16      | Bit width of PWM counter |
