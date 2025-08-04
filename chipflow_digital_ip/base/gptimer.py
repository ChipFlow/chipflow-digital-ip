from amaranth import Module, Signal, unsigned
from amaranth.lib.wiring import Component, In, Out , connect, flipped

from amaranth_soc import csr


__all__ = ["GPTimer"]

class GPTimer(Component):
    """
    General-Purpose Timer:
      - 32-bit up-counter
      - 8-bit prescaler
      - compare match + auto-reload
      - level-high IRQ on match
    """
    class Ctrl(csr.Register, access="rw"):
        """CTRL: [0]=EN, [1]=RST, [2]=AR, [3]=IRQ_EN"""
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

        # CSR bridge
        self._bridge = csr.Bridge(regs.as_memory_map())

        # Declare our external ports:
        super().__init__({
            "bus": In (csr.Signature(addr_width=regs.addr_width,
                                     data_width=regs.data_width)),
            "irq": Out(1),
        })

        # Hook up the bridge to our bus port:
        self.bus.memory_map = self._bridge.bus.memory_map

        # Internal timer signals:
        self._prescaler_cnt = Signal(8)
        self._counter       = Signal(32)
        self._match_flag    = Signal()

    def elaborate(self, platform):
        m = Module()
        # hook up the CSR bridge
        m.submodules.bridge = self._bridge
        connect(m, flipped(self.bus), self._bridge.bus)

        # shorthands to the field-ports
        ctrl   = self._ctrl.f
        presc  = self._presc.f
        cmp_   = self._compare.f
        cnt    = self._count.f
        status = self._status.f

        p_cnt  = self._prescaler_cnt
        cnt_r  = self._counter
        mflag  = self._match_flag

        # -- prescaler & counter logic --
        with m.If(ctrl.rst.data):
            m.d.sync += [
                p_cnt.eq(0),
                cnt_r.eq(0),
                mflag.eq(0),
            ]
        with m.Elif(ctrl.en.data):
            with m.If(p_cnt == presc.val.data):
                m.d.sync += [
                    p_cnt.eq(0),
                    cnt_r.eq(cnt_r + 1),
                ]
            with m.Else():
                m.d.sync += p_cnt.eq(p_cnt + 1)

        # -- compare & auto-reload --
        with m.If((cnt_r == cmp_.val.data) & ctrl.en.data):
            m.d.sync += mflag.eq(1)
            with m.If(ctrl.ar.data):
                m.d.sync += cnt_r.eq(0)

        # -- IRQ output (level-high) --
        m.d.comb += self.irq.eq(mflag & ctrl.irq_en.data)

        # -- mirror into CSRs --
        # COUNT read portc
        m.d.comb += cnt.val.r_data.eq(cnt_r)
        # STATUS.MATCH read port
        m.d.comb += status.match.data.eq(mflag)

        # write-1-to-clear: if SW writes a ‘1’, clear the flag
        with m.If(status.match.w_stb & status.match.w_data):
            m.d.sync += mflag.eq(0)

        return m




                