# amaranth: UnusedElaboratable=no

# SPDX-License-Identifier: BSD-2-Clause

from amaranth import *
from amaranth.sim import Simulator

from chipflow_digital_ip.io import SPIPeripheral
import unittest


class TestSpiPeripheral(unittest.TestCase):
    REG_CONFIG = 0x00
    REG_DIV = 0x04
    REG_SEND_DATA = 0x08
    REG_RECEIVE_DATA = 0x0C
    REG_STATUS = 0x10

    async def _write_reg(self, ctx, dut, reg, value, width=4):
        for i in range(width):
            ctx.set(dut.bus.addr, reg + i)
            ctx.set(dut.bus.w_data, (value >> (8 * i)) & 0xFF)
            ctx.set(dut.bus.w_stb, 1)
            await ctx.tick()
        ctx.set(dut.bus.w_stb, 0)

    async def _check_reg(self, ctx, dut, reg, value, width=4):
        result = 0
        for i in range(width):
            ctx.set(dut.bus.addr, reg + i)
            ctx.set(dut.bus.r_stb, 1)
            await ctx.tick()
            result |= ctx.get(dut.bus.r_data) << (8 * i)
        ctx.set(dut.bus.r_stb, 0)
        self.assertEqual(result, value)

    def test_chip_select(self):
        dut = SPIPeripheral()

        async def testbench(ctx):
            await self._write_reg(ctx, dut, self.REG_CONFIG, 1 << 2, 1)
            await ctx.tick()
            self.assertEqual(ctx.get(dut.spi_pins.csn.o), 0)
            await self._write_reg(ctx, dut, self.REG_CONFIG, 0 << 2, 1)
            await ctx.tick()
            self.assertEqual(ctx.get(dut.spi_pins.csn.o), 1)

        sim = Simulator(dut)
        sim.add_clock(1e-5)
        sim.add_testbench(testbench)
        with sim.write_vcd("spi_cs_test.vcd", "spi_cs_test.gtkw"):
            sim.run()

    def test_xfer(self):
        dut = SPIPeripheral()
        tests = [(13, 0x1C3, 0x333), (8, 0x66, 0x5A), (32, 0xDEADBEEF, 0xC0FFEE11)]

        async def testbench(ctx):
            for sck_idle, sck_edge in ((0, 0), (0, 1), (1, 0), (1, 1)):
                for width, d_send, d_recv in tests:
                    await self._write_reg(
                        ctx,
                        dut,
                        self.REG_CONFIG,
                        ((width - 1) << 3) | (sck_edge << 1) | (sck_idle),
                        4,
                    )
                    await self._write_reg(ctx, dut, self.REG_DIV, 1, 1)
                    await ctx.tick()
                    await self._check_reg(ctx, dut, self.REG_STATUS, 0, 1)  # not full
                    await self._write_reg(
                        ctx, dut, self.REG_SEND_DATA, (d_send << (32 - width)), 4
                    )
                    await ctx.tick()
                    for i in reversed(range(width)):
                        if sck_edge:
                            ctx.set(dut.spi_pins.cipo.i, (d_recv >> i) & 0x1)
                        else:
                            self.assertEqual(
                                ctx.get(dut.spi_pins.copi.o), (d_send >> i) & 0x1
                            )
                        self.assertEqual(ctx.get(dut.spi_pins.sck.o), 0 ^ sck_idle)
                        await ctx.tick()
                        self.assertEqual(ctx.get(dut.spi_pins.sck.o), 0 ^ sck_idle)
                        if sck_edge:
                            self.assertEqual(
                                ctx.get(dut.spi_pins.copi.o), (d_send >> i) & 0x1
                            )
                        else:
                            ctx.set(dut.spi_pins.cipo.i, (d_recv >> i) & 0x1)
                        await ctx.tick()
                        self.assertEqual(ctx.get(dut.spi_pins.sck.o), 1 ^ sck_idle)
                        await ctx.tick()
                        self.assertEqual(ctx.get(dut.spi_pins.sck.o), 1 ^ sck_idle)
                        await ctx.tick()
                    await ctx.tick()
                    await ctx.tick()
                    await self._check_reg(ctx, dut, self.REG_STATUS, 1, 1)  # full
                    await self._check_reg(
                        ctx, dut, self.REG_RECEIVE_DATA, d_recv, 4
                    )  # received correct data
                    await self._check_reg(ctx, dut, self.REG_STATUS, 0, 1)  # not full

        sim = Simulator(dut)
        sim.add_clock(1e-5)
        sim.add_testbench(testbench)
        with sim.write_vcd("spi_xfer_test.vcd", "spi_xfer_test.gtkw"):
            sim.run()

    def test_divider(self):
        dut = SPIPeripheral()

        async def testbench(ctx):
            width = 8
            d_send = 0x73
            divide = 13

            await self._write_reg(ctx, dut, self.REG_CONFIG, ((width - 1) << 3), 4)
            await self._write_reg(ctx, dut, self.REG_DIV, divide, 1)
            await ctx.tick()
            await self._check_reg(ctx, dut, self.REG_STATUS, 0, 1)  # not full
            await self._write_reg(
                ctx, dut, self.REG_SEND_DATA, (d_send << (32 - width)), 4
            )
            await ctx.tick()
            for i in reversed(range(width)):
                self.assertEqual(ctx.get(dut.spi_pins.copi.o), (d_send >> i) & 0x1)
                self.assertEqual(ctx.get(dut.spi_pins.sck.o), 0)
                for j in range(divide + 1):
                    await ctx.tick()
                self.assertEqual(ctx.get(dut.spi_pins.sck.o), 1)
                for j in range(divide + 1):
                    await ctx.tick()
            await ctx.tick()
            await ctx.tick()
            await self._check_reg(ctx, dut, self.REG_STATUS, 1, 1)  # full

        sim = Simulator(dut)
        sim.add_clock(1e-5)
        sim.add_testbench(testbench)
        with sim.write_vcd("spi_div_test.vcd", "spi_div_test.gtkw"):
            sim.run()
