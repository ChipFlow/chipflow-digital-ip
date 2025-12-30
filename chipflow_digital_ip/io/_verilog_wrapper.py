"""Verilog wrapper for external Verilog/SystemVerilog/SpinalHDL modules.

This module provides a TOML-based configuration system for wrapping external Verilog
modules as Amaranth wiring.Component classes. It supports:

- Automatic Signature generation from TOML port definitions
- SpinalHDL code generation
- SystemVerilog to Verilog conversion via sv2v
- Clock and reset signal mapping
- Port and pin interface mapping to Verilog signals
"""

import os
import re
import shutil
import subprocess
from enum import StrEnum, auto
from importlib import import_module
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Self

import tomli
from pydantic import BaseModel, JsonValue, ValidationError, model_validator

from amaranth import ClockSignal, Instance, Module, ResetSignal
from amaranth.lib import wiring
from amaranth.lib.wiring import In, Out

from chipflow import ChipFlowError


__all__ = [
    "VerilogWrapper",
    "load_wrapper_from_toml",
    "_generate_auto_map",
    "_INTERFACE_REGISTRY",
]


class Files(BaseModel):
    """Specifies the source location for Verilog files."""

    module: Optional[str] = None
    path: Optional[Path] = None

    @model_validator(mode="after")
    def verify_module_or_path(self) -> Self:
        if (self.module and self.path) or (not self.module and not self.path):
            raise ValueError("You must set exactly one of `module` or `path`.")
        return self

    def get_source_path(self) -> Path:
        """Get the resolved source path."""
        if self.path:
            return self.path
        if self.module:
            try:
                mod = import_module(self.module)
                if hasattr(mod, "data_location"):
                    return Path(mod.data_location)
                elif hasattr(mod, "__path__"):
                    return Path(mod.__path__[0])
                else:
                    return Path(mod.__file__).parent
            except ImportError as e:
                raise ChipFlowError(f"Could not import module '{self.module}': {e}")
        raise ChipFlowError("No source path available")


class GenerateSpinalHDL(BaseModel):
    """Configuration for SpinalHDL code generation."""

    scala_class: str
    options: List[str] = []

    def generate(
        self, source_path: Path, dest_path: Path, name: str, parameters: Dict[str, JsonValue]
    ) -> List[str]:
        """Generate Verilog from SpinalHDL.

        Args:
            source_path: Path to SpinalHDL project
            dest_path: Output directory for generated Verilog
            name: Output file name (without extension)
            parameters: Template parameters for options

        Returns:
            List of generated Verilog file names
        """
        gen_args = [o.format(**parameters) for o in self.options]
        path = source_path / "ext" / "SpinalHDL"
        args = " ".join(
            gen_args + [f"--netlist-directory={dest_path.absolute()}", f"--netlist-name={name}"]
        )
        cmd = (
            f'cd {path} && sbt -J--enable-native-access=ALL-UNNAMED -v '
            f'"lib/runMain {self.scala_class} {args}"'
        )
        os.environ["GRADLE_OPTS"] = "--enable-native-access=ALL-UNNAMED"

        if os.system(cmd) != 0:
            raise ChipFlowError(f"Failed to run SpinalHDL generation: {cmd}")

        return [f"{name}.v"]


class GenerateSV2V(BaseModel):
    """Configuration for SystemVerilog to Verilog conversion using sv2v."""

    include_dirs: List[str] = []
    defines: Dict[str, str] = {}
    top_module: Optional[str] = None

    def generate(
        self, source_path: Path, dest_path: Path, name: str, parameters: Dict[str, JsonValue]
    ) -> List[Path]:
        """Convert SystemVerilog files to Verilog using sv2v.

        Args:
            source_path: Path containing SystemVerilog files
            dest_path: Output directory for converted Verilog
            name: Output file name (without extension)
            parameters: Template parameters (unused for sv2v)

        Returns:
            List of generated Verilog file paths
        """
        # Check if sv2v is available
        if shutil.which("sv2v") is None:
            raise ChipFlowError(
                "sv2v is not installed or not in PATH. "
                "Install from: https://github.com/zachjs/sv2v"
            )

        # Collect all SystemVerilog files
        sv_files = list(source_path.glob("**/*.sv"))
        if not sv_files:
            raise ChipFlowError(f"No SystemVerilog files found in {source_path}")

        # Build sv2v command
        cmd = ["sv2v"]

        # Add include directories
        for inc_dir in self.include_dirs:
            inc_path = source_path / inc_dir
            if inc_path.exists():
                cmd.extend(["-I", str(inc_path)])

        # Add defines
        for define_name, define_value in self.defines.items():
            if define_value:
                cmd.append(f"-D{define_name}={define_value}")
            else:
                cmd.append(f"-D{define_name}")

        # Add top module if specified
        if self.top_module:
            cmd.extend(["--top", self.top_module])

        # Add all SV files
        cmd.extend(str(f) for f in sv_files)

        # Output file
        output_file = dest_path / f"{name}.v"
        cmd.extend(["-w", str(output_file)])

        # Run sv2v
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True,
            )
        except subprocess.CalledProcessError as e:
            raise ChipFlowError(
                f"sv2v conversion failed:\nCommand: {' '.join(cmd)}\n"
                f"Stderr: {e.stderr}\nStdout: {e.stdout}"
            )

        if not output_file.exists():
            raise ChipFlowError(f"sv2v did not produce output file: {output_file}")

        return [output_file]


class Generators(StrEnum):
    """Supported code generators."""

    SPINALHDL = auto()
    VERILOG = auto()
    SYSTEMVERILOG = auto()


class Generate(BaseModel):
    """Code generation configuration."""

    parameters: Optional[Dict[str, JsonValue]] = None
    generator: Generators
    spinalhdl: Optional[GenerateSpinalHDL] = None
    sv2v: Optional[GenerateSV2V] = None


class Port(BaseModel):
    """Port interface mapping configuration."""

    interface: str  # Interface type (e.g., 'amaranth_soc.wishbone.Signature')
    params: Optional[Dict[str, JsonValue]] = None
    vars: Optional[Dict[str, Literal["int"]]] = None
    map: Optional[str | Dict[str, Dict[str, str] | str]] = None  # Auto-generated if not provided
    prefix: Optional[str] = None  # Prefix for auto-generated signal names
    direction: Optional[Literal["in", "out"]] = None  # Explicit direction override


class DriverConfig(BaseModel):
    """Software driver configuration for SoftwareDriverSignature."""

    regs_struct: Optional[str] = None
    c_files: List[str] = []
    h_files: List[str] = []


class ExternalWrapConfig(BaseModel):
    """Complete configuration for wrapping an external Verilog module."""

    name: str
    files: Files
    generate: Optional[Generate] = None
    clocks: Dict[str, str] = {}
    resets: Dict[str, str] = {}
    ports: Dict[str, Port] = {}
    pins: Dict[str, Port] = {}
    driver: Optional[DriverConfig] = None


def _resolve_interface_type(interface_str: str) -> type | tuple:
    """Resolve an interface type string to an actual class.

    Args:
        interface_str: Dotted path to interface class (e.g., 'amaranth_soc.wishbone.Interface')

    Returns:
        The resolved interface class, or a tuple of (direction, width) for simple signals
    """
    # Handle simple Out/In expressions like "amaranth.lib.wiring.Out(1)"
    out_match = re.match(r"amaranth\.lib\.wiring\.(Out|In)\((\d+)\)", interface_str)
    if out_match:
        direction, width = out_match.groups()
        return (direction, int(width))

    # Import the module and get the class
    parts = interface_str.rsplit(".", 1)
    if len(parts) == 2:
        module_path, class_name = parts
        try:
            mod = import_module(module_path)
            return getattr(mod, class_name)
        except (ImportError, AttributeError) as e:
            raise ChipFlowError(f"Could not resolve interface '{interface_str}': {e}")

    raise ChipFlowError(f"Invalid interface specification: '{interface_str}'")


def _parse_signal_direction(signal_name: str) -> str:
    """Determine signal direction from Verilog naming convention.

    Args:
        signal_name: Verilog signal name (e.g., 'i_clk', 'o_data')

    Returns:
        'i' for input, 'o' for output
    """
    if signal_name.startswith("i_"):
        return "i"
    elif signal_name.startswith("o_"):
        return "o"
    else:
        # Default to input for unknown
        return "i"


def _flatten_port_map(
    port_map: str | Dict[str, Dict[str, str] | str],
) -> Dict[str, str]:
    """Flatten a nested port map into a flat dictionary.

    Args:
        port_map: Port mapping (simple string or nested dict)

    Returns:
        Flat dictionary mapping Amaranth signal paths to Verilog signal names
    """
    if isinstance(port_map, str):
        return {"": port_map}

    result = {}
    for key, value in port_map.items():
        if isinstance(value, str):
            result[key] = value
        elif isinstance(value, dict):
            for subkey, subvalue in value.items():
                result[f"{key}.{subkey}"] = subvalue

    return result


def _get_nested_attr(obj: Any, path: str) -> Any:
    """Get a nested attribute using dot notation."""
    if not path:
        return obj
    for part in path.split("."):
        obj = getattr(obj, part)
    return obj


# =============================================================================
# Interface Auto-Mapping Registry
# =============================================================================
# Defines signal mappings for well-known interfaces. Each entry maps
# signal paths to (direction, suffix) tuples where:
# - direction: 'i' for input, 'o' for output
# - suffix: the Verilog signal suffix to use after the prefix

# Wishbone B4 bus interface signals
_WISHBONE_SIGNALS: Dict[str, tuple[str, str]] = {
    "cyc": ("i", "cyc"),
    "stb": ("i", "stb"),
    "we": ("i", "we"),
    "sel": ("i", "sel"),
    "adr": ("i", "adr"),
    "dat_w": ("i", "dat"),  # Write data goes into the peripheral
    "dat_r": ("o", "dat"),  # Read data comes out of the peripheral
    "ack": ("o", "ack"),
    # Optional Wishbone signals
    "err": ("o", "err"),
    "rty": ("o", "rty"),
    "stall": ("o", "stall"),
    "lock": ("i", "lock"),
    "cti": ("i", "cti"),
    "bte": ("i", "bte"),
}

# CSR bus interface signals
_CSR_SIGNALS: Dict[str, tuple[str, str]] = {
    "addr": ("i", "addr"),
    "r_data": ("o", "rdata"),
    "r_stb": ("i", "rstb"),
    "w_data": ("i", "wdata"),
    "w_stb": ("i", "wstb"),
}

# GPIO interface signals (directly on signature.gpio member)
_GPIO_SIGNALS: Dict[str, tuple[str, str]] = {
    "gpio.i": ("i", "i"),
    "gpio.o": ("o", "o"),
    "gpio.oe": ("o", "oe"),
}

# UART interface signals
_UART_SIGNALS: Dict[str, tuple[str, str]] = {
    "tx.o": ("o", "tx"),
    "rx.i": ("i", "rx"),
}

# I2C interface signals (open-drain, active-low)
_I2C_SIGNALS: Dict[str, tuple[str, str]] = {
    "sda.i": ("i", "sda"),
    "sda.oe": ("o", "sda_oe"),
    "scl.i": ("i", "scl"),
    "scl.oe": ("o", "scl_oe"),
}

# SPI interface signals
_SPI_SIGNALS: Dict[str, tuple[str, str]] = {
    "sck.o": ("o", "sck"),
    "copi.o": ("o", "copi"),  # MOSI
    "cipo.i": ("i", "cipo"),  # MISO
    "csn.o": ("o", "csn"),
}

# QSPI Flash interface signals
_QSPI_SIGNALS: Dict[str, tuple[str, str]] = {
    "clk.o": ("o", "clk"),
    "csn.o": ("o", "csn"),
    "d.i": ("i", "d"),
    "d.o": ("o", "d"),
    "d.oe": ("o", "d_oe"),
}

# Bidirectional IO signals (generic)
_BIDIR_IO_SIGNALS: Dict[str, tuple[str, str]] = {
    "i": ("i", ""),
    "o": ("o", ""),
    "oe": ("o", "oe"),
}

# Output IO signals (generic)
_OUTPUT_IO_SIGNALS: Dict[str, tuple[str, str]] = {
    "o": ("o", ""),
}

# Registry mapping interface type patterns to their signal definitions
_INTERFACE_REGISTRY: Dict[str, Dict[str, tuple[str, str]]] = {
    "amaranth_soc.wishbone.Signature": _WISHBONE_SIGNALS,
    "amaranth_soc.csr.Signature": _CSR_SIGNALS,
    "chipflow.platform.GPIOSignature": _GPIO_SIGNALS,
    "chipflow.platform.UARTSignature": _UART_SIGNALS,
    "chipflow.platform.I2CSignature": _I2C_SIGNALS,
    "chipflow.platform.SPISignature": _SPI_SIGNALS,
    "chipflow.platform.QSPIFlashSignature": _QSPI_SIGNALS,
    "chipflow.platform.BidirIOSignature": _BIDIR_IO_SIGNALS,
    "chipflow.platform.OutputIOSignature": _OUTPUT_IO_SIGNALS,
}


def _generate_auto_map(
    interface_str: str, prefix: str, port_direction: str = "in"
) -> Dict[str, str]:
    """Generate automatic port mapping for a well-known interface.

    Args:
        interface_str: Interface type string (e.g., 'amaranth_soc.wishbone.Signature')
        prefix: Prefix for signal names (e.g., 'wb' -> 'i_wb_cyc', 'o_wb_ack')
        port_direction: Direction of the port ('in' or 'out'), affects signal directions

    Returns:
        Dictionary mapping interface signal paths to Verilog signal names

    Raises:
        ChipFlowError: If interface is not in the registry
    """
    # Handle simple Out/In expressions like "amaranth.lib.wiring.Out(1)"
    out_match = re.match(r"amaranth\.lib\.wiring\.(Out|In)\((\d+)\)", interface_str)
    if out_match:
        direction, _width = out_match.groups()
        # For simple signals, the direction prefix depends on the interface direction
        if direction == "Out":
            return {"": f"o_{prefix}"}
        else:
            return {"": f"i_{prefix}"}

    # Look up in registry
    if interface_str not in _INTERFACE_REGISTRY:
        raise ChipFlowError(
            f"No auto-mapping available for interface '{interface_str}'. "
            f"Please provide an explicit 'map' in the TOML configuration. "
            f"Known interfaces: {', '.join(_INTERFACE_REGISTRY.keys())}"
        )

    signal_defs = _INTERFACE_REGISTRY[interface_str]
    result = {}

    for signal_path, (sig_direction, suffix) in signal_defs.items():
        # For ports with direction="out" (from Amaranth's perspective),
        # we flip the signal directions because we're providing signals TO the interface
        if port_direction == "out":
            actual_dir = "o" if sig_direction == "i" else "i"
        else:
            actual_dir = sig_direction

        # Build the Verilog signal name
        if suffix:
            verilog_name = f"{actual_dir}_{prefix}_{suffix}"
        else:
            verilog_name = f"{actual_dir}_{prefix}"

        result[signal_path] = verilog_name

    return result


def _infer_prefix_from_port_name(port_name: str, interface_str: str) -> str:
    """Infer a reasonable prefix from the port name and interface type.

    Args:
        port_name: Name of the port (e.g., 'bus', 'uart', 'i2c_pins')
        interface_str: Interface type string

    Returns:
        Suggested prefix for signal names
    """
    # Use the port name directly as the prefix
    # But apply some common transformations
    name = port_name.lower()

    # Remove common suffixes
    for suffix in ("_pins", "_bus", "_port", "_interface"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
            break

    # Map some interface types to common prefixes if port name is generic
    if name in ("bus", "port"):
        if "wishbone" in interface_str.lower():
            return "wb"
        elif "csr" in interface_str.lower():
            return "csr"

    return name


class VerilogWrapper(wiring.Component):
    """Dynamic Amaranth Component that wraps an external Verilog module.

    This component is generated from TOML configuration and creates the appropriate
    Signature and elaborate() implementation to instantiate the Verilog module.

    When a driver configuration is provided, the component uses SoftwareDriverSignature
    to enable automatic driver generation and register struct creation.
    """

    def __init__(self, config: ExternalWrapConfig, verilog_files: List[Path] | None = None):
        """Initialize the Verilog wrapper.

        Args:
            config: Parsed TOML configuration
            verilog_files: List of Verilog file paths to include
        """
        self._config = config
        self._verilog_files = verilog_files or []
        self._port_mappings: Dict[str, Dict[str, str]] = {}

        # Build signature from ports and pins
        signature_members = {}

        # Process ports (bus interfaces like Wishbone) - typically direction="in"
        for port_name, port_config in config.ports.items():
            default_dir = "in"
            sig_member = self._create_signature_member(port_config, config, default_direction=default_dir)
            signature_members[port_name] = sig_member
            self._port_mappings[port_name] = self._get_port_mapping(
                port_name, port_config, port_config.direction or default_dir
            )

        # Process pins (I/O interfaces to pads) - typically direction="out"
        for pin_name, pin_config in config.pins.items():
            default_dir = "out"
            sig_member = self._create_signature_member(pin_config, config, default_direction=default_dir)
            signature_members[pin_name] = sig_member
            self._port_mappings[pin_name] = self._get_port_mapping(
                pin_name, pin_config, pin_config.direction or default_dir
            )

        # Use SoftwareDriverSignature if driver config is provided
        if config.driver:
            try:
                from chipflow.platform import SoftwareDriverSignature

                super().__init__(
                    SoftwareDriverSignature(
                        members=signature_members,
                        component=self,
                        regs_struct=config.driver.regs_struct,
                        c_files=config.driver.c_files,
                        h_files=config.driver.h_files,
                    )
                )
            except ImportError:
                # Fallback if chipflow.platform not available
                super().__init__(signature_members)
        else:
            super().__init__(signature_members)

    def _get_port_mapping(
        self, port_name: str, port_config: Port, direction: str
    ) -> Dict[str, str]:
        """Get port mapping, auto-generating if not explicitly provided.

        Args:
            port_name: Name of the port
            port_config: Port configuration from TOML
            direction: Direction of the port ('in' or 'out')

        Returns:
            Flattened port mapping dictionary
        """
        if port_config.map is not None:
            # Explicit mapping provided
            return _flatten_port_map(port_config.map)

        # Auto-generate mapping
        prefix = port_config.prefix
        if prefix is None:
            prefix = _infer_prefix_from_port_name(port_name, port_config.interface)

        return _generate_auto_map(port_config.interface, prefix, direction)

    def _create_signature_member(
        self, port_config: Port, config: ExternalWrapConfig, default_direction: str = "in"
    ) -> In | Out:
        """Create a signature member from port configuration.

        Args:
            port_config: Port configuration from TOML
            config: Full wrapper configuration
            default_direction: Default direction if not specified ('in' or 'out')

        Returns:
            In or Out wrapped signature member
        """
        interface_info = _resolve_interface_type(port_config.interface)

        if isinstance(interface_info, tuple):
            # Simple Out/In(width) - direction already specified in interface string
            direction, width = interface_info
            if direction == "Out":
                return Out(width)
            else:
                return In(width)

        # Complex interface class - instantiate with params
        params = port_config.params or {}
        # Resolve parameter references from generate.parameters
        resolved_params = {}
        for k, v in params.items():
            if isinstance(v, str) and v.startswith("{") and v.endswith("}"):
                param_name = v[1:-1]
                if config.generate and config.generate.parameters:
                    resolved_params[k] = config.generate.parameters.get(param_name, v)
                else:
                    resolved_params[k] = v
            else:
                resolved_params[k] = v

        try:
            # Try to instantiate the interface/signature
            if hasattr(interface_info, "Signature"):
                sig = interface_info.Signature(**resolved_params)
            else:
                sig = interface_info(**resolved_params)

            # Determine direction:
            # 1. Explicit direction in TOML takes precedence
            # 2. Otherwise use default_direction (ports="in", pins="out")
            if port_config.direction:
                direction = port_config.direction
            else:
                direction = default_direction

            if direction == "in":
                return In(sig)
            else:
                return Out(sig)
        except Exception as e:
            raise ChipFlowError(
                f"Could not create interface '{port_config.interface}' "
                f"with params {resolved_params}: {e}"
            )

    def elaborate(self, platform):
        """Generate the Amaranth module with Verilog instance.

        Creates an Instance() of the wrapped Verilog module with all
        port mappings configured from the TOML specification.
        """
        m = Module()

        # Build Instance port arguments
        instance_ports = {}

        # Add clock signals
        for clock_name, verilog_signal in self._config.clocks.items():
            if clock_name == "sys":
                instance_ports[f"i_{verilog_signal}"] = ClockSignal()
            else:
                instance_ports[f"i_{verilog_signal}"] = ClockSignal(clock_name)

        # Add reset signals (active-low is common convention)
        for reset_name, verilog_signal in self._config.resets.items():
            if reset_name == "sys":
                instance_ports[f"i_{verilog_signal}"] = ~ResetSignal()
            else:
                instance_ports[f"i_{verilog_signal}"] = ~ResetSignal(reset_name)

        # Add port mappings
        for port_name, port_map in self._port_mappings.items():
            amaranth_port = getattr(self, port_name)

            for signal_path, verilog_signal in port_map.items():
                # Handle variable substitution in signal names (e.g., {n} for arrays)
                if "{" in verilog_signal:
                    # For now, expand with index 0. Future: support multiple instances
                    verilog_signal = verilog_signal.format(n=0)

                # Navigate to the signal in the Amaranth interface
                amaranth_signal = _get_nested_attr(amaranth_port, signal_path)

                # The Verilog signal name already includes i_/o_ prefix
                # Use it directly for the Instance parameter
                instance_ports[verilog_signal] = amaranth_signal

        # Create the Verilog instance
        m.submodules.wrapped = Instance(self._config.name, **instance_ports)

        # Add Verilog files to the platform
        if platform is not None:
            for verilog_file in self._verilog_files:
                if verilog_file.exists():
                    with open(verilog_file, "r") as f:
                        platform.add_file(verilog_file.name, f.read())

        return m


def load_wrapper_from_toml(
    toml_path: Path | str, generate_dest: Path | None = None
) -> VerilogWrapper:
    """Load a VerilogWrapper from a TOML configuration file.

    Args:
        toml_path: Path to the TOML configuration file
        generate_dest: Destination directory for generated Verilog (if using SpinalHDL)

    Returns:
        Configured VerilogWrapper component

    Raises:
        ChipFlowError: If configuration is invalid or generation fails
    """
    toml_path = Path(toml_path)

    with open(toml_path, "rb") as f:
        raw_config = tomli.load(f)

    try:
        config = ExternalWrapConfig.model_validate(raw_config)
    except ValidationError as e:
        error_messages = []
        for error in e.errors():
            location = ".".join(str(loc) for loc in error["loc"])
            message = error["msg"]
            error_messages.append(f"Error at '{location}': {message}")
        error_str = "\n".join(error_messages)
        raise ChipFlowError(f"Validation error in {toml_path}:\n{error_str}")

    verilog_files = []

    # Get source path
    source_path = config.files.get_source_path()

    # Handle code generation if configured
    if config.generate:
        if generate_dest is None:
            generate_dest = Path("./build/verilog")
        generate_dest.mkdir(parents=True, exist_ok=True)

        parameters = config.generate.parameters or {}

        if config.generate.generator == Generators.SPINALHDL:
            if config.generate.spinalhdl is None:
                raise ChipFlowError(
                    "SpinalHDL generator selected but no spinalhdl config provided"
                )

            generated = config.generate.spinalhdl.generate(
                source_path, generate_dest, config.name, parameters
            )
            verilog_files.extend(generate_dest / f for f in generated)

        elif config.generate.generator == Generators.SYSTEMVERILOG:
            # Convert SystemVerilog to Verilog using sv2v
            sv2v_config = config.generate.sv2v or GenerateSV2V()
            generated = sv2v_config.generate(
                source_path, generate_dest, config.name, parameters
            )
            verilog_files.extend(generated)

        elif config.generate.generator == Generators.VERILOG:
            # Just use existing Verilog files from source
            for v_file in source_path.glob("**/*.v"):
                verilog_files.append(v_file)
    else:
        # No generation - look for Verilog and SystemVerilog files in source
        for v_file in source_path.glob("**/*.v"):
            verilog_files.append(v_file)
        for sv_file in source_path.glob("**/*.sv"):
            verilog_files.append(sv_file)

    return VerilogWrapper(config, verilog_files)


# CLI entry point for testing
if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python -m chipflow_digital_ip.io._verilog_wrapper <toml_file>")
        sys.exit(1)

    try:
        wrapper = load_wrapper_from_toml(sys.argv[1])
        print(f"Successfully loaded wrapper: {wrapper._config.name}")
        print(f"Signature: {wrapper.signature}")
    except ChipFlowError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
