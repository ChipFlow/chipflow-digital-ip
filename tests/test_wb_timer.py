# amaranth: UnusedElaboratable=no

# SPDX-License-Identifier: BSD-2-Clause

"""Tests for the wb_timer Wishbone timer peripheral.

This module tests the wb_timer SystemVerilog IP wrapped as an Amaranth component
via the VerilogWrapper system. It demonstrates how external Verilog/SystemVerilog
modules can be integrated and tested within the ChipFlow ecosystem.

Note: Full simulation requires sv2v to be installed for SystemVerilog conversion.
The configuration and signature tests work without sv2v.
"""

import shutil
import tempfile
import unittest
import warnings
from pathlib import Path

from amaranth import Elaboratable, Module, Signal
from amaranth.hdl import UnusedElaboratable
from amaranth.sim import Simulator

from chipflow_digital_ip.io import load_wrapper_from_toml


# Path to the wb_timer TOML configuration
WB_TIMER_TOML = Path(__file__).parent.parent / "chipflow_digital_ip" / "io" / "sv_timer" / "wb_timer.toml"


class WbTimerConfigTestCase(unittest.TestCase):
    """Test the wb_timer TOML configuration loading."""

    def setUp(self):
        warnings.simplefilter(action="ignore", category=UnusedElaboratable)

    def test_toml_exists(self):
        """Verify the wb_timer TOML configuration file exists."""
        self.assertTrue(WB_TIMER_TOML.exists(), f"TOML not found at {WB_TIMER_TOML}")

    def test_load_wrapper_config(self):
        """Test that the wb_timer wrapper can be loaded (config parsing only)."""
        # This test verifies TOML parsing works
        # It will fail at Verilog file loading if sv2v is not installed
        # but the config parsing should succeed
        import tomli
        from chipflow_digital_ip.io._verilog_wrapper import ExternalWrapConfig

        with open(WB_TIMER_TOML, "rb") as f:
            raw_config = tomli.load(f)

        config = ExternalWrapConfig.model_validate(raw_config)

        self.assertEqual(config.name, "wb_timer")
        self.assertIn("bus", config.ports)
        self.assertIn("irq", config.pins)
        self.assertEqual(config.ports["bus"].interface, "amaranth_soc.wishbone.Signature")
        self.assertEqual(config.pins["irq"].interface, "amaranth.lib.wiring.Out(1)")

    def test_driver_config(self):
        """Test that driver configuration is present."""
        import tomli
        from chipflow_digital_ip.io._verilog_wrapper import ExternalWrapConfig

        with open(WB_TIMER_TOML, "rb") as f:
            raw_config = tomli.load(f)

        config = ExternalWrapConfig.model_validate(raw_config)

        self.assertIsNotNone(config.driver)
        self.assertEqual(config.driver.regs_struct, "wb_timer_regs_t")
        self.assertIn("drivers/wb_timer.h", config.driver.h_files)


@unittest.skipUnless(shutil.which("sv2v"), "sv2v not installed")
class WbTimerWrapperTestCase(unittest.TestCase):
    """Test the wb_timer wrapper instantiation (requires sv2v)."""

    def setUp(self):
        warnings.simplefilter(action="ignore", category=UnusedElaboratable)
        self._generate_dest = tempfile.mkdtemp(prefix="wb_timer_test_")

    def tearDown(self):
        import shutil as sh
        sh.rmtree(self._generate_dest, ignore_errors=True)

    def test_load_wrapper(self):
        """Test loading the complete wb_timer wrapper."""
        wrapper = load_wrapper_from_toml(WB_TIMER_TOML, generate_dest=Path(self._generate_dest))

        self.assertEqual(wrapper._config.name, "wb_timer")
        # Check signature has the expected members
        self.assertIn("bus", wrapper.signature.members)
        self.assertIn("irq", wrapper.signature.members)

    def test_wrapper_elaborate(self):
        """Test that the wrapper can be elaborated."""
        wrapper = load_wrapper_from_toml(WB_TIMER_TOML, generate_dest=Path(self._generate_dest))

        # Elaborate with no platform (simulation mode)
        m = wrapper.elaborate(platform=None)
        self.assertIsInstance(m, Module)


class _WbTimerHarness(Elaboratable):
    """Test harness for wb_timer simulation.

    This harness wraps the wb_timer and provides clock/reset.
    """

    def __init__(self, toml_path: Path, generate_dest: Path):
        self.timer = load_wrapper_from_toml(toml_path, generate_dest=generate_dest)
        # Expose the IRQ signal for testing
        self.irq = Signal()

    def elaborate(self, platform):
        m = Module()
        m.submodules.timer = self.timer

        # Connect IRQ output
        m.d.comb += self.irq.eq(self.timer.irq)

        return m


@unittest.skipUnless(shutil.which("sv2v"), "sv2v not installed")
class WbTimerSimulationTestCase(unittest.TestCase):
    """Simulation tests for the wb_timer peripheral.

    These tests verify the timer functionality through Wishbone bus transactions.
    Register map (32-bit registers, word-addressed):
        0x0: CTRL    - [31:16] prescaler, [1] irq_en, [0] enable
        0x1: COMPARE - Compare value for timer match
        0x2: COUNTER - Current counter (read) / Reload value (write)
        0x3: STATUS  - [1] match, [0] irq_pending
    """

    # Register addresses (word-addressed for 32-bit Wishbone)
    REG_CTRL = 0x0
    REG_COMPARE = 0x1
    REG_COUNTER = 0x2
    REG_STATUS = 0x3

    # Control register bits
    CTRL_ENABLE = 1 << 0
    CTRL_IRQ_EN = 1 << 1

    def setUp(self):
        warnings.simplefilter(action="ignore", category=UnusedElaboratable)
        self._generate_dest = tempfile.mkdtemp(prefix="wb_timer_sim_")

    def tearDown(self):
        import shutil as sh
        sh.rmtree(self._generate_dest, ignore_errors=True)

    async def _wb_write(self, ctx, bus, addr, data):
        """Perform a Wishbone write transaction."""
        ctx.set(bus.cyc, 1)
        ctx.set(bus.stb, 1)
        ctx.set(bus.we, 1)
        ctx.set(bus.adr, addr)
        ctx.set(bus.dat_w, data)
        ctx.set(bus.sel, 0xF)  # All byte lanes

        # Wait for acknowledge
        await ctx.tick()
        while not ctx.get(bus.ack):
            await ctx.tick()

        ctx.set(bus.cyc, 0)
        ctx.set(bus.stb, 0)
        ctx.set(bus.we, 0)
        await ctx.tick()

    async def _wb_read(self, ctx, bus, addr):
        """Perform a Wishbone read transaction."""
        ctx.set(bus.cyc, 1)
        ctx.set(bus.stb, 1)
        ctx.set(bus.we, 0)
        ctx.set(bus.adr, addr)
        ctx.set(bus.sel, 0xF)

        # Wait for acknowledge
        await ctx.tick()
        while not ctx.get(bus.ack):
            await ctx.tick()

        data = ctx.get(bus.dat_r)

        ctx.set(bus.cyc, 0)
        ctx.set(bus.stb, 0)
        await ctx.tick()

        return data

    def test_timer_enable_and_count(self):
        """Test that the timer counts when enabled."""
        dut = _WbTimerHarness(WB_TIMER_TOML, Path(self._generate_dest))

        async def testbench(ctx):
            bus = dut.timer.bus

            # Set compare value high so we don't trigger a match
            await self._wb_write(ctx, bus, self.REG_COMPARE, 0xFFFFFFFF)

            # Enable timer with prescaler=0 (count every cycle)
            await self._wb_write(ctx, bus, self.REG_CTRL, self.CTRL_ENABLE)

            # Let it count for a few cycles
            for _ in range(10):
                await ctx.tick()

            # Read counter value - should be > 0
            count = await self._wb_read(ctx, bus, self.REG_COUNTER)
            self.assertGreater(count, 0, "Counter should have incremented")

        sim = Simulator(dut)
        sim.add_clock(1e-6)
        sim.add_testbench(testbench)
        with sim.write_vcd("wb_timer_count_test.vcd", "wb_timer_count_test.gtkw"):
            sim.run()

    def test_timer_match_and_irq(self):
        """Test that compare match sets status and IRQ."""
        dut = _WbTimerHarness(WB_TIMER_TOML, Path(self._generate_dest))

        async def testbench(ctx):
            bus = dut.timer.bus

            # Set compare value to 5
            await self._wb_write(ctx, bus, self.REG_COMPARE, 5)

            # Enable timer with IRQ enabled
            await self._wb_write(ctx, bus, self.REG_CTRL, self.CTRL_ENABLE | self.CTRL_IRQ_EN)

            # Wait for match (counter should reach 5)
            for _ in range(20):
                await ctx.tick()
                if ctx.get(dut.irq):
                    break

            # Check IRQ is asserted
            self.assertEqual(ctx.get(dut.irq), 1, "IRQ should be asserted on match")

            # Check status register
            status = await self._wb_read(ctx, bus, self.REG_STATUS)
            self.assertTrue(status & 0x1, "IRQ pending flag should be set")
            self.assertTrue(status & 0x2, "Match flag should be set")

            # Clear status by writing 1s to pending bits
            await self._wb_write(ctx, bus, self.REG_STATUS, 0x3)

            # IRQ should clear
            await ctx.tick()
            status = await self._wb_read(ctx, bus, self.REG_STATUS)
            self.assertEqual(status & 0x1, 0, "IRQ pending should be cleared")

        sim = Simulator(dut)
        sim.add_clock(1e-6)
        sim.add_testbench(testbench)
        with sim.write_vcd("wb_timer_irq_test.vcd", "wb_timer_irq_test.gtkw"):
            sim.run()

    def test_timer_prescaler(self):
        """Test that prescaler divides the count rate."""
        dut = _WbTimerHarness(WB_TIMER_TOML, Path(self._generate_dest))

        async def testbench(ctx):
            bus = dut.timer.bus

            # Set compare value high
            await self._wb_write(ctx, bus, self.REG_COMPARE, 0xFFFFFFFF)

            # Enable timer with prescaler=3 (count every 4 cycles)
            # Prescaler is in upper 16 bits of CTRL
            prescaler = 3 << 16
            await self._wb_write(ctx, bus, self.REG_CTRL, self.CTRL_ENABLE | prescaler)

            # Run for 20 cycles - should get 20/4 = 5 counts
            for _ in range(20):
                await ctx.tick()

            count = await self._wb_read(ctx, bus, self.REG_COUNTER)
            # Allow some tolerance for setup cycles
            self.assertGreater(count, 0, "Counter should have incremented")
            self.assertLessEqual(count, 6, "Counter should be limited by prescaler")

        sim = Simulator(dut)
        sim.add_clock(1e-6)
        sim.add_testbench(testbench)
        with sim.write_vcd("wb_timer_presc_test.vcd", "wb_timer_presc_test.gtkw"):
            sim.run()


if __name__ == "__main__":
    unittest.main()
