Verilog/SystemVerilog Integration
==================================

The VerilogWrapper system allows you to integrate external Verilog and SystemVerilog
modules into Amaranth designs using a TOML-based configuration. It supports:

- Automatic interface binding for common bus protocols (Wishbone, SPI, UART, etc.)
- SystemVerilog to Verilog conversion via yosys-slang
- SpinalHDL code generation
- CXXRTL compiled simulation for fast testbench execution
- Software driver integration

Quick Start
-----------

1. Create a TOML configuration file for your Verilog module
2. Load the wrapper and use it as an Amaranth component
3. Simulate using CXXRTL or synthesize with your Amaranth design

.. code-block:: python

   from chipflow_digital_ip.io import load_wrapper_from_toml

   # Load and instantiate
   wrapper = load_wrapper_from_toml("my_module.toml")

   # Use in your design
   m.submodules.my_module = wrapper
   m.d.comb += my_bus.connect(wrapper.bus)

TOML Configuration
------------------

The TOML file defines how to wrap your Verilog module. Here's a complete example:

.. code-block:: toml

   # Module name - must match the Verilog module name
   name = 'wb_timer'

   [files]
   # Source location (relative path or Python module)
   path = '.'
   # Or: module = 'mypackage.data'

   [generate]
   # Generator: 'yosys_slang', 'systemverilog', 'spinalhdl', or 'verilog'
   generator = 'yosys_slang'

   [generate.yosys_slang]
   top_module = 'wb_timer'

   [clocks]
   # Map Amaranth clock domains to Verilog signals
   sys = 'clk'      # ClockSignal() -> i_clk

   [resets]
   # Map Amaranth reset domains to Verilog signals (active-low)
   sys = 'rst_n'    # ~ResetSignal() -> i_rst_n

   [ports.bus]
   # Bus interface with auto-mapping
   interface = 'amaranth_soc.wishbone.Signature'
   direction = 'in'

   [ports.bus.params]
   addr_width = 4
   data_width = 32
   granularity = 8

   [pins.irq]
   # Simple signal with explicit mapping
   interface = 'amaranth.lib.wiring.Out(1)'
   map = 'o_irq'

   [driver]
   # Optional: Software driver files
   regs_struct = 'my_regs_t'
   h_files = ['drivers/my_module.h']

Configuration Sections
^^^^^^^^^^^^^^^^^^^^^^

**[files]**
   Specifies where to find the Verilog source files.

   - ``path``: Relative path from the TOML file
   - ``module``: Python module containing data files (uses ``data_location`` attribute)

**[generate]**
   Controls how SystemVerilog/SpinalHDL is processed.

   - ``generator``: One of ``'yosys_slang'``, ``'systemverilog'``, ``'spinalhdl'``, ``'verilog'``
   - ``parameters``: Dictionary of parameters for SpinalHDL generation

**[clocks]** and **[resets]**
   Maps Amaranth clock/reset domains to Verilog signal names.
   The wrapper adds ``i_`` prefix to clock signals and inverts reset signals
   (assuming active-low reset convention).

**[ports.<name>]**
   Defines a bus interface port.

   - ``interface``: Dotted path to Amaranth interface class
   - ``direction``: ``'in'`` or ``'out'``
   - ``params``: Interface constructor parameters
   - ``map``: Optional explicit signal mapping (auto-mapped if omitted)

**[pins.<name>]**
   Defines a simple signal or pin interface.

   - ``interface``: Interface specification (e.g., ``'amaranth.lib.wiring.Out(1)'``)
   - ``map``: Verilog signal name

**[driver]**
   Software driver configuration for SoftwareDriverSignature.

   - ``regs_struct``: C struct name for register access
   - ``c_files``, ``h_files``: Driver source/header files

Auto-Mapping
------------

When ``map`` is not specified for a port, the wrapper automatically matches
Verilog signals to interface members using pattern recognition:

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Interface Member
     - Recognized Patterns
   * - ``cyc``
     - ``*cyc*``, ``*CYC*``
   * - ``stb``
     - ``*stb*``, ``*STB*``
   * - ``ack``
     - ``*ack*``, ``*ACK*``
   * - ``we``
     - ``*we*``, ``*WE*``
   * - ``adr``
     - ``*adr*``, ``*addr*``, ``*ADR*``
   * - ``dat_w``, ``dat.w``
     - ``*dat*w*``, ``*data*in*``, ``*DAT*MOSI*``
   * - ``dat_r``, ``dat.r``
     - ``*dat*r*``, ``*data*out*``, ``*DAT*MISO*``

This allows the wrapper to work with various naming conventions.

CXXRTL Simulation
-----------------

The VerilogWrapper integrates with CXXRTL for fast compiled simulation,
allowing you to write Python testbenches that execute real Verilog code.

.. code-block:: python

   from chipflow_digital_ip.io import load_wrapper_from_toml

   # Load wrapper
   wrapper = load_wrapper_from_toml("my_module.toml", generate_dest="build")

   # Build CXXRTL simulator
   sim = wrapper.build_simulator("build/sim")

   # Clock cycle helper
   def tick():
       sim.set("i_clk", 0)
       sim.step()
       sim.set("i_clk", 1)
       sim.step()

   # Reset
   sim.set("i_rst_n", 0)
   tick()
   tick()
   sim.set("i_rst_n", 1)

   # Interact with the design
   sim.set("i_wb_cyc", 1)
   sim.set("i_wb_stb", 1)
   tick()
   value = sim.get("o_wb_dat")

   sim.close()

Signal Names
^^^^^^^^^^^^

In CXXRTL simulation, signals are accessed by their Verilog names (not Amaranth paths):

.. list-table::
   :header-rows: 1
   :widths: 30 30

   * - Amaranth
     - Verilog
   * - ``wrapper.bus.cyc``
     - ``"i_wb_cyc"``
   * - ``wrapper.bus.dat_r``
     - ``"o_wb_dat"``
   * - Clock
     - ``"i_clk"``
   * - Reset
     - ``"i_rst_n"``

Use ``wrapper.get_signal_map()`` to get the complete mapping.

SpinalHDL Integration
---------------------

For SpinalHDL-based IP, use the ``spinalhdl`` generator:

.. code-block:: toml

   [generate]
   generator = 'spinalhdl'
   parameters.nusb = 1
   parameters.dma_data_width = 32

   [generate.spinalhdl]
   scala_class = 'spinal.lib.com.usb.ohci.UsbOhciWishbone'
   options = [
       '--port-count {nusb}',
       '--dma-width {dma_data_width}',
   ]

The wrapper will invoke the SpinalHDL generator to produce Verilog before
wrapping the module.

API Reference
-------------

.. autofunction:: chipflow_digital_ip.io.load_wrapper_from_toml

.. autoclass:: chipflow_digital_ip.io.VerilogWrapper
   :members:
   :special-members: __init__

Examples
--------

See the ``examples/sv_timer_simulation/`` directory for a complete example
including:

- SystemVerilog timer IP (``wb_timer.sv``)
- TOML configuration (``wb_timer.toml``)
- Simulation script (``simulate_timer.py``)
- C driver header (``drivers/wb_timer.h``)
