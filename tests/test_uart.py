# amaranth: UnusedElaboratable=no

# SPDX-License-Identifier: BSD-2-Clause

import unittest
from amaranth import *
from amaranth.sim import *

from chipflow_digital_ip.io import UARTPeripheral


class PeripheralTestCase(unittest.TestCase):
    async def _csr_access(self, ctx, dut, addr, r_stb=0, w_stb=0, w_data=0, r_data=0):
        ctx.set(dut.bus.addr, addr)
        ctx.set(dut.bus.r_stb, r_stb)
        ctx.set(dut.bus.w_stb, w_stb)
        ctx.set(dut.bus.w_data, w_data)
        await ctx.tick()
        if r_stb:
            self.assertEqual(ctx.get(dut.bus.r_data), r_data)
        ctx.set(dut.bus.r_stb, 0)
        ctx.set(dut.bus.w_stb, 0)

    def test_smoke_test(self):
        """
        Smoke test GPIO. We assume that amaranth-soc GPIO tests are fully testing functionality.
        """
        rx_addr = 0x00
        tx_addr = 0x10
        config_addr = 0x00
        status_addr = 0x08
        data_addr = 0x09

        sim_divisor = 8

        dut = UARTPeripheral(init_divisor=sim_divisor, addr_width=5)

        # simulated UART receiver
        last_sent_byte = None

        async def uart_rx_proc(ctx):
            nonlocal last_sent_byte
            counter = 0
            tx_last = 0
            sr = 0
            async for clk_edge, rst, tx in ctx.tick().sample(dut.pins.tx.o):
                if rst:
                    pass
                elif clk_edge:
                    if counter == 0:  # waiting for start transition
                        if tx_last and not tx:  # falling edge
                            counter = 1
                    else:
                        counter += 1
                        if (counter > (sim_divisor // 2)) and (
                            (counter - (sim_divisor // 2)) % sim_divisor
                        ) == 0:  # in middle of bit
                            bit = (counter - (sim_divisor // 2)) // sim_divisor
                            if bit >= 1 and bit <= 8:
                                sr = (tx << 7) | (sr >> 1)
                            if bit == 8:
                                last_sent_byte = sr
                            elif bit == 9:  # stop
                                counter = 0
                    tx_last = tx

        to_send_byte = None

        async def uart_tx_proc(ctx):
            nonlocal to_send_byte
            counter = 0
            ctx.set(dut.pins.rx.i, 1)
            async for clk_edge, rst in ctx.tick().sample():
                if rst:
                    pass
                elif clk_edge:
                    if to_send_byte is not None:
                        bit = counter // sim_divisor
                        if bit == 0:
                            ctx.set(dut.pins.rx.i, 0)  # start
                        elif bit >= 1 and bit <= 8:
                            ctx.set(dut.pins.rx.i, (to_send_byte >> (bit - 1)) & 0x1)
                        if bit > 8:
                            ctx.set(dut.pins.rx.i, 1)  # stop
                            to_send_byte = None
                            counter = 0
                        else:
                            counter += 1

        async def testbench(ctx):
            nonlocal to_send_byte
            # enable tx
            await self._csr_access(ctx, dut, tx_addr | config_addr, w_stb=1, w_data=1)
            # check tx ready
            await self._csr_access(ctx, dut, tx_addr | status_addr, r_stb=1, r_data=1)
            # write byte
            await self._csr_access(ctx, dut, tx_addr | data_addr, w_stb=1, w_data=0xA5)
            await ctx.tick()
            # check tx not ready
            await self._csr_access(ctx, dut, tx_addr | status_addr, r_stb=1, r_data=0)
            # wait for UART to do its thing
            for i in range(sim_divisor * 12):
                await ctx.tick()
            # check tx ready
            await self._csr_access(ctx, dut, tx_addr | status_addr, r_stb=1, r_data=1)
            # check the byte was sent correctly
            self.assertEqual(last_sent_byte, 0xA5)

            # enable rx
            await self._csr_access(ctx, dut, rx_addr | config_addr, w_stb=1, w_data=1)
            # check rx not ready
            await self._csr_access(ctx, dut, rx_addr | status_addr, r_stb=1, r_data=0)
            for i in range(sim_divisor):
                await ctx.tick()
            # send a byte to the UART
            to_send_byte = 0x73
            for i in range(sim_divisor * 12):
                await ctx.tick()
            # check rx ready
            await self._csr_access(ctx, dut, rx_addr | status_addr, r_stb=1, r_data=1)
            # check the byte was received correctly
            await self._csr_access(ctx, dut, rx_addr | data_addr, r_stb=1, r_data=0x73)

        sim = Simulator(dut)
        sim.add_clock(1e-6)
        sim.add_process(uart_rx_proc)
        sim.add_process(uart_tx_proc)
        sim.add_testbench(testbench)
        with sim.write_vcd(vcd_file="test_uart.vcd"):
            sim.run()
