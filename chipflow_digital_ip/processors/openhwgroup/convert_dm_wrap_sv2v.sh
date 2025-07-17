#!/usr/bin/env bash
set -ex

DESIGN_RTL_DIR=3rdparty/cv32e40p/rtl
DEBUG_RTL_DIR=3rdparty/riscv-dbg/src
COMMON_CELLS=3rdparty/cv32e40p/rtl/vendor/pulp_platform_common_cells

sv2v -D SYNTHESIS -D PULP_FPGA_EMUL \
	-I ${DESIGN_RTL_DIR}/include \
	-w ./amaranth_cv32e40p/verilog/dm_wrap_conv_sv2v.v \
	--top dm_wrap \
	${DEBUG_RTL_DIR}/dm_pkg.sv \
	${DEBUG_RTL_DIR}/dm_csrs.sv \
	${DEBUG_RTL_DIR}/dmi_cdc.sv \
	${DEBUG_RTL_DIR}/dm_mem.sv \
	${DEBUG_RTL_DIR}/dmi_intf.sv \
	${DEBUG_RTL_DIR}/dm_obi_top.sv \
	${DEBUG_RTL_DIR}/dmi_jtag.sv  \
	${DEBUG_RTL_DIR}/dmi_jtag_tap.sv  \
	${DEBUG_RTL_DIR}/dm_sba.sv \
	${DEBUG_RTL_DIR}/dm_top.sv \
	${DEBUG_RTL_DIR}/../debug_rom/debug_rom.sv \
	${DEBUG_RTL_DIR}/../debug_rom/debug_rom_one_scratch.sv \
	${COMMON_CELLS}/src/deprecated/fifo_v2.sv \
	${COMMON_CELLS}/src/fifo_v3.sv \
	harness/dm_wrap.sv
