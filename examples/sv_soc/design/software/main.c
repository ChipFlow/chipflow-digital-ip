// SPDX-License-Identifier: BSD-2-Clause
// SoC firmware demonstrating SystemVerilog timer usage

#include <stdint.h>
#include "generated/soc.h"

// Timer register base address (matches design.py csr_timer_base)
#define TIMER_BASE 0xB3000000

// Include the timer driver header
#include "../rtl/drivers/wb_timer.h"

// Timer instance at the hardware address
#define TIMER ((wb_timer_regs_t *)TIMER_BASE)

void delay_cycles(uint32_t cycles) {
    // Simple delay using the timer
    wb_timer_disable(TIMER);
    TIMER->counter = 0;
    TIMER->compare = cycles;
    TIMER->ctrl = WB_TIMER_CTRL_ENABLE;  // Enable without IRQ

    // Wait for match
    while (!(TIMER->status & WB_TIMER_STATUS_MATCH))
        ;

    wb_timer_disable(TIMER);
    TIMER->status = WB_TIMER_STATUS_MATCH;  // Clear match flag
}

void blink_leds(uint8_t pattern) {
    // Write pattern to GPIO0 (LEDs)
    GPIO_0->out = pattern;
}

void main() {
    // Initialize UART
    uart_init(UART_0, 25000000 / 115200);

    puts("SystemVerilog Timer SoC Example\r\n");
    puts("================================\r\n\n");

    // Print SoC ID
    puts("SoC type: ");
    puthex(SOC_ID->type);
    puts("\r\n");

    // Initialize and test the SystemVerilog timer
    puts("\nTimer test:\r\n");

    // Configure timer with prescaler=0 (no division), compare=1000
    TIMER->compare = 1000;
    TIMER->counter = 0;  // Sets reload value
    TIMER->ctrl = (0 << WB_TIMER_CTRL_PRESCALER_SHIFT) | WB_TIMER_CTRL_ENABLE;

    // Wait for a few timer cycles and read counter
    for (int i = 0; i < 5; i++) {
        puts("Counter: ");
        puthex(TIMER->counter);
        puts("\r\n");

        // Small delay
        for (volatile int j = 0; j < 1000; j++)
            ;
    }

    // Disable timer
    wb_timer_disable(TIMER);
    puts("\nTimer stopped.\r\n");

    // LED blinking demo
    puts("\nLED blink demo (binary counter):\r\n");

    uint8_t led_val = 0;
    while (1) {
        blink_leds(led_val);

        // Use timer for delay
        delay_cycles(25000000 / 4);  // ~250ms at 25MHz

        led_val++;

        // Print every 16 counts
        if ((led_val & 0x0F) == 0) {
            puts("LED: ");
            puthex(led_val);
            puts("\r\n");
        }
    }
}
