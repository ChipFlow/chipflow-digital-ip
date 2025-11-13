# amaranth: UnusedElaboratable=no

# SPDX-License-Identifier: BSD-2-Clause

import warnings

from amaranth import Module
from amaranth.sim import Simulator
from amaranth.hdl import UnusedElaboratable

from chipflow_digital_ip.memory import HyperRAM


def test_hyperram_smoke():
    warnings.simplefilter(action="ignore", category=UnusedElaboratable)

    m = Module()
    m.submodules.hram = hram = HyperRAM()
    sim = Simulator(m)
    sim.add_clock(1e-6)

    async def process(ctx):
        ctx.set(hram.data_bus.adr, 0x5A5A5A)
        ctx.set(hram.data_bus.dat_w, 0xF0F0F0F0)
        ctx.set(hram.data_bus.sel, 1)
        ctx.set(hram.data_bus.we, 1)
        ctx.set(hram.data_bus.stb, 1)
        ctx.set(hram.data_bus.cyc, 1)
        for i in range(100):
            if ctx.get(hram.data_bus.ack):
                ctx.set(hram.data_bus.stb, 0)
                ctx.set(hram.data_bus.cyc, 0)
            await ctx.tick()
        ctx.set(hram.data_bus.adr, 0x5A5A5A)
        ctx.set(hram.data_bus.sel, 1)
        ctx.set(hram.data_bus.we, 0)
        ctx.set(hram.data_bus.stb, 1)
        ctx.set(hram.data_bus.cyc, 1)
        ctx.set(hram.pins.rwds.i, 1)
        ctx.set(hram.pins.dq.i, 0xFF)
        for i in range(100):
            if ctx.get(hram.data_bus.ack):
                ctx.set(hram.data_bus.stb, 0)
                ctx.set(hram.data_bus.cyc, 0)
            await ctx.tick()
    sim.add_testbench(process)
    with sim.write_vcd("hyperram.vcd", "hyperram.gtkw"):
        sim.run()
