from amaranth import *
from amaranth.lib import wiring
from amaranth.lib.wiring import In, Out, flipped, connect

from amaranth_soc import csr


__all__ = ["PlatformTimer"]

# Some deep weirness going on, putting docstrings in the normal location
# doesn't work with subclasses of csr.Register. I have no idea why!!!
#
class CNT(csr.Register, access="r"):
    """
    Cycle counter (read-only).
    """
    def __init__(self, width):
        super().__init__({"val": csr.Field(csr.action.R, unsigned(width))})


class CMP(csr.Register, access="rw"):
    """
    Comparator (read/write).

    If set to a non-zero value, an interrupt is triggered when CNT is greater than or equal
    to CMP.
    """
    def __init__(self, width):
        super().__init__({"val": csr.Field(csr.action.RW, unsigned(width))})


class PlatformTimer(wiring.Component):
    """
    Simple timer that counts clock cycles and raises an interrupt when the count hits a configured threshold
    """
    def __init__(self):
        self.width = 48

        regs = csr.Builder(addr_width=4, data_width=8)

        self._cnt = regs.add("cnt", CNT(self.width), offset=0x0)
        self._cmp = regs.add("cmp", CMP(self.width), offset=0x8)

        self._bridge = csr.Bridge(regs.as_memory_map())

        super().__init__({
            "bus": In(csr.Signature(addr_width=regs.addr_width, data_width=regs.data_width)),
            "irq": Out(unsigned(1)),
        })
        self.bus.memory_map = self._bridge.bus.memory_map

    def elaborate(self, platform):
        m = Module()
        m.submodules.bridge = self._bridge

        connect(m, flipped(self.bus), self._bridge.bus)

        m.d.sync += [
            self._cnt.f.val.r_data.eq(self._cnt.f.val.r_data + 1),
            self.irq.eq((self._cmp.f.val.data != 0) &
                        (self._cmp.f.val.data <= self._cnt.f.val.r_data)),
        ]

        return m
