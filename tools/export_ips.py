import inspect
import json
import sys

from amaranth import Elaboratable
from amaranth.lib import wiring
from amaranth_soc.memory import MemoryMap
from docstring_parser import parse_from_object


import chipflow_digital_ip

def children(mod):
    level = "chipflow_digital_ip"
    stack = [(f"{level}.{attr}", getattr(mod, attr)) for attr in dir(mod) if not attr.startswith("_")]
    done = []
    while stack:
        i = stack.pop()
        e,o = i
        if inspect.isclass(o) and o.__module__.startswith('chipflow_digital_ip') and issubclass(o, wiring.Component):
            yield e,o
        if inspect.ismodule(o):
            if e in done:
                continue
            done.append(e)
            stack.extend([(f"{e}.{attr}", getattr(o, attr)) for attr in dir(o) if not attr.startswith("_")])

def name_to_str(n: MemoryMap.Name) -> str:
    return  ".".join(f"{part}" for part in n)

def docs_for_obj(obj) -> dict:
    docstring = parse_from_object(obj)
    #init_signature = inspect.signature(cls.__init__)
    #print(f"{name} Signature:i {init_signature}")
    d = {}
    if docstring.short_description:
        d['short_description'] = docstring.short_description
    if docstring.long_description:
        d['long_description'] = docstring.long_description
    if docstring.params:
        d['params'] = [p.__dict__ for p in docstring.params if p.args[0]=="param"]
        d['attributes'] = [p.__dict__ for p in docstring.params if p.args[0]=="attribute"]
    if docstring.raises:
        d['raises'] = [p.__dict__ for p in docstring.raises]
    if docstring.examples:
        d['examples'] = [ e.__dict__ for e in docstring.examples]
    return d


def list_resources(mm: MemoryMap) -> dict:
    d = {}
    for resource, rname, _ in mm.resources():
        cls = resource.__class__
        #print(f"adding resource {resource}. {type(resource)} {cls.__name__}, {cls.__qualname__}, {cls.__doc__}")
        ri = mm.find_resource(resource)
        d[name_to_str(rname)] = {
                'resource': docs_for_obj(resource),
                'start': f"{ri.start:#x}",
                'end': f"{ri.end:#x}",
                'width': ri.width,
        }
    for window, wname, (start, end, ratio) in mm.windows():
        d[name_to_str(wname)] = {
                'window': docs_for_obj(window),
                'start': f"{start:#x}",
                'end': f"{end:#x}",
                'ratio': ratio,
                'children': list_resources(window)
                }
    return d

gen = children(chipflow_digital_ip)
output={}
for name, cls in gen:
    # instantiate and get registers
    obj = cls()
    d = docs_for_obj(obj)
    if hasattr(obj, 'bus') and hasattr(obj.bus, 'memory_map') and isinstance(obj.bus.memory_map, MemoryMap):
        d['memory_map'] = list_resources(obj.bus.memory_map)
    output[name] = d

json.dump(output, sys.stdout, indent=2)
