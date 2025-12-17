# Makefile for PWM Peripheral Simulation
#
# Usage:
#   make                    # Run cocotb tests with Icarus Verilog
#   make SIM=verilator      # Run cocotb tests with Verilator
#   make sim-sv             # Run pure SystemVerilog testbench with iverilog
#   make sim-sv-verilator   # Run pure SystemVerilog testbench with Verilator
#   make convert            # Convert SV to RTLIL using yosys-slang
#   make clean              # Clean generated files

# Cocotb configuration
TOPLEVEL_LANG = verilog
VERILOG_SOURCES = $(PWD)/pwm_peripheral.sv
TOPLEVEL = pwm_peripheral
MODULE = test_pwm

# Default simulator
SIM ?= icarus

# Verilator-specific options
ifeq ($(SIM),verilator)
    EXTRA_ARGS += --timing
    EXTRA_ARGS += -Wno-fatal
endif

# Include cocotb makefile
include $(shell cocotb-config --makefiles)/Makefile.sim

# Pure SystemVerilog simulation with Icarus Verilog
.PHONY: sim-sv
sim-sv:
	@echo "=== Running SystemVerilog testbench with Icarus Verilog ==="
	iverilog -g2012 -o pwm_sim.vvp pwm_peripheral.sv pwm_tb.sv
	vvp pwm_sim.vvp
	@echo "=== Waveform saved to pwm_tb.vcd ==="

# Pure SystemVerilog simulation with Verilator
.PHONY: sim-sv-verilator
sim-sv-verilator:
	@echo "=== Running SystemVerilog testbench with Verilator ==="
	verilator --binary --timing -j 0 \
		-Wno-fatal \
		--top-module pwm_tb \
		pwm_peripheral.sv pwm_tb.sv
	./obj_dir/Vpwm_tb
	@echo "=== Simulation complete ==="

# Convert to RTLIL using yosys-slang
.PHONY: convert
convert:
	./convert_yosys_slang.sh

# View waveforms (requires GTKWave)
.PHONY: waves
waves: pwm_tb.vcd
	gtkwave pwm_tb.vcd &

# Clean generated files
.PHONY: clean
clean::
	rm -rf obj_dir/
	rm -f pwm_sim.vvp
	rm -f pwm_tb.vcd
	rm -f results.xml
	rm -rf sim_build/
	rm -rf __pycache__/
	rm -rf rtlil/*.il
