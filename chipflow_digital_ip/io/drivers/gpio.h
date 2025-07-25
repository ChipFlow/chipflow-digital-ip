/* SPDX-License-Identifier: BSD-2-Clause */
#ifndef GPIO_H
#define GPIO_H

#include <stdint.h>

typedef struct __attribute__((packed, aligned(2))) {
	uint16_t mode;
	uint8_t input;
	uint8_t output;
	uint16_t setclr;
} gpio_regs_t;

typedef enum {
#define _GPIO_PIN(n) \
	GPIO_PIN ## n ## _INPUT_ONLY = (0 << 2 * (n)), \
	GPIO_PIN ## n ## _PUSH_PULL  = (1 << 2 * (n)), \
	GPIO_PIN ## n ## _OPEN_DRAIN = (2 << 2 * (n)), \
	GPIO_PIN ## n ## _ALTERNATE  = (3 << 2 * (n))

	_GPIO_PIN(0),
	_GPIO_PIN(1),
	_GPIO_PIN(2),
	_GPIO_PIN(3),
	_GPIO_PIN(4),
	_GPIO_PIN(5),
	_GPIO_PIN(6),
	_GPIO_PIN(7),
#undef _GPIO_PIN
} gpio_mode_t;

typedef enum {
#define _GPIO_PIN(n) \
	GPIO_PIN ## n ## _SET   = (1 << 2 * (n)), \
	GPIO_PIN ## n ## _CLEAR = (2 << 2 * (n))

	_GPIO_PIN(0),
	_GPIO_PIN(1),
	_GPIO_PIN(2),
	_GPIO_PIN(3),
	_GPIO_PIN(4),
	_GPIO_PIN(5),
	_GPIO_PIN(6),
	_GPIO_PIN(7),
#undef _GPIO_PIN
} gpio_setclr_t;

#endif
