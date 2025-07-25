/* SPDX-License-Identifier: BSD-2-Clause */
#ifndef SPI_FLASH_H
#define SPI_FLASH_H

#include <stdint.h>

#define WINBOND_ID 0x40
#define ISSI_ID 0x60

typedef struct __attribute__((packed, aligned(4))) {
    uint32_t config;
    uint32_t raw_control;
    uint32_t raw_tx_data;
    uint32_t raw_rx_data;
} spiflash_regs_t;

void spiflash_io(volatile spiflash_regs_t *flash, uint8_t *data, int len, uint8_t wrencmd);
uint32_t spiflash_read_id(volatile spiflash_regs_t *flash);
void spiflash_set_qspi_flag(volatile spiflash_regs_t *flash);
void spiflash_set_quad_mode(volatile spiflash_regs_t *flash);

#endif
