import os
import sys
import tomli

from enum import StrEnum, auto
from pathlib import Path
from typing import Dict, Optional, Any, List, Annotated, Literal, Self

from amaranth import Module, unsigned
from amaranth.lib import wiring
from amaranth.lib.wiring import In, Out, flipped, connect

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


class Generators(StrEnum):
    SPINALHDL = auto()
    VERILOG = auto()

    def generate(self, vdir: Path, parameters: Dict[str, list|dict|str|bool|int|float|None], options: List[str]):
        gen_args = [o.format(**parameters) for o in options]
        match self.name:
            case "SPINALHDL":
                cmd = 'cd {path} && sbt "lib/runMain spinal.lib.com.usb.ohci.UsbOhciWishbone {args}"'.format(
                    path=vdir / "ext" / "SpinalHDL", args=" ".join(gen_args))
                print("!!! "   + cmd)
                if os.system(cmd) != 0:
                    raise OSError('Failed to run sbt')
            case _ as v:
                raise TypeError(f"Undefined generator type: {v}")



class Generate(BaseModel):
    parameters: List[str] = []
    defaults: Optional[Dict[str, JsonValue]] = None
    generator: Generators
    options: List[str] = []


class Port(BaseModel):
    interface: str  # ImportString
    params: Optional[Dict[str, JsonValue]] = None
    vars: Optional[Dict[str, Literal["int"]]] = None
    map: str | Dict[str, Dict[str, str] | str]  


class ExternalWrap(BaseModel):
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

        vloc = Path()
        if wrap.files.module:
            vloc = Path(wrap.files.module.data_location)
        elif wrap.files.path:
            vloc = path
        else:
            assert True

        if wrap.generate:
            wrap.generate.generator.generate(vloc, wrap.generate.defaults, wrap.generate.options)

        
    except ValidationError as e:
        # Format Pydantic validation errors in a user-friendly way
        error_messages = []
        for error in e.errors():
            location = ".".join(str(loc) for loc in error["loc"])
            message = error["msg"]
            error_messages.append(f"Error at '{location}': {message}")

        error_str = "\n".join(error_messages)
        raise ChipFlowError(f"Validation error in chipflow.toml:\n{error_str}")



