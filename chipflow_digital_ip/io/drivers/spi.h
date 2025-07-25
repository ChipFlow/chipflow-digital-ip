/* SPDX-License-Identifier: BSD-2-Clause */
#ifndef SPI_H
#define SPI_H

#include <stdint.h>
#include <stdbool.h>

typedef struct {
	uint32_t config;
	uint32_t divider;
	uint32_t send_data;
	uint32_t receive_data;
	uint32_t status;
} spi_regs_t;

void spi_init(volatile spi_regs_t *spi, uint32_t divider);
uint32_t spi_xfer(volatile spi_regs_t *spi, uint32_t data, uint32_t width, bool deselect);

#endif
