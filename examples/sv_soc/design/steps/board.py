# SPDX-License-Identifier: BSD-2-Clause
"""Board step for FPGA prototyping."""

from amaranth import Module, ClockDomain, ClockSignal, ResetSignal, Instance
from amaranth.lib import wiring
from amaranth.lib.cdc import ResetSynchronizer

from amaranth_boards.ulx3s import ULX3S_85F_Platform

from chipflow.platform import BoardStep

from ..design import SVTimerSoC


class BoardSocWrapper(wiring.Component):
    """Wrapper that connects the SoC to FPGA board peripherals."""

    def __init__(self):
        super().__init__({})

    def elaborate(self, platform):
        m = Module()

        # Instantiate the SoC
        m.submodules.soc = soc = SVTimerSoC()

        # Clock domain setup
        m.domains += ClockDomain("sync")
        m.d.comb += ClockSignal("sync").eq(platform.request("clk25").i)

        # Reset synchronizer from power button
        btn_rst = platform.request("button_pwr")
        m.submodules.rst_sync = ResetSynchronizer(arst=btn_rst.i, domain="sync")

        # ========================================
        # SPI Flash connection
        # ========================================
        flash = platform.request(
            "spi_flash",
            dir=dict(cs='-', copi='-', cipo='-', wp='-', hold='-')
        )

        # Flash clock requires special primitive on ECP5
        m.submodules.usrmclk = Instance(
            "USRMCLK",
            i_USRMCLKI=soc.flash.clk.o,
            i_USRMCLKTS=ResetSignal(),  # Tristate in reset for programmer access
            a_keep=1,
        )

        # Flash chip select
        m.submodules += Instance(
            "OBZ",
            o_O=flash.cs.io,
            i_I=soc.flash.csn.o,
            i_T=ResetSignal(),
        )

        # Flash data pins (QSPI)
        data_pins = ["copi", "cipo", "wp", "hold"]
        for i in range(4):
            m.submodules += Instance(
                "BB",
                io_B=getattr(flash, data_pins[i]).io,
                i_I=soc.flash.d.o[i],
                i_T=~soc.flash.d.oe[i],
                o_O=soc.flash.d.i[i],
            )

        # ========================================
        # LED connection (from GPIO0)
        # ========================================
        for i in range(8):
            led = platform.request("led", i)
            m.d.comb += led.o.eq(soc.gpio_0.gpio.o[i])

        # ========================================
        # UART connection
        # ========================================
        uart = platform.request("uart")
        m.d.comb += [
            uart.tx.o.eq(soc.uart_0.tx.o),
            soc.uart_0.rx.i.eq(uart.rx.i),
        ]

        return m


class MyBoardStep(BoardStep):
    """Board build step for ULX3S FPGA board."""

    def __init__(self, config):
        platform = ULX3S_85F_Platform()
        super().__init__(config, platform)

    def build(self):
        design = BoardSocWrapper()
        self.platform.build(design, do_program=False)
