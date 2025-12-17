#!/usr/bin/env bash
# Convert CV32E40P SystemVerilog to RTLIL using yosys-slang
# This is an alternative to sv2v using Yosys with the slang plugin
# Output is RTLIL (Yosys intermediate representation) for submission
set -ex

CV32E40P_PATH="${CV32E40P_DIR:=../../../vendor/cv32e40p}"
DESIGN_RTL_DIR="$CV32E40P_PATH/rtl"
OUTPUT_DIR="rtlil_yosys_slang"

# Create output directory if it doesn't exist
mkdir -p "$OUTPUT_DIR"

# Build the file list for read_slang
# Note: Order matters - packages and includes first
SV_FILES=(
    "${DESIGN_RTL_DIR}/include/cv32e40p_apu_core_pkg.sv"
    "${DESIGN_RTL_DIR}/include/cv32e40p_fpu_pkg.sv"
    "${DESIGN_RTL_DIR}/include/cv32e40p_pkg.sv"
    "${DESIGN_RTL_DIR}/cv32e40p_if_stage.sv"
    "${DESIGN_RTL_DIR}/cv32e40p_cs_registers.sv"
    "${DESIGN_RTL_DIR}/cv32e40p_register_file_ff.sv"
    "${DESIGN_RTL_DIR}/cv32e40p_load_store_unit.sv"
    "${DESIGN_RTL_DIR}/cv32e40p_id_stage.sv"
    "${DESIGN_RTL_DIR}/cv32e40p_aligner.sv"
    "${DESIGN_RTL_DIR}/cv32e40p_decoder.sv"
    "${DESIGN_RTL_DIR}/cv32e40p_compressed_decoder.sv"
    "${DESIGN_RTL_DIR}/cv32e40p_fifo.sv"
    "${DESIGN_RTL_DIR}/cv32e40p_prefetch_buffer.sv"
    "${DESIGN_RTL_DIR}/cv32e40p_hwloop_regs.sv"
    "${DESIGN_RTL_DIR}/cv32e40p_mult.sv"
    "${DESIGN_RTL_DIR}/cv32e40p_int_controller.sv"
    "${DESIGN_RTL_DIR}/cv32e40p_ex_stage.sv"
    "${DESIGN_RTL_DIR}/cv32e40p_alu_div.sv"
    "${DESIGN_RTL_DIR}/cv32e40p_alu.sv"
    "${DESIGN_RTL_DIR}/cv32e40p_ff_one.sv"
    "${DESIGN_RTL_DIR}/cv32e40p_popcnt.sv"
    "${DESIGN_RTL_DIR}/cv32e40p_apu_disp.sv"
    "${DESIGN_RTL_DIR}/cv32e40p_controller.sv"
    "${DESIGN_RTL_DIR}/cv32e40p_obi_interface.sv"
    "${DESIGN_RTL_DIR}/cv32e40p_prefetch_controller.sv"
    "${DESIGN_RTL_DIR}/cv32e40p_sleep_unit.sv"
    "${DESIGN_RTL_DIR}/cv32e40p_core.sv"
    "harness/dummy_clock_gate.v"
    "${DESIGN_RTL_DIR}/cv32e40p_top.sv"
)

# Build the include paths for read_slang
INCLUDE_PATHS=(
    "-I${DESIGN_RTL_DIR}/include"
    "-I${DESIGN_RTL_DIR}/../bhv"
    "-I${DESIGN_RTL_DIR}/../bhv/include"
    "-I${DESIGN_RTL_DIR}/../sva"
)

# Run yosys with the slang plugin
# The slang plugin provides read_slang command for SystemVerilog parsing
yosys -m slang -p "
    read_slang \\
        -D SYNTHESIS \\
        -D PULP_FPGA_EMUL \\
        --top cv32e40p_top \\
        ${INCLUDE_PATHS[*]} \\
        ${SV_FILES[*]}

    # Check hierarchy only - no synthesis passes
    hierarchy -check -top cv32e40p_top

    # Write RTLIL output (preserves RTL structure for downstream synthesis)
    write_rtlil ${OUTPUT_DIR}/cv32e40p_yosys_slang.il
"

echo "Conversion complete: ${OUTPUT_DIR}/cv32e40p_yosys_slang.il"
