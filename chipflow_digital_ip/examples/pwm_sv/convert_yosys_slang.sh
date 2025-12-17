#!/usr/bin/env bash
# Convert PWM peripheral SystemVerilog to RTLIL using yosys-slang
# Example demonstrating peripheral with pad ring connections
set -ex

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUTPUT_DIR="${SCRIPT_DIR}/rtlil"

# Create output directory if it doesn't exist
mkdir -p "$OUTPUT_DIR"

# Run yosys with the slang plugin
yosys -m slang -p "
    read_slang \\
        --top pwm_peripheral \\
        ${SCRIPT_DIR}/pwm_peripheral.sv

    # Check hierarchy only - no synthesis passes
    # This preserves RTL structure for downstream tools
    hierarchy -check -top pwm_peripheral

    # Write RTLIL output
    write_rtlil ${OUTPUT_DIR}/pwm_peripheral.il
"

echo "Conversion complete: ${OUTPUT_DIR}/pwm_peripheral.il"
echo ""
echo "The RTLIL output preserves the module interface with pad connections:"
echo "  - pwm_o[3:0]     : PWM outputs to pad ring"
echo "  - pwm_oe_o[3:0]  : Output enables for PWM pads"
echo "  - capture_i[3:0] : Input capture from pad ring"
echo "  - gpio_o[7:0]    : GPIO outputs to pad ring"
echo "  - gpio_oe_o[7:0] : Output enables for GPIO pads"
echo "  - gpio_i[7:0]    : GPIO inputs from pad ring"
