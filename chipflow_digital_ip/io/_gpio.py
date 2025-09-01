from typing import Unpack

from amaranth import Module, unsigned
from amaranth.lib import wiring
from amaranth.lib.wiring import In, Out, flipped, connect

from amaranth_soc import csr, gpio

from chipflow_lib.platforms import BidirIOSignature, IOModelOptions

__all__ = ["GPIOPeripheral"]


class GPIOPeripheral(wiring.Component):
    """Wrapper for amaranth_soc gpio with chipflow_lib.IOSignature support

    Parameters
    ----------
    pin_count : :class:`int`
        Number of GPIO pins.
    addr_width : :class:`int`
        CSR bus address width. Defaults to ``4``.
    data_width : :class:`int`
        CSR bus data width. Defaults to ``8``.
    input_stages : :class:`int`
        Number of synchronization stages between pin inputs and the :class:`~Peripheral.Input`
        register. Optional. Defaults to ``2``.

    Attributes
    ----------
    bus : :class:`csr.Interface`
        CSR bus interface providing access to registers.
    pins : :class:`list` of :class:`wiring.PureInterface` of :class:`IOSignature`
        GPIO pin interfaces.
    alt_mode : :class:`Signal`
        Indicates which members of the :attr:`Peripheral.pins` array are in alternate mode.

    Raises
    ------
    :exc:`TypeError`
        If ``pin_count`` is not a positive integer.
    :exc:`TypeError`
        If ``input_stages`` is not a non-negative integer.
    """

    class Signature(wiring.Signature):
        """
        Signature of the gpio port wiring
        """
        def __init__(self, pin_count=1):
            if pin_count > 32:
                raise ValueError(f"Pin pin_count must be lesser than or equal to 32, not {pin_count}")
            self._pin_count = pin_count
            super().__init__({
                "gpio": Out(BidirIOSignature(pin_count, all_have_oe=True))
                })

        @property
        def pin_count(self):
            return self._pin_count

    def __init__(self, *, pin_count=8, addr_width=4, data_width=8, input_stages=2):
        self._gpio = gpio.Peripheral(pin_count=pin_count,
                                     addr_width=addr_width,
                                     data_width=data_width,
                                     input_stages=input_stages)

        super().__init__({
            "bus": In(csr.Signature(addr_width=addr_width, data_width=data_width)),
            "pins": Out(self.Signature(pin_count)),
            "alt_mode": Out(unsigned(pin_count)),
        })
        self.bus.memory_map = self._gpio.bus.memory_map

    def elaborate(self, platform):
        m = Module()
        m.submodules._gpio = gpio = self._gpio

        connect(m, flipped(self.bus), self._gpio.bus)
        for i in range(self._gpio.pin_count):
            m.d.comb += self._gpio.pins[i].i.eq(self.pins.gpio.i[i])
            m.d.comb += self.pins.gpio.o[i].eq(self._gpio.pins[i].o)
            m.d.comb += self.pins.gpio.oe[i].eq(self._gpio.pins[i].oe)

        return m

    @property
    def pin_count(self):
        return self._gpio.pin_count

    @property
    def input_stages(self):
        return self._gpio.input_stages
