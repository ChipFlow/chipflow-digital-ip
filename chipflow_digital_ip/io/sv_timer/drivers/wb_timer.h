// SPDX-License-Identifier: BSD-2-Clause
// Wishbone Timer Driver Header

#ifndef WB_TIMER_H
#define WB_TIMER_H

#include <stdint.h>

// Register offsets
#define WB_TIMER_CTRL    0x00
#define WB_TIMER_COMPARE 0x04
#define WB_TIMER_COUNTER 0x08
#define WB_TIMER_STATUS  0x0C

// Control register bits
#define WB_TIMER_CTRL_ENABLE   (1 << 0)
#define WB_TIMER_CTRL_IRQ_EN   (1 << 1)
#define WB_TIMER_CTRL_PRESCALER_SHIFT 16

// Status register bits
#define WB_TIMER_STATUS_IRQ_PENDING (1 << 0)
#define WB_TIMER_STATUS_MATCH       (1 << 1)

// Register structure for SoftwareDriverSignature
typedef struct {
    volatile uint32_t ctrl;     // Control: [31:16] prescaler, [1] irq_en, [0] enable
    volatile uint32_t compare;  // Compare value for match interrupt
    volatile uint32_t counter;  // Current counter (read) / Reload value (write)
    volatile uint32_t status;   // Status: [1] match, [0] irq_pending (write 1 to clear)
} wb_timer_regs_t;

static inline void wb_timer_init(wb_timer_regs_t *regs, uint16_t prescaler, uint32_t compare) {
    regs->compare = compare;
    regs->counter = 0;
    regs->ctrl = ((uint32_t)prescaler << WB_TIMER_CTRL_PRESCALER_SHIFT)
               | WB_TIMER_CTRL_ENABLE
               | WB_TIMER_CTRL_IRQ_EN;
}

static inline void wb_timer_enable(wb_timer_regs_t *regs) {
    regs->ctrl |= WB_TIMER_CTRL_ENABLE;
}

static inline void wb_timer_disable(wb_timer_regs_t *regs) {
    regs->ctrl &= ~WB_TIMER_CTRL_ENABLE;
}

static inline void wb_timer_set_compare(wb_timer_regs_t *regs, uint32_t value) {
    regs->compare = value;
}

static inline uint32_t wb_timer_get_counter(wb_timer_regs_t *regs) {
    return regs->counter;
}

static inline void wb_timer_clear_irq(wb_timer_regs_t *regs) {
    regs->status = WB_TIMER_STATUS_IRQ_PENDING | WB_TIMER_STATUS_MATCH;
}

static inline int wb_timer_irq_pending(wb_timer_regs_t *regs) {
    return (regs->status & WB_TIMER_STATUS_IRQ_PENDING) != 0;
}

#endif // WB_TIMER_H
