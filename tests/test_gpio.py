# amaranth: UnusedElaboratable=no

# SPDX-License-Identifier: BSD-2-Clause

import unittest
import warnings

from amaranth import *
from amaranth.sim import *
from amaranth.hdl import UnusedElaboratable

from chipflow_digital_ip.io import GPIOPeripheral


class PeripheralTestCase(unittest.TestCase):
    def test_init(self):
        dut_1 = GPIOPeripheral(pin_count=4, addr_width=2, data_width=8)
        self.assertEqual(dut_1.pin_count, 4)
        self.assertEqual(dut_1.input_stages, 2)
        self.assertEqual(dut_1.bus.addr_width, 2)
        self.assertEqual(dut_1.bus.data_width, 8)
        dut_2 = GPIOPeripheral(pin_count=1, addr_width=8, data_width=16, input_stages=3)
        self.assertEqual(dut_2.pin_count, 1)
        self.assertEqual(dut_2.input_stages, 3)
        self.assertEqual(dut_2.bus.addr_width, 8)
        self.assertEqual(dut_2.bus.data_width, 16)

    def test_init_wrong_pin_count(self):
        with self.assertRaisesRegex(TypeError,
                r"Pin count must be a positive integer, not foo"):
            GPIOPeripheral(pin_count="foo", addr_width=2, data_width=8)
        with self.assertRaisesRegex(ValueError,
                r"Pin pin_count must be a positive integer 32 or less, not -1"):
            GPIOPeripheral(pin_count=-1, addr_width=2, data_width=8)
        with self.assertRaisesRegex(ValueError,
                r"Pin pin_count must be a positive integer 32 or less, not 0"):
            GPIOPeripheral(pin_count=0, addr_width=2, data_width=8)
        with self.assertRaisesRegex(ValueError,
                r"Pin pin_count must be a positive integer 32 or less, not 33"):
            GPIOPeripheral(pin_count=33, addr_width=2, data_width=8)

    def test_init_wrong_input_stages(self):
        with self.assertRaisesRegex(TypeError,
                r"Input stages must be a non-negative integer, not 'foo'"):
            GPIOPeripheral(pin_count=1, addr_width=2, data_width=8, input_stages="foo")
        with self.assertRaisesRegex(TypeError,
                r"Input stages must be a non-negative integer, not -1"):
            GPIOPeripheral(pin_count=1, addr_width=2, data_width=8, input_stages=-1)

    async def _csr_access(self, ctx, dut, addr, r_stb=0, w_stb=0, w_data=0, r_data=0):
        ctx.set(dut.bus.addr, addr)
        ctx.set(dut.bus.r_stb, r_stb)
        ctx.set(dut.bus.w_stb, w_stb)
        ctx.set(dut.bus.w_data, w_data)
        await ctx.tick()
        if r_stb:
            self.assertEqual(ctx.get(dut.bus.r_data), r_data)
        ctx.set(dut.bus.r_stb, 0)
        ctx.set(dut.bus.w_stb, 0)

    def test_smoke_test(self):
        """
        Smoke test GPIO. We assume that amaranth-soc GPIO tests are fully testing functionality.
        """

        warnings.simplefilter(action="ignore", category=UnusedElaboratable)

        dut = GPIOPeripheral(pin_count=4, addr_width=2, data_width=8)

        mode_addr   = 0x0
        input_addr  = 0x1
        output_addr = 0x2
        setclr_addr = 0x3

        async def testbench(ctx):
            # INPUT_ONLY mode =====================================================================

            # - read Mode:
            await self._csr_access(ctx, dut, mode_addr, r_stb=1, r_data=0b00000000)
            self.assertEqual(ctx.get(dut.alt_mode), 0b0000)
            self.assertEqual(ctx.get(dut.pins.gpio.oe), 0b0000)
            self.assertEqual(ctx.get(dut.pins.gpio.o), 0b0000)

            # - read Input:
            ctx.set(dut.pins.gpio.i[1], 1)
            ctx.set(dut.pins.gpio.i[3], 1)
            await self._csr_access(ctx, dut, input_addr, r_stb=1, r_data=0x0)
            ctx.set(dut.pins.gpio.i[1], 0)
            ctx.set(dut.pins.gpio.i[3], 0)
            await self._csr_access(ctx, dut, input_addr, r_stb=1, r_data=0x0)
            await self._csr_access(ctx, dut, input_addr, r_stb=1, r_data=0xa)
            await self._csr_access(ctx, dut, input_addr, r_stb=1, r_data=0x0)

            # - write 0xf to Output:
            await self._csr_access(ctx, dut, output_addr, r_stb=1, r_data=0x0, w_stb=1, w_data=0xf)
            await ctx.tick()
            self.assertEqual(ctx.get(dut.pins.gpio.oe), 0b0000)
            self.assertEqual(ctx.get(dut.pins.gpio.o), 0b1111)

            # - write 0x22 to SetClr (clear pins[0] and pins[2]):
            await self._csr_access(ctx, dut, setclr_addr, w_stb=1, w_data=0x22)
            await ctx.tick()
            self.assertEqual(ctx.get(dut.pins.gpio.oe), 0b0000)
            self.assertEqual(ctx.get(dut.pins.gpio.o), 0b1010)

            # - write 0x0 to Output:
            await self._csr_access(ctx, dut, output_addr, r_stb=1, r_data=0xa, w_stb=1, w_data=0x0)
            await ctx.tick()
            self.assertEqual(ctx.get(dut.pins.gpio.oe), 0b0000)
            self.assertEqual(ctx.get(dut.pins.gpio.o), 0b0000)

            # - write 0x44 to SetClr (set pins[1] and pins[3]):
            await self._csr_access(ctx, dut, setclr_addr, w_stb=1, w_data=0x44)
            await ctx.tick()
            self.assertEqual(ctx.get(dut.pins.gpio.oe), 0b0000)
            self.assertEqual(ctx.get(dut.pins.gpio.o), 0b1010)

            # - write 0x0 to Output:
            await self._csr_access(ctx, dut, output_addr, r_stb=1, r_data=0xa, w_stb=1, w_data=0x0)
            await ctx.tick()
            self.assertEqual(ctx.get(dut.pins.gpio.oe), 0b0000)
            self.assertEqual(ctx.get(dut.pins.gpio.o), 0b0000)

            # - write 0xff to SetClr (no-op):
            await self._csr_access(ctx, dut, setclr_addr, w_stb=1, w_data=0xff)
            await ctx.tick()
            self.assertEqual(ctx.get(dut.pins.gpio.oe), 0b0000)
            self.assertEqual(ctx.get(dut.pins.gpio.o), 0b0000)

            # PUSH_PULL mode ======================================================================

            # - write Mode:
            await self._csr_access(ctx, dut, mode_addr, w_stb=1, w_data=0b01010101)
            await ctx.tick()
            self.assertEqual(ctx.get(dut.alt_mode), 0b0000)
            self.assertEqual(ctx.get(dut.pins.gpio.oe), 0b1111)
            self.assertEqual(ctx.get(dut.pins.gpio.o), 0b0000)

            # - read Input:
            ctx.set(dut.pins.gpio.i[1], 1)
            ctx.set(dut.pins.gpio.i[3], 1)
            await self._csr_access(ctx, dut, input_addr, r_stb=1, r_data=0x0)
            ctx.set(dut.pins.gpio.i[1], 0)
            ctx.set(dut.pins.gpio.i[3], 0)
            await self._csr_access(ctx, dut, input_addr, r_stb=1, r_data=0x0)
            await self._csr_access(ctx, dut, input_addr, r_stb=1, r_data=0xa)
            await self._csr_access(ctx, dut, input_addr, r_stb=1, r_data=0x0)

            # - write 0xf to Output:
            await self._csr_access(ctx, dut, output_addr, r_stb=1, r_data=0x0, w_stb=1, w_data=0xf)
            await ctx.tick()
            self.assertEqual(ctx.get(dut.pins.gpio.oe), 0b1111)
            self.assertEqual(ctx.get(dut.pins.gpio.o), 0b1111)

            # - write 0x22 to SetClr (clear pins[0] and pins[2]):
            await self._csr_access(ctx, dut, setclr_addr, w_stb=1, w_data=0x22)
            await ctx.tick()
            self.assertEqual(ctx.get(dut.pins.gpio.oe), 0b1111)
            self.assertEqual(ctx.get(dut.pins.gpio.o), 0b1010)

            # - write 0x0 to Output:
            await self._csr_access(ctx, dut, output_addr, r_stb=1, r_data=0xa, w_stb=1, w_data=0x0)
            await ctx.tick()
            self.assertEqual(ctx.get(dut.pins.gpio.oe), 0b1111)
            self.assertEqual(ctx.get(dut.pins.gpio.o), 0b0000)

            # - write 0x44 to SetClr (set pins[1] and pins[3]):
            await self._csr_access(ctx, dut, setclr_addr, w_stb=1, w_data=0x44)
            await ctx.tick()
            self.assertEqual(ctx.get(dut.pins.gpio.oe), 0b1111)
            self.assertEqual(ctx.get(dut.pins.gpio.o), 0b1010)

        sim = Simulator(dut)
        sim.add_clock(1e-6)
        sim.add_testbench(testbench)
        with sim.write_vcd(vcd_file="test.vcd"):
            sim.run()

    def test_sim_without_input_sync(self):
        dut = GPIOPeripheral(pin_count=4, addr_width=2, data_width=8, input_stages=0)
        input_addr = 0x1

        async def testbench(ctx):
            await self._csr_access(ctx, dut, input_addr, r_stb=1, r_data=0x0)
            ctx.set(dut.pins.gpio.i[1], 1)
            ctx.set(dut.pins.gpio.i[3], 1)
            await self._csr_access(ctx, dut, input_addr, r_stb=1, r_data=0xa)
            ctx.set(dut.pins.gpio.i[1], 0)
            ctx.set(dut.pins.gpio.i[3], 0)
            await self._csr_access(ctx, dut, input_addr, r_stb=1, r_data=0x0)

        sim = Simulator(dut)
        sim.add_clock(1e-6)
        sim.add_testbench(testbench)
        with sim.write_vcd(vcd_file="test.vcd"):
            sim.run()
