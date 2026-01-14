"""Verilog wrapper for external Verilog/SystemVerilog/SpinalHDL modules.

This module provides a TOML-based configuration system for wrapping external Verilog
modules as Amaranth wiring.Component classes. It supports:

- Automatic Signature generation from TOML port definitions
- SpinalHDL code generation
- SystemVerilog to Verilog conversion via sv2v or yosys-slang
- Clock and reset signal mapping
- Port and pin interface mapping to Verilog signals
"""

import logging
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

logger = logging.getLogger(__name__)


__all__ = [
    "VerilogWrapper",
    "load_wrapper_from_toml",
    "_generate_auto_map",
    "_infer_auto_map",
    "_parse_verilog_ports",
    "_INTERFACE_PATTERNS",
    "_INTERFACE_REGISTRY",  # Backwards compat alias
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


class GenerateYosysSlang(BaseModel):
    """Configuration for SystemVerilog to Verilog conversion using yosys-slang.

    This uses the yosys-slang plugin (https://github.com/povik/yosys-slang) to read
    SystemVerilog directly into Yosys, then outputs Verilog.

    For yowasp-yosys, slang is built-in (statically linked), so no plugin loading
    is needed. For native yosys, the slang plugin must be loaded with -m slang.
    """

    include_dirs: List[str] = []
    defines: Dict[str, str] = {}
    top_module: Optional[str] = None
    yosys_command: str = "yosys"  # Can be overridden

    def generate(
        self, source_path: Path, dest_path: Path, name: str, parameters: Dict[str, JsonValue]
    ) -> List[Path]:
        """Convert SystemVerilog files to Verilog using yosys-slang.

        Args:
            source_path: Path containing SystemVerilog files
            dest_path: Output directory for converted Verilog
            name: Output file name (without extension)
            parameters: Template parameters (unused)

        Returns:
            List of generated Verilog file paths
        """
        # Find yosys and determine if slang is built-in
        yosys_cmd, slang_builtin = self._find_yosys()

        # Collect all SystemVerilog files
        sv_files = list(source_path.glob("**/*.sv"))
        if not sv_files:
            raise ChipFlowError(f"No SystemVerilog files found in {source_path}")

        # Build yosys script
        output_file = dest_path / f"{name}.v"

        # Build read_slang arguments
        read_slang_args = []
        if self.top_module:
            read_slang_args.append(f"--top {self.top_module}")
        for inc_dir in self.include_dirs:
            inc_path = source_path / inc_dir
            if inc_path.exists():
                read_slang_args.append(f"-I{inc_path}")
        for define_name, define_value in self.defines.items():
            if define_value:
                read_slang_args.append(f"-D{define_name}={define_value}")
            else:
                read_slang_args.append(f"-D{define_name}")

        # Add source files
        read_slang_args.extend(str(f) for f in sv_files)

        yosys_script = f"""
read_slang {' '.join(read_slang_args)}
hierarchy -check {f'-top {self.top_module}' if self.top_module else ''}
proc
write_verilog -noattr {output_file}
"""

        # Build command - yowasp-yosys has slang built-in, native yosys needs plugin
        if slang_builtin:
            cmd = [yosys_cmd, "-p", yosys_script]
        else:
            cmd = [yosys_cmd, "-m", "slang", "-p", yosys_script]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True,
            )
        except subprocess.CalledProcessError as e:
            raise ChipFlowError(
                f"yosys-slang conversion failed:\nCommand: {' '.join(cmd)}\n"
                f"Stderr: {e.stderr}\nStdout: {e.stdout}"
            )
        except FileNotFoundError:
            raise ChipFlowError(
                f"yosys not found. Install yowasp-yosys (pip install yowasp-yosys) "
                f"or native yosys with slang plugin. Tried: {yosys_cmd}"
            )

        if not output_file.exists():
            raise ChipFlowError(f"yosys-slang did not produce output file: {output_file}")

        return [output_file]

    def _find_yosys(self) -> tuple[str, bool]:
        """Find yosys executable and determine if slang is built-in.

        Returns:
            Tuple of (command, slang_builtin) where slang_builtin is True for
            yowasp-yosys (slang statically linked) and False for native yosys
            (slang loaded as plugin).
        """
        # Check if custom command is set
        if self.yosys_command != "yosys":
            # Assume custom command needs plugin unless it's yowasp-yosys
            is_yowasp = "yowasp" in self.yosys_command.lower()
            return (self.yosys_command, is_yowasp)

        # Try yowasp-yosys first (Python package) - slang is built-in
        try:
            import yowasp_yosys  # noqa: F401
            return ("yowasp-yosys", True)
        except ImportError:
            pass

        # Try native yosys - slang must be loaded as plugin
        if shutil.which("yosys"):
            return ("yosys", False)

        raise ChipFlowError(
            "Neither yowasp-yosys nor native yosys found. "
            "Install yowasp-yosys: pip install yowasp-yosys, "
            "or install native yosys with slang plugin."
        )


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
# Interface Auto-Mapping from Verilog Signal Names
# =============================================================================
# Auto-mapping works by parsing the Verilog module to find its actual port names,
# then matching patterns to identify which signals correspond to interface members.
# This adapts to whatever naming convention the Verilog code uses.

# Pattern definitions for each interface type.
# Each pattern is a tuple of (regex_pattern, interface_member_path, expected_direction)
# The regex should match common naming conventions for that signal.

_WISHBONE_PATTERNS: List[tuple[str, str, str]] = [
    # Core Wishbone signals - match various naming styles
    (r"(?:^|_)(cyc)(?:_|$)", "cyc", "i"),       # wb_cyc, cyc_i, i_wb_cyc
    (r"(?:^|_)(stb)(?:_|$)", "stb", "i"),       # wb_stb, stb_i, i_wb_stb
    (r"(?:^|_)(we)(?:_|$)", "we", "i"),         # wb_we, we_i, i_wb_we
    (r"(?:^|_)(sel)(?:_|$)", "sel", "i"),       # wb_sel, sel_i, i_wb_sel
    (r"(?:^|_)(adr|addr)(?:_|$)", "adr", "i"),  # wb_adr, addr_i, i_wb_adr
    (r"(?:^|_)(ack)(?:_|$)", "ack", "o"),       # wb_ack, ack_o, o_wb_ack
    # Data signals - need to distinguish read vs write
    (r"(?:^|_)dat(?:a)?_?w(?:r(?:ite)?)?(?:_|$)", "dat_w", "i"),  # dat_w, data_wr, wdata
    (r"(?:^|_)w(?:r(?:ite)?)?_?dat(?:a)?(?:_|$)", "dat_w", "i"),  # wdat, write_data
    (r"(?:^|_)dat(?:a)?_?r(?:d|ead)?(?:_|$)", "dat_r", "o"),      # dat_r, data_rd, rdata
    (r"(?:^|_)r(?:d|ead)?_?dat(?:a)?(?:_|$)", "dat_r", "o"),      # rdat, read_data
    # Fallback for generic dat - use direction to disambiguate
    (r"(?:^|_)(dat|data)(?:_|$)", "dat_w", "i"),  # Input data = write
    (r"(?:^|_)(dat|data)(?:_|$)", "dat_r", "o"),  # Output data = read
    # Optional Wishbone signals
    (r"(?:^|_)(err)(?:_|$)", "err", "o"),
    (r"(?:^|_)(rty)(?:_|$)", "rty", "o"),
    (r"(?:^|_)(stall)(?:_|$)", "stall", "o"),
    (r"(?:^|_)(lock)(?:_|$)", "lock", "i"),
    (r"(?:^|_)(cti)(?:_|$)", "cti", "i"),
    (r"(?:^|_)(bte)(?:_|$)", "bte", "i"),
]

_CSR_PATTERNS: List[tuple[str, str, str]] = [
    (r"(?:^|_)(addr|adr)(?:_|$)", "addr", "i"),
    (r"(?:^|_)r(?:ead)?_?data(?:_|$)", "r_data", "o"),
    (r"(?:^|_)r(?:ead)?_?stb(?:_|$)", "r_stb", "i"),
    (r"(?:^|_)w(?:rite)?_?data(?:_|$)", "w_data", "i"),
    (r"(?:^|_)w(?:rite)?_?stb(?:_|$)", "w_stb", "i"),
]

_UART_PATTERNS: List[tuple[str, str, str]] = [
    (r"(?:^|_)(tx|txd)(?:_|$)", "tx.o", "o"),
    (r"(?:^|_)(rx|rxd)(?:_|$)", "rx.i", "i"),
]

_I2C_PATTERNS: List[tuple[str, str, str]] = [
    (r"(?:^|_)sda(?:_i|_in)?(?:_|$)", "sda.i", "i"),
    (r"(?:^|_)sda(?:_o|_out|_oe)(?:_|$)", "sda.oe", "o"),
    (r"(?:^|_)scl(?:_i|_in)?(?:_|$)", "scl.i", "i"),
    (r"(?:^|_)scl(?:_o|_out|_oe)(?:_|$)", "scl.oe", "o"),
]

_SPI_PATTERNS: List[tuple[str, str, str]] = [
    (r"(?:^|_)(sck|sclk|clk)(?:_|$)", "sck.o", "o"),
    (r"(?:^|_)(mosi|copi|sdo)(?:_|$)", "copi.o", "o"),
    (r"(?:^|_)(miso|cipo|sdi)(?:_|$)", "cipo.i", "i"),
    (r"(?:^|_)(cs|csn|ss|ssn)(?:_|$)", "csn.o", "o"),
]

_GPIO_PATTERNS: List[tuple[str, str, str]] = [
    (r"(?:^|_)gpio(?:_i|_in)(?:_|$)", "gpio.i", "i"),
    (r"(?:^|_)gpio(?:_o|_out)(?:_|$)", "gpio.o", "o"),
    (r"(?:^|_)gpio(?:_oe|_en)(?:_|$)", "gpio.oe", "o"),
]

# Registry mapping interface types to their pattern lists
_INTERFACE_PATTERNS: Dict[str, List[tuple[str, str, str]]] = {
    "amaranth_soc.wishbone.Signature": _WISHBONE_PATTERNS,
    "amaranth_soc.csr.Signature": _CSR_PATTERNS,
    "chipflow.platform.GPIOSignature": _GPIO_PATTERNS,
    "chipflow.platform.UARTSignature": _UART_PATTERNS,
    "chipflow.platform.I2CSignature": _I2C_PATTERNS,
    "chipflow.platform.SPISignature": _SPI_PATTERNS,
}

# For backwards compatibility
_INTERFACE_REGISTRY = _INTERFACE_PATTERNS


def _parse_verilog_ports(verilog_content: str, module_name: str) -> Dict[str, str]:
    """Parse Verilog/SystemVerilog to extract module port names and directions.

    Args:
        verilog_content: The Verilog source code
        module_name: Name of the module to parse

    Returns:
        Dictionary mapping port names to directions ('input', 'output', 'inout')
    """
    ports: Dict[str, str] = {}

    # Find the module definition
    # Match both Verilog and SystemVerilog module syntax
    module_pattern = rf"module\s+{re.escape(module_name)}\s*(?:#\s*\([^)]*\))?\s*\(([^;]*)\)\s*;"
    module_match = re.search(module_pattern, verilog_content, re.DOTALL | re.IGNORECASE)

    if not module_match:
        # Try ANSI-style port declarations
        ansi_pattern = rf"module\s+{re.escape(module_name)}\s*(?:#\s*\([^)]*\))?\s*\("
        ansi_match = re.search(ansi_pattern, verilog_content, re.IGNORECASE)
        if ansi_match:
            # Find matching parenthesis
            start = ansi_match.end()
            depth = 1
            end = start
            while depth > 0 and end < len(verilog_content):
                if verilog_content[end] == "(":
                    depth += 1
                elif verilog_content[end] == ")":
                    depth -= 1
                end += 1
            port_section = verilog_content[start : end - 1]
        else:
            return ports
    else:
        port_section = module_match.group(1)

    # Parse ANSI-style port declarations (input/output in port list)
    # Matches: input logic [31:0] signal_name
    ansi_port_pattern = r"(input|output|inout)\s+(?:logic|wire|reg)?\s*(?:\[[^\]]*\])?\s*(\w+)"
    for match in re.finditer(ansi_port_pattern, port_section, re.IGNORECASE):
        direction, name = match.groups()
        ports[name] = direction.lower()

    # Also look for non-ANSI declarations after the module header
    # The module_match already includes the trailing semicolon, so start from there
    module_body_start = module_match.end() if module_match else 0
    if module_body_start > 0:
        # Look for standalone input/output declarations
        body_pattern = r"^\s*(input|output|inout)\s+(?:logic|wire|reg)?\s*(?:\[[^\]]*\])?\s*(\w+)"
        for match in re.finditer(
            body_pattern, verilog_content[module_body_start:], re.MULTILINE | re.IGNORECASE
        ):
            direction, name = match.groups()
            if name not in ports:
                ports[name] = direction.lower()

    return ports


def _infer_signal_direction(signal_name: str) -> str:
    """Infer signal direction from common naming conventions.

    Args:
        signal_name: Verilog signal name

    Returns:
        'i' for input, 'o' for output, 'io' for unknown/bidirectional
    """
    name_lower = signal_name.lower()

    # Check prefixes
    if name_lower.startswith("i_") or name_lower.startswith("in_"):
        return "i"
    if name_lower.startswith("o_") or name_lower.startswith("out_"):
        return "o"

    # Check suffixes
    if name_lower.endswith("_i") or name_lower.endswith("_in"):
        return "i"
    if name_lower.endswith("_o") or name_lower.endswith("_out"):
        return "o"
    if name_lower.endswith("_oe") or name_lower.endswith("_en"):
        return "o"

    return "io"  # Unknown


def _infer_auto_map(
    interface_str: str,
    verilog_ports: Dict[str, str],
    port_direction: str = "in",
) -> Dict[str, str]:
    """Infer port mapping by matching Verilog signals to interface patterns.

    Args:
        interface_str: Interface type string (e.g., 'amaranth_soc.wishbone.Signature')
        verilog_ports: Dictionary of Verilog port names to their directions
        port_direction: Direction of the port ('in' or 'out')

    Returns:
        Dictionary mapping interface signal paths to matched Verilog signal names

    Raises:
        ChipFlowError: If interface is not in the registry or required signals not found
    """
    # Handle simple Out/In expressions
    out_match = re.match(r"amaranth\.lib\.wiring\.(Out|In)\((\d+)\)", interface_str)
    if out_match:
        # For simple signals, we can't auto-infer - need explicit mapping
        raise ChipFlowError(
            f"Cannot auto-infer mapping for simple signal '{interface_str}'. "
            "Please provide an explicit 'map' in the TOML configuration."
        )

    if interface_str not in _INTERFACE_PATTERNS:
        raise ChipFlowError(
            f"No auto-mapping patterns available for interface '{interface_str}'. "
            f"Please provide an explicit 'map' in the TOML configuration. "
            f"Known interfaces: {', '.join(_INTERFACE_PATTERNS.keys())}"
        )

    patterns = _INTERFACE_PATTERNS[interface_str]
    result: Dict[str, str] = {}
    used_ports: set[str] = set()

    for pattern, member_path, expected_dir in patterns:
        if member_path in result:
            continue  # Already matched

        for port_name, port_dir in verilog_ports.items():
            if port_name in used_ports:
                continue

            # Check if the port name matches the pattern
            if not re.search(pattern, port_name, re.IGNORECASE):
                continue

            # Infer direction from port name if not explicitly declared
            inferred_dir = _infer_signal_direction(port_name)
            actual_dir = "i" if port_dir == "input" else ("o" if port_dir == "output" else inferred_dir)

            # For bus interfaces (Wishbone, CSR), direction determines master/slave
            # and we flip signal directions accordingly. For pin interfaces (UART, I2C, etc.),
            # direction="out" is the normal case and signals shouldn't be flipped.
            is_bus_interface = interface_str in (
                "amaranth_soc.wishbone.Signature",
                "amaranth_soc.csr.Signature",
            )
            if is_bus_interface and port_direction == "out":
                check_dir = "o" if expected_dir == "i" else "i"
            else:
                check_dir = expected_dir

            # Match if directions align (or if we couldn't determine)
            if actual_dir == "io" or actual_dir == check_dir:
                result[member_path] = port_name
                used_ports.add(port_name)
                break

    return result


def _generate_auto_map(
    interface_str: str, prefix: str, port_direction: str = "in"
) -> Dict[str, str]:
    """Generate automatic port mapping for a well-known interface using prefix convention.

    This is a fallback when Verilog ports aren't available for inference.
    Generates signal names like i_wb_cyc, o_wb_ack based on the prefix.

    Args:
        interface_str: Interface type string
        prefix: Prefix for signal names (e.g., 'wb')
        port_direction: Direction of the port ('in' or 'out')

    Returns:
        Dictionary mapping interface signal paths to Verilog signal names
    """
    # Handle simple Out/In expressions
    out_match = re.match(r"amaranth\.lib\.wiring\.(Out|In)\((\d+)\)", interface_str)
    if out_match:
        direction, _width = out_match.groups()
        if direction == "Out":
            return {"": f"o_{prefix}"}
        else:
            return {"": f"i_{prefix}"}

    if interface_str not in _INTERFACE_PATTERNS:
        raise ChipFlowError(
            f"No auto-mapping available for interface '{interface_str}'. "
            f"Please provide an explicit 'map' in the TOML configuration."
        )

    # Build map from patterns - use the matched group as suffix
    patterns = _INTERFACE_PATTERNS[interface_str]
    result: Dict[str, str] = {}
    seen_members: set[str] = set()

    for pattern, member_path, expected_dir in patterns:
        if member_path in seen_members:
            continue
        seen_members.add(member_path)

        # Determine actual direction
        if port_direction == "out":
            actual_dir = "o" if expected_dir == "i" else "i"
        else:
            actual_dir = expected_dir

        # Extract a reasonable suffix from the member path
        suffix = member_path.replace(".", "_")

        result[member_path] = f"{actual_dir}_{prefix}_{suffix}"

    return result


class VerilogWrapper(wiring.Component):
    """Dynamic Amaranth Component that wraps an external Verilog module.

    This component is generated from TOML configuration and creates the appropriate
    Signature and elaborate() implementation to instantiate the Verilog module.

    When a driver configuration is provided, the component uses SoftwareDriverSignature
    to enable automatic driver generation and register struct creation.

    Auto-mapping works by parsing the Verilog files to find actual port names,
    then matching patterns to identify which signals correspond to interface members.
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

        # Parse Verilog to get port information for auto-mapping
        verilog_ports = self._parse_verilog_ports()

        # Build signature from ports and pins
        signature_members = {}

        # Process ports (bus interfaces like Wishbone) - typically direction="in"
        for port_name, port_config in config.ports.items():
            default_dir = "in"
            sig_member = self._create_signature_member(port_config, config, default_direction=default_dir)
            signature_members[port_name] = sig_member
            self._port_mappings[port_name] = self._get_port_mapping(
                port_name, port_config, port_config.direction or default_dir, verilog_ports
            )

        # Process pins (I/O interfaces to pads) - typically direction="out"
        for pin_name, pin_config in config.pins.items():
            default_dir = "out"
            sig_member = self._create_signature_member(pin_config, config, default_direction=default_dir)
            signature_members[pin_name] = sig_member
            self._port_mappings[pin_name] = self._get_port_mapping(
                pin_name, pin_config, pin_config.direction or default_dir, verilog_ports
            )

        # Validate signal bindings after port mappings are built
        self._validate_signal_bindings(verilog_ports)

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

    def _parse_verilog_ports(self) -> Dict[str, str]:
        """Parse all Verilog files to extract port information.

        Returns:
            Dictionary mapping port names to their directions
        """
        all_ports: Dict[str, str] = {}

        for verilog_file in self._verilog_files:
            if verilog_file.exists():
                try:
                    content = verilog_file.read_text()
                    ports = _parse_verilog_ports(content, self._config.name)
                    all_ports.update(ports)
                except Exception:
                    # If parsing fails, continue without those ports
                    pass

        return all_ports

    def _validate_signal_bindings(self, verilog_ports: Dict[str, str]) -> None:
        """Validate that configured signals exist in the Verilog module.

        Raises ChipFlowError for missing required signals (clocks/resets).
        Logs warnings for unmapped Verilog ports.
        """
        if not verilog_ports:
            logger.warning(
                f"[{self._config.name}] Could not parse Verilog ports - "
                "signal validation skipped"
            )
            return

        # Track which Verilog ports are mapped
        mapped_ports: set[str] = set()

        # Validate clock signals
        for clock_name, verilog_signal in self._config.clocks.items():
            expected_port = f"i_{verilog_signal}"
            mapped_ports.add(expected_port)
            if expected_port not in verilog_ports:
                raise ChipFlowError(
                    f"[{self._config.name}] Clock signal '{verilog_signal}' "
                    f"(expecting port '{expected_port}') not found in Verilog module. "
                    f"Available ports: {sorted(verilog_ports.keys())}"
                )

        # Validate reset signals
        for reset_name, verilog_signal in self._config.resets.items():
            expected_port = f"i_{verilog_signal}"
            mapped_ports.add(expected_port)
            if expected_port not in verilog_ports:
                raise ChipFlowError(
                    f"[{self._config.name}] Reset signal '{verilog_signal}' "
                    f"(expecting port '{expected_port}') not found in Verilog module. "
                    f"Available ports: {sorted(verilog_ports.keys())}"
                )

        # Collect all mapped port signals from the actual port mappings
        for port_name, port_map in self._port_mappings.items():
            mapped_ports.update(port_map.values())

        # Warn about unmapped Verilog ports (excluding clk/rst which are handled specially)
        unmapped = set(verilog_ports.keys()) - mapped_ports
        if unmapped:
            logger.warning(
                f"[{self._config.name}] Unmapped Verilog ports: {sorted(unmapped)}. "
                "These signals will not be connected."
            )

    def _get_port_mapping(
        self, port_name: str, port_config: Port, direction: str, verilog_ports: Dict[str, str]
    ) -> Dict[str, str]:
        """Get port mapping, auto-inferring from Verilog if not explicitly provided.

        Args:
            port_name: Name of the port
            port_config: Port configuration from TOML
            direction: Direction of the port ('in' or 'out')
            verilog_ports: Dictionary of Verilog port names to directions

        Returns:
            Flattened port mapping dictionary
        """
        if port_config.map is not None:
            # Explicit mapping provided
            return _flatten_port_map(port_config.map)

        # Try to infer mapping from Verilog ports
        if verilog_ports:
            try:
                return _infer_auto_map(port_config.interface, verilog_ports, direction)
            except ChipFlowError:
                pass  # Fall through to prefix-based generation

        # Fallback: generate mapping using prefix convention
        prefix = port_config.prefix
        if prefix is None:
            # Infer prefix from port name
            name = port_name.lower()
            for suffix in ("_pins", "_bus", "_port", "_interface"):
                if name.endswith(suffix):
                    name = name[: -len(suffix)]
                    break
            if name in ("bus", "port"):
                if "wishbone" in port_config.interface.lower():
                    prefix = "wb"
                elif "csr" in port_config.interface.lower():
                    prefix = "csr"
                else:
                    prefix = name
            else:
                prefix = name

        return _generate_auto_map(port_config.interface, prefix, direction)

    def _create_signature_member(
        self, port_config: Port, config: ExternalWrapConfig, default_direction: str = "in"
    ):
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

    # Get source path, resolving relative paths against the TOML file's directory
    source_path = config.files.get_source_path()
    if not source_path.is_absolute():
        source_path = (toml_path.parent / source_path).resolve()

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
            # Convert SystemVerilog to Verilog using yosys-slang
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
