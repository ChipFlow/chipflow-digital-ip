from amaranth import *
from amaranth_soc import csr

class GPTimer(Elaboratable):
    """
    General-Purpose Timer (GPTimer) peripheral.

    Features:
      - 32-bit up-counter
      - 8-bit prescaler (divide-by N+1)
      - Single 32-bit compare register
      - Auto-reload on compare match
      - Interrupt on match (level-high)
      - CSR-based register interface
    """
