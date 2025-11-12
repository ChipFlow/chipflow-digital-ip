import os
import sys
import tomli

from enum import StrEnum, auto
from pathlib import Path
from typing import Dict, Optional, List, Literal, Self

from amaranth.lib import wiring

from pydantic import (
        BaseModel, ImportString, JsonValue, ValidationError,
        model_validator
        )

from chipflow import ChipFlowError


class Files(BaseModel):
    module: Optional[ImportString] = None
    path: Optional[Path] = None

    @model_validator(mode="after")
    def verify_module_or_path(self) -> Self:
        print(self.module)
        print(self.path)
        if (self.module and self.path) or (not self.module and not self.path):
            raise ValueError("You must set `module` or `path`.")
        return self


class GenerateSpinalHDL(BaseModel):

    scala_class: str
    options: List[str] = []

    def generate(self, source_path: Path, dest_path: Path, name: str, parameters: Dict[str, JsonValue]):
        gen_args = [o.format(**parameters) for o in self.options]
        path = source_path / "ext" / "SpinalHDL"
        args=" ".join(gen_args + [f'--netlist-directory={dest_path.absolute()}', f'--netlist-name={name}'])
        cmd = f'cd {path} && sbt -J--enable-native-access=ALL-UNNAMED -v "lib/runMain {self.scala_class} {args}"'
        os.environ["GRADLE_OPTS"] = "--enable-native-access=ALL-UNNAMED"
        print("!!! "   + cmd)
        if os.system(cmd) != 0:
            raise OSError('Failed to run sbt')
        return [f'{name}.v']


class Generators(StrEnum):
    SPINALHDL = auto()
    VERILOG = auto()


class Generate(BaseModel):
    parameters: Optional[Dict[str, JsonValue]] = None
    generator: Generators
    spinalhdl: Optional[GenerateSpinalHDL] = None


class Port(BaseModel):
    interface: str  # ImportString
    params: Optional[Dict[str, JsonValue]] = None
    vars: Optional[Dict[str, Literal["int"]]] = None
    map: str | Dict[str, Dict[str, str] | str]


class ExternalWrap(BaseModel):
    name: str
    files: Files
    generate: Optional[Generate] = None
    clocks: Dict[str, str] = {}
    resets: Dict[str, str] = {}
    ports: Dict[str,Port] = {}
    pins: Dict[str, Port] = {}


if __name__ == "__main__":
    with open(sys.argv[1], "rb") as f:
        wrapper = tomli.load(f)

    try:
        # Validate with Pydantic
        wrap = ExternalWrap.model_validate(wrapper)  # Valiate
        print(wrap)

        source = Path()
        if wrap.files.module:
            source = Path(wrap.files.module.data_location)
        elif wrap.files.path:
            source = wrap.files.path
        else:
            assert True

        if wrap.generate:
            dest = Path("./build/verilog")
            dest.mkdir(parents=True, exist_ok=True)
            files = getattr(wrap.generate, wrap.generate.generator.value).generate(source, Path(dest), wrap.name, wrap.generate.parameters)
            print(f'Generated files: {files}')

            def init(self, **kwargs):
                for name, value in kwargs.items():
                    setattr(self, name, value)

            attr = {
                '__init__': init
                }
            _class = type(wrap.name, (wiring.Component,), attr)




    except ValidationError as e:
        # Format Pydantic validation errors in a user-friendly way
        error_messages = []
        for error in e.errors():
            location = ".".join(str(loc) for loc in error["loc"])
            message = error["msg"]
            error_messages.append(f"Error at '{location}': {message}")

        error_str = "\n".join(error_messages)
        raise ChipFlowError(f"Validation error in chipflow.toml:\n{error_str}")



