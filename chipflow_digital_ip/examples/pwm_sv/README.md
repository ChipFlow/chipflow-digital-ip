# PWM Peripheral Example (SystemVerilog)

This example demonstrates a SystemVerilog peripheral with pad ring connections,
suitable for conversion to RTLIL using yosys-slang.

## Pad Ring Interface

The peripheral exposes signals that connect to the chip's pad ring:

### PWM Outputs (Active Drive)
```
pwm_o[3:0]    - PWM output signals
pwm_oe_o[3:0] - Output enable (active high)
```

### Input Capture
```
capture_i[3:0] - External signals for input capture
```

### GPIO (Bidirectional)
```
gpio_i[7:0]   - Input from pads
gpio_o[7:0]   - Output to pads
gpio_oe_o[7:0] - Output enable for pads
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

## Converting to RTLIL

```bash
./convert_yosys_slang.sh
```

This produces `rtlil/pwm_peripheral.il` which can be loaded into Yosys:

```tcl
read_rtlil pwm_peripheral.il
# Continue with synthesis...
```

## Parameters

| Parameter      | Default | Description |
|----------------|---------|-------------|
| NUM_CHANNELS   | 4       | Number of PWM/capture channels |
| COUNTER_WIDTH  | 16      | Bit width of PWM counter |
