from amaranth import *
from amaranth.lib import enum, data, wiring, stream, io
from amaranth.lib.wiring import In, Out, connect, flipped
from amaranth.utils import exact_log2

from amaranth_soc import wishbone, csr
from amaranth_soc.memory import MemoryMap

from ..io._glasgow_iostream import PortGroup
from ..memory._glasgow_qspi import QSPIMode, QSPIController

from chipflow_lib.platforms import BidirIOSignature, OutputIOSignature


class QSPIFlashCommand(enum.Enum, shape=8):
    Read                = 0x03
    FastRead            = 0x0B
    FastReadDualOut     = 0x3B
    FastReadQuadOut     = 0x6B
    FastReadDualInOut   = 0xBB
    FastReadQuadInOut   = 0xEB

class QSPIFlashWidth(enum.Enum, shape=2):
    X1                = 0x00
    X1Fast            = 0x01
    X2                = 0x02
    X4                = 0x03

class _RawTxDataField(csr.FieldAction):
    """A field that is read/write and exposes a strobe"""
    def __init__(self, shape, *, init=0):
        super().__init__(shape, access="rw", members=(
            ("data", Out(shape)),
            ("w_stb", Out(1)),
        ))
        self._storage = Signal(shape, init=init)

    def elaborate(self, platform):
        m = Module()

        with m.If(self.port.w_stb):
            m.d.sync += self._storage.eq(self.port.w_data)

        m.d.comb += [
            self.port.r_data.eq(self._storage),
            self.data.eq(self._storage),
        ]

        # delayed by one cycle to match storage
        m.d.sync += self.w_stb.eq(self.port.w_stb)

        return m

class WishboneQSPIFlashController(wiring.Component):

    class Config(csr.Register, access="rw"):
        raw_enable:   csr.Field(csr.action.RW, 1)
        width:        csr.Field(csr.action.RW, QSPIFlashWidth)
        dummy_bytes:  csr.Field(csr.action.RW, 2)

    class RawControl(csr.Register, access="rw"):
        ready: csr.Field(csr.action.R, 1)
        deselect: csr.Field(csr.action.W, 1)

    class RawTxData(csr.Register, access="rw"):
        data: csr.Field(_RawTxDataField, 8)

    class RawRxData(csr.Register, access="rw"):
        data: csr.Field(csr.action.R, 8)


    def __init__(self, *, addr_width, data_width):
        super().__init__({
            "csr_bus": In(csr.Signature(addr_width=4, data_width=8)),
            "wb_bus": In(wishbone.Signature(addr_width=addr_width, data_width=data_width, granularity=8)),
            "spi_bus": Out(wiring.Signature({
                "o_octets": Out(stream.Signature(data.StructLayout({
                    "chip": 1,
                    "mode": QSPIMode,
                    "data": 8,
                }))),
                "i_octets": In(stream.Signature(data.StructLayout({
                    "data": 8,
                }))),
                "divisor": Out(16),
            })),
        })

        self.wb_bus.memory_map = MemoryMap(addr_width=addr_width + exact_log2(data_width // 8),
                                           data_width=8)
        self.wb_bus.memory_map.add_resource(self, name="data", size=0x400000) # FIXME

        regs = csr.Builder(addr_width=4, data_width=8)

        self._config      = regs.add("Config",     self.Config(),     offset=0x000)
        self._raw_control = regs.add("RawControl", self.RawControl(), offset=0x004)
        self._raw_tx_data = regs.add("RawTxData",  self.RawTxData(),  offset=0x008)
        self._raw_rx_data = regs.add("RawRxData",  self.RawRxData(),  offset=0x00c)

        self._csr_bridge = csr.Bridge(regs.as_memory_map())
        self.csr_bus.memory_map = self._csr_bridge.bus.memory_map


    def elaborate(self, platform):
        m = Module()

        m.submodules.csr_bridge = self._csr_bridge

        connect(m, flipped(self.csr_bus), self._csr_bridge.bus)

        wb_data_octets = self.wb_bus.data_width // 8


        o_addr_count = Signal(range(3))
        o_dummy_count = Signal(range(4))
        o_data_count = Signal(range(wb_data_octets + 1))
        i_data_count = Signal(range(wb_data_octets + 1))

        flash_addr = self.wb_bus.adr << exact_log2(wb_data_octets)

        raw_tx_data = Signal(8)
        raw_rx_data = Signal(8)

        o_command = Signal(QSPIFlashCommand, init=QSPIFlashCommand.Read)
        o_mode = Signal(QSPIMode, init=QSPIMode.PutX1)
        i_mode = Signal(QSPIMode, init=QSPIMode.GetX1)

        with m.Switch(self._config.f.width.data):
            with m.Case(QSPIFlashWidth.X1):
                m.d.comb += o_command.eq(QSPIFlashCommand.Read)
                m.d.comb += o_mode.eq(QSPIMode.PutX1)
                m.d.comb += i_mode.eq(QSPIMode.GetX1)
            with m.Case(QSPIFlashWidth.X1Fast):
                m.d.comb += o_command.eq(QSPIFlashCommand.FastRead)
                m.d.comb += o_mode.eq(QSPIMode.PutX1)
                m.d.comb += i_mode.eq(QSPIMode.GetX1)
            with m.Case(QSPIFlashWidth.X2):
                m.d.comb += o_command.eq(QSPIFlashCommand.FastReadDualInOut)
                m.d.comb += o_mode.eq(QSPIMode.PutX2)
                m.d.comb += i_mode.eq(QSPIMode.GetX2)
            with m.Case(QSPIFlashWidth.X4):
                m.d.comb += o_command.eq(QSPIFlashCommand.FastReadQuadInOut)
                m.d.comb += o_mode.eq(QSPIMode.PutX4)
                m.d.comb += i_mode.eq(QSPIMode.GetX4)

        with m.FSM() as fsm:
            # WB Memory-mapped mode
            with m.State("Wait"):
                m.d.comb += self.spi_bus.o_octets.p.chip.eq(1)
                m.d.comb += self.spi_bus.o_octets.p.mode.eq(QSPIMode.PutX1)
                m.d.comb += self.spi_bus.o_octets.p.data.eq(o_command)
                with m.If(self._config.f.raw_enable.data):
                    m.next = "Raw-Wait"
                with m.Elif(self.wb_bus.cyc & self.wb_bus.stb & ~self.wb_bus.we):
                    m.d.comb += self.spi_bus.o_octets.valid.eq(1)
                    with m.If(self.spi_bus.o_octets.ready):
                        m.d.sync += o_addr_count.eq(2)
                        m.next = "SPI-Address"

            with m.State("SPI-Address"):
                m.d.comb += self.spi_bus.o_octets.p.chip.eq(1)
                m.d.comb += self.spi_bus.o_octets.p.mode.eq(o_mode)
                m.d.comb += self.spi_bus.o_octets.p.data.eq(flash_addr.word_select(o_addr_count, 8))
                m.d.comb += self.spi_bus.o_octets.valid.eq(1)
                with m.If(self.spi_bus.o_octets.ready):
                    with m.If(o_addr_count != 0):
                        m.d.sync += o_addr_count.eq(o_addr_count - 1)
                    with m.Elif(self._config.f.dummy_bytes.data != 0):
                        m.d.sync += o_dummy_count.eq(self._config.f.dummy_bytes.data - 1)
                        m.next = "SPI-Dummy-Bytes"
                    with m.Else():
                        m.next = "SPI-Data-Read"

            with m.State("SPI-Dummy-Bytes"):
                m.d.comb += self.spi_bus.o_octets.p.chip.eq(1)
                m.d.comb += self.spi_bus.o_octets.p.mode.eq(o_mode)
                m.d.comb += self.spi_bus.o_octets.p.data.eq(0xFF)
                m.d.comb += self.spi_bus.o_octets.valid.eq(1)
                with m.If(self.spi_bus.o_octets.ready):
                    with m.If(o_dummy_count != 0):
                        m.d.sync += o_dummy_count.eq(o_dummy_count - 1)
                    with m.Else():
                        m.next = "SPI-Data-Read"


            with m.State("SPI-Data-Read"):
                m.d.comb += self.spi_bus.o_octets.p.chip.eq(1)
                m.d.comb += self.spi_bus.o_octets.p.mode.eq(i_mode)
                with m.If(o_data_count != wb_data_octets):
                    m.d.comb += self.spi_bus.o_octets.valid.eq(1)
                    with m.If(self.spi_bus.o_octets.ready):
                        m.d.sync += o_data_count.eq(o_data_count + 1)

                m.d.comb += self.spi_bus.i_octets.ready.eq(1)
                with m.If(self.spi_bus.i_octets.valid):
                    m.d.sync += self.wb_bus.dat_r.word_select(i_data_count, 8).eq(self.spi_bus.i_octets.p.data)
                    with m.If(i_data_count != wb_data_octets - 1):
                        m.d.sync += i_data_count.eq(i_data_count + 1)
                    with m.Else():
                        m.d.sync += self.wb_bus.ack.eq(1)
                        m.d.sync += o_data_count.eq(0)
                        m.d.sync += i_data_count.eq(0)
                        m.next = "SPI-Deselect"

            with m.State("SPI-Deselect"):
                m.d.sync += self.wb_bus.ack.eq(0)
                m.d.comb += self.spi_bus.o_octets.p.chip.eq(0)
                m.d.comb += self.spi_bus.o_octets.p.mode.eq(QSPIMode.Dummy)
                m.d.comb += self.spi_bus.o_octets.valid.eq(1)
                with m.If(self.spi_bus.o_octets.ready):
                    m.next = "Wait"

            # Raw IO mode
            with m.State("Raw-Wait"):
                with m.If(~self._config.f.raw_enable.data):
                    # Back to Wishbone mode, but make sure to deselect chip first
                    m.next = "SPI-Deselect"
                with m.Elif(self._raw_control.f.deselect.w_stb & self._raw_control.f.deselect.w_data):
                    m.next = "Raw-Deselect"
                with m.Elif(self._raw_tx_data.f.data.w_stb):
                    m.d.sync += raw_tx_data.eq(self._raw_tx_data.f.data.data)
                    m.next = "Raw-Data-Write"

            with m.State("Raw-Data-Write"):
                m.d.comb += self.spi_bus.o_octets.p.chip.eq(1)
                m.d.comb += self.spi_bus.o_octets.p.mode.eq(QSPIMode.Swap)
                m.d.comb += self.spi_bus.o_octets.p.data.eq(raw_tx_data)
                m.d.comb += self.spi_bus.o_octets.valid.eq(1)
                with m.If(self.spi_bus.o_octets.ready):
                    m.next = "Raw-Data-Read"

            with m.State("Raw-Data-Read"):
                m.d.comb += self.spi_bus.i_octets.ready.eq(1)
                with m.If(self.spi_bus.i_octets.valid):
                    m.d.sync += raw_rx_data.eq(self.spi_bus.i_octets.p.data)
                    m.next = "Raw-Wait"

            with m.State("Raw-Deselect"):
                m.d.sync += self.wb_bus.ack.eq(0)
                m.d.comb += self.spi_bus.o_octets.p.chip.eq(0)
                m.d.comb += self.spi_bus.o_octets.p.mode.eq(QSPIMode.Dummy)
                m.d.comb += self.spi_bus.o_octets.valid.eq(1)
                with m.If(self.spi_bus.o_octets.ready):
                    m.next = "Raw-Wait"

            m.d.comb += self._raw_rx_data.f.data.r_data.eq(raw_rx_data)
            m.d.comb += self._raw_control.f.ready.r_data.eq(fsm.ongoing("Raw-Wait"))
        return m

class QSPIFlash(wiring.Component):
    class Signature(wiring.Signature):
        def __init__(self):
            super().__init__({
                "clk": Out(OutputIOSignature(1)),
                "csn": Out(OutputIOSignature(1)),
                "d": Out(BidirIOSignature(4, all_have_oe=True)),
            })

    def __init__(self, *, addr_width, data_width):
        super().__init__({
            "pins": Out(self.Signature()),
            "csr_bus": In(csr.Signature(addr_width=4, data_width=8)),
            "wb_bus": In(wishbone.Signature(addr_width=addr_width, data_width=data_width, granularity=8)),
        })

        self._ctrl = WishboneQSPIFlashController(addr_width=addr_width, data_width=data_width)
        self.csr_bus.memory_map = self._ctrl.csr_bus.memory_map
        self.wb_bus.memory_map = self._ctrl.wb_bus.memory_map

        self.qspi_ports = PortGroup() # amaranth style ports, not chipflow
        self.qspi_ports.sck = io.SimulationPort("o",  1, name="qspi_sck")
        self.qspi_ports.io  = io.SimulationPort("io", 4, name="qspi_io")
        self.qspi_ports.cs  = io.SimulationPort("o",  1, name="qspi_cs")

        self._phy = QSPIController(ports=self.qspi_ports)

    def elaborate(self, platform):
        m = Module()

        m.submodules.ctrl = self._ctrl
        m.submodules.phy = self._phy

        connect(m, self._ctrl.csr_bus, flipped(self.csr_bus))
        connect(m, self._ctrl.wb_bus, flipped(self.wb_bus))
        connect(m, self._ctrl.spi_bus, self._phy)

        m.d.comb += [
            self.pins.clk.o.eq(self.qspi_ports.sck.o),
            self.pins.csn.o.eq(~self.qspi_ports.cs.o),
            self.pins.d.o.eq(self.qspi_ports.io.o),
            self.pins.d.oe.eq(self.qspi_ports.io.oe),
            self.qspi_ports.io.i.eq(self.pins.d.i),
        ]

        return m

