#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-2-Clause
"""Example: Simulating a SystemVerilog timer with CXXRTL.

This script demonstrates the complete workflow for simulating a SystemVerilog
IP module using the ChipFlow VerilogWrapper and CXXRTL compiled simulation.

The wb_timer is a simple 32-bit programmable timer with:
- Wishbone B4 bus interface
- Configurable prescaler
- Compare match with interrupt generation
- Status register with clear-on-write

Usage:
    python simulate_timer.py
"""

from pathlib import Path

from chipflow_digital_ip.io import load_wrapper_from_toml


# Register addresses (word-addressed)
REG_CTRL = 0x0
REG_COMPARE = 0x1
REG_COUNTER = 0x2
REG_STATUS = 0x3

# Control register bits
CTRL_ENABLE = 1 << 0
CTRL_IRQ_EN = 1 << 1


class WbTimerSimulation:
    """Helper class for simulating the wb_timer peripheral."""

    def __init__(self, sim):
        self.sim = sim

    def tick(self):
        """Perform one clock cycle."""
        self.sim.set("i_clk", 0)
        self.sim.step()
        self.sim.set("i_clk", 1)
        self.sim.step()

    def reset(self):
        """Reset the design."""
        self.sim.set("i_rst_n", 0)
        self.sim.set("i_clk", 0)
        self.tick()
        self.tick()
        self.sim.set("i_rst_n", 1)
        self.tick()

    def wb_write(self, addr: int, data: int):
        """Perform a Wishbone write transaction."""
        self.sim.set("i_wb_cyc", 1)
        self.sim.set("i_wb_stb", 1)
        self.sim.set("i_wb_we", 1)
        self.sim.set("i_wb_adr", addr)
        self.sim.set("i_wb_dat", data)
        self.sim.set("i_wb_sel", 0xF)

        # Clock until ack
        for _ in range(10):
            self.tick()
            if self.sim.get("o_wb_ack"):
                break

        self.sim.set("i_wb_cyc", 0)
        self.sim.set("i_wb_stb", 0)
        self.sim.set("i_wb_we", 0)
        self.tick()

    def wb_read(self, addr: int) -> int:
        """Perform a Wishbone read transaction."""
        self.sim.set("i_wb_cyc", 1)
        self.sim.set("i_wb_stb", 1)
        self.sim.set("i_wb_we", 0)
        self.sim.set("i_wb_adr", addr)
        self.sim.set("i_wb_sel", 0xF)

        # Clock until ack
        for _ in range(10):
            self.tick()
            if self.sim.get("o_wb_ack"):
                break

        data = self.sim.get("o_wb_dat")

        self.sim.set("i_wb_cyc", 0)
        self.sim.set("i_wb_stb", 0)
        self.tick()

        return data


def main():
    print("=" * 60)
    print("SystemVerilog Timer CXXRTL Simulation Example")
    print("=" * 60)

    # Path to the wb_timer TOML configuration
    # In a real project, this would be your own IP's TOML file
    toml_path = (
        Path(__file__).parent.parent.parent
        / "chipflow_digital_ip"
        / "io"
        / "sv_timer"
        / "wb_timer.toml"
    )

    build_dir = Path("build/example_sim")
    build_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n1. Loading wrapper from: {toml_path}")
    wrapper = load_wrapper_from_toml(toml_path, generate_dest=build_dir)
    print(f"   Module name: {wrapper.get_top_module()}")
    print(f"   Source files: {[f.name for f in wrapper.get_source_files()]}")

    print("\n2. Building CXXRTL simulator...")
    sim = wrapper.build_simulator(build_dir)
    print("   Simulator built successfully!")

    # List discovered signals
    print("\n3. Discovered signals:")
    for name, obj in list(sim.signals())[:10]:  # First 10
        print(f"   - {name} (width={obj.width})")
    print("   ...")

    # Create helper
    timer = WbTimerSimulation(sim)

    print("\n4. Resetting design...")
    timer.reset()

    # Verify reset state
    ctrl = timer.wb_read(REG_CTRL)
    print(f"   CTRL after reset: 0x{ctrl:08X} (expected 0x00000000)")

    print("\n5. Testing register write/read...")
    timer.wb_write(REG_COMPARE, 0xDEADBEEF)
    compare = timer.wb_read(REG_COMPARE)
    print(f"   Wrote 0xDEADBEEF to COMPARE, read back: 0x{compare:08X}")
    assert compare == 0xDEADBEEF, "Register readback failed!"

    print("\n6. Testing timer counting...")
    timer.wb_write(REG_COMPARE, 0xFFFFFFFF)  # High compare value
    timer.wb_write(REG_CTRL, CTRL_ENABLE)  # Enable timer

    # Let it count for some cycles
    for _ in range(20):
        timer.tick()

    counter = timer.wb_read(REG_COUNTER)
    print(f"   Counter value after 20 cycles: {counter}")
    assert counter > 0, "Counter should have incremented!"

    print("\n7. Testing IRQ generation...")
    timer.reset()
    timer.wb_write(REG_COMPARE, 5)  # Trigger at count 5
    timer.wb_write(REG_CTRL, CTRL_ENABLE | CTRL_IRQ_EN)

    # Wait for IRQ
    irq_fired = False
    cycles = 0
    for _ in range(50):
        timer.tick()
        cycles += 1
        if sim.get("o_irq"):
            irq_fired = True
            break

    print(f"   IRQ fired after {cycles} cycles: {irq_fired}")
    assert irq_fired, "IRQ should have fired!"

    # Check status
    status = timer.wb_read(REG_STATUS)
    print(f"   STATUS register: 0x{status:08X}")
    print(f"   - IRQ pending: {bool(status & 0x1)}")
    print(f"   - Match flag: {bool(status & 0x2)}")

    # Clean up
    sim.close()

    print("\n" + "=" * 60)
    print("Simulation completed successfully!")
    print("=" * 60)


if __name__ == "__main__":
    main()
