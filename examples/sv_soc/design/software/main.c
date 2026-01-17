// SPDX-License-Identifier: BSD-2-Clause
// SoC firmware demonstrating SystemVerilog timer usage

#include <stdint.h>
#include "generated/soc.h"

// Timer register base address (matches design.py csr_timer_base)
#define TIMER_BASE 0xB3000000

// Timer register structure (matches wb_timer.sv)
typedef struct {
    volatile uint32_t ctrl;     // [31:16] prescaler, [1] irq_en, [0] enable
    volatile uint32_t compare;  // Compare value for match interrupt
    volatile uint32_t counter;  // Current counter (read) / Reload value (write)
    volatile uint32_t status;   // [1] match, [0] irq_pending (write 1 to clear)
} timer_regs_t;

#define TIMER ((timer_regs_t *)TIMER_BASE)

// Control register bits
#define TIMER_CTRL_ENABLE         (1 << 0)
#define TIMER_CTRL_IRQ_EN         (1 << 1)
#define TIMER_CTRL_PRESCALER_SHIFT 16

// Status register bits
#define TIMER_STATUS_IRQ_PENDING  (1 << 0)
#define TIMER_STATUS_MATCH        (1 << 1)

void timer_disable(void) {
    TIMER->ctrl &= ~TIMER_CTRL_ENABLE;
}

void delay_cycles(uint32_t cycles) {
    // Simple delay using the timer
    timer_disable();
    TIMER->counter = 0;
    TIMER->compare = cycles;
    TIMER->ctrl = TIMER_CTRL_ENABLE;  // Enable without IRQ

    // Wait for match
    while (!(TIMER->status & TIMER_STATUS_MATCH))
        ;

    timer_disable();
    TIMER->status = TIMER_STATUS_MATCH;  // Clear match flag
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
    TIMER->ctrl = (0 << TIMER_CTRL_PRESCALER_SHIFT) | TIMER_CTRL_ENABLE;

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
    timer_disable();
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
