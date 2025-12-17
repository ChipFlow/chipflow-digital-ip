"""PWM Peripheral wrapper for Amaranth SoC integration.

This module wraps a SystemVerilog PWM peripheral for use in Amaranth-based SoCs,
following the same pattern as the CV32E40P processor wrapper.
"""

from amaranth import *
from amaranth.lib import wiring
from amaranth.lib.wiring import In, Out, flipped, connect

from amaranth_soc import csr

from pathlib import Path


__all__ = ["PWMPeripheral"]


class PWMPinSignature(wiring.Signature):
    """Signature for PWM output pins connecting to pad ring."""

    def __init__(self, num_channels=4):
        super().__init__({
            "o":  Out(num_channels),  # PWM output
            "oe": Out(num_channels),  # Output enable
        })


class PWMCaptureSignature(wiring.Signature):
    """Signature for input capture pins from pad ring."""

    def __init__(self, num_channels=4):
        super().__init__({
            "i": In(num_channels),  # Capture input
        })


class PWMGPIOSignature(wiring.Signature):
    """Signature for GPIO pins connecting to pad ring."""

    def __init__(self, width=8):
        super().__init__({
            "i":  In(width),   # Input from pad
            "o":  Out(width),  # Output to pad
            "oe": Out(width),  # Output enable
        })


class PWMPeripheral(wiring.Component):
    """PWM Peripheral with pad ring connections.

    A multi-channel PWM controller with input capture and GPIO, wrapped from
    SystemVerilog for use in Amaranth SoCs. The SystemVerilog source is
    converted to RTLIL using yosys-slang during synthesis.

    Parameters
    ----------
    num_channels : int
        Number of PWM/capture channels. Default is 4.
    counter_width : int
        Bit width of the PWM counter. Default is 16.

    Attributes
    ----------
    bus : csr.Interface
        CSR bus interface for register access.
    pwm : PWMPinSignature
        PWM output pins (active drive with output enable).
    capture : PWMCaptureSignature
        Input capture pins from pad ring.
    gpio : PWMGPIOSignature
        Bidirectional GPIO pins.
    """

    def __init__(self, *, num_channels=4, counter_width=16):
        self._num_channels = num_channels
        self._counter_width = counter_width

        super().__init__({
            "bus":     In(csr.Signature(addr_width=8, data_width=32)),
            "pwm":     Out(PWMPinSignature(num_channels)),
            "capture": In(PWMCaptureSignature(num_channels)),
            "gpio":    Out(PWMGPIOSignature(8)).flip(),  # flip for bidirectional
        })

    @property
    def num_channels(self):
        return self._num_channels

    @property
    def counter_width(self):
        return self._counter_width

    def elaborate(self, platform):
        m = Module()

        # Directly connect CSR signals to the SV instance
        # The SV module has a simple CSR interface, not Wishbone
        m.submodules.pwm_core = Instance("pwm_peripheral",
            # Parameters
            p_NUM_CHANNELS=self._num_channels,
            p_COUNTER_WIDTH=self._counter_width,

            # Clock and reset
            i_clk_i=ClockSignal(),
            i_rst_ni=~ResetSignal(),

            # CSR interface
            i_csr_addr_i=self.bus.addr,
            i_csr_we_i=self.bus.w_stb,
            i_csr_wdata_i=self.bus.w_data,
            o_csr_rdata_o=self.bus.r_data,

            # PWM outputs to pad ring
            o_pwm_o=self.pwm.o,
            o_pwm_oe_o=self.pwm.oe,

            # Input capture from pad ring
            i_capture_i=self.capture.i,

            # GPIO to/from pad ring
            i_gpio_i=self.gpio.i,
            o_gpio_o=self.gpio.o,
            o_gpio_oe_o=self.gpio.oe,
        )

        # Add the SystemVerilog source file to the platform
        if platform is not None:
            sv_path = Path(__file__).parent / "pwm_peripheral.sv"
            with open(sv_path, 'r') as f:
                platform.add_file(sv_path.name, f)

        return m
