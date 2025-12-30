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
    DriverConfig,
    ExternalWrapConfig,
    Files,
    Generate,
    GenerateSV2V,
    Generators,
    Port,
    VerilogWrapper,
    _flatten_port_map,
    _generate_auto_map,
    _infer_auto_map,
    _infer_signal_direction,
    _INTERFACE_PATTERNS,
    _INTERFACE_REGISTRY,
    _parse_signal_direction,
    _parse_verilog_ports,
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


class DriverConfigTestCase(unittest.TestCase):
    def test_driver_config_defaults(self):
        driver = DriverConfig()
        self.assertIsNone(driver.regs_struct)
        self.assertEqual(driver.c_files, [])
        self.assertEqual(driver.h_files, [])

    def test_driver_config_full(self):
        driver = DriverConfig(
            regs_struct='timer_regs_t',
            c_files=['drivers/timer.c'],
            h_files=['drivers/timer.h'],
        )
        self.assertEqual(driver.regs_struct, 'timer_regs_t')
        self.assertEqual(driver.c_files, ['drivers/timer.c'])
        self.assertEqual(driver.h_files, ['drivers/timer.h'])


class PortDirectionTestCase(unittest.TestCase):
    def test_port_direction_explicit(self):
        port = Port(
            interface='amaranth.lib.wiring.Out(1)',
            map='o_signal',
            direction='out'
        )
        self.assertEqual(port.direction, 'out')

    def test_port_direction_none(self):
        port = Port(
            interface='amaranth.lib.wiring.Out(1)',
            map='o_signal',
        )
        self.assertIsNone(port.direction)

    def test_config_with_ports_and_pins(self):
        config = ExternalWrapConfig(
            name="TestModule",
            files=Files(path=Path("/tmp")),
            ports={
                "bus": Port(
                    interface="amaranth.lib.wiring.Out(1)",
                    map="i_bus",
                    direction="in"
                )
            },
            pins={
                "irq": Port(
                    interface="amaranth.lib.wiring.Out(1)",
                    map="o_irq",
                    direction="out"
                )
            },
            driver=DriverConfig(
                regs_struct='test_regs_t',
                h_files=['drivers/test.h']
            )
        )
        self.assertIn("bus", config.ports)
        self.assertIn("irq", config.pins)
        self.assertIsNotNone(config.driver)
        self.assertEqual(config.driver.regs_struct, 'test_regs_t')

    def test_load_toml_with_driver(self):
        toml_content = """
name = 'DriverTest'

[files]
path = '/tmp'

[clocks]
sys = 'clk'

[resets]
sys = 'rst_n'

[ports.bus]
interface = 'amaranth.lib.wiring.Out(1)'
map = 'i_bus'
direction = 'in'

[pins.irq]
interface = 'amaranth.lib.wiring.Out(1)'
map = 'o_irq'

[driver]
regs_struct = 'my_regs_t'
c_files = ['drivers/my_driver.c']
h_files = ['drivers/my_driver.h']
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.toml', delete=False) as f:
            f.write(toml_content)
            toml_path = Path(f.name)

        try:
            import tomli
            with open(toml_path, 'rb') as f:
                raw = tomli.load(f)
            config = ExternalWrapConfig.model_validate(raw)
            self.assertEqual(config.name, "DriverTest")
            self.assertIn("bus", config.ports)
            self.assertEqual(config.ports["bus"].direction, "in")
            self.assertIn("irq", config.pins)
            self.assertIsNotNone(config.driver)
            self.assertEqual(config.driver.regs_struct, "my_regs_t")
            self.assertEqual(config.driver.c_files, ["drivers/my_driver.c"])
            self.assertEqual(config.driver.h_files, ["drivers/my_driver.h"])
        finally:
            toml_path.unlink()


class AutoMappingTestCase(unittest.TestCase):
    def test_interface_patterns_has_known_interfaces(self):
        """Verify the interface patterns registry contains expected entries."""
        self.assertIn("amaranth_soc.wishbone.Signature", _INTERFACE_PATTERNS)
        self.assertIn("amaranth_soc.csr.Signature", _INTERFACE_PATTERNS)
        self.assertIn("chipflow.platform.GPIOSignature", _INTERFACE_PATTERNS)
        self.assertIn("chipflow.platform.UARTSignature", _INTERFACE_PATTERNS)
        self.assertIn("chipflow.platform.I2CSignature", _INTERFACE_PATTERNS)
        self.assertIn("chipflow.platform.SPISignature", _INTERFACE_PATTERNS)

    def test_parse_verilog_ports_ansi_style(self):
        """Test parsing ANSI-style Verilog port declarations."""
        verilog = """
module test_module (
    input  logic        i_clk,
    input  logic        i_rst_n,
    input  logic        i_wb_cyc,
    input  logic        i_wb_stb,
    output logic [31:0] o_wb_dat,
    output logic        o_wb_ack
);
endmodule
"""
        ports = _parse_verilog_ports(verilog, "test_module")
        self.assertEqual(ports.get("i_clk"), "input")
        self.assertEqual(ports.get("i_wb_cyc"), "input")
        self.assertEqual(ports.get("o_wb_dat"), "output")
        self.assertEqual(ports.get("o_wb_ack"), "output")

    def test_infer_signal_direction(self):
        """Test inferring signal direction from naming conventions."""
        # Prefixes
        self.assertEqual(_infer_signal_direction("i_clk"), "i")
        self.assertEqual(_infer_signal_direction("o_data"), "o")
        self.assertEqual(_infer_signal_direction("in_signal"), "i")
        self.assertEqual(_infer_signal_direction("out_signal"), "o")
        # Suffixes
        self.assertEqual(_infer_signal_direction("clk_i"), "i")
        self.assertEqual(_infer_signal_direction("data_o"), "o")
        self.assertEqual(_infer_signal_direction("enable_oe"), "o")
        # Unknown
        self.assertEqual(_infer_signal_direction("signal"), "io")

    def test_infer_auto_map_wishbone(self):
        """Test auto-inferring Wishbone mapping from Verilog ports."""
        verilog_ports = {
            "i_wb_cyc": "input",
            "i_wb_stb": "input",
            "i_wb_we": "input",
            "i_wb_sel": "input",
            "i_wb_adr": "input",
            "i_wb_dat": "input",
            "o_wb_dat": "output",
            "o_wb_ack": "output",
        }
        result = _infer_auto_map("amaranth_soc.wishbone.Signature", verilog_ports, "in")
        self.assertEqual(result.get("cyc"), "i_wb_cyc")
        self.assertEqual(result.get("stb"), "i_wb_stb")
        self.assertEqual(result.get("we"), "i_wb_we")
        self.assertEqual(result.get("ack"), "o_wb_ack")

    def test_infer_auto_map_uart(self):
        """Test auto-inferring UART mapping from Verilog ports."""
        verilog_ports = {
            "uart_tx": "output",
            "uart_rx": "input",
        }
        result = _infer_auto_map("chipflow.platform.UARTSignature", verilog_ports, "out")
        self.assertEqual(result.get("tx.o"), "uart_tx")
        self.assertEqual(result.get("rx.i"), "uart_rx")

    def test_generate_auto_map_fallback(self):
        """Test fallback prefix-based auto-mapping."""
        result = _generate_auto_map("amaranth_soc.wishbone.Signature", "wb", "in")
        self.assertIn("cyc", result)
        self.assertIn("stb", result)
        self.assertIn("ack", result)

    def test_generate_auto_map_simple_out(self):
        """Test auto-mapping for simple Out(1) interface."""
        result = _generate_auto_map("amaranth.lib.wiring.Out(1)", "irq", "out")
        self.assertEqual(result[""], "o_irq")

    def test_generate_auto_map_simple_in(self):
        """Test auto-mapping for simple In(1) interface."""
        result = _generate_auto_map("amaranth.lib.wiring.In(8)", "data", "in")
        self.assertEqual(result[""], "i_data")

    def test_generate_auto_map_unknown_interface(self):
        """Test that unknown interfaces raise an error."""
        with self.assertRaises(ChipFlowError) as ctx:
            _generate_auto_map("unknown.interface.Type", "prefix", "in")
        self.assertIn("No auto-mapping available", str(ctx.exception))

    def test_port_with_auto_map(self):
        """Test Port configuration without explicit map."""
        port = Port(
            interface='amaranth_soc.wishbone.Signature',
            prefix='wb',
        )
        self.assertIsNone(port.map)
        self.assertEqual(port.prefix, 'wb')

    def test_port_with_explicit_map_and_prefix(self):
        """Test Port configuration with both map and prefix (map takes precedence)."""
        port = Port(
            interface='amaranth.lib.wiring.Out(1)',
            map='o_custom_signal',
            prefix='ignored',
        )
        self.assertEqual(port.map, 'o_custom_signal')
        self.assertEqual(port.prefix, 'ignored')

    def test_config_with_auto_mapped_ports(self):
        """Test ExternalWrapConfig with auto-mapped ports."""
        config = ExternalWrapConfig(
            name="AutoMapTest",
            files=Files(path=Path("/tmp")),
            ports={
                "bus": Port(
                    interface="amaranth_soc.wishbone.Signature",
                    prefix="wb",
                    params={"addr_width": 4, "data_width": 32, "granularity": 8}
                )
            },
            pins={
                "irq": Port(
                    interface="amaranth.lib.wiring.Out(1)",
                    prefix="irq"
                )
            },
            clocks={"sys": "clk"},
            resets={"sys": "rst_n"},
        )
        self.assertEqual(config.name, "AutoMapTest")
        self.assertIsNone(config.ports["bus"].map)
        self.assertEqual(config.ports["bus"].prefix, "wb")

    def test_load_toml_with_auto_map(self):
        """Test loading TOML with auto-mapped port."""
        toml_content = """
name = 'AutoMapTomlTest'

[files]
path = '/tmp'

[clocks]
sys = 'clk'

[resets]
sys = 'rst_n'

[ports.bus]
interface = 'amaranth_soc.wishbone.Signature'
prefix = 'wb'
direction = 'in'

[ports.bus.params]
addr_width = 4
data_width = 32
granularity = 8

[pins.irq]
interface = 'amaranth.lib.wiring.Out(1)'
prefix = 'irq'
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.toml', delete=False) as f:
            f.write(toml_content)
            toml_path = Path(f.name)

        try:
            import tomli
            with open(toml_path, 'rb') as f:
                raw = tomli.load(f)
            config = ExternalWrapConfig.model_validate(raw)
            self.assertEqual(config.name, "AutoMapTomlTest")
            self.assertIsNone(config.ports["bus"].map)
            self.assertEqual(config.ports["bus"].prefix, "wb")
            self.assertIsNone(config.pins["irq"].map)
            self.assertEqual(config.pins["irq"].prefix, "irq")
        finally:
            toml_path.unlink()


if __name__ == "__main__":
    unittest.main()
