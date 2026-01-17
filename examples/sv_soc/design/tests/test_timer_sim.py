#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-2-Clause
"""CXXRTL simulation test for the SystemVerilog timer.

This test demonstrates using VerilogWrapper.build_simulator() to create
a CXXRTL simulator and test the timer peripheral.
"""

import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from chipflow_digital_ip.io import load_wrapper_from_toml


def main():
    """Run timer simulation test."""
    # Paths
    rtl_dir = Path(__file__).parent.parent / "rtl"
    build_dir = Path(__file__).parent.parent.parent / "build" / "timer_sim"

    print("SystemVerilog Timer CXXRTL Simulation Test")
    print("=" * 50)

    # Load the timer wrapper from TOML
    print(f"\n1. Loading timer from: {rtl_dir / 'wb_timer.toml'}")
    wrapper = load_wrapper_from_toml(
        rtl_dir / "wb_timer.toml",
        generate_dest=build_dir / "gen"
    )

    print(f"   Module: {wrapper.get_top_module()}")
    print(f"   Source files: {[f.name for f in wrapper.get_source_files()]}")

    # Build the CXXRTL simulator
    print(f"\n2. Building CXXRTL simulator in: {build_dir}")
    sim = wrapper.build_simulator(build_dir)
    print("   Simulator ready!")

    # Helper functions
    def reset():
        """Apply reset."""
        sim.set("i_rst_n", 0)
        for _ in range(5):
            sim.set("i_clk", 0)
            sim.step()
            sim.set("i_clk", 1)
            sim.step()
        sim.set("i_rst_n", 1)

    def tick():
        """One clock cycle."""
        sim.set("i_clk", 0)
        sim.step()
        sim.set("i_clk", 1)
        sim.step()

    def wb_write(addr, data):
        """Wishbone write transaction."""
        sim.set("i_wb_cyc", 1)
        sim.set("i_wb_stb", 1)
        sim.set("i_wb_we", 1)
        sim.set("i_wb_sel", 0xF)
        sim.set("i_wb_adr", addr)
        sim.set("i_wb_dat", data)
        tick()
        while not sim.get("o_wb_ack"):
            tick()
        sim.set("i_wb_cyc", 0)
        sim.set("i_wb_stb", 0)
        tick()

    def wb_read(addr):
        """Wishbone read transaction."""
        sim.set("i_wb_cyc", 1)
        sim.set("i_wb_stb", 1)
        sim.set("i_wb_we", 0)
        sim.set("i_wb_sel", 0xF)
        sim.set("i_wb_adr", addr)
        tick()
        while not sim.get("o_wb_ack"):
            tick()
        data = sim.get("o_wb_dat")
        sim.set("i_wb_cyc", 0)
        sim.set("i_wb_stb", 0)
        tick()
        return data

    # Register addresses
    ADDR_CTRL = 0
    ADDR_COMPARE = 1
    ADDR_COUNTER = 2
    ADDR_STATUS = 3

    # Test 1: Reset and read initial values
    print("\n3. Test: Reset and read initial values")
    reset()

    ctrl = wb_read(ADDR_CTRL)
    counter = wb_read(ADDR_COUNTER)
    status = wb_read(ADDR_STATUS)

    print(f"   CTRL:    0x{ctrl:08X} (expected: 0x00000000)")
    print(f"   COUNTER: 0x{counter:08X} (expected: 0x00000000)")
    print(f"   STATUS:  0x{status:08X} (expected: 0x00000000)")

    assert ctrl == 0, f"CTRL should be 0 after reset, got {ctrl}"
    assert counter == 0, f"COUNTER should be 0 after reset, got {counter}"
    assert status == 0, f"STATUS should be 0 after reset, got {status}"
    print("   PASS!")

    # Test 2: Configure and start timer
    print("\n4. Test: Configure timer (compare=10, prescaler=0, enable)")
    wb_write(ADDR_COMPARE, 10)  # Compare value
    wb_write(ADDR_COUNTER, 0)   # Reload value
    wb_write(ADDR_CTRL, 0x00000001)  # Enable, no prescaler

    # Verify configuration
    compare = wb_read(ADDR_COMPARE)
    ctrl = wb_read(ADDR_CTRL)
    print(f"   COMPARE: {compare} (expected: 10)")
    print(f"   CTRL:    0x{ctrl:08X} (expected: 0x00000001)")

    assert compare == 10
    assert ctrl == 1
    print("   PASS!")

    # Test 3: Let counter run and check it increments
    print("\n5. Test: Counter increments")
    for _ in range(5):
        tick()

    counter = wb_read(ADDR_COUNTER)
    print(f"   COUNTER after 5 ticks: {counter}")
    assert counter > 0, "Counter should have incremented"
    print("   PASS!")

    # Test 4: Wait for match and check IRQ
    print("\n6. Test: Wait for compare match")

    # Enable IRQ and restart
    wb_write(ADDR_CTRL, 0)  # Disable
    wb_write(ADDR_COUNTER, 0)  # Reset reload
    wb_write(ADDR_STATUS, 0x3)  # Clear any pending flags
    wb_write(ADDR_CTRL, 0x00000003)  # Enable + IRQ enable

    # Run until match
    for i in range(20):
        tick()
        status = wb_read(ADDR_STATUS)
        if status & 0x2:  # Match flag
            print(f"   Match occurred at tick {i}")
            break

    irq = sim.get("o_irq")
    print(f"   STATUS: 0x{status:08X}")
    print(f"   o_irq:  {irq}")

    assert status & 0x2, "Match flag should be set"
    assert irq == 1, "IRQ should be asserted"
    print("   PASS!")

    # Test 5: Clear IRQ
    print("\n7. Test: Clear IRQ by writing to STATUS")
    wb_write(ADDR_STATUS, 0x3)  # Write 1 to clear

    status = wb_read(ADDR_STATUS)
    irq = sim.get("o_irq")

    print(f"   STATUS: 0x{status:08X} (expected: 0x00000000)")
    print(f"   o_irq:  {irq} (expected: 0)")

    assert status == 0, "Status should be cleared"
    assert irq == 0, "IRQ should be deasserted"
    print("   PASS!")

    print("\n" + "=" * 50)
    print("All tests passed!")
    print("=" * 50)


if __name__ == "__main__":
    main()
