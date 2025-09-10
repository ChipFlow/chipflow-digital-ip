# amaranth: UnusedElaboratable=no

# SPDX-License-Identifier: BSD-2-Clause

import warnings

from amaranth import Module
from amaranth.sim import Simulator, Tick
from amaranth.hdl import UnusedElaboratable

from chipflow_digital_ip.memory import HyperRAM


def test_hyperram_smoke():

    warnings.simplefilter(action="ignore", category=UnusedElaboratable)

    m = Module()
    m.submodules.hram = hram = HyperRAM()
    sim = Simulator(m)
    sim.add_clock(1e-6)

    async def process():
        hram.data_bus.adr.eq(0x5A5A5A)
        hram.data_bus.dat_w.eq(0xF0F0F0F0)
        hram.data_bus.sel.eq(1)
        hram.data_bus.we.eq(1)
        hram.data_bus.stb.eq(1)
        hram.data_bus.cyc.eq(1)
        await sim.tick().sample(hram.data_bus.ack and  hram.data_bus.stb and hram.data_bus.cyc).until(1)

        hram.data_bus.adr.eq(0x5A5A5A)
        hram.data_bus.sel.eq(1)
        hram.data_bus.we.eq(0)
        hram.data_bus.stb.eq(1)
        hram.data_bus.cyc.eq(1)
        hram.pins.rwds.i.eq(1)
        hram.pins.dq.i.eq(0xFF)
        await sim.tick().sample(hram.data_bus.ack and  hram.data_bus.stb and hram.data_bus.cyc).until(1)
    sim.add_testbench(process)
    with sim.write_vcd("hyperram.vcd", "hyperram.gtkw"):
        sim.run()
