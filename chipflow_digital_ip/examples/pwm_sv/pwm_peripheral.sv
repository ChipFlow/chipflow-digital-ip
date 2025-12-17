// Simple PWM Peripheral with Pad Ring Connections
// This example demonstrates a SystemVerilog peripheral with:
// - CSR bus interface for configuration
// - PWM output pins connecting to the pad ring
// - Input capture pin for external feedback

module pwm_peripheral #(
    parameter int NUM_CHANNELS = 4,
    parameter int COUNTER_WIDTH = 16
) (
    // Clock and reset
    input  logic clk_i,
    input  logic rst_ni,

    // CSR bus interface (directly exposed, no Wishbone wrapper)
    input  logic [7:0]  csr_addr_i,
    input  logic        csr_we_i,
    input  logic [31:0] csr_wdata_i,
    output logic [31:0] csr_rdata_o,

    // Pad ring connections - PWM outputs
    output logic [NUM_CHANNELS-1:0] pwm_o,      // PWM output to pads
    output logic [NUM_CHANNELS-1:0] pwm_oe_o,   // Output enable for pads

    // Pad ring connections - Input capture
    input  logic [NUM_CHANNELS-1:0] capture_i,  // Capture input from pads

    // Optional: direct GPIO-style bidirectional port
    input  logic [7:0] gpio_i,
    output logic [7:0] gpio_o,
    output logic [7:0] gpio_oe_o
);

    // --------------------------------------------------------------------------
    // Register map:
    //   0x00: Control register (enable bits, prescaler)
    //   0x04: Status register (capture events)
    //   0x10-0x1C: PWM period registers (per channel)
    //   0x20-0x2C: PWM duty cycle registers (per channel)
    //   0x30-0x3C: Capture value registers (per channel)
    //   0x40: GPIO output register
    //   0x44: GPIO output enable register
    // --------------------------------------------------------------------------

    // Control register fields
    logic [NUM_CHANNELS-1:0] pwm_enable;
    logic [7:0] prescaler;

    // PWM configuration per channel
    logic [COUNTER_WIDTH-1:0] pwm_period   [NUM_CHANNELS];
    logic [COUNTER_WIDTH-1:0] pwm_duty     [NUM_CHANNELS];
    logic [COUNTER_WIDTH-1:0] capture_val  [NUM_CHANNELS];

    // Internal state
    logic [COUNTER_WIDTH-1:0] counter;
    logic [7:0] prescale_cnt;
    logic tick;

    // GPIO registers
    logic [7:0] gpio_out_reg;
    logic [7:0] gpio_oe_reg;

    // Capture edge detection
    logic [NUM_CHANNELS-1:0] capture_prev;
    logic [NUM_CHANNELS-1:0] capture_event;

    // --------------------------------------------------------------------------
    // Prescaler and main counter
    // --------------------------------------------------------------------------
    always_ff @(posedge clk_i or negedge rst_ni) begin
        if (!rst_ni) begin
            prescale_cnt <= '0;
            tick <= 1'b0;
        end else begin
            if (prescale_cnt >= prescaler) begin
                prescale_cnt <= '0;
                tick <= 1'b1;
            end else begin
                prescale_cnt <= prescale_cnt + 1'b1;
                tick <= 1'b0;
            end
        end
    end

    always_ff @(posedge clk_i or negedge rst_ni) begin
        if (!rst_ni) begin
            counter <= '0;
        end else if (tick) begin
            counter <= counter + 1'b1;
        end
    end

    // --------------------------------------------------------------------------
    // PWM output generation
    // --------------------------------------------------------------------------
    generate
        for (genvar i = 0; i < NUM_CHANNELS; i++) begin : gen_pwm
            always_ff @(posedge clk_i or negedge rst_ni) begin
                if (!rst_ni) begin
                    pwm_o[i] <= 1'b0;
                end else begin
                    // Simple PWM: output high when counter < duty
                    if (counter < pwm_duty[i]) begin
                        pwm_o[i] <= 1'b1;
                    end else begin
                        pwm_o[i] <= 1'b0;
                    end
                end
            end

            // Output enable follows channel enable
            assign pwm_oe_o[i] = pwm_enable[i];
        end
    endgenerate

    // --------------------------------------------------------------------------
    // Input capture
    // --------------------------------------------------------------------------
    always_ff @(posedge clk_i or negedge rst_ni) begin
        if (!rst_ni) begin
            capture_prev <= '0;
            capture_event <= '0;
        end else begin
            capture_prev <= capture_i;
            // Rising edge detection
            capture_event <= capture_i & ~capture_prev;
        end
    end

    generate
        for (genvar i = 0; i < NUM_CHANNELS; i++) begin : gen_capture
            always_ff @(posedge clk_i or negedge rst_ni) begin
                if (!rst_ni) begin
                    capture_val[i] <= '0;
                end else if (capture_event[i]) begin
                    capture_val[i] <= counter;
                end
            end
        end
    endgenerate

    // --------------------------------------------------------------------------
    // GPIO output
    // --------------------------------------------------------------------------
    assign gpio_o = gpio_out_reg;
    assign gpio_oe_o = gpio_oe_reg;

    // --------------------------------------------------------------------------
    // CSR read/write logic
    // --------------------------------------------------------------------------
    always_ff @(posedge clk_i or negedge rst_ni) begin
        if (!rst_ni) begin
            pwm_enable <= '0;
            prescaler <= 8'd0;
            gpio_out_reg <= '0;
            gpio_oe_reg <= '0;
            for (int i = 0; i < NUM_CHANNELS; i++) begin
                pwm_period[i] <= '1;  // Max period by default
                pwm_duty[i] <= '0;
            end
        end else if (csr_we_i) begin
            case (csr_addr_i)
                8'h00: begin
                    pwm_enable <= csr_wdata_i[NUM_CHANNELS-1:0];
                    prescaler <= csr_wdata_i[15:8];
                end
                8'h10: pwm_duty[0] <= csr_wdata_i[COUNTER_WIDTH-1:0];
                8'h14: pwm_duty[1] <= csr_wdata_i[COUNTER_WIDTH-1:0];
                8'h18: pwm_duty[2] <= csr_wdata_i[COUNTER_WIDTH-1:0];
                8'h1C: pwm_duty[3] <= csr_wdata_i[COUNTER_WIDTH-1:0];
                8'h20: pwm_period[0] <= csr_wdata_i[COUNTER_WIDTH-1:0];
                8'h24: pwm_period[1] <= csr_wdata_i[COUNTER_WIDTH-1:0];
                8'h28: pwm_period[2] <= csr_wdata_i[COUNTER_WIDTH-1:0];
                8'h2C: pwm_period[3] <= csr_wdata_i[COUNTER_WIDTH-1:0];
                8'h40: gpio_out_reg <= csr_wdata_i[7:0];
                8'h44: gpio_oe_reg <= csr_wdata_i[7:0];
                default: ;
            endcase
        end
    end

    // CSR read mux
    always_comb begin
        case (csr_addr_i)
            8'h00: csr_rdata_o = {16'b0, prescaler, {(8-NUM_CHANNELS){1'b0}}, pwm_enable};
            8'h04: csr_rdata_o = {{(32-NUM_CHANNELS){1'b0}}, capture_event};
            8'h10: csr_rdata_o = {{(32-COUNTER_WIDTH){1'b0}}, pwm_duty[0]};
            8'h14: csr_rdata_o = {{(32-COUNTER_WIDTH){1'b0}}, pwm_duty[1]};
            8'h18: csr_rdata_o = {{(32-COUNTER_WIDTH){1'b0}}, pwm_duty[2]};
            8'h1C: csr_rdata_o = {{(32-COUNTER_WIDTH){1'b0}}, pwm_duty[3]};
            8'h20: csr_rdata_o = {{(32-COUNTER_WIDTH){1'b0}}, pwm_period[0]};
            8'h24: csr_rdata_o = {{(32-COUNTER_WIDTH){1'b0}}, pwm_period[1]};
            8'h28: csr_rdata_o = {{(32-COUNTER_WIDTH){1'b0}}, pwm_period[2]};
            8'h2C: csr_rdata_o = {{(32-COUNTER_WIDTH){1'b0}}, pwm_period[3]};
            8'h30: csr_rdata_o = {{(32-COUNTER_WIDTH){1'b0}}, capture_val[0]};
            8'h34: csr_rdata_o = {{(32-COUNTER_WIDTH){1'b0}}, capture_val[1]};
            8'h38: csr_rdata_o = {{(32-COUNTER_WIDTH){1'b0}}, capture_val[2]};
            8'h3C: csr_rdata_o = {{(32-COUNTER_WIDTH){1'b0}}, capture_val[3]};
            8'h40: csr_rdata_o = {24'b0, gpio_out_reg};
            8'h44: csr_rdata_o = {24'b0, gpio_oe_reg};
            8'h48: csr_rdata_o = {24'b0, gpio_i};
            default: csr_rdata_o = 32'b0;
        endcase
    end

endmodule
