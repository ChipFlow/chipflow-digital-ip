from amaranth import Module, Signal, unsigned
from amaranth.lib import wiring
from amaranth.lib.wiring import Component, In, Out , connect, flipped

from amaranth_soc import csr

"""
General-Purpose Timer:
 - 32-bit up-counter
 - 8-bit prescaler
 - compare match + auto-reload
 - level-high IRQ on match
"""


__all__ = ["GPTimer"]

class GPTimer(Component):
    class Ctrl(csr.Register, access="rw"):
        '''CTRL: [0]=EN, [1]=RST, [2]=AR, [3]=IRQ_EN
            EN = Enables the counter
            RST = Resets the counter
            AR = Enable auto reload
            IRQ_EN = Enable interrupt on match
        '''
        en: csr.Field(csr.action.RW, unsigned(1))
        rst: csr.Field(csr.action.RW, unsigned(1))
        ar: csr.Field(csr.action.RW, unsigned(1))
        irq_en: csr.Field(csr.action.RW, unsigned(1))
        # bits [4:8) reserved

    class Presc(csr.Register, access="rw"):
        """Prescaler divisor (0 => /1, 255 => /256)"""
        val: csr.Field(csr.action.RW, unsigned(8))

    class Compare(csr.Register, access="rw"):
        """32-bit compare value"""
        val: csr.Field(csr.action.RW, unsigned(32))

    class Count(csr.Register, access="r"):
        """32-bit free-running counter (read-only)"""
        val: csr.Field(csr.action.R, unsigned(32))

    class Status(csr.Register, access="rw"):
        """STATUS: [0]=MATCH (W1C)"""
        match: csr.Field(csr.action.RW1C, unsigned(1))
        # bits [1:8) reserved

    def __init__(self):
        # CSR bank: 5-bit address, 8-bit data bus
        regs = csr.Builder(addr_width=5, data_width=8)
        self._ctrl    = regs.add("ctrl",    self.Ctrl(),    offset=0x00)
        self._presc   = regs.add("presc",   self.Presc(),   offset=0x04)
        self._count   = regs.add("count",   self.Count(),   offset=0x08)
        self._compare = regs.add("compare", self.Compare(), offset=0x0C)
        self._status  = regs.add("status",  self.Status(),  offset=0x10)

        self._bridge = csr.Bridge(regs.as_memory_map())

        super().__init__({
            "bus": In (csr.Signature(addr_width=regs.addr_width, data_width=regs.data_width)),
            "irq": Out(1),
        })
        self.bus.memory_map = self._bridge.bus.memory_map


    def elaborate(self, platform):
        m = Module()
        m.submodules.bridge = self._bridge
        connect(m, flipped(self.bus), self._bridge.bus)

        # shorthands to the field-ports
        ctrl   = self._ctrl.f
        presc  = self._presc.f
        cmp_   = self._compare.f
        cnt    = self._count.f
        status = self._status.f

         # Internal timer signals:
        p_cnt  = Signal(8,  name="prescaler_cnt")
        cnt_r  = Signal(32, name="counter")
        mflag  = Signal(1,  name="match_pulse")
 
        # prescaler & counter logic
        with m.If(ctrl.rst.data):
            m.d.sync += [p_cnt.eq(0), cnt_r.eq(0), mflag.eq(0)]
        with m.Elif(ctrl.en.data):
            with m.If(p_cnt == presc.val.data):  
                m.d.sync += [p_cnt.eq(0), cnt_r.eq(cnt_r + 1)]
            with m.Else():
                m.d.sync += p_cnt.eq(p_cnt + 1)

        #default no pulse match
        m.d.sync += mflag.eq(0)

        # compare & auto-reload, set match-flag
        with m.If((cnt_r == cmp_.val.data) & ctrl.en.data):
            m.d.sync += mflag.eq(1)
            with m.If(ctrl.ar.data):
                m.d.sync += cnt_r.eq(0)

        m.d.comb += status.match.set.eq(mflag)                        # drive the RW1C “set” port from that pulse
        m.d.comb += cnt.val.r_data.eq(cnt_r)                          # mirror into COUNT CSR
        m.d.comb += self.irq.eq(status.match.data & ctrl.irq_en.data) # irq follows the *CSR storage

        return m




                