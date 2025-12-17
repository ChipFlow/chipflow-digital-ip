// SPDX-License-Identifier: BSD-2-Clause
// Simple Wishbone Timer/Counter in SystemVerilog
//
// A basic 32-bit programmable timer with Wishbone B4 interface.
// Useful for MCU applications requiring periodic interrupts or timing.
//
// Registers:
//   0x00: CTRL    - Control register (enable, mode, interrupt enable)
//   0x04: COMPARE - Compare value for timer match
//   0x08: COUNTER - Current counter value (read) / Reload value (write)
//   0x0C: STATUS  - Status register (interrupt pending, match flag)

module wb_timer #(
    parameter int WIDTH = 32,
    parameter int PRESCALER_WIDTH = 16
) (
    // Clock and reset
    input  logic                    i_clk,
    input  logic                    i_rst_n,

    // Wishbone B4 slave interface
    input  logic                    i_wb_cyc,
    input  logic                    i_wb_stb,
    input  logic                    i_wb_we,
    input  logic [3:0]              i_wb_sel,
    input  logic [3:0]              i_wb_adr,   // Word address (4 registers)
    input  logic [31:0]             i_wb_dat,
    output logic [31:0]             o_wb_dat,
    output logic                    o_wb_ack,

    // Interrupt output
    output logic                    o_irq
);

    // Register addresses (word-aligned)
    localparam logic [3:0] ADDR_CTRL    = 4'h0;
    localparam logic [3:0] ADDR_COMPARE = 4'h1;
    localparam logic [3:0] ADDR_COUNTER = 4'h2;
    localparam logic [3:0] ADDR_STATUS  = 4'h3;

    // Control register bits
    typedef struct packed {
        logic [15:0] prescaler;   // [31:16] Prescaler divider value
        logic [13:0] reserved;    // [15:2]  Reserved
        logic        irq_en;      // [1]     Interrupt enable
        logic        enable;      // [0]     Timer enable
    } ctrl_t;

    // Status register bits
    typedef struct packed {
        logic [29:0] reserved;    // [31:2]  Reserved
        logic        match;       // [1]     Compare match occurred
        logic        irq_pending; // [0]     Interrupt pending
    } status_t;

    // Registers
    ctrl_t   ctrl_reg;
    logic [WIDTH-1:0] compare_reg;
    logic [WIDTH-1:0] counter_reg;
    logic [WIDTH-1:0] reload_reg;
    status_t status_reg;

    // Prescaler counter
    logic [PRESCALER_WIDTH-1:0] prescaler_cnt;
    logic prescaler_tick;

    // Wishbone acknowledge - single cycle response
    logic wb_access;
    assign wb_access = i_wb_cyc & i_wb_stb;

    always_ff @(posedge i_clk or negedge i_rst_n) begin
        if (!i_rst_n) begin
            o_wb_ack <= 1'b0;
        end else begin
            o_wb_ack <= wb_access & ~o_wb_ack;
        end
    end

    // Prescaler logic
    always_ff @(posedge i_clk or negedge i_rst_n) begin
        if (!i_rst_n) begin
            prescaler_cnt <= '0;
            prescaler_tick <= 1'b0;
        end else if (ctrl_reg.enable) begin
            if (prescaler_cnt >= ctrl_reg.prescaler) begin
                prescaler_cnt <= '0;
                prescaler_tick <= 1'b1;
            end else begin
                prescaler_cnt <= prescaler_cnt + 1'b1;
                prescaler_tick <= 1'b0;
            end
        end else begin
            prescaler_cnt <= '0;
            prescaler_tick <= 1'b0;
        end
    end

    // Counter logic
    logic counter_match;
    assign counter_match = (counter_reg == compare_reg);

    always_ff @(posedge i_clk or negedge i_rst_n) begin
        if (!i_rst_n) begin
            counter_reg <= '0;
        end else if (ctrl_reg.enable && prescaler_tick) begin
            if (counter_match) begin
                counter_reg <= reload_reg;
            end else begin
                counter_reg <= counter_reg + 1'b1;
            end
        end
    end

    // Status and interrupt logic
    always_ff @(posedge i_clk or negedge i_rst_n) begin
        if (!i_rst_n) begin
            status_reg <= '0;
        end else begin
            // Set match flag on compare match
            if (ctrl_reg.enable && prescaler_tick && counter_match) begin
                status_reg.match <= 1'b1;
                if (ctrl_reg.irq_en) begin
                    status_reg.irq_pending <= 1'b1;
                end
            end

            // Clear flags on status register write
            if (wb_access && i_wb_we && (i_wb_adr == ADDR_STATUS)) begin
                if (i_wb_sel[0] && i_wb_dat[0]) status_reg.irq_pending <= 1'b0;
                if (i_wb_sel[0] && i_wb_dat[1]) status_reg.match <= 1'b0;
            end
        end
    end

    assign o_irq = status_reg.irq_pending;

    // Register write logic
    always_ff @(posedge i_clk or negedge i_rst_n) begin
        if (!i_rst_n) begin
            ctrl_reg <= '0;
            compare_reg <= '1;  // Default to max value
            reload_reg <= '0;
        end else if (wb_access && i_wb_we) begin
            case (i_wb_adr)
                ADDR_CTRL: begin
                    if (i_wb_sel[0]) ctrl_reg[7:0]   <= i_wb_dat[7:0];
                    if (i_wb_sel[1]) ctrl_reg[15:8]  <= i_wb_dat[15:8];
                    if (i_wb_sel[2]) ctrl_reg[23:16] <= i_wb_dat[23:16];
                    if (i_wb_sel[3]) ctrl_reg[31:24] <= i_wb_dat[31:24];
                end
                ADDR_COMPARE: begin
                    if (i_wb_sel[0]) compare_reg[7:0]   <= i_wb_dat[7:0];
                    if (i_wb_sel[1]) compare_reg[15:8]  <= i_wb_dat[15:8];
                    if (i_wb_sel[2]) compare_reg[23:16] <= i_wb_dat[23:16];
                    if (i_wb_sel[3]) compare_reg[31:24] <= i_wb_dat[31:24];
                end
                ADDR_COUNTER: begin
                    // Writing to counter sets the reload value
                    if (i_wb_sel[0]) reload_reg[7:0]   <= i_wb_dat[7:0];
                    if (i_wb_sel[1]) reload_reg[15:8]  <= i_wb_dat[15:8];
                    if (i_wb_sel[2]) reload_reg[23:16] <= i_wb_dat[23:16];
                    if (i_wb_sel[3]) reload_reg[31:24] <= i_wb_dat[31:24];
                end
                default: ;
            endcase
        end
    end

    // Register read logic
    always_comb begin
        o_wb_dat = '0;
        case (i_wb_adr)
            ADDR_CTRL:    o_wb_dat = ctrl_reg;
            ADDR_COMPARE: o_wb_dat = compare_reg;
            ADDR_COUNTER: o_wb_dat = counter_reg;
            ADDR_STATUS:  o_wb_dat = status_reg;
            default:      o_wb_dat = '0;
        endcase
    end

endmodule
