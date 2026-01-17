# SPDX-License-Identifier: BSD-2-Clause
"""SoC design using SystemVerilog timer via VerilogWrapper.

This example demonstrates how to integrate SystemVerilog/Verilog components
into a ChipFlow SoC design using VerilogWrapper.
"""

from pathlib import Path

from amaranth import Module
from amaranth.lib import wiring
from amaranth.lib.wiring import Out, flipped, connect

from amaranth_soc import csr, wishbone
from amaranth_soc.csr.wishbone import WishboneCSRBridge
from amaranth_soc.wishbone.sram import WishboneSRAM

from chipflow_digital_ip.base import SoCID
from chipflow_digital_ip.memory import QSPIFlash
from chipflow_digital_ip.io import GPIOPeripheral, UARTPeripheral
from chipflow_digital_ip.io import load_wrapper_from_toml

from minerva.core import Minerva

from chipflow.platform import (
    GPIOSignature,
    UARTSignature,
    QSPIFlashSignature,
    attach_data,
    SoftwareBuild,
)


__all__ = ["SVTimerSoC"]

# Path to the RTL directory containing the SystemVerilog timer
RTL_DIR = Path(__file__).parent / "rtl"
TIMER_TOML = RTL_DIR / "wb_timer.toml"


class SVTimerSoC(wiring.Component):
    """SoC with SystemVerilog timer peripheral.

    This SoC demonstrates integrating a SystemVerilog peripheral (wb_timer)
    alongside native Amaranth peripherals. The timer is loaded via VerilogWrapper
    and connected to the Wishbone bus.

    Memory Map:
        0x00000000 - SPI Flash (code/data)
        0x10000000 - SRAM (1KB working memory)
        0xB0000000 - CSR region start
        0xB0000000 - SPI Flash CSRs
        0xB1000000 - GPIO
        0xB2000000 - UART
        0xB3000000 - Timer (SystemVerilog)
        0xB4000000 - SoC ID
    """

    def __init__(self):
        super().__init__({
            "flash": Out(QSPIFlashSignature()),
            "uart_0": Out(UARTSignature()),
            "gpio_0": Out(GPIOSignature(pin_count=8)),
        })

        # Memory regions
        self.mem_spiflash_base = 0x00000000
        self.mem_sram_base     = 0x10000000

        # CSR regions
        self.csr_base          = 0xB0000000
        self.csr_spiflash_base = 0xB0000000
        self.csr_gpio_base     = 0xB1000000
        self.csr_uart_base     = 0xB2000000
        self.csr_timer_base    = 0xB3000000  # SystemVerilog timer
        self.csr_soc_id_base   = 0xB4000000

        # SRAM size
        self.sram_size = 0x400  # 1KB

        # BIOS start (1MB into flash to leave room for bitstream)
        self.bios_start = 0x100000

        # Build directory for generated Verilog
        self.build_dir = Path(__file__).parent.parent / "build"

    def elaborate(self, platform):
        m = Module()

        # Create Wishbone arbiter and decoder
        wb_arbiter = wishbone.Arbiter(addr_width=30, data_width=32, granularity=8)
        wb_decoder = wishbone.Decoder(addr_width=30, data_width=32, granularity=8)
        csr_decoder = csr.Decoder(addr_width=28, data_width=8)

        m.submodules.wb_arbiter = wb_arbiter
        m.submodules.wb_decoder = wb_decoder
        m.submodules.csr_decoder = csr_decoder

        connect(m, wb_arbiter.bus, wb_decoder.bus)

        # ========================================
        # CPU - Minerva RISC-V
        # ========================================
        cpu = Minerva(reset_address=self.bios_start, with_muldiv=True)
        wb_arbiter.add(cpu.ibus)
        wb_arbiter.add(cpu.dbus)
        m.submodules.cpu = cpu

        # ========================================
        # QSPI Flash - Code and data storage
        # ========================================
        spiflash = QSPIFlash(addr_width=24, data_width=32)
        wb_decoder.add(spiflash.wb_bus, name="spiflash", addr=self.mem_spiflash_base)
        csr_decoder.add(spiflash.csr_bus, name="spiflash",
                        addr=self.csr_spiflash_base - self.csr_base)
        m.submodules.spiflash = spiflash
        connect(m, flipped(self.flash), spiflash.pins)

        # ========================================
        # SRAM - Working memory
        # ========================================
        sram = WishboneSRAM(size=self.sram_size, data_width=32, granularity=8)
        wb_decoder.add(sram.wb_bus, name="sram", addr=self.mem_sram_base)
        m.submodules.sram = sram

        # ========================================
        # GPIO - LED control
        # ========================================
        gpio_0 = GPIOPeripheral(pin_count=8)
        csr_decoder.add(gpio_0.bus, name="gpio_0",
                        addr=self.csr_gpio_base - self.csr_base)
        m.submodules.gpio_0 = gpio_0
        connect(m, flipped(self.gpio_0), gpio_0.pins)

        # ========================================
        # UART - Serial output
        # ========================================
        uart_0 = UARTPeripheral(init_divisor=int(25e6 // 115200), addr_width=5)
        csr_decoder.add(uart_0.bus, name="uart_0",
                        addr=self.csr_uart_base - self.csr_base)
        m.submodules.uart_0 = uart_0
        connect(m, flipped(self.uart_0), uart_0.pins)

        # ========================================
        # SystemVerilog Timer - Using VerilogWrapper
        # ========================================
        # Load the timer from TOML configuration
        timer_wrapper = load_wrapper_from_toml(
            TIMER_TOML,
            generate_dest=self.build_dir / "timer_gen"
        )

        # Add the timer to the Wishbone decoder
        # The timer has a 32-bit Wishbone interface
        wb_decoder.add(timer_wrapper.bus, name="timer",
                       addr=self.csr_timer_base)

        # Add the timer module
        m.submodules.timer = timer_wrapper

        # Timer IRQ could be connected to CPU interrupt if needed
        # For this example, we just expose it for monitoring

        # ========================================
        # SoC ID - Device identification
        # ========================================
        soc_id = SoCID(type_id=0xCA7F100F)
        csr_decoder.add(soc_id.bus, name="soc_id",
                        addr=self.csr_soc_id_base - self.csr_base)
        m.submodules.soc_id = soc_id

        # ========================================
        # Wishbone-CSR bridge
        # ========================================
        wb_to_csr = WishboneCSRBridge(csr_decoder.bus, data_width=32)
        wb_decoder.add(wb_to_csr.wb_bus, name="csr", addr=self.csr_base, sparse=False)
        m.submodules.wb_to_csr = wb_to_csr

        # ========================================
        # Software build configuration
        # ========================================
        sw = SoftwareBuild(
            sources=Path(__file__).parent.glob("software/*.c"),
            offset=self.bios_start,
        )

        # Attach software data to flash
        attach_data(self.flash, m.submodules.spiflash, sw)

        return m


if __name__ == "__main__":
    # Generate standalone Verilog for inspection
    from amaranth.back import verilog

    soc = SVTimerSoC()
    with open("build/sv_timer_soc.v", "w") as f:
        f.write(verilog.convert(soc, name="sv_timer_soc"))
    print("Generated build/sv_timer_soc.v")
