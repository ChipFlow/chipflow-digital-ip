#!/usr/bin/env bash
# Convert Debug Module (dm_wrap) SystemVerilog to Verilog using yosys-slang
# This is an alternative to sv2v using Yosys with the slang plugin
set -ex

VERILOG_PATH="${VERILOG_DIR:=$PWD/verilog_yosys_slang}"
CV32E40P_PATH="${CV32E40P_DIR:=../../../vendor/cv32e40p}"
RISCV_DBG_PATH="${RISCV_DBG_PATH:=../../../vendor/riscv-dbg}"

DESIGN_RTL_DIR=$CV32E40P_PATH/rtl
DEBUG_RTL_DIR=$RISCV_DBG_PATH/src
COMMON_CELLS=$CV32E40P_PATH/rtl/vendor/pulp_platform_common_cells

# Create output directory if it doesn't exist
mkdir -p "$VERILOG_PATH"

# Build the file list for read_slang
# Note: Order matters - packages first, then modules
SV_FILES=(
    "${DEBUG_RTL_DIR}/dm_pkg.sv"
    "${DEBUG_RTL_DIR}/dm_csrs.sv"
    "${DEBUG_RTL_DIR}/dmi_cdc.sv"
    "${DEBUG_RTL_DIR}/dm_mem.sv"
    "${DEBUG_RTL_DIR}/dmi_intf.sv"
    "${DEBUG_RTL_DIR}/dm_obi_top.sv"
    "${DEBUG_RTL_DIR}/dmi_jtag.sv"
    "${DEBUG_RTL_DIR}/dmi_jtag_tap.sv"
    "${DEBUG_RTL_DIR}/dm_sba.sv"
    "${DEBUG_RTL_DIR}/dm_top.sv"
    "${DEBUG_RTL_DIR}/../debug_rom/debug_rom.sv"
    "${DEBUG_RTL_DIR}/../debug_rom/debug_rom_one_scratch.sv"
    "${COMMON_CELLS}/src/deprecated/fifo_v2.sv"
    "${COMMON_CELLS}/src/fifo_v3.sv"
    "harness/dm_wrap.sv"
)

# Build the include paths for read_slang
INCLUDE_PATHS=(
    "-I${DESIGN_RTL_DIR}/include"
)

# Run yosys with the slang plugin
# The slang plugin provides read_slang command for SystemVerilog parsing
yosys -m slang -p "
    read_slang \\
        -D SYNTHESIS \\
        -D PULP_FPGA_EMUL \\
        --top dm_wrap \\
        ${INCLUDE_PATHS[*]} \\
        ${SV_FILES[*]}

    # Flatten and optimize the design
    hierarchy -check -top dm_wrap
    proc
    opt_clean

    # Write the converted Verilog output
    write_verilog -noattr ${VERILOG_PATH}/dm_wrap_conv_yosys_slang.v
"

echo "Conversion complete: ${VERILOG_PATH}/dm_wrap_conv_yosys_slang.v"
