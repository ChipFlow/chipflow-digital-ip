# SPDX-License-Identifier: BSD-2-Clause
# amaranth: UnusedElaboratable=no

import unittest
from amaranth import *
from amaranth.sim import *
from amaranth.hdl import Assert, Cover

from tests.test_utils import mk_sim_with_assertcov, merge_assertcov, emit_assert_summary


class AssertTop(Elaboratable):
    def __init__(self):
        self.a = Signal(init=0)
        self.b = Signal(init=0)

    def elaborate(self, platform):
        m = Module()

        # Make sure a 'sync' domain exists so add_clock() succeeds
        keep_alive = Signal()
        m.d.sync += keep_alive.eq(~keep_alive)

        # 1) Always-true assert (sanity that an assert is instrumented)
        m.d.sync += Assert(Const(1))

        # 2) Real property: never allow a & b both high (we will NOT violate it)
        m.d.sync += Assert(~(self.a & self.b))

        # Some activity for good measure
        m.d.sync += Cover(self.a ^ self.b)
        return m


class TestAssertCoverage(unittest.TestCase):
    def test_assert_cov(self):
        top = AssertTop()
        sim, assert_cov, assert_info, fragment = mk_sim_with_assertcov(top, verbose=True)

        async def tb(ctx):
            # Cycle 0: a=0, b=0
            await ctx.tick()
            # Cycle 1: a=1, b=0
            ctx.set(top.a, 1); ctx.set(top.b, 0)
            await ctx.tick()
            # Cycle 2: a=0, b=1
            ctx.set(top.a, 0); ctx.set(top.b, 1)
            await ctx.tick()
            # Cycle 3: back to 0,0
            ctx.set(top.a, 0); ctx.set(top.b, 0)
            await ctx.tick()

        sim.add_clock(1e-6)
        sim.add_testbench(tb)
        with sim.write_vcd("test_assert.vcd", "test_assert.gtkw"):
            sim.run()

        results = assert_cov.get_results()
        assert_cov.close(0)
        merge_assertcov(results, assert_info)

    @classmethod
    def tearDownClass(cls):
        emit_assert_summary("assert_cov.json", label="test_assert.py")


if __name__ == "__main__":
    unittest.main()
