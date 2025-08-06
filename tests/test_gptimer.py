# amaranth: UnusedElaboratable=no
# SPDX-License-Identifier: BSD-2-Clause

from amaranth import *
from amaranth.sim import Simulator
from chipflow_digital_ip.base import GPTimer
import unittest

class _GPTimerHarness(Elaboratable):
    def __init__(self):
        self.timer = GPTimer()
    def elaborate(self, platform):
        m = Module()
        m.submodules.timer = self.timer
        return m

class TestGPTimer(unittest.TestCase):
    # CSR register offsets:
    REG_CTRL    = 0x00
    REG_PRESC   = 0x04
    REG_COUNT   = 0x08
    REG_COMPARE = 0x0C
    REG_STATUS  = 0x10

    async def _write_reg(self, ctx, bus, addr, value, width=1):
        for i in range(width):
            ctx.set(bus.addr, addr + i)
            ctx.set(bus.w_data, (value >> (8 * i)) & 0xFF)
            ctx.set(bus.w_stb, 1)
            await ctx.tick()
        ctx.set(bus.w_stb, 0)
        await ctx.tick()

    async def _read_reg(self, ctx, bus, addr, width=1):
        result = 0
        for i in range(width):
            ctx.set(bus.addr, addr + i)
            ctx.set(bus.r_stb, 1)
            await ctx.tick()
            result |= ctx.get(bus.r_data) << (8 * i)
        ctx.set(bus.r_stb, 0)
        await ctx.tick()
        return result

    def test_prescaler_and_count(self):
        """Counter should increment once per (PRESC+1) cycles."""
        dut = _GPTimerHarness()

        async def testbench(ctx):
            bus = dut.timer.bus

            # prescaler = 2 → increment every 3 cycles, enable timer
            await self._write_reg(ctx, bus, self.REG_PRESC, 2, 1)
            await self._write_reg(ctx, bus, self.REG_CTRL, 1 << 0, 1)

            # run 10 cycles → floor(10/3) = 3
            for _ in range(10):
                await ctx.tick()

            cnt = await self._read_reg(ctx, bus, self.REG_COUNT, width=4)
            self.assertEqual(cnt, 3)

        sim = Simulator(dut)
        sim.add_clock(1e-6)
        sim.add_testbench(testbench)
        with sim.write_vcd("gptimer_presc_test.vcd", "gptimer_presc_test.gtkw"):
            sim.run()

    def test_match_and_irq_and_auto_reload(self):
        """COMPARE match should set STATUS.MATCH, assert IRQ, then auto-reload."""
        dut = _GPTimerHarness()

        async def testbench(ctx):
            bus = dut.timer.bus

            # fastest tick, compare = 5, enable + auto-reload + irq enable
            await self._write_reg(ctx, bus, self.REG_PRESC,   0,    1)
            await self._write_reg(ctx, bus, self.REG_COMPARE, 5,    4)
            ctrl_bits = (1 << 0) | (1 << 2) | (1 << 3)
            await self._write_reg(ctx, bus, self.REG_CTRL, ctrl_bits, 1)

            # step up to compare
            for _ in range(5):
                await ctx.tick()
            # on next tick, match → STATUS.MATCH=1 and irq=1
            await ctx.tick()
            status = await self._read_reg(ctx, bus, self.REG_STATUS, 1)
            self.assertEqual(status & 0x1, 1)
            self.assertEqual(ctx.get(dut.timer.irq), 1)

            # next tick, counter should reload to 0 then increment → 1
            await ctx.tick()
            cnt = await self._read_reg(ctx, bus, self.REG_COUNT, 4)
            self.assertEqual(cnt, 1)

            # clear the match bit
            await self._write_reg(ctx, bus, self.REG_STATUS, 1, 1)
            status2 = await self._read_reg(ctx, bus, self.REG_STATUS, 1)
            self.assertEqual(status2 & 0x1, 0)

        sim = Simulator(dut)
        sim.add_clock(1e-6)
        sim.add_testbench(testbench)
        with sim.write_vcd("gptimer_match_test.vcd", "gptimer_match_test.gtkw"):
            sim.run()

if __name__ == "__main__":
    unittest.main()
