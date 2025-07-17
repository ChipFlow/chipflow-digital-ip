# Original litehyperbus version:
# Copyright (c) 2019 Antti Lukats <antti.lukats@gmail.com>
# Copyright (c) 2019 Florent Kermarrec <florent@enjoy-digital.fr>
# Improved aramanth-soc port:
# Copyright (c) 2021-2022 gatecat <gatecat@ds0.me>
# SPDX-License-Identifier: BSD-2-Clause

from amaranth import Module, ClockSignal, ResetSignal, Signal, unsigned, ClockDomain, Cat
from amaranth.lib import wiring
from amaranth.lib.wiring import In, Out, connect, flipped
from amaranth.utils import ceil_log2

from amaranth_soc import csr, wishbone
from amaranth_soc.memory import MemoryMap

from chipflow_lib.platforms import BidirIOSignature, OutputIOSignature

__all__ = ["HyperRAM"]


class HyperRAM(wiring.Component):
    """
    HyperRAM.interface

    Provides a very simple/minimal HyperRAM core that should work with all FPGA/HyperRam chips:
    - FPGA vendor agnostic.
    - no setup/chip configuration (use default latency).

    This core favors portability and ease of use over performance.

    Params:
        mem_name: Nane of this memory
        cs_count: Number of Chip Select lines to instantiate
        init_latency: Initial latency in clock cycles for a transaction
    """

    class Signature(wiring.Signature):
        """
        IO signature for Hyperram interdace

        Params:
            clk: Clock output
            csn: Chip Select lines (width `cs_count`)
            rstn: Hardware Reset
            rwds: Read/Write Data Strobe
            dq: Data Input/Output.
        """
        def __init__(self, *, cs_count=1):
            super().__init__({
                "clk": Out(OutputIOSignature(1)),
                "csn": Out(OutputIOSignature(cs_count)),
                "rstn": Out(OutputIOSignature(1)),
                "rwds": Out(BidirIOSignature(1)),
                "dq": Out(BidirIOSignature(8)),
            })

    class CtrlConfig(csr.Register, access="rw"):
        def __init__(self, init_latency):
            super().__init__({
                "latency": csr.Field(csr.action.RW, unsigned(4), init=init_latency),
            })

    class HRAMConfig(csr.Register, access="w"):
        val: csr.Field(csr.action.W, unsigned(32))

    def __init__(self, mem_name=("mem",), *, cs_count=1, init_latency=7):
        self.cs_count = cs_count
        self.size = 2**23 * self.cs_count # 8MB per CS pin
        self.init_latency = init_latency
        assert self.init_latency in (6, 7) # TODO: anything else possible ?

        regs = csr.Builder(addr_width=3, data_width=8)

        self._ctrl_cfg = regs.add("ctrl_cfg", self.CtrlConfig(init_latency), offset=0x0)
        self._hram_cfg = regs.add("hram_cfg", self.HRAMConfig(), offset=0x4)

        self._bridge = csr.Bridge(regs.as_memory_map())
        ctrl_memory_map = self._bridge.bus.memory_map

        data_memory_map = MemoryMap(addr_width=ceil_log2(self.size), data_width=8)
        data_memory_map.add_resource(name=mem_name, size=self.size, resource=self)

        super().__init__({
            "ctrl_bus": In(csr.Signature(addr_width=regs.addr_width, data_width=regs.data_width)),
            "data_bus": In(wishbone.Signature(addr_width=ceil_log2(self.size >> 2), data_width=32,
                           granularity=8)),
            "pins": Out(self.Signature()),
        })
        self.ctrl_bus.memory_map = ctrl_memory_map
        self.data_bus.memory_map = data_memory_map

    def elaborate(self, platform):
        m = Module()
        m.submodules.bridge = self._bridge

        connect(m, flipped(self.ctrl_bus), self._bridge.bus)

        is_ctrl_write = Signal()
        latched_adr = Signal(len(self.data_bus.adr))
        latched_we = Signal()
        latched_cfg = Signal(16)

        counter = Signal(8)
        wait_count = Signal(4)
        clk = Signal()
        csn = Signal(self.cs_count)

        # Data shift register
        sr = Signal(48)

        # Whether or not we need to apply x2 latency
        x2_lat = Signal()

        # Drive out clock on negedge while active
        m.domains += ClockDomain("neg", clk_edge="neg")
        m.d.comb += [
            ClockSignal("neg").eq(ClockSignal()),
            ResetSignal("neg").eq(ResetSignal()),
        ]
        with m.If(csn.all()):
            # Reset clock if nothing active
            m.d.neg += clk.eq(0)
        with m.Elif(counter.any()):
            m.d.neg += clk.eq(~clk)
            m.d.sync += counter.eq(counter-1)
        with m.If(counter.any()):
            # move shift register (sample/output data) on posedge
            m.d.sync += sr.eq(Cat(self.pins.dq.i, sr[:-8]))

        m.d.comb += [
            self.pins.clk.o.eq(clk),
            self.pins.csn.o.eq(csn),
            self.pins.rstn.o.eq(~ResetSignal()),
            self.pins.dq.o.eq(sr[-8:]),
            self.data_bus.dat_r.eq(sr[:32]),
        ]

        with m.FSM():
            with m.State("IDLE"):
                m.d.sync += [
                    counter.eq(0),
                    self.pins.rwds.oe.eq(0),
                    csn.eq((1 << self.cs_count) - 1), # all disabled
                ]
                with m.If(self.data_bus.stb & self.data_bus.cyc): # data bus activity
                    m.d.sync += [
                        csn.eq(~(1 << (self.data_bus.adr[21:]))),
                        self.pins.dq.oe.eq(1),
                        counter.eq(6),
                        # Assign CA
                        sr[47].eq(~self.data_bus.we),           # R/W#
                        sr[46].eq(0),                           # memory space
                        sr[45].eq(1),                           # linear burst
                        sr[16:45].eq(self.data_bus.adr[2:21]),  # upper address
                        sr[4:16].eq(0),                         # RFU
                        sr[1:3].eq(self.data_bus.adr[0:2]),     # lower address
                        sr[0].eq(0),                            # address LSB (0 for 32-bit xfers)
                        latched_adr.eq(self.data_bus.adr),
                        latched_we.eq(self.data_bus.we),
                        is_ctrl_write.eq(0),
                    ]
                    m.next = "WAIT_CA"
                with m.If(self._hram_cfg.f.val.w_stb):  # config register write
                    m.d.sync += [
                        csn.eq(~(1 << (self._hram_cfg.f.val.w_data[16:16+ceil_log2(self.cs_count)]))),
                        self.pins.dq.oe.eq(1),
                        counter.eq(6),
                        # Assign CA
                        sr[47].eq(0),      # R/W#
                        sr[46].eq(1),      # memory space
                        sr[45].eq(1),      # linear burst
                        sr[24:45].eq(1),   # upper address
                        sr[16:24].eq(0),   #
                        sr[4:16].eq(0),    # RFU
                        sr[1:3].eq(0),     # lower address
                        sr[0].eq(0),       # address LSB (0 for 32-bit xfers)
                        latched_cfg.eq(self._hram_cfg.f.val.w_data[0:16]),
                        is_ctrl_write.eq(1),
                    ]
                    m.next = "WAIT_CA"
            with m.State("WAIT_CA"):
                # Waiting to shift out CA
                with m.If(counter == 3):
                    # RWDS tells us if we need 2x latency or not
                    #   sample at an arbitrary midpoint in CA
                    m.d.sync += x2_lat.eq(self.pins.rwds.i)
                with m.If(counter == 1):
                    # (almost) done shifting CA
                    with m.If(is_ctrl_write):
                        # no latency for control register writes
                        m.d.sync += [
                            counter.eq(2),
                            sr[32:].eq(latched_cfg),
                        ]
                        m.next = "SHIFT_DAT_CTRL"
                    with m.Else():
                        # wait for the specified latency period
                        with m.If(x2_lat):
                            m.d.sync += counter.eq(4*self._ctrl_cfg.f.latency.data - 2)
                        with m.Else():
                            m.d.sync += counter.eq(2*self._ctrl_cfg.f.latency.data - 2)
                        m.next = "WAIT_LAT"
            with m.State("WAIT_LAT"):
                m.d.sync += self.pins.dq.oe.eq(0)
                with m.If(counter == 1):
                    # About to shift data
                    m.d.sync += [
                        sr[:16].eq(0),
                        sr[16:].eq(self.data_bus.dat_w),
                        self.pins.dq.oe.eq(self.data_bus.we),
                        self.pins.rwds.oe.eq(self.data_bus.we),
                        self.pins.rwds.o.eq(~self.data_bus.sel[3]),
                        counter.eq(4),
                    ]
                    m.next = "SHIFT_DAT"
            with m.State("SHIFT_DAT"):
                with m.If(counter == 4):
                    m.d.sync += self.pins.rwds.o.eq(~self.data_bus.sel[2])
                with m.If(counter == 3):
                    m.d.sync += self.pins.rwds.o.eq(~self.data_bus.sel[1])
                with m.If(counter == 2):
                    m.d.sync += self.pins.rwds.o.eq(~self.data_bus.sel[0])
                with m.If(counter == 1):
                    m.next = "ACK_XFER"
            with m.State("ACK_XFER"):
                m.d.sync += [
                    self.pins.rwds.oe.eq(0),
                    self.pins.dq.oe.eq(0),
                    self.data_bus.ack.eq(1),
                    wait_count.eq(9)
                ]
                m.next = "WAIT_NEXT"
            with m.State("WAIT_NEXT"):
                m.d.sync += [
                    self.data_bus.ack.eq(0),
                    wait_count.eq(wait_count-1),
                ]
                with m.If(self.data_bus.stb & self.data_bus.cyc & ~self.data_bus.ack):
                    # Is a valid continuation within same page
                    with m.If((self.data_bus.adr[6:] == latched_adr[6:]) & (self.data_bus.adr[:6] == latched_adr[:6] + 1) & (self.data_bus.we == latched_we)):
                        m.d.sync += [
                            sr[:16].eq(0),
                            sr[16:].eq(self.data_bus.dat_w),
                            self.pins.dq.oe.eq(self.data_bus.we),
                            self.pins.rwds.oe.eq(self.data_bus.we),
                            self.pins.rwds.o.eq(~self.data_bus.sel[3]),
                            latched_adr.eq(self.data_bus.adr),
                            counter.eq(4),
                        ]
                        m.next = "SHIFT_DAT"
                    with m.Else():
                        # start a new xfer
                        m.d.sync += csn.eq((1 << self.cs_count) - 1)
                        m.next = "IDLE"
                with m.Elif(wait_count == 0):
                    m.d.sync += csn.eq((1 << self.cs_count) - 1)
                    m.next = "IDLE"
            with m.State("SHIFT_DAT_CTRL"):
                with m.If(counter == 1):
                    m.next = "CTRL_DONE"
            with m.State("CTRL_DONE"):
                m.d.sync += [
                    self.pins.rwds.oe.eq(0),
                    self.pins.dq.oe.eq(0),
                    csn.eq((1 << self.cs_count) - 1),
                ]
                m.next = "IDLE"
        return m
