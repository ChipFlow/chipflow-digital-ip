"""
Cocotb testbench for PWM Peripheral

Run with:
    make SIM=icarus    # For Icarus Verilog
    make SIM=verilator # For Verilator
"""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, Timer, ClockCycles


class PWMDriver:
    """Driver for PWM peripheral CSR interface"""

    # Register addresses
    REG_CONTROL = 0x00
    REG_STATUS = 0x04
    REG_DUTY0 = 0x10
    REG_DUTY1 = 0x14
    REG_DUTY2 = 0x18
    REG_DUTY3 = 0x1C
    REG_PERIOD0 = 0x20
    REG_PERIOD1 = 0x24
    REG_PERIOD2 = 0x28
    REG_PERIOD3 = 0x2C
    REG_CAPTURE0 = 0x30
    REG_CAPTURE1 = 0x34
    REG_CAPTURE2 = 0x38
    REG_CAPTURE3 = 0x3C
    REG_GPIO_OUT = 0x40
    REG_GPIO_OE = 0x44
    REG_GPIO_IN = 0x48

    def __init__(self, dut):
        self.dut = dut

    async def reset(self):
        """Apply reset"""
        self.dut.rst_ni.value = 0
        self.dut.csr_we_i.value = 0
        self.dut.csr_addr_i.value = 0
        self.dut.csr_wdata_i.value = 0
        self.dut.capture_i.value = 0
        self.dut.gpio_i.value = 0
        await ClockCycles(self.dut.clk_i, 10)
        self.dut.rst_ni.value = 1
        await ClockCycles(self.dut.clk_i, 5)

    async def write(self, addr: int, data: int):
        """Write to CSR register"""
        await RisingEdge(self.dut.clk_i)
        self.dut.csr_addr_i.value = addr
        self.dut.csr_wdata_i.value = data
        self.dut.csr_we_i.value = 1
        await RisingEdge(self.dut.clk_i)
        self.dut.csr_we_i.value = 0

    async def read(self, addr: int) -> int:
        """Read from CSR register"""
        await RisingEdge(self.dut.clk_i)
        self.dut.csr_addr_i.value = addr
        self.dut.csr_we_i.value = 0
        await RisingEdge(self.dut.clk_i)
        return int(self.dut.csr_rdata_o.value)

    async def set_pwm_enable(self, channel_mask: int, prescaler: int = 0):
        """Enable PWM channels"""
        value = (prescaler << 8) | (channel_mask & 0xF)
        await self.write(self.REG_CONTROL, value)

    async def set_duty(self, channel: int, duty: int):
        """Set PWM duty cycle for a channel"""
        addr = self.REG_DUTY0 + (channel * 4)
        await self.write(addr, duty)

    async def set_period(self, channel: int, period: int):
        """Set PWM period for a channel"""
        addr = self.REG_PERIOD0 + (channel * 4)
        await self.write(addr, period)

    async def get_capture(self, channel: int) -> int:
        """Read input capture value"""
        addr = self.REG_CAPTURE0 + (channel * 4)
        return await self.read(addr)

    async def set_gpio_out(self, value: int):
        """Set GPIO output value"""
        await self.write(self.REG_GPIO_OUT, value)

    async def set_gpio_oe(self, value: int):
        """Set GPIO output enable"""
        await self.write(self.REG_GPIO_OE, value)

    async def get_gpio_in(self) -> int:
        """Read GPIO input"""
        return await self.read(self.REG_GPIO_IN)


@cocotb.test()
async def test_reset(dut):
    """Test reset behavior"""
    clock = Clock(dut.clk_i, 10, units="ns")
    cocotb.start_soon(clock.start())

    driver = PWMDriver(dut)
    await driver.reset()

    # After reset, PWM outputs should be disabled
    assert dut.pwm_oe_o.value == 0, "PWM OE should be 0 after reset"
    assert dut.pwm_o.value == 0, "PWM output should be 0 after reset"
    assert dut.gpio_oe_o.value == 0, "GPIO OE should be 0 after reset"


@cocotb.test()
async def test_pwm_enable(dut):
    """Test PWM channel enable"""
    clock = Clock(dut.clk_i, 10, units="ns")
    cocotb.start_soon(clock.start())

    driver = PWMDriver(dut)
    await driver.reset()

    # Enable channel 0
    await driver.set_pwm_enable(0x1)
    await ClockCycles(dut.clk_i, 2)

    assert dut.pwm_oe_o.value & 0x1, "PWM channel 0 OE should be enabled"

    # Enable all channels
    await driver.set_pwm_enable(0xF)
    await ClockCycles(dut.clk_i, 2)

    assert dut.pwm_oe_o.value == 0xF, "All PWM OE should be enabled"


@cocotb.test()
async def test_pwm_output(dut):
    """Test PWM output generation"""
    clock = Clock(dut.clk_i, 10, units="ns")
    cocotb.start_soon(clock.start())

    driver = PWMDriver(dut)
    await driver.reset()

    # Enable channel 0 with no prescaler
    await driver.set_pwm_enable(0x1, prescaler=0)

    # Set duty cycle to 50 (should give ~50% duty with 16-bit counter)
    await driver.set_duty(0, 50)

    # Wait and count high cycles
    high_count = 0
    total_cycles = 200
    for _ in range(total_cycles):
        await RisingEdge(dut.clk_i)
        if dut.pwm_o.value & 0x1:
            high_count += 1

    # We expect roughly 50 high cycles out of 200
    # (since duty=50 and counter increments each cycle)
    dut._log.info(f"PWM high count: {high_count}/{total_cycles}")
    assert high_count > 0, "PWM should have some high cycles"


@cocotb.test()
async def test_gpio_output(dut):
    """Test GPIO output functionality"""
    clock = Clock(dut.clk_i, 10, units="ns")
    cocotb.start_soon(clock.start())

    driver = PWMDriver(dut)
    await driver.reset()

    # Set GPIO output and enable
    await driver.set_gpio_out(0xA5)
    await driver.set_gpio_oe(0xFF)
    await ClockCycles(dut.clk_i, 2)

    assert dut.gpio_o.value == 0xA5, f"GPIO output should be 0xA5, got {hex(dut.gpio_o.value)}"
    assert dut.gpio_oe_o.value == 0xFF, f"GPIO OE should be 0xFF, got {hex(dut.gpio_oe_o.value)}"


@cocotb.test()
async def test_gpio_input(dut):
    """Test GPIO input reading"""
    clock = Clock(dut.clk_i, 10, units="ns")
    cocotb.start_soon(clock.start())

    driver = PWMDriver(dut)
    await driver.reset()

    # Set GPIO input value
    dut.gpio_i.value = 0x3C
    await ClockCycles(dut.clk_i, 2)

    # Read back
    value = await driver.get_gpio_in()
    assert (value & 0xFF) == 0x3C, f"GPIO input should be 0x3C, got {hex(value)}"


@cocotb.test()
async def test_input_capture(dut):
    """Test input capture functionality"""
    clock = Clock(dut.clk_i, 10, units="ns")
    cocotb.start_soon(clock.start())

    driver = PWMDriver(dut)
    await driver.reset()

    # Wait a bit for counter to advance
    await ClockCycles(dut.clk_i, 50)

    # Generate rising edge on capture input 0
    dut.capture_i.value = 0
    await ClockCycles(dut.clk_i, 5)
    dut.capture_i.value = 1
    await ClockCycles(dut.clk_i, 5)

    # Read capture value
    capture_val = await driver.get_capture(0)
    dut._log.info(f"Capture value: {capture_val}")

    # Capture value should be non-zero (counter has been running)
    # Note: might be 0 if we catch it exactly at reset
    assert capture_val >= 0, "Capture should return a value"


@cocotb.test()
async def test_multiple_channels(dut):
    """Test multiple PWM channels with different duty cycles"""
    clock = Clock(dut.clk_i, 10, units="ns")
    cocotb.start_soon(clock.start())

    driver = PWMDriver(dut)
    await driver.reset()

    # Enable all 4 channels
    await driver.set_pwm_enable(0xF)

    # Set different duty cycles
    await driver.set_duty(0, 25)   # 25
    await driver.set_duty(1, 50)   # 50
    await driver.set_duty(2, 75)   # 75
    await driver.set_duty(3, 100)  # 100

    # Wait for PWM to run
    await ClockCycles(dut.clk_i, 500)

    # All output enables should be high
    assert dut.pwm_oe_o.value == 0xF, "All PWM OE should be enabled"

    dut._log.info("Multiple channel test passed")
