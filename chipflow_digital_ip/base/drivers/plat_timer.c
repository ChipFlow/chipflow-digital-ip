/* SPDX-License-Identifier: BSD-2-Clause */
#include "plat_timer.h"

uint64_t plat_timer_read(volatile plat_timer_regs_t *timer) {
	uint32_t cnt_lo = timer->cnt_lo;
	__asm__ volatile ("" : : : "memory");
	return (((uint64_t)timer->cnt_hi) << 32ULL) | cnt_lo;
}

void plat_timer_schedule(volatile plat_timer_regs_t *timer, uint64_t val) {
	timer->cmp_lo = val & 0xFFFFFFFFU;
	__asm__ volatile ("" : : : "memory");
	timer->cmp_hi = (val >> 32U) & 0xFFFFFFFFU;
}
