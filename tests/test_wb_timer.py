# amaranth: UnusedElaboratable=no

# SPDX-License-Identifier: BSD-2-Clause

"""Tests for the wb_timer Wishbone timer peripheral.

This module tests the wb_timer SystemVerilog IP wrapped as an Amaranth component
via the VerilogWrapper system. It demonstrates how external Verilog/SystemVerilog
modules can be integrated and tested within the ChipFlow ecosystem.

Configuration and signature tests work without additional dependencies.
Simulation tests require yosys with slang plugin (or yowasp-yosys) and use
CXXRTL for fast compiled simulation of the SystemVerilog code.
"""

import importlib.util
import shutil
import unittest
import warnings
from pathlib import Path

from amaranth import Module
from amaranth.hdl import UnusedElaboratable

from chipflow_digital_ip.io import load_wrapper_from_toml


# Path to the wb_timer TOML configuration
WB_TIMER_TOML = Path(__file__).parent.parent / "chipflow_digital_ip" / "io" / "sv_timer" / "wb_timer.toml"


def _has_yosys_slang() -> bool:
    """Check if yosys with slang plugin is available."""
    # Try yowasp-yosys first (use find_spec to avoid F401 lint warning)
    if importlib.util.find_spec("yowasp_yosys") is not None:
        return True

    # Try native yosys with slang
    if shutil.which("yosys"):
        import subprocess
        try:
            result = subprocess.run(
                ["yosys", "-m", "slang", "-p", "help read_slang"],
                capture_output=True,
                timeout=10
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

    return False


def _has_chipflow_sim() -> bool:
    """Check if chipflow.sim module is available for CXXRTL simulation."""
    return importlib.util.find_spec("chipflow.sim") is not None


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


@unittest.skipUnless(_has_yosys_slang(), "yosys with slang plugin not available")
class WbTimerWrapperTestCase(unittest.TestCase):
    """Test the wb_timer wrapper instantiation (requires yosys-slang)."""

    def setUp(self):
        warnings.simplefilter(action="ignore", category=UnusedElaboratable)
        # Use a local directory instead of /tmp - yowasp-yosys (WASM) can't access /tmp
        self._generate_dest = Path("build/test_wb_timer").absolute()
        self._generate_dest.mkdir(parents=True, exist_ok=True)

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


@unittest.skipUnless(_has_yosys_slang(), "yosys with slang plugin not available")
@unittest.skipUnless(_has_chipflow_sim(), "chipflow.sim not available")
class WbTimerCxxrtlSimulationTestCase(unittest.TestCase):
    """CXXRTL simulation tests for the wb_timer peripheral.

    These tests verify the timer functionality through Wishbone bus transactions
    using CXXRTL compiled simulation. Unlike Amaranth's Python simulator,
    CXXRTL actually executes the SystemVerilog code.

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

    @classmethod
    def setUpClass(cls):
        """Build the CXXRTL simulator once for all tests."""
        warnings.simplefilter(action="ignore", category=UnusedElaboratable)
        cls._build_dir = Path("build/test_wb_timer_cxxrtl").absolute()
        cls._build_dir.mkdir(parents=True, exist_ok=True)

        # Load wrapper and build simulator
        cls._wrapper = load_wrapper_from_toml(WB_TIMER_TOML, generate_dest=cls._build_dir)
        cls._sim = cls._wrapper.build_simulator(cls._build_dir)

    @classmethod
    def tearDownClass(cls):
        """Clean up simulator and build artifacts."""
        if hasattr(cls, "_sim"):
            cls._sim.close()
        shutil.rmtree(cls._build_dir, ignore_errors=True)

    def setUp(self):
        """Reset simulator state before each test."""
        self._reset()

    def _tick(self):
        """Perform a clock cycle."""
        self._sim.set("i_clk", 0)
        self._sim.step()
        self._sim.set("i_clk", 1)
        self._sim.step()

    def _reset(self):
        """Reset the design."""
        self._sim.set("i_rst_n", 0)
        self._sim.set("i_clk", 0)
        self._tick()
        self._tick()
        self._sim.set("i_rst_n", 1)
        self._tick()

    def _wb_write(self, addr: int, data: int):
        """Perform a Wishbone write transaction."""
        self._sim.set("i_wb_cyc", 1)
        self._sim.set("i_wb_stb", 1)
        self._sim.set("i_wb_we", 1)
        self._sim.set("i_wb_adr", addr)
        self._sim.set("i_wb_dat", data)
        self._sim.set("i_wb_sel", 0xF)

        # Clock until ack
        for _ in range(10):
            self._tick()
            if self._sim.get("o_wb_ack"):
                break

        self._sim.set("i_wb_cyc", 0)
        self._sim.set("i_wb_stb", 0)
        self._sim.set("i_wb_we", 0)
        self._tick()

    def _wb_read(self, addr: int) -> int:
        """Perform a Wishbone read transaction."""
        self._sim.set("i_wb_cyc", 1)
        self._sim.set("i_wb_stb", 1)
        self._sim.set("i_wb_we", 0)
        self._sim.set("i_wb_adr", addr)
        self._sim.set("i_wb_sel", 0xF)

        # Clock until ack
        for _ in range(10):
            self._tick()
            if self._sim.get("o_wb_ack"):
                break

        data = self._sim.get("o_wb_dat")

        self._sim.set("i_wb_cyc", 0)
        self._sim.set("i_wb_stb", 0)
        self._tick()

        return data

    def test_reset(self):
        """Test that reset clears state."""
        ctrl = self._wb_read(self.REG_CTRL)
        self.assertEqual(ctrl, 0, "CTRL should be 0 after reset")

    def test_register_write_read(self):
        """Test register write and readback."""
        # Write to COMPARE register
        self._wb_write(self.REG_COMPARE, 0x12345678)

        # Read back
        value = self._wb_read(self.REG_COMPARE)
        self.assertEqual(value, 0x12345678, "COMPARE should retain written value")

    def test_timer_enable_and_count(self):
        """Test that the timer counts when enabled."""
        # Set compare value high so we don't trigger a match
        self._wb_write(self.REG_COMPARE, 0xFFFFFFFF)

        # Enable timer with prescaler=0 (count every cycle)
        self._wb_write(self.REG_CTRL, self.CTRL_ENABLE)

        # Let it count for a few cycles
        for _ in range(20):
            self._tick()

        # Read counter value - should be > 0
        count = self._wb_read(self.REG_COUNTER)
        self.assertGreater(count, 0, "Counter should have incremented")

    def test_timer_match_and_irq(self):
        """Test that compare match sets status and IRQ."""
        # Set compare value to 5
        self._wb_write(self.REG_COMPARE, 5)

        # Enable timer with IRQ enabled
        self._wb_write(self.REG_CTRL, self.CTRL_ENABLE | self.CTRL_IRQ_EN)

        # Wait for match (counter should reach 5)
        irq_fired = False
        for _ in range(50):
            self._tick()
            if self._sim.get("o_irq"):
                irq_fired = True
                break

        # Check IRQ is asserted
        self.assertTrue(irq_fired, "IRQ should fire on compare match")

        # Check status register
        status = self._wb_read(self.REG_STATUS)
        self.assertTrue(status & 0x1, "IRQ pending flag should be set")
        self.assertTrue(status & 0x2, "Match flag should be set")

    def test_timer_prescaler(self):
        """Test that prescaler divides the count rate."""
        # Set compare value high
        self._wb_write(self.REG_COMPARE, 0xFFFFFFFF)

        # Enable timer with prescaler=3 (count every 4 cycles)
        # Prescaler is in upper 16 bits of CTRL
        prescaler = 3 << 16
        self._wb_write(self.REG_CTRL, self.CTRL_ENABLE | prescaler)

        # Run for 20 cycles - should get 20/4 = 5 counts
        for _ in range(20):
            self._tick()

        count = self._wb_read(self.REG_COUNTER)
        # Allow some tolerance for setup cycles
        self.assertGreater(count, 0, "Counter should have incremented")
        self.assertLessEqual(count, 6, "Counter should be limited by prescaler")


if __name__ == "__main__":
    unittest.main()
