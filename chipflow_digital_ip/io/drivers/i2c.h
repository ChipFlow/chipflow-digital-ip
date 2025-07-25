/* SPDX-License-Identifier: BSD-2-Clause */
#ifndef I2C_H
#define I2C_H

#include <stdint.h>

typedef struct {
	uint32_t divider;
	uint32_t action;
	uint32_t send_data;
	uint32_t receive_data;
	uint32_t status;
} i2c_regs_t;

void i2c_init(volatile i2c_regs_t *i2c, uint32_t divider);
void i2c_start(volatile i2c_regs_t *i2c);
int i2c_write(volatile i2c_regs_t *i2c, uint8_t data);
uint8_t i2c_read(volatile i2c_regs_t *i2c);
void i2c_stop(volatile i2c_regs_t *i2c);

#endif
