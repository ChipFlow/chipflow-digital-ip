# SPDX-License-Identifier: BSD-2-Clause

import unittest

from amaranth import *
from amaranth.lib import enum, data, wiring, stream
from amaranth.lib.wiring import In, Out, connect
from amaranth.sim import *

from chipflow_digital_ip.memory.qspi_flash import WishboneQSPIFlashController, QSPIMode


class _QSPIFlashCommand(enum.Enum, shape=8):
    Read                = 0x03
    FastRead            = 0x0B
    FastReadDualOut     = 0x3B
    FastReadQuadOut     = 0x6B
    FastReadDualInOut   = 0xBB
    FastReadQuadInOut   = 0xEB
    ReadID              = 0x9F


class _MockFlash(wiring.Component):
    def __init__(self):
        super().__init__({"o_octets": In(stream.Signature(data.StructLayout({
                "chip": range(2),
                "mode": QSPIMode,
                "data": 8
            }))),
            "i_octets": Out(stream.Signature(data.StructLayout({
                "data": 8
            }))),
            "divisor": In(16),
        })

        # exposed for testbench
        self.last_command = Signal(_QSPIFlashCommand, init=_QSPIFlashCommand.Read)

    def elaborate(self, platform):
        m = Module()
        command = Signal(_QSPIFlashCommand, init=_QSPIFlashCommand.Read)
        address_count = Signal(2)
        dummy_count = Signal(2)
        address = Signal(24)

        m.d.comb += self.o_octets.ready.eq(1)
        m.d.sync += self.i_octets.valid.eq(0) # default

        dummy_bytes = Signal(2)
        expected_addr_mode = Signal(QSPIMode, init=QSPIMode.Dummy)
        expected_data_mode = Signal(QSPIMode, init=QSPIMode.Dummy)

        with m.Switch(command):
            with m.Case(_QSPIFlashCommand.Read):
                m.d.comb += [
                    dummy_bytes.eq(0),
                    expected_addr_mode.eq(QSPIMode.PutX1),
                    expected_data_mode.eq(QSPIMode.GetX1),
                ]
            with m.Case(_QSPIFlashCommand.FastRead):
                m.d.comb += [
                    dummy_bytes.eq(1),
                    expected_addr_mode.eq(QSPIMode.PutX1),
                    expected_data_mode.eq(QSPIMode.GetX1),
                ]


        with m.FSM():
            with m.State("Idle"):
                with m.If(self.o_octets.valid):
                    with m.If(self.o_octets.p.mode == QSPIMode.Dummy):
                        m.next = "Idle"
                    with m.Else():
                        m.d.sync += [
                            Assert(self.o_octets.p.chip == 1),
                            Assert((self.o_octets.p.mode == QSPIMode.PutX1) | (self.o_octets.p.mode == QSPIMode.Swap)),
                            command.eq(self.o_octets.p.data),
                            address_count.eq(2)
                        ]
                        with m.If(self.o_octets.p.mode == QSPIMode.Swap):
                            # send a dummy response to the swap
                            m.d.sync += self.i_octets.valid.eq(1)
                            m.d.sync += self.i_octets.p.data.eq(0xFF)
                        with m.If(self.o_octets.p.data == _QSPIFlashCommand.ReadID):
                            m.next = "Send-ID"
                        with m.Else():
                            m.next = "Get-Address"
            with m.State("Get-Address"):
                with m.If(self.o_octets.valid):
                    m.d.sync += [
                        Assert(self.o_octets.p.chip == 1),
                        Assert(self.o_octets.p.mode == expected_addr_mode),
                        address.word_select(address_count, 8).eq(self.o_octets.p.data),
                        address_count.eq(address_count - 1)
                    ]
                    with m.If(address_count == 0):
                        with m.If(dummy_bytes == 0):
                            m.next = "Send-Data"
                        with m.Else():
                            m.d.sync += dummy_count.eq(dummy_bytes - 1)
                            m.next = "Get-Dummy"
            with m.State("Get-Dummy"):
                with m.If(self.o_octets.valid):
                    m.d.sync += [
                        Assert(self.o_octets.p.chip == 1),
                        Assert(self.o_octets.p.mode == expected_addr_mode),
                        dummy_count.eq(dummy_count - 1)
                    ]
                    with m.If(dummy_count == 0):
                        m.next = "Send-Data"
            with m.State("Send-Data"):
                with m.If(self.o_octets.valid):
                    with m.If(self.o_octets.p.mode == QSPIMode.Dummy):
                        m.next = "Idle"
                    with m.Else():
                        m.d.sync += [
                            Assert(self.o_octets.p.chip == 1),
                            Assert(self.o_octets.p.mode == expected_data_mode),
                            Assert(self.i_octets.ready == 1), # TODO: allowed to be not ready, too
                            self.i_octets.p.data.eq(0xAA ^ address[0:8]), # TODO: something more useful here
                            self.i_octets.valid.eq(1),
                            address.eq(address + 1)
                        ]
            with m.State("Send-ID"):
                with m.If(self.o_octets.valid):
                    with m.If(self.o_octets.p.mode == QSPIMode.Dummy):
                        m.next = "Idle"
                    with m.Else():
                        m.d.sync += [
                            Assert(self.o_octets.p.chip == 1),
                            Assert(self.o_octets.p.mode == QSPIMode.Swap),
                            self.i_octets.p.data.eq(C(0xEF4018, 24).word_select(address_count, 8)),
                            self.i_octets.valid.eq(1),
                            address_count.eq(address_count - 1)
                        ]
        m.d.comb += self.last_command.eq(command)
        return m

async def _wb_read(self, ctx, dut, addr, r_data):
    ctx.set(dut.wb_bus.adr, addr >> 2)
    ctx.set(dut.wb_bus.we, 0)
    ctx.set(dut.wb_bus.cyc, 1)
    ctx.set(dut.wb_bus.stb, 1)
    await ctx.tick()
    while ctx.get(dut.wb_bus.ack) == 0:
        await ctx.tick()
    ctx.set(dut.wb_bus.cyc, 0)
    ctx.set(dut.wb_bus.stb, 0)
    self.assertEqual(ctx.get(dut.wb_bus.dat_r), r_data)

async def _csr_access(self, ctx, dut, addr, r_stb=0, r_data=0, w_stb=0, w_data=0):

    ctx.set(dut.csr_bus.addr, addr)
    ctx.set(dut.csr_bus.r_stb, r_stb)
    ctx.set(dut.csr_bus.w_stb, w_stb)
    ctx.set(dut.csr_bus.w_data, w_data)

    await ctx.tick()

    if r_stb:
        self.assertEqual(ctx.get(dut.csr_bus.r_data), r_data)

    ctx.set(dut.csr_bus.r_stb, 0)
    ctx.set(dut.csr_bus.w_stb, 0)




class QSPITestCase(unittest.TestCase):
    def test_sim(self):
        dut = WishboneQSPIFlashController(addr_width=24, data_width=32)
        phy = _MockFlash()

        m = Module()
        m.submodules.dut = dut
        m.submodules.phy = phy

        connect(m, dut.spi_bus, phy)

        config_addr       = 0x000
        raw_control_addr  = 0x004
        raw_tx_data_addr  = 0x008
        raw_rx_data_addr  = 0x00c

        async def testbench(ctx):
            await _wb_read(self, ctx, dut, 0x0, 0xa9a8abaa)
            await _wb_read(self, ctx, dut, 0x4, 0xadacafae)

            # check default mode is regular read
            self.assertEqual(ctx.get(phy.last_command), _QSPIFlashCommand.Read)

            # in WB mode: bypass mode not ready
            await _csr_access(self, ctx, dut, raw_control_addr, r_stb=1, r_data=0)
            # enter bypass mode
            await _csr_access(self, ctx, dut, config_addr, w_stb=1, w_data=1)
            for _ in range(10):
                await ctx.tick()
            # in bypass mode: bypass ready
            await _csr_access(self, ctx, dut, raw_control_addr, r_stb=1, r_data=1)
            # read ID command
            await _csr_access(self, ctx, dut, raw_tx_data_addr, w_stb=1, w_data=_QSPIFlashCommand.ReadID)
            for _ in range(4):
                await ctx.tick()
            for byte in reversed(range(3)):
                await _csr_access(self, ctx, dut, raw_tx_data_addr, w_stb=1, w_data=0xFF)
                for _ in range(4):
                    await ctx.tick()
                await _csr_access(self, ctx, dut, raw_rx_data_addr, r_stb=1, r_data=((0xEF4018 >> (8 * byte)) & 0xFF))

            # exit bypass mode
            await _csr_access(self, ctx, dut, config_addr, w_stb=1, w_data=0)
            for _ in range(10):
                await ctx.tick()
            # in WB mode: bypass mode not ready
            await _csr_access(self, ctx, dut, raw_control_addr, r_stb=1, r_data=0)

            # check that WB functions again
            await _wb_read(self, ctx, dut, 0x4, 0xadacafae)

            # switch to fast read mode
            await _csr_access(self, ctx, dut, config_addr, w_stb=1, w_data=(0x01 << 1) | (0x01 << 3)) # X1Fast, 1 dummy byte
            for _ in range(1):
                await ctx.tick()
            # check fast read mode
            await _wb_read(self, ctx, dut, 0x4, 0xadacafae)
            self.assertEqual(ctx.get(phy.last_command), _QSPIFlashCommand.FastRead)

        sim = Simulator(m)
        sim.add_clock(period=1 / 48e6)
        sim.add_testbench(testbench)
        with sim.write_vcd(vcd_file="test_qspi.vcd"):
            sim.run()
