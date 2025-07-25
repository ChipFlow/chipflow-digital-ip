/* SPDX-License-Identifier: BSD-2-Clause */
#include "spi.h"

void spi_init(volatile spi_regs_t *spi, uint32_t divider) {
    spi->divider = divider;
    spi->config = 0x02; // CS=0, SCK_EDGE=1, SCK_IDLE=0
}

uint32_t spi_xfer(volatile spi_regs_t *spi, uint32_t data, uint32_t width, bool deselect) {
    spi->config = ((width - 1) << 3) | 0x06; // CS=1, SCK_EDGE=1, SCK_IDLE=0
    spi->send_data = data << (32U - width);
    while (!(spi->status & 0x1)) // wait for rx full
        ;
    if (deselect) {
        spi->config = ((width - 1) << 3) | 0x02; // CS=0, SCK_EDGE=1, SCK_IDLE=0
    }
    return spi->receive_data;
}
