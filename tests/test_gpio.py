# amaranth: UnusedElaboratable=no

# SPDX-License-Identifier: BSD-2-Clause
# chipflow-digital-ip % PYTHONPATH=. pdm run pytest -s tests/test_gpio.py
import unittest
from amaranth import *
from amaranth.sim import *
from amaranth.sim._coverage import ToggleCoverageObserver, ToggleDirection, StatementCoverageObserver
from tests.test_utils import *
from chipflow_digital_ip.io import GPIOPeripheral
from amaranth.hdl._ir import Fragment

class PeripheralTestCase(unittest.TestCase):
    def test_init(self):
        dut_1 = GPIOPeripheral(pin_count=4, addr_width=2, data_width=8)
        self.assertEqual(dut_1.pin_count, 4)
        self.assertEqual(dut_1.input_stages, 2)
        self.assertEqual(dut_1.bus.addr_width, 2)
        self.assertEqual(dut_1.bus.data_width, 8)
        dut_2 = GPIOPeripheral(pin_count=1, addr_width=8, data_width=16, input_stages=3)
        self.assertEqual(dut_2.pin_count, 1)
        self.assertEqual(dut_2.input_stages, 3)
        self.assertEqual(dut_2.bus.addr_width, 8)
        self.assertEqual(dut_2.bus.data_width, 16)

    def test_init_wrong_pin_count(self):
        with self.assertRaisesRegex(TypeError,
                r"Pin count must be a positive integer, not 'foo'"):
            GPIOPeripheral(pin_count="foo", addr_width=2, data_width=8)
        with self.assertRaisesRegex(TypeError,
                r"Pin count must be a positive integer, not 0"):
            GPIOPeripheral(pin_count=0, addr_width=2, data_width=8)

    def test_init_wrong_input_stages(self):
        with self.assertRaisesRegex(TypeError,
                r"Input stages must be a non-negative integer, not 'foo'"):
            GPIOPeripheral(pin_count=1, addr_width=2, data_width=8, input_stages="foo")
        with self.assertRaisesRegex(TypeError,
                r"Input stages must be a non-negative integer, not -1"):
            GPIOPeripheral(pin_count=1, addr_width=2, data_width=8, input_stages=-1)

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
        dut = GPIOPeripheral(pin_count=4, addr_width=2, data_width=8)

        sim, assert_cov, assert_info, fragment = mk_sim_with_assertcov(dut, verbose=True)


        # mod = dut.elaborate(platform=None)
        # fragment = Fragment.get(mod, platform=None)
        # _, stmtid_to_info = tag_all_statements(fragment)
        # coverage_signals = insert_coverage_signals(fragment) 
        # signal_to_stmtid = { id(sig): stmt_id for stmt_id, sig in coverage_signals.items() }

        # stmtid_to_name = {}
        # for domain, stmts in fragment.statements.items():
        #     for stmt in stmts:
        #         if hasattr(stmt, "_coverage_id") and hasattr(stmt, "_coverage_name"):
        #             stmtid_to_name[stmt._coverage_id] = stmt._coverage_name

        # sim = Simulator(fragment)
        # statement_cov = StatementCoverageObserver(signal_to_stmtid, sim._engine.state, stmtid_to_info=stmtid_to_info)
        # sim._engine.add_observer(statement_cov)

        mode_addr   = 0x0
        input_addr  = 0x1
        output_addr = 0x2
        setclr_addr = 0x3

        async def testbench(ctx):
            # INPUT_ONLY mode =====================================================================

            # - read Mode:
            await self._csr_access(ctx, dut, mode_addr, r_stb=1, r_data=0b00000000)
            self.assertEqual(ctx.get(dut.alt_mode), 0b0000)
            self.assertEqual(ctx.get(dut.pins.gpio.oe), 0b0000)
            self.assertEqual(ctx.get(dut.pins.gpio.o), 0b0000)

            # - read Input:
            ctx.set(dut.pins.gpio.i[1], 1)
            ctx.set(dut.pins.gpio.i[3], 1)
            await self._csr_access(ctx, dut, input_addr, r_stb=1, r_data=0x0)
            ctx.set(dut.pins.gpio.i[1], 0)
            ctx.set(dut.pins.gpio.i[3], 0)
            await self._csr_access(ctx, dut, input_addr, r_stb=1, r_data=0x0)
            await self._csr_access(ctx, dut, input_addr, r_stb=1, r_data=0xa)
            await self._csr_access(ctx, dut, input_addr, r_stb=1, r_data=0x0)

            # COMMENT OUT TO TEST MISS
            # - write 0xf to Output:
            await self._csr_access(ctx, dut, output_addr, r_stb=1, r_data=0x0, w_stb=1, w_data=0xf)
            await ctx.tick()
            self.assertEqual(ctx.get(dut.pins.gpio.oe), 0b0000)
            self.assertEqual(ctx.get(dut.pins.gpio.o), 0b1111)

            # - write 0x22 to SetClr (clear pins[0] and pins[2]):
            await self._csr_access(ctx, dut, setclr_addr, w_stb=1, w_data=0x22)
            await ctx.tick()
            self.assertEqual(ctx.get(dut.pins.gpio.oe), 0b0000)
            self.assertEqual(ctx.get(dut.pins.gpio.o), 0b1010)

            # - write 0x0 to Output:
            await self._csr_access(ctx, dut, output_addr, r_stb=1, r_data=0xa, w_stb=1, w_data=0x0)
            await ctx.tick()
            self.assertEqual(ctx.get(dut.pins.gpio.oe), 0b0000)
            self.assertEqual(ctx.get(dut.pins.gpio.o), 0b0000)

            # - write 0x44 to SetClr (set pins[1] and pins[3]):
            await self._csr_access(ctx, dut, setclr_addr, w_stb=1, w_data=0x44)
            await ctx.tick()
            self.assertEqual(ctx.get(dut.pins.gpio.oe), 0b0000)
            self.assertEqual(ctx.get(dut.pins.gpio.o), 0b1010)

            # - write 0x0 to Output:
            await self._csr_access(ctx, dut, output_addr, r_stb=1, r_data=0xa, w_stb=1, w_data=0x0)
            await ctx.tick()
            self.assertEqual(ctx.get(dut.pins.gpio.oe), 0b0000)
            self.assertEqual(ctx.get(dut.pins.gpio.o), 0b0000)

            # - write 0xff to SetClr (no-op):
            await self._csr_access(ctx, dut, setclr_addr, w_stb=1, w_data=0xff)
            await ctx.tick()
            self.assertEqual(ctx.get(dut.pins.gpio.oe), 0b0000)
            self.assertEqual(ctx.get(dut.pins.gpio.o), 0b0000)

            # PUSH_PULL mode ======================================================================

            # - write Mode:
            await self._csr_access(ctx, dut, mode_addr, w_stb=1, w_data=0b01010101)
            await ctx.tick()
            self.assertEqual(ctx.get(dut.alt_mode), 0b0000)
            self.assertEqual(ctx.get(dut.pins.gpio.oe), 0b1111)
            self.assertEqual(ctx.get(dut.pins.gpio.o), 0b0000)

            # - read Input:
            ctx.set(dut.pins.gpio.i[1], 1)
            ctx.set(dut.pins.gpio.i[3], 1)
            await self._csr_access(ctx, dut, input_addr, r_stb=1, r_data=0x0)
            ctx.set(dut.pins.gpio.i[1], 0)
            ctx.set(dut.pins.gpio.i[3], 0)
            await self._csr_access(ctx, dut, input_addr, r_stb=1, r_data=0x0)
            await self._csr_access(ctx, dut, input_addr, r_stb=1, r_data=0xa)
            await self._csr_access(ctx, dut, input_addr, r_stb=1, r_data=0x0)

            # - write 0xf to Output:
            await self._csr_access(ctx, dut, output_addr, r_stb=1, r_data=0x0, w_stb=1, w_data=0xf)
            await ctx.tick()
            self.assertEqual(ctx.get(dut.pins.gpio.oe), 0b1111)
            self.assertEqual(ctx.get(dut.pins.gpio.o), 0b1111)

            # - write 0x22 to SetClr (clear pins[0] and pins[2]):
            await self._csr_access(ctx, dut, setclr_addr, w_stb=1, w_data=0x22)
            await ctx.tick()
            self.assertEqual(ctx.get(dut.pins.gpio.oe), 0b1111)
            self.assertEqual(ctx.get(dut.pins.gpio.o), 0b1010)

            # - write 0x0 to Output:
            await self._csr_access(ctx, dut, output_addr, r_stb=1, r_data=0xa, w_stb=1, w_data=0x0)
            await ctx.tick()
            self.assertEqual(ctx.get(dut.pins.gpio.oe), 0b1111)
            self.assertEqual(ctx.get(dut.pins.gpio.o), 0b0000)

            # - write 0x44 to SetClr (set pins[1] and pins[3]):
            await self._csr_access(ctx, dut, setclr_addr, w_stb=1, w_data=0x44)
            await ctx.tick()
            self.assertEqual(ctx.get(dut.pins.gpio.oe), 0b1111)
            self.assertEqual(ctx.get(dut.pins.gpio.o), 0b1010)

        # sim = Simulator(dut)
        # design = sim._engine._design
        # signal_path_map = get_signal_full_paths(design)
        # toggle_cov = ToggleCoverageObserver(sim._engine.state, signal_path_map=signal_path_map)
        # sim._engine.add_observer(toggle_cov)

        sim.add_clock(1e-6)
        sim.add_testbench(testbench)
        # all_signals = collect_all_signals(dut)
        all_signals = collect_all_signals(fragment)
        with sim.write_vcd(vcd_file="smoke_test.vcd", gtkw_file="smoke_test.gtkw", traces=all_signals):
            print("Running simulation and writing VCD...")
            sim.run()

        # results = toggle_cov.get_results()
        # toggle_cov.close(0)
        # results = statement_cov.get_results()
        # statement_cov.close(0)
        
        aresults = assert_cov.get_results()
        assert_cov.close(0)
        merge_assertcov(aresults, assert_info)

    def test_sim_without_input_sync(self):
        dut = GPIOPeripheral(pin_count=4, addr_width=2, data_width=8, input_stages=0)
        sim, assert_cov, assert_info, fragment = mk_sim_with_assertcov(dut, verbose=True)
        input_addr = 0x1

        async def testbench(ctx):
            await self._csr_access(ctx, dut, input_addr, r_stb=1, r_data=0x0)
            ctx.set(dut.pins.gpio.i[1], 1)
            ctx.set(dut.pins.gpio.i[3], 1)
            await self._csr_access(ctx, dut, input_addr, r_stb=1, r_data=0xa)
            ctx.set(dut.pins.gpio.i[1], 0)
            ctx.set(dut.pins.gpio.i[3], 0)
            await self._csr_access(ctx, dut, input_addr, r_stb=1, r_data=0x0)

        # sim = Simulator(dut)
        sim.add_clock(1e-6)
        sim.add_testbench(testbench)
        with sim.write_vcd(vcd_file="test.vcd"):
            sim.run()

        aresults = assert_cov.get_results()
        assert_cov.close(0)
        merge_assertcov(aresults, assert_info)

    @classmethod
    def tearDownClass(cls):
        # Write the aggregated assertion coverage JSON for this suite
        emit_assert_summary("gpio_assertion_cov.json", label="test_gpio.py")

if __name__ == "__main__":
    unittest.main()