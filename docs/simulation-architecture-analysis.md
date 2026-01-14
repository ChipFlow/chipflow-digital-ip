# Simulation Architecture Analysis

## Overview

This document analyzes simulation options for the ChipFlow ecosystem, focusing on the requirements for simulating mixed Amaranth/SystemVerilog designs with customer IP integration.

## Requirements

1. **Fast simulation** - compilation-based preferred over interpreted
2. **Multi-HDL support** - Amaranth, SystemVerilog minimum; VHDL and others desirable
3. **Python-based tests** - leverage existing Amaranth test infrastructure
4. **Graphical debugging** - interactive signal inspection, waveform viewing
5. **Customer IP integration** - ingest customer designs with their simulation models
6. **Commercial verification IP** - support for industry-standard verification methodologies

## Available Tools

| Tool | Type | Strengths | Weaknesses |
|------|------|-----------|------------|
| **CXXRTL** | Compiled (C++) | Clean debug API, Yosys integration, multi-HDL via frontends | Single maintainer (whitequark), newer/less battle-tested |
| **Verilator** | Compiled (C++) | Very fast, mature, industry adoption, CHIPS Alliance backing | VPI requires explicit marking, debug API less elegant |
| **Amaranth sim** | Python interpreter | Native Python, easy testbenches | Cannot simulate Instance() black boxes |
| **cocotb** | Python + VPI | Works with any VPI simulator, popular | Slow due to Python↔simulator context switches |
| **GEM** | GPU-accelerated | Potentially very fast | WIP, lacking features |
| **rtl-debugger** | VS Code plugin | Graphical debugging for CXXRTL | WIP, possibly broken |

## Key Insight: yosys-slang + CXXRTL Pipeline

Since yosys-slang (SystemVerilog frontend) and CXXRTL (simulation backend) both operate on Yosys's RTLIL intermediate representation, they should work together:

```
SystemVerilog ──→ yosys-slang ──→ RTLIL ──→ CXXRTL ──→ C++ simulation
Amaranth ──────→ back.rtlil ────→ RTLIL ──↗
Verilog ───────→ read_verilog ──→ RTLIL ──↗
VHDL ──────────→ ghdl-yosys ────→ RTLIL ──↗
```

This pipeline could provide:
- Multi-HDL support through Yosys frontends
- Fast compiled simulation
- Clean debug API for Python tests and graphical debugging
- No VPI context-switch overhead

**Status: Validated** - see [Pipeline Validation Results](#pipeline-validation-results) below.

## Debug API Comparison

### Verilator VPI

From [Verilator documentation](https://verilator.org/guide/latest/connecting.html):

- Limited VPI subset for "inspection, examination, value change callbacks, and depositing of values"
- **Requires explicit marking**: signals must have `/*verilator public*/` pragmas or use `--public-flat-rw`
- **Performance tradeoff**: VPI access is "hundreds of instructions" vs "couple of instructions" for direct C++ access
- **Non-immediate propagation**: value changes require explicit `eval()` call
- VCD/FST tracing with multithreaded support

### CXXRTL Debug API

From [cxxrtl.org/protocol.html](https://cxxrtl.org/protocol.html) and [Tom Verbeure's analysis](https://tomverbeure.github.io/2020/08/08/CXXRTL-the-New-Yosys-Simulation-Backend.html):

- **Automatic introspection**: discovers all signals at runtime without explicit marking
- **debug_items API**: maps hierarchical names to values/wires/memories
- **Formal protocol specification**: well-documented debug server protocol
- **Purpose-built for debugging**: designed with interactive tools in mind
- VCD generation via introspection

### Comparison Summary

| Aspect | Verilator | CXXRTL |
|--------|-----------|--------|
| Signal discovery | Requires explicit marking | Automatic introspection |
| Access overhead | VPI slow, direct C++ fast | Unified debug_items API |
| Protocol | VPI (standard but limited) | Custom (well-specified) |
| Tool integration | cocotb via VPI | rtl-debugger native |
| Tracing | VCD/FST (mature, multithreaded) | VCD (via introspection) |

**Conclusion**: CXXRTL has a cleaner, purpose-built debug API. Verilator's VPI works but requires more ceremony and has performance tradeoffs.

## Maintainer/Sustainability Analysis

### CXXRTL

- **Primary maintainer**: whitequark
- **Backing**: Part of Yosys (YosysHQ ecosystem)
- **Track record**: ~2020+
- **Risk**: Single maintainer, smaller community
- **Mitigating factor**: Deeply integrated with Amaranth ecosystem

### Verilator

- **Primary maintainer**: Wilson Snyder (since 2001)
- **Backing**: CHIPS Alliance, Linux Foundation, corporate contributors (Intel, Arm, Broadcom, etc.)
- **Track record**: 20+ years
- **Risk**: Still essentially single maintainer, but with institutional support
- **Mitigating factor**: Wide industry adoption, corporate backing

Both projects have single-maintainer concerns, but Verilator has significantly more institutional backing and longer track record.

## Proposed Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Design Sources                          │
├──────────┬──────────┬──────────┬──────────┬────────────────┤
│ Amaranth │    SV    │ Verilog  │   VHDL   │ Customer IP    │
│          │(slang)   │          │ (ghdl)   │                │
└────┬─────┴────┬─────┴────┬─────┴────┬─────┴───────┬────────┘
     │          │          │          │             │
     ▼          ▼          ▼          ▼             ▼
┌─────────────────────────────────────────────────────────────┐
│                    Yosys RTLIL                              │
│              (unified intermediate repr)                    │
└─────────────────────────┬───────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│                      CXXRTL                                 │
│  • Compiled C++ simulation                                  │
│  • Black box API for commercial IP stubs                    │
│  • Well-defined debug/trace interface                       │
└─────────────────────────┬───────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│              Python Test Interface                          │
│  • Direct ctypes/pybind11 binding (no VPI overhead)         │
│  • Amaranth-style async testbenches                         │
│  • pytest integration                                       │
└─────────────────────────┬───────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────┐
│               rtl-debugger (VS Code)                        │
│  • Connect to CXXRTL debug API                              │
│  • Real-time signal inspection                              │
│  • Waveform viewing                                         │
└─────────────────────────────────────────────────────────────┘
```

## Pipeline Validation Results

The yosys-slang → CXXRTL pipeline was validated on 2025-01-14 using the wb_timer SystemVerilog IP.

### Test Setup

- **yowasp-yosys**: 0.61 (includes slang frontend)
- **Design**: wb_timer (Wishbone timer peripheral in SystemVerilog)
- **Test**: C++ harness exercising register read/write, timer counting, compare match, and IRQ

### Pipeline Steps (all successful)

```bash
# 1. Read SystemVerilog with slang frontend
read_slang wb_timer.sv

# 2. Set top module
hierarchy -top wb_timer

# 3. Generate CXXRTL C++
write_cxxrtl wb_timer_cxxrtl.cc

# 4. Compile with system C++ compiler
c++ -std=c++17 -O2 -I<yosys>/include/backends/cxxrtl/runtime \
    -o test_wb_timer test_harness.cpp
```

### Test Results

```
=== CXXRTL wb_timer Test ===
Testing yosys-slang -> CXXRTL pipeline

Test 1: Reset and initial state... PASSED
Test 2: Write/read COMPARE register... PASSED
Test 3: Timer counting... PASSED (counter = 21)
Test 4: Compare match and IRQ... PASSED
Test 5: Clear IRQ... PASSED (status after clear = 0x0)

=== All tests PASSED ===
yosys-slang -> CXXRTL pipeline validated!
```

### Validation Conclusions

1. **Pipeline works end-to-end**: SystemVerilog → slang → RTLIL → CXXRTL → compiled simulation
2. **Full functionality**: Timer counting, prescaler, compare match, IRQ generation all work correctly
3. **Clean integration**: yowasp-yosys 0.61+ includes slang, no separate plugin needed
4. **Good signal visibility**: Generated code includes all internal registers and signals

### Remaining Work for Production Use

1. **Python wrapper**: Need ctypes/pybind11 binding for Python testbench integration
2. **Mixed Amaranth+SV**: Test combining Amaranth-generated Verilog with SV modules
3. **VCD generation**: Verify waveform tracing works through CXXRTL's VCD API
4. **Performance benchmarks**: Compare against Verilator for representative designs

## Hybrid Approach (Risk Mitigation)

To hedge against single-maintainer risk while getting benefits of both tools:

1. **CXXRTL for development/debug** - leverage clean debug API, Yosys ecosystem integration
2. **Verilator for CI/regression** - leverage speed for large test suites
3. **Shared testbench format** - Python tests that can target either backend

## Commercial IP Considerations

### Challenges

- UVM testbenches are deeply SystemVerilog/simulator-coupled
- Commercial verification IP often requires specific simulator features
- DPI/VPI interfaces may have simulator-specific behaviors

### Potential Approaches

1. **CXXRTL black boxes**: Write C++ stubs for commercial IP behavioral models
2. **Separate verification flow**: Keep UVM/commercial IP in traditional simulator flow
3. **Interface adapters**: VPI/DPI bridges to commercial simulators for specific blocks

## Open Questions

1. ~~**yosys-slang → CXXRTL**: Has this pipeline been validated?~~ **ANSWERED**: Yes, validated successfully. See [Pipeline Validation Results](#pipeline-validation-results).
2. **CXXRTL black box workflow**: How practical is it for complex IP?
3. **Python wrapper maturity**: What's the state of Amaranth's `back.cxxrtl` Python integration?
4. **rtl-debugger status**: Is it functional? What's needed to make it production-ready?
5. **Performance comparison**: Actual benchmarks of CXXRTL vs Verilator for representative designs?

## Next Steps

1. ~~**Validate yosys-slang + CXXRTL pipeline**~~ **DONE** - see [Pipeline Validation Results](#pipeline-validation-results)
2. **Evaluate rtl-debugger** current state and roadmap
3. **Prototype Python wrapper** for CXXRTL simulation control
4. **Benchmark** CXXRTL vs Verilator on representative designs
5. **Document black box workflow** for customer/commercial IP integration

## References

- [Verilator Documentation](https://verilator.org/guide/latest/)
- [CXXRTL Debug Protocol](https://cxxrtl.org/protocol.html)
- [Tom Verbeure: CXXRTL Tutorial](https://tomverbeure.github.io/2020/08/08/CXXRTL-the-New-Yosys-Simulation-Backend.html)
- [Tom Verbeure: VHDL/Verilog Cosimulation](https://tomverbeure.github.io/2020/11/04/VHDL_Verilog_Cosimulation_with_CXXRTL.html)
- [Yosys CXXRTL Backend](https://yosyshq.readthedocs.io/projects/yosys/en/latest/cmd/write_cxxrtl.html)
- [rtl-debugger](https://github.com/amaranth-lang/rtl-debugger)
- [Amaranth Documentation](https://amaranth-lang.org/docs/amaranth/latest/)
