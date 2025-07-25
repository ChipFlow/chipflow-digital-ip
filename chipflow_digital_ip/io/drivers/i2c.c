/* SPDX-License-Identifier: BSD-2-Clause */
#include "i2c.h"

void i2c_init(volatile i2c_regs_t *i2c, uint32_t divider) {
	i2c->divider = divider;
}

void i2c_start(volatile i2c_regs_t *i2c) {
	i2c->action = (1<<1);
	while (i2c->status & 0x1)
		;
}

int i2c_write(volatile i2c_regs_t *i2c, uint8_t data) {
	i2c->send_data = data;
	while (i2c->status & 0x1)
		;
	return (i2c->status & 0x2) != 0; // check ACK
}

uint8_t i2c_read(volatile i2c_regs_t *i2c) {
	i2c->action = (1<<3);
	while (i2c->status & 0x1)
		;
	return i2c->receive_data;
}

void i2c_stop(volatile i2c_regs_t *i2c) {
	i2c->action = (1<<2);
	while (i2c->status & 0x1)
		;
}
