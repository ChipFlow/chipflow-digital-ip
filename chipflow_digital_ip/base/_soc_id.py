import subprocess

from amaranth import *
from amaranth.lib import wiring
from amaranth.lib.wiring import In, flipped, connect

from amaranth_soc import csr

from chipflow_lib.platforms import DriverSignature

__all__ = ["SoCID"]


class SoCID(wiring.Component):
    class Register(csr.Register, access="r"):
        def __init__(self, width):
            super().__init__({"val": csr.Field(csr.action.R, unsigned(width))})

    """
    SoC identifier peripheral.

    Two read-only CSRs; the first contains a SoC-defined type ID and the second the git hash of the
    repo being used to build the SoC.
    """
    def __init__(self, *, type_id=0xbadca77e):
        self.type_id  = type_id
        self.git_hash = int(subprocess.check_output('git rev-parse --verify HEAD'.split(' ')).strip()[0:8], base=16)

        regs = csr.Builder(addr_width=4, data_width=8)

        self._soc_type    = regs.add("soc_type",    self.Register(32), offset=0x0)
        self._soc_version = regs.add("soc_version", self.Register(32), offset=0x4)

        self._bridge = csr.Bridge(regs.as_memory_map())
        super().__init__(
            DriverSignature(
                members={
                    "bus": In(csr.Signature(addr_width=regs.addr_width, data_width=regs.data_width)),
                },
                component=self,
                regs_struct='soc_id_regs_t',
                h_files=['drivers/soc_id.h'])
            )

        self.bus.memory_map = self._bridge.bus.memory_map

    def elaborate(self, platform):
        m = Module()
        m.submodules.bridge = self._bridge

        connect(m, flipped(self.bus), self._bridge.bus)

        m.d.comb += [
            self._soc_type   .f.val.r_data.eq(self.type_id),
            self._soc_version.f.val.r_data.eq(self.git_hash),
        ]

        return m
