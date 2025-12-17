# amaranth: UnusedElaboratable=no

# SPDX-License-Identifier: BSD-2-Clause

import tempfile
import unittest
import warnings
from pathlib import Path

from amaranth import *
from amaranth.hdl import UnusedElaboratable

from chipflow import ChipFlowError
from chipflow_digital_ip.io._verilog_wrapper import (
    ExternalWrapConfig,
    Files,
    Generate,
    GenerateSV2V,
    Generators,
    Port,
    VerilogWrapper,
    _flatten_port_map,
    _parse_signal_direction,
    _resolve_interface_type,
    load_wrapper_from_toml,
)


class HelperFunctionsTestCase(unittest.TestCase):
    def test_parse_signal_direction_input(self):
        self.assertEqual(_parse_signal_direction("i_clk"), "i")
        self.assertEqual(_parse_signal_direction("i_data_in"), "i")

    def test_parse_signal_direction_output(self):
        self.assertEqual(_parse_signal_direction("o_data_out"), "o")
        self.assertEqual(_parse_signal_direction("o_valid"), "o")

    def test_parse_signal_direction_default(self):
        self.assertEqual(_parse_signal_direction("clk"), "i")
        self.assertEqual(_parse_signal_direction("data"), "i")

    def test_flatten_port_map_string(self):
        result = _flatten_port_map("i_signal")
        self.assertEqual(result, {"": "i_signal"})

    def test_flatten_port_map_simple_dict(self):
        result = _flatten_port_map({"cyc": "i_cyc", "stb": "i_stb"})
        self.assertEqual(result, {"cyc": "i_cyc", "stb": "i_stb"})

    def test_flatten_port_map_nested_dict(self):
        result = _flatten_port_map({
            "dat": {"r": "o_dat_r", "w": "i_dat_w"},
            "cyc": "i_cyc"
        })
        self.assertEqual(result, {
            "dat.r": "o_dat_r",
            "dat.w": "i_dat_w",
            "cyc": "i_cyc"
        })

    def test_resolve_interface_type_simple(self):
        result = _resolve_interface_type("amaranth.lib.wiring.Out(1)")
        self.assertEqual(result, ("Out", 1))

        result = _resolve_interface_type("amaranth.lib.wiring.In(8)")
        self.assertEqual(result, ("In", 8))

    def test_resolve_interface_type_invalid(self):
        with self.assertRaises(ChipFlowError):
            _resolve_interface_type("invalid")


class FilesConfigTestCase(unittest.TestCase):
    def test_files_module_only(self):
        files = Files(module="os.path")
        self.assertEqual(files.module, "os.path")
        self.assertIsNone(files.path)

    def test_files_path_only(self):
        files = Files(path=Path("/tmp"))
        self.assertIsNone(files.module)
        self.assertEqual(files.path, Path("/tmp"))

    def test_files_neither_raises(self):
        with self.assertRaises(ValueError):
            Files()

    def test_files_both_raises(self):
        with self.assertRaises(ValueError):
            Files(module="os.path", path=Path("/tmp"))


class ExternalWrapConfigTestCase(unittest.TestCase):
    def test_minimal_config(self):
        config = ExternalWrapConfig(
            name="TestModule",
            files=Files(path=Path("/tmp")),
        )
        self.assertEqual(config.name, "TestModule")
        self.assertEqual(config.clocks, {})
        self.assertEqual(config.resets, {})
        self.assertEqual(config.ports, {})
        self.assertEqual(config.pins, {})

    def test_config_with_ports(self):
        config = ExternalWrapConfig(
            name="TestModule",
            files=Files(path=Path("/tmp")),
            ports={
                "interrupt": Port(
                    interface="amaranth.lib.wiring.Out(1)",
                    map="o_interrupt"
                )
            },
            clocks={"sys": "clk"},
            resets={"sys": "rst_n"},
        )
        self.assertEqual(config.name, "TestModule")
        self.assertIn("interrupt", config.ports)
        self.assertEqual(config.clocks["sys"], "clk")
        self.assertEqual(config.resets["sys"], "rst_n")


class VerilogWrapperTestCase(unittest.TestCase):
    def setUp(self):
        warnings.simplefilter(action="ignore", category=UnusedElaboratable)

    def test_simple_wrapper(self):
        config = ExternalWrapConfig(
            name="TestModule",
            files=Files(path=Path("/tmp")),
            ports={
                "interrupt": Port(
                    interface="amaranth.lib.wiring.Out(1)",
                    map="o_interrupt"
                )
            },
            clocks={"sys": "clk"},
            resets={"sys": "rst_n"},
        )

        wrapper = VerilogWrapper(config)
        self.assertEqual(wrapper._config.name, "TestModule")
        # Check that the signature has the interrupt port
        self.assertIn("interrupt", wrapper.signature.members)

    def test_elaborate_creates_instance(self):
        config = ExternalWrapConfig(
            name="TestModule",
            files=Files(path=Path("/tmp")),
            ports={
                "interrupt": Port(
                    interface="amaranth.lib.wiring.Out(1)",
                    map="o_interrupt"
                )
            },
            clocks={"sys": "clk"},
            resets={"sys": "rst_n"},
        )

        wrapper = VerilogWrapper(config)
        # Elaborate with no platform (simulation mode)
        m = wrapper.elaborate(platform=None)
        self.assertIsInstance(m, Module)
        # Check that the wrapped submodule exists
        self.assertIn("wrapped", m._submodules)


class LoadWrapperFromTomlTestCase(unittest.TestCase):
    def setUp(self):
        warnings.simplefilter(action="ignore", category=UnusedElaboratable)

    def test_load_simple_toml(self):
        toml_content = """
name = 'SimpleTest'

[files]
path = '/tmp'

[clocks]
sys = 'clk'

[resets]
sys = 'rst_n'

[ports.interrupt]
interface = 'amaranth.lib.wiring.Out(1)'
map = 'o_interrupt'
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.toml', delete=False) as f:
            f.write(toml_content)
            toml_path = Path(f.name)

        try:
            wrapper = load_wrapper_from_toml(toml_path)
            self.assertEqual(wrapper._config.name, "SimpleTest")
            self.assertIn("interrupt", wrapper.signature.members)
        finally:
            toml_path.unlink()

    def test_load_invalid_toml_raises(self):
        toml_content = """
# Missing required 'name' field
[files]
path = '/tmp'
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.toml', delete=False) as f:
            f.write(toml_content)
            toml_path = Path(f.name)

        try:
            with self.assertRaises(ChipFlowError):
                load_wrapper_from_toml(toml_path)
        finally:
            toml_path.unlink()


class SystemVerilogConfigTestCase(unittest.TestCase):
    def test_generators_enum(self):
        self.assertEqual(Generators.VERILOG, "verilog")
        self.assertEqual(Generators.SYSTEMVERILOG, "systemverilog")
        self.assertEqual(Generators.SPINALHDL, "spinalhdl")

    def test_generate_config_systemverilog(self):
        gen = Generate(
            generator=Generators.SYSTEMVERILOG,
            sv2v=GenerateSV2V(
                top_module="wb_timer",
                include_dirs=["inc"],
                defines={"SIMULATION": "1"}
            )
        )
        self.assertEqual(gen.generator, Generators.SYSTEMVERILOG)
        self.assertIsNotNone(gen.sv2v)
        self.assertEqual(gen.sv2v.top_module, "wb_timer")
        self.assertIn("inc", gen.sv2v.include_dirs)

    def test_sv2v_config_defaults(self):
        sv2v = GenerateSV2V()
        self.assertEqual(sv2v.include_dirs, [])
        self.assertEqual(sv2v.defines, {})
        self.assertIsNone(sv2v.top_module)

    def test_config_with_systemverilog_generator(self):
        config = ExternalWrapConfig(
            name="SVModule",
            files=Files(path=Path("/tmp")),
            generate=Generate(
                generator=Generators.SYSTEMVERILOG,
                sv2v=GenerateSV2V(top_module="test")
            ),
            clocks={"sys": "clk"},
            resets={"sys": "rst_n"},
        )
        self.assertEqual(config.name, "SVModule")
        self.assertEqual(config.generate.generator, Generators.SYSTEMVERILOG)

    def test_load_systemverilog_toml(self):
        toml_content = """
name = 'SVTest'

[files]
path = '/tmp'

[generate]
generator = 'systemverilog'

[generate.sv2v]
top_module = 'test_module'
include_dirs = ['inc', 'src']
defines = { DEBUG = '1', FEATURE_A = '' }

[clocks]
sys = 'clk'

[resets]
sys = 'rst_n'

[ports.irq]
interface = 'amaranth.lib.wiring.Out(1)'
map = 'o_irq'
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.toml', delete=False) as f:
            f.write(toml_content)
            toml_path = Path(f.name)

        try:
            # This will fail at sv2v stage since no .sv files exist, but config parsing should work
            # So we test the config parsing separately
            import tomli
            with open(toml_path, 'rb') as f:
                raw = tomli.load(f)
            config = ExternalWrapConfig.model_validate(raw)
            self.assertEqual(config.name, "SVTest")
            self.assertEqual(config.generate.generator, Generators.SYSTEMVERILOG)
            self.assertEqual(config.generate.sv2v.top_module, "test_module")
        finally:
            toml_path.unlink()


if __name__ == "__main__":
    unittest.main()
