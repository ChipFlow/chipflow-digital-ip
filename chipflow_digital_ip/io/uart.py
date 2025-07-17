from amaranth import Module, unsigned, ResetInserter
from amaranth.lib import wiring, data, stream
from amaranth.lib.wiring import In, Out, flipped, connect

from amaranth_soc import csr
from amaranth_stdio.serial import AsyncSerialRX, AsyncSerialTX

from chipflow_lib.platforms import OutputIOSignature, InputIOSignature

from . import rfc_uart

__all__ = ["UARTPeripheral"]

class UARTPhyRx(wiring.Component):
    class Signature(wiring.Signature):
        def __init__(self):
            super().__init__({
                "rst":    Out(1),
                "config":   Out(data.StructLayout({"divisor": unsigned(24)})),
                "symbols":  In(stream.Signature(unsigned(8))),
                "overflow": In(1),
                "error":    In(1),
            })

    def __init__(self, port, init_divisor):
        super().__init__(self.Signature().flip())
        self._port = port
        self._init_divisor = init_divisor

    def elaborate(self, platform):
        m = Module()

        lower = AsyncSerialRX(divisor=self._init_divisor, divisor_bits=24)
        lower = ResetInserter(self.rst)(lower)
        m.submodules.lower = lower

        m.d.sync += self.overflow.eq(0)
        with m.If(lower.rdy):
            with m.If(self.symbols.valid):
                m.d.sync += self.overflow.eq(1)
            with m.Else():
                m.d.sync += [
                    self.symbols.payload.eq(lower.data),
                    self.symbols.valid.eq(1),
                ]

        with m.If(self.symbols.ready):
            m.d.sync += self.symbols.valid.eq(0)

        m.d.comb += [
            lower.i.eq(self._port.i),

            lower.divisor.eq(self.config.divisor),
            lower.ack.eq(1),

            self.error.eq(lower.err.frame),
        ]

        return m


class UARTPhyTx(wiring.Component):
    class Signature(wiring.Signature):
        def __init__(self):
            super().__init__({
                "rst":   Out(1),
                "config":  Out(data.StructLayout({"divisor": unsigned(24)})),
                "symbols": Out(stream.Signature(unsigned(8)))
            })

    def __init__(self, port, init_divisor):
        super().__init__(self.Signature().flip())
        self._port = port
        self._init_divisor = init_divisor

    def elaborate(self, platform):
        m = Module()

        lower = AsyncSerialTX(divisor=self._init_divisor, divisor_bits=24)
        lower = ResetInserter(self.rst)(lower)
        m.submodules.lower = lower

        m.d.comb += [
            self._port.o.eq(lower.o),

            lower.divisor.eq(self.config.divisor),

            lower.data.eq(self.symbols.payload),
            lower.ack.eq(self.symbols.valid),
            self.symbols.ready.eq(lower.rdy),
        ]

        return m


class UARTPhy(wiring.Component):
    class Signature(wiring.Signature):
        def __init__(self):
            super().__init__({
                "rx": Out(UARTPhyRx.Signature()),
                "tx": Out(UARTPhyTx.Signature()),
            })

    def __init__(self, ports, init_divisor):
        super().__init__(self.Signature().flip())
        self._rx = UARTPhyRx(ports.rx, init_divisor)
        self._tx = UARTPhyTx(ports.tx, init_divisor)

    def elaborate(self, platform):
        m = Module()

        m.submodules.rx = self._rx
        m.submodules.tx = self._tx

        connect(m, self._rx, flipped(self.rx))
        connect(m, self._tx, flipped(self.tx))

        return m


class UARTPeripheral(wiring.Component):

    class Signature(wiring.Signature):
        def __init__(self):
            super().__init__({
                "tx": Out(OutputIOSignature(1)),
                "rx": Out(InputIOSignature(1)),
            })


    """Wrapper for amaranth_soc RFC UART with PHY and chipflow_lib.IOSignature support

    Parameters
    ----------
    addr_width : :class:`int`
        CSR bus address width. Defaults to ``5``.
    data_width : :class:`int`
        CSR bus data width. Defaults to ``8``.
    init_divisor : :class:`int`
        Initial divisor value

    Attributes
    ----------
    bus : :class:`csr.Interface`
        CSR bus interface providing access to registers.
    pins : :class:`list` of :class:`wiring.PureInterface` of :class:`IOSignature`
        UART pin interfaces.

    """

    def __init__(self, *, addr_width=5, data_width=8, init_divisor=0):
        phy_config_shape = data.StructLayout({"divisor": unsigned(24)})
        self._uart = rfc_uart.Peripheral(
            addr_width=addr_width,
            data_width=data_width,
            phy_config_shape=phy_config_shape,
            phy_config_init=phy_config_shape.const({"divisor": init_divisor}),
        )

        super().__init__({
            "bus": In(csr.Signature(addr_width=addr_width, data_width=data_width)),
            "pins": Out(self.Signature()),
        })
        self.bus.memory_map = self._uart.bus.memory_map
        self._phy = UARTPhy(ports=self.pins, init_divisor=init_divisor)

    def elaborate(self, platform):
        m = Module()
        m.submodules._uart = uart = self._uart
        m.submodules._phy = phy = self._phy

        connect(m, flipped(self.bus), self._uart.bus)
        connect(m, uart.tx, phy.tx)
        connect(m, uart.rx, phy.rx)

        return m
