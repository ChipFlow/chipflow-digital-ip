/* SPDX-License-Identifier: BSD-2-Clause */
#ifndef UART_H
#define UART_H

#include <stdint.h>

typedef struct __attribute__((packed, aligned(4))) {
    uint8_t config;
    uint8_t padding_0[3];
    uint32_t phy_config;
    uint8_t status;
    uint8_t data;
    uint8_t padding_1[6];
} uart_mod_regs_t;

typedef struct __attribute__((packed, aligned(4))) {
    uart_mod_regs_t rx;
    uart_mod_regs_t tx;
} uart_regs_t;

void uart_init(volatile uart_regs_t *uart, uint32_t divisor);
void uart_putc(volatile uart_regs_t *uart, char c);
void uart_puts(volatile uart_regs_t *uart, const char *s);
void uart_puthex(volatile uart_regs_t *uart, uint32_t x);

#endif
