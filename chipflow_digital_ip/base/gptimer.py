from amaranth import Module, Signal, unsigned
from amaranth.lib.wiring import Component, In, Out , connect, flipped

from amaranth_soc import csr


__all__ = ["GPTimer"]

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

class GPTimer(Component):
    """
    General-Purpose Timer:
      - 32-bit up-counter
      - 8-bit prescaler
      - compare match + auto-reload
      - level-high IRQ on match
    """
    def __init__(self):
        # CSR bank: 5-bit address, 8-bit data bus
        regs = csr.Builder(addr_width=5, data_width=8)
        self._ctrl    = regs.add("ctrl",    Ctrl(),    offset=0x00)
        self._presc   = regs.add("presc",   Presc(),   offset=0x04)
        self._count   = regs.add("count",   Count(),   offset=0x08)
        self._compare = regs.add("compare", Compare(), offset=0x0C)
        self._status  = regs.add("status",  Status(),  offset=0x10)

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
        m.submodules.bridge = self._bridge

        connect(m, flipped(self.bus), self._bridge.bus)

        ctrl_f    = self._ctrl.f
        presc_f   = self._presc.f
        cmp_f     = self._compare.f
        cnt_f     = self._count.f
        status_f  = self._status.f

        prescaler_cnt = self._prescaler_cnt
        counter       = self._counter
        match_flag    = self._match_flag

        # Default IRQ low
        m.d.comb += self.irq.eq(0)

        # ---- prescaler & counter ----
        with m.If(ctrl_f.rst):
            m.d.sync += [
                prescaler_cnt.eq(0),
                counter.eq(0),
                match_flag.eq(0),
            ]
        with m.Elif(ctrl_f.en):
            with m.If(prescaler_cnt == presc_f.val):
                m.d.sync += [
                    prescaler_cnt.eq(0),
                    counter.eq(counter + 1),
                ]
            with m.Else():
                m.d.sync += prescaler_cnt.eq(prescaler_cnt + 1)

        # ---- compare & match ----
        with m.If((counter == cmp_f.val) & ctrl_f.en):
            m.d.sync += match_flag.eq(1)
            with m.If(ctrl_f.ar):
                m.d.sync += counter.eq(0)

        # ---- IRQ ----
        with m.If(match_flag & ctrl_f.irq_en):
            m.d.comb += self.irq.eq(1)

        # ---- mirror counter & status ----
        m.d.comb += cnt_f.val.eq(counter)
        # W1C clear
        with m.If(status_f.w_stb & status_f.w_data[0]):
            m.d.sync += match_flag.eq(0)
        m.d.comb += status_f.match.eq(match_flag)

        return m
