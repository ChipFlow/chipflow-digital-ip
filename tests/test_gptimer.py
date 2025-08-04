# first version of simple test bench for general purpose timer


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
    # Offsets must match your CSR mapping order:
    REG_CTRL = 0x00
    REG_PRESC = 0x04
    REG_COUNT = 0x08
    REG_COMPARE = 0x0C
    REG_STATUS = 0x10

    async def _write_reg(self, ctx, bus, addr, value, width=1):
        # width = number of bytes
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
        """Counter should increment only once per (PRESC+1) clocks."""
        dut = _GPTimerHarness()

        async def tb(ctx):
            bus = dut.timer.bus

            # 1) Enable timer with prescaler=2 (so counter increments every 3 cycles)
            await self._write_reg(ctx, bus, self.REG_PRESC, 2, width=1)
            # EN=1
            await self._write_reg(ctx, bus, self.REG_CTRL, 1 << 0, width=1)

            # 2) Run 10 cycles; expect COUNT = floor(10/3) = 3
            for _ in range(10):
                await ctx.tick()
            cnt = await self._read_reg(ctx, bus, self.REG_COUNT, width=4)
            self.assertEqual(cnt, 3)

        sim = Simulator(dut)
        sim.add_clock(1e-6)
        sim.add_sync_process(tb)
        sim.run()

    def test_match_and_irq_and_auto_reload(self):
        """COMPARE match sets STATUS.MATCH, asserts irq, and auto-reloads."""
        dut = _GPTimerHarness()

        async def tb(ctx):
            bus = dut.timer.bus

            # Set prescaler=0 (fastest)
            await self._write_reg(ctx, bus, self.REG_PRESC, 0, width=1)
            # Set compare = 5
            await self._write_reg(ctx, bus, self.REG_COMPARE, 5, width=4)
            # Enable timer + auto-reload + IRQ enable (EN=bit0, AR=bit2, IRQ_EN=bit3)
            ctrl_bits = (1 << 0) | (1 << 2) | (1 << 3)
            await self._write_reg(ctx, bus, self.REG_CTRL, ctrl_bits, width=1)

            # Step until just before match
            for _ in range(5):
                await ctx.tick()
            # On the 6th tick, COUNT==5 => match occurs
            # After that tick, STATUS.MATCH should be 1 and irq=1
            await ctx.tick()
            status = await self._read_reg(ctx, bus, self.REG_STATUS, width=1)
            self.assertEqual(status & 0x1, 1)
            self.assertEqual(ctx.get(dut.timer.irq), 1)

            # Because auto-reload=1, on next tick counter resets to 0
            await ctx.tick()
            cnt = await self._read_reg(ctx, bus, self.REG_COUNT, width=4)
            self.assertEqual(cnt, 1)  # it incremented once after reload

            # Clear the match flag by writing 1
            await self._write_reg(ctx, bus, self.REG_STATUS, 1, width=1)
            status2 = await self._read_reg(ctx, bus, self.REG_STATUS, width=1)
            self.assertEqual(status2 & 0x1, 0)

        sim = Simulator(dut)
        sim.add_clock(1e-6)
        sim.add_sync_process(tb)
        sim.run()


if __name__ == "__main__":
    unittest.main()
