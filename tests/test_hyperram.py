# amaranth: UnusedElaboratable=no

# SPDX-License-Identifier: BSD-2-Clause

from amaranth import Module
from amaranth.sim import Simulator
from chipflow_digital_ip.memory import HyperRAM


def test_hyperram_smoke():
    m = Module()
    m.submodules.hram = hram = HyperRAM()
    sim = Simulator(m)
    sim.add_clock(1e-6)

    def process():
        yield hram.data_bus.adr.eq(0x5A5A5A)
        yield hram.data_bus.dat_w.eq(0xF0F0F0F0)
        yield hram.data_bus.sel.eq(1)
        yield hram.data_bus.we.eq(1)
        yield hram.data_bus.stb.eq(1)
        yield hram.data_bus.cyc.eq(1)
        for i in range(100):
            if (yield hram.data_bus.ack):
                yield hram.data_bus.stb.eq(0)
                yield hram.data_bus.cyc.eq(0)
            yield
        yield hram.data_bus.adr.eq(0x5A5A5A)
        yield hram.data_bus.sel.eq(1)
        yield hram.data_bus.we.eq(0)
        yield hram.data_bus.stb.eq(1)
        yield hram.data_bus.cyc.eq(1)
        yield hram.pins.rwds.i.eq(1)
        yield hram.pins.dq.i.eq(0xFF)
        for i in range(100):
            if (yield hram.data_bus.ack):
                yield hram.data_bus.stb.eq(0)
                yield hram.data_bus.cyc.eq(0)
            yield

    sim.add_sync_process(process)
    with sim.write_vcd("hyperram.vcd", "hyperram.gtkw"):
        sim.run()
