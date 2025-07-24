from amaranth import *
from amaranth_soc import csr


class GPTimer(Elaboratable):
    """
    General-Purpose Timer (GPTimer) peripheral.

    Features:
      - 32-bit up-counter
      - 8-bit prescaler (divide-by N+1)
      - Single 32-bit compare register
      - Auto-reload on compare match
      - Interrupt on match (level-high)
      - CSR-based register interface
    """

    def __init__(self):
        # Interrupt output
        self.irq = Signal()

        # Control/Status Registers (CSR)
        # CTRL: [0]=EN, [1]=RST, [2]=AR (auto-reload), [3]=IRQ_EN
        self.ctrl = csr.Register(width=8)
        # PRESC: prescaler divisor (0 => /1, 255 => /256)
        self.presc = csr.Register(width=8)
        # COMPARE: target value for match
        self.compare = csr.Register(width=32)
        # COUNT: current counter value (read-only) 
        self.count = csr.Register(width=32)
        # STATUS: [0]=MATCH flag (W1C)
        self.status = csr.Register(width=8)

        # CSR bus interface
        self.bus = csr.Interface(data_width=8)

    def elaborate(self, platform):
        m = Module()

        # Register submodules for CSR
        m.submodules += [
            self.ctrl, self.presc,
            self.compare, self.count,
            self.status,
            self.bus
        ]

        # Internal signals
        prescaler_cnt = Signal(8)
        counter = Signal(32)
        match_flag = Signal()

        # Default IRQ low
        m.d.comb += self.irq.eq(0)

        # Prescaler: tick only when prescaler_cnt == PRESC
        with m.If(self.ctrl.fields.rst):
            m.d.sync += prescaler_cnt.eq(0)
        with m.Elif(self.ctrl.fields.en):
            with m.If(prescaler_cnt == self.presc.fields):
                m.d.sync += prescaler_cnt.eq(0)
                # Increment main counter
                m.d.sync += counter.eq(counter + 1)
            with m.Else():
                m.d.sync += prescaler_cnt.eq(prescaler_cnt + 1)

        # Compare & match logic
        with m.If((counter == self.compare.fields) & self.ctrl.fields.en):
            m.d.sync += match_flag.eq(1)
            # Auto-reload behavior
            with m.If(self.ctrl.fields.ar):
                m.d.sync += counter.eq(0)

        # IRQ output if match and IRQ_EN
        with m.If(match_flag & self.ctrl.fields.irq_en):
            m.d.comb += self.irq.eq(1)

        # Update COUNT CSR (read-only)
        m.d.comb += self.count.fields.eq(counter)

        # STATUS MATCH flag update (W1C)
        # Write-1-to-clear: if software writes 1, clear match_flag
        with m.If(self.status.w_stb & self.status.w_data[0]):
            m.d.sync += match_flag.eq(0)
        # Reflect match_flag into STATUS bit 0
        m.d.comb += self.status.fields[0].eq(match_flag)

        return m
