# amaranth: UnusedElaboratable=no

"""Amaranth-based tests for PWM Peripheral wrapper.

These tests verify the Amaranth wrapper interface. For full RTL simulation
of the SystemVerilog implementation, use the cocotb tests or SV testbench.
"""

import unittest
import warnings

from amaranth import *
from amaranth.sim import *
from amaranth.hdl import UnusedElaboratable

from pwm import PWMPeripheral, PWMPinSignature, PWMCaptureSignature, PWMGPIOSignature


class SignatureTestCase(unittest.TestCase):
    """Test the pin signatures."""

    def test_pwm_pin_signature(self):
        sig = PWMPinSignature(num_channels=4)
        self.assertEqual(len(sig.members), 2)
        self.assertIn("o", sig.members)
        self.assertIn("oe", sig.members)

    def test_pwm_pin_signature_custom_channels(self):
        sig = PWMPinSignature(num_channels=8)
        # Verify the signature can be created with different channel counts
        self.assertEqual(len(sig.members), 2)

    def test_capture_signature(self):
        sig = PWMCaptureSignature(num_channels=4)
        self.assertEqual(len(sig.members), 1)
        self.assertIn("i", sig.members)

    def test_gpio_signature(self):
        sig = PWMGPIOSignature(width=8)
        self.assertEqual(len(sig.members), 3)
        self.assertIn("i", sig.members)
        self.assertIn("o", sig.members)
        self.assertIn("oe", sig.members)


class PeripheralTestCase(unittest.TestCase):
    """Test the PWM peripheral wrapper."""

    def setUp(self):
        warnings.simplefilter(action="ignore", category=UnusedElaboratable)

    def test_init_default(self):
        """Test default initialization."""
        dut = PWMPeripheral()
        self.assertEqual(dut.num_channels, 4)
        self.assertEqual(dut.counter_width, 16)

    def test_init_custom(self):
        """Test custom initialization."""
        dut = PWMPeripheral(num_channels=8, counter_width=12)
        self.assertEqual(dut.num_channels, 8)
        self.assertEqual(dut.counter_width, 12)

    def test_signature_members(self):
        """Test that all expected signature members exist."""
        dut = PWMPeripheral()

        # Check bus interface
        self.assertTrue(hasattr(dut, 'bus'))
        self.assertEqual(dut.bus.addr_width, 8)
        self.assertEqual(dut.bus.data_width, 32)

        # Check PWM outputs
        self.assertTrue(hasattr(dut, 'pwm'))

        # Check capture inputs
        self.assertTrue(hasattr(dut, 'capture'))

        # Check GPIO
        self.assertTrue(hasattr(dut, 'gpio'))


class IntegrationTestCase(unittest.TestCase):
    """Integration tests showing how to use the peripheral in an SoC.

    Note: These tests use a mock elaboration since the actual SystemVerilog
    cannot be simulated directly by Amaranth's simulator. For full RTL
    simulation, use iverilog/verilator with the cocotb or SV testbenches.
    """

    def setUp(self):
        warnings.simplefilter(action="ignore", category=UnusedElaboratable)

    def test_elaborate_without_platform(self):
        """Test that elaboration works without a platform (for structure check)."""
        dut = PWMPeripheral()
        # Elaborating without platform should work (no file added)
        # This just verifies the Instance is created correctly
        module = dut.elaborate(platform=None)
        self.assertIsInstance(module, Module)


class MockPWMPeripheral(Elaboratable):
    """Mock PWM peripheral for simulation testing.

    This provides a pure-Amaranth implementation of the PWM interface
    for testing SoC integration without needing the SystemVerilog source.
    """

    def __init__(self, *, num_channels=4):
        self.num_channels = num_channels

        # CSR interface
        self.csr_addr = Signal(8)
        self.csr_we = Signal()
        self.csr_wdata = Signal(32)
        self.csr_rdata = Signal(32)

        # Pad ring connections
        self.pwm_o = Signal(num_channels)
        self.pwm_oe = Signal(num_channels)
        self.capture_i = Signal(num_channels)
        self.gpio_i = Signal(8)
        self.gpio_o = Signal(8)
        self.gpio_oe = Signal(8)

        # Internal registers
        self._enable = Signal(num_channels)
        self._gpio_out = Signal(8)
        self._gpio_oe_reg = Signal(8)

    def elaborate(self, platform):
        m = Module()

        # Simple register writes
        with m.If(self.csr_we):
            with m.Switch(self.csr_addr):
                with m.Case(0x00):  # Control
                    m.d.sync += self._enable.eq(self.csr_wdata[:self.num_channels])
                with m.Case(0x40):  # GPIO out
                    m.d.sync += self._gpio_out.eq(self.csr_wdata[:8])
                with m.Case(0x44):  # GPIO OE
                    m.d.sync += self._gpio_oe_reg.eq(self.csr_wdata[:8])

        # Register reads
        with m.Switch(self.csr_addr):
            with m.Case(0x00):
                m.d.comb += self.csr_rdata.eq(self._enable)
            with m.Case(0x40):
                m.d.comb += self.csr_rdata.eq(self._gpio_out)
            with m.Case(0x44):
                m.d.comb += self.csr_rdata.eq(self._gpio_oe_reg)
            with m.Case(0x48):
                m.d.comb += self.csr_rdata.eq(self.gpio_i)

        # Output connections
        m.d.comb += [
            self.pwm_oe.eq(self._enable),
            self.gpio_o.eq(self._gpio_out),
            self.gpio_oe.eq(self._gpio_oe_reg),
        ]

        return m


class MockSimulationTestCase(unittest.TestCase):
    """Test using the mock peripheral for interface verification."""

    def setUp(self):
        warnings.simplefilter(action="ignore", category=UnusedElaboratable)

    async def _csr_write(self, ctx, dut, addr, data):
        ctx.set(dut.csr_addr, addr)
        ctx.set(dut.csr_wdata, data)
        ctx.set(dut.csr_we, 1)
        await ctx.tick()
        ctx.set(dut.csr_we, 0)

    async def _csr_read(self, ctx, dut, addr):
        ctx.set(dut.csr_addr, addr)
        ctx.set(dut.csr_we, 0)
        await ctx.tick()
        return ctx.get(dut.csr_rdata)

    def test_gpio_output(self):
        """Test GPIO output via mock."""
        dut = MockPWMPeripheral()

        async def testbench(ctx):
            # Write GPIO output value
            await self._csr_write(ctx, dut, 0x40, 0xA5)
            await ctx.tick()
            self.assertEqual(ctx.get(dut.gpio_o), 0xA5)

            # Write GPIO output enable
            await self._csr_write(ctx, dut, 0x44, 0xFF)
            await ctx.tick()
            self.assertEqual(ctx.get(dut.gpio_oe), 0xFF)

        sim = Simulator(dut)
        sim.add_clock(1e-6)
        sim.add_testbench(testbench)
        sim.run()

    def test_gpio_input(self):
        """Test GPIO input reading via mock."""
        dut = MockPWMPeripheral()

        async def testbench(ctx):
            # Set input value
            ctx.set(dut.gpio_i, 0x3C)
            await ctx.tick()

            # Read it back
            value = await self._csr_read(ctx, dut, 0x48)
            self.assertEqual(value, 0x3C)

        sim = Simulator(dut)
        sim.add_clock(1e-6)
        sim.add_testbench(testbench)
        sim.run()

    def test_pwm_enable(self):
        """Test PWM channel enable via mock."""
        dut = MockPWMPeripheral()

        async def testbench(ctx):
            # Enable channels 0 and 2
            await self._csr_write(ctx, dut, 0x00, 0x05)
            await ctx.tick()
            self.assertEqual(ctx.get(dut.pwm_oe), 0x05)

        sim = Simulator(dut)
        sim.add_clock(1e-6)
        sim.add_testbench(testbench)
        sim.run()


if __name__ == "__main__":
    unittest.main()
