"""Verilog wrapper for external Verilog/SystemVerilog/SpinalHDL modules.

This module provides a TOML-based configuration system for wrapping external Verilog
modules as Amaranth wiring.Component classes. It supports:

- Automatic Signature generation from TOML port definitions
- SpinalHDL code generation
- SystemVerilog to Verilog conversion via sv2v
- SystemVerilog to Verilog conversion via yosys-slang
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


__all__ = ["VerilogWrapper", "load_wrapper_from_toml"]


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


class GenerateYosysSlang(BaseModel):
    """Configuration for SystemVerilog to Verilog conversion using yosys-slang.

    Uses the yosys-slang plugin to parse SystemVerilog and output plain Verilog
    that can be used with Amaranth's Instance() mechanism.
    """

    include_dirs: List[str] = []
    defines: Dict[str, str] = {}
    top_module: Optional[str] = None

    def generate(
        self, source_path: Path, dest_path: Path, name: str, parameters: Dict[str, JsonValue]
    ) -> List[Path]:
        """Convert SystemVerilog files to Verilog using yosys-slang.

        Args:
            source_path: Path containing SystemVerilog files
            dest_path: Output directory for Verilog output
            name: Output file name (without extension)
            parameters: Template parameters (unused for yosys-slang)

        Returns:
            List of generated Verilog file paths
        """
        # Check if yosys is available
        if shutil.which("yosys") is None:
            raise ChipFlowError(
                "yosys is not installed or not in PATH. "
                "Install from: https://github.com/YosysHQ/yosys"
            )

        # Collect all SystemVerilog files
        sv_files = list(source_path.glob("**/*.sv"))
        v_files = list(source_path.glob("**/*.v"))
        all_files = sv_files + v_files
        if not all_files:
            raise ChipFlowError(f"No Verilog/SystemVerilog files found in {source_path}")

        # Build yosys script
        script_lines = []

        # Build read_slang command
        read_cmd_parts = ["read_slang"]

        # Add defines
        for define_name, define_value in self.defines.items():
            if define_value:
                read_cmd_parts.append(f"-D{define_name}={define_value}")
            else:
                read_cmd_parts.append(f"-D{define_name}")

        # Add include directories
        for inc_dir in self.include_dirs:
            inc_path = source_path / inc_dir
            if inc_path.exists():
                read_cmd_parts.append(f"-I{inc_path}")

        # Add top module if specified
        if self.top_module:
            read_cmd_parts.append(f"--top {self.top_module}")

        # Add all source files
        for f in all_files:
            read_cmd_parts.append(str(f))

        script_lines.append(" ".join(read_cmd_parts))

        # Hierarchy check only - preserve RTL structure
        if self.top_module:
            script_lines.append(f"hierarchy -check -top {self.top_module}")
        else:
            script_lines.append("hierarchy -check")

        # Output Verilog (compatible with Amaranth's Instance mechanism)
        output_file = dest_path / f"{name}.v"
        script_lines.append(f"write_verilog -noattr {output_file}")

        script = "\n".join(script_lines)

        # Run yosys with slang plugin
        try:
            result = subprocess.run(
                ["yosys", "-m", "slang", "-p", script],
                capture_output=True,
                text=True,
                check=True,
            )
        except subprocess.CalledProcessError as e:
            raise ChipFlowError(
                f"yosys-slang conversion failed:\nScript:\n{script}\n"
                f"Stderr: {e.stderr}\nStdout: {e.stdout}"
            )

        if not output_file.exists():
            raise ChipFlowError(f"yosys-slang did not produce output file: {output_file}")

        return [output_file]


class Generators(StrEnum):
    """Supported code generators."""

    SPINALHDL = auto()
    VERILOG = auto()
    SYSTEMVERILOG = auto()
    YOSYS_SLANG = auto()


class Generate(BaseModel):
    """Code generation configuration."""

    parameters: Optional[Dict[str, JsonValue]] = None
    generator: Generators
    spinalhdl: Optional[GenerateSpinalHDL] = None
    sv2v: Optional[GenerateSV2V] = None
    yosys_slang: Optional[GenerateYosysSlang] = None


class Port(BaseModel):
    """Port interface mapping configuration."""

    interface: str  # Interface type (e.g., 'amaranth_soc.wishbone.Interface')
    params: Optional[Dict[str, JsonValue]] = None
    vars: Optional[Dict[str, Literal["int"]]] = None
    map: str | Dict[str, Dict[str, str] | str]


class ExternalWrapConfig(BaseModel):
    """Complete configuration for wrapping an external Verilog module."""

    name: str
    files: Files
    generate: Optional[Generate] = None
    clocks: Dict[str, str] = {}
    resets: Dict[str, str] = {}
    ports: Dict[str, Port] = {}
    pins: Dict[str, Port] = {}
    drivers: Optional[Dict[str, Any]] = None


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
    """Get a nested attribute using dot notation.

    Args:
        obj: The root object
        path: Dot-separated attribute path (e.g., 'gpio.o')

    Returns:
        The nested attribute value

    Raises:
        ChipFlowError: If the attribute path doesn't exist
    """
    if not path:
        return obj
    current = obj
    parts = path.split(".")
    for i, part in enumerate(parts):
        try:
            current = getattr(current, part)
        except AttributeError:
            traversed = ".".join(parts[:i]) if i > 0 else "(root)"
            raise ChipFlowError(
                f"Invalid signal path '{path}': attribute '{part}' not found "
                f"(traversed: {traversed}, available: {dir(current)})"
            )
    return current


class VerilogWrapper(wiring.Component):
    """Dynamic Amaranth Component that wraps an external Verilog module.

    This component is generated from TOML configuration and creates the appropriate
    Signature and elaborate() implementation to instantiate the Verilog module.
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

        # Process ports (bus interfaces like Wishbone)
        for port_name, port_config in config.ports.items():
            sig_member = self._create_signature_member(port_config, config)
            signature_members[port_name] = sig_member
            self._port_mappings[port_name] = _flatten_port_map(port_config.map)

        # Process pins (I/O interfaces)
        for pin_name, pin_config in config.pins.items():
            sig_member = self._create_signature_member(pin_config, config)
            signature_members[pin_name] = sig_member
            self._port_mappings[pin_name] = _flatten_port_map(pin_config.map)

        super().__init__(signature_members)

    def _create_signature_member(
        self, port_config: Port, config: ExternalWrapConfig
    ) -> In | Out:
        """Create a signature member from port configuration."""
        interface_info = _resolve_interface_type(port_config.interface)

        if isinstance(interface_info, tuple):
            # Simple Out/In(width)
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
            # Determine direction based on signal mapping
            port_map = _flatten_port_map(port_config.map)
            first_signal = next(iter(port_map.values()), "")
            direction = _parse_signal_direction(first_signal)

            # Try to instantiate the interface
            # Handle different interface constructor patterns
            sig = None
            if hasattr(interface_info, "Signature"):
                sig = interface_info.Signature(**resolved_params)
            else:
                # Try keyword args first
                try:
                    sig = interface_info(**resolved_params)
                except TypeError:
                    # Some interfaces take positional args (e.g., GPIOSignature(width))
                    # Try passing the first param value as positional
                    if resolved_params:
                        first_value = next(iter(resolved_params.values()))
                        sig = interface_info(first_value)
                    else:
                        sig = interface_info()

            # Input signals to the Verilog module are outputs from Amaranth's perspective
            # (we provide them), and vice versa
            if direction == "i":
                return Out(sig)
            else:
                return In(sig)
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

        elif config.generate.generator == Generators.YOSYS_SLANG:
            # Convert SystemVerilog to RTLIL using yosys-slang
            yosys_slang_config = config.generate.yosys_slang or GenerateYosysSlang()
            generated = yosys_slang_config.generate(
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
