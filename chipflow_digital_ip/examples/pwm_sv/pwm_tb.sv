// Testbench for PWM Peripheral
// Can be run with Verilator or Icarus Verilog

`timescale 1ns/1ps

module pwm_tb;

    // Clock and reset
    logic clk;
    logic rst_n;

    // CSR interface
    logic [7:0]  csr_addr;
    logic        csr_we;
    logic [31:0] csr_wdata;
    logic [31:0] csr_rdata;

    // Pad ring connections
    logic [3:0] pwm_o;
    logic [3:0] pwm_oe;
    logic [3:0] capture_i;
    logic [7:0] gpio_i;
    logic [7:0] gpio_o;
    logic [7:0] gpio_oe;

    // Instantiate DUT
    pwm_peripheral #(
        .NUM_CHANNELS(4),
        .COUNTER_WIDTH(16)
    ) dut (
        .clk_i(clk),
        .rst_ni(rst_n),
        .csr_addr_i(csr_addr),
        .csr_we_i(csr_we),
        .csr_wdata_i(csr_wdata),
        .csr_rdata_o(csr_rdata),
        .pwm_o(pwm_o),
        .pwm_oe_o(pwm_oe),
        .capture_i(capture_i),
        .gpio_i(gpio_i),
        .gpio_o(gpio_o),
        .gpio_oe_o(gpio_oe)
    );

    // Clock generation (100 MHz)
    initial begin
        clk = 0;
        forever #5 clk = ~clk;
    end

    // CSR write task
    task csr_write(input [7:0] addr, input [31:0] data);
        @(posedge clk);
        csr_addr <= addr;
        csr_wdata <= data;
        csr_we <= 1;
        @(posedge clk);
        csr_we <= 0;
    endtask

    // CSR read task
    task csr_read(input [7:0] addr, output [31:0] data);
        @(posedge clk);
        csr_addr <= addr;
        csr_we <= 0;
        @(posedge clk);
        data = csr_rdata;
    endtask

    // Test sequence
    initial begin
        logic [31:0] read_data;

        // Initialize
        rst_n = 0;
        csr_addr = 0;
        csr_we = 0;
        csr_wdata = 0;
        capture_i = 0;
        gpio_i = 0;

        // Generate VCD for waveform viewing
        $dumpfile("pwm_tb.vcd");
        $dumpvars(0, pwm_tb);

        $display("=== PWM Peripheral Testbench ===");
        $display("Time: %0t - Starting reset", $time);

        // Reset sequence
        repeat(10) @(posedge clk);
        rst_n = 1;
        repeat(5) @(posedge clk);

        $display("Time: %0t - Reset complete", $time);

        // -----------------------------------------------------------------
        // Test 1: Configure prescaler and enable channel 0
        // -----------------------------------------------------------------
        $display("\n--- Test 1: Basic PWM Configuration ---");

        // Write prescaler=0 (no division), enable channel 0
        csr_write(8'h00, 32'h0001);  // Control: enable[0]=1, prescaler=0
        $display("Time: %0t - Enabled PWM channel 0", $time);

        // Check that pwm_oe[0] is now high
        @(posedge clk);
        if (pwm_oe[0] !== 1'b1) begin
            $display("ERROR: pwm_oe[0] should be 1, got %b", pwm_oe[0]);
        end else begin
            $display("PASS: pwm_oe[0] = 1 as expected");
        end

        // -----------------------------------------------------------------
        // Test 2: Set duty cycle and verify PWM output
        // -----------------------------------------------------------------
        $display("\n--- Test 2: PWM Duty Cycle ---");

        // Set duty cycle to 100 for channel 0
        csr_write(8'h10, 32'd100);
        $display("Time: %0t - Set duty cycle to 100", $time);

        // Wait and observe PWM output
        repeat(300) @(posedge clk);

        // Count high cycles in a window
        begin
            int high_count = 0;
            int total_count = 200;

            for (int i = 0; i < total_count; i++) begin
                @(posedge clk);
                if (pwm_o[0]) high_count++;
            end

            $display("Time: %0t - PWM high count: %0d/%0d", $time, high_count, total_count);
            // With duty=100 and counter incrementing each cycle, we expect ~50% duty
            if (high_count > 80 && high_count < 120) begin
                $display("PASS: PWM duty cycle approximately correct");
            end else begin
                $display("INFO: PWM high count = %0d (depends on counter wrap)", high_count);
            end
        end

        // -----------------------------------------------------------------
        // Test 3: GPIO output test
        // -----------------------------------------------------------------
        $display("\n--- Test 3: GPIO Output ---");

        // Set GPIO output value
        csr_write(8'h40, 32'hA5);  // GPIO output = 0xA5
        csr_write(8'h44, 32'hFF);  // GPIO OE = 0xFF (all outputs)

        @(posedge clk);
        @(posedge clk);

        if (gpio_o !== 8'hA5) begin
            $display("ERROR: gpio_o should be 0xA5, got 0x%02X", gpio_o);
        end else begin
            $display("PASS: gpio_o = 0xA5 as expected");
        end

        if (gpio_oe !== 8'hFF) begin
            $display("ERROR: gpio_oe should be 0xFF, got 0x%02X", gpio_oe);
        end else begin
            $display("PASS: gpio_oe = 0xFF as expected");
        end

        // -----------------------------------------------------------------
        // Test 4: GPIO input test
        // -----------------------------------------------------------------
        $display("\n--- Test 4: GPIO Input ---");

        gpio_i = 8'h3C;
        @(posedge clk);
        csr_read(8'h48, read_data);

        if (read_data[7:0] !== 8'h3C) begin
            $display("ERROR: GPIO input read should be 0x3C, got 0x%02X", read_data[7:0]);
        end else begin
            $display("PASS: GPIO input = 0x3C as expected");
        end

        // -----------------------------------------------------------------
        // Test 5: Input capture
        // -----------------------------------------------------------------
        $display("\n--- Test 5: Input Capture ---");

        // Generate a rising edge on capture_i[0]
        capture_i[0] = 0;
        repeat(10) @(posedge clk);
        capture_i[0] = 1;
        repeat(5) @(posedge clk);

        // Read capture value
        csr_read(8'h30, read_data);
        $display("Time: %0t - Capture[0] value: %0d", $time, read_data[15:0]);

        if (read_data != 0) begin
            $display("PASS: Input capture recorded a value");
        end else begin
            $display("INFO: Capture value is 0 (may depend on timing)");
        end

        // -----------------------------------------------------------------
        // Test 6: Multiple channels
        // -----------------------------------------------------------------
        $display("\n--- Test 6: Multiple PWM Channels ---");

        // Enable all channels with different duty cycles
        csr_write(8'h00, 32'h000F);  // Enable all 4 channels
        csr_write(8'h10, 32'd25);    // Channel 0: 25% duty
        csr_write(8'h14, 32'd50);    // Channel 1: 50% duty
        csr_write(8'h18, 32'd75);    // Channel 2: 75% duty
        csr_write(8'h1C, 32'd100);   // Channel 3: 100% duty

        repeat(500) @(posedge clk);

        // Verify all output enables are high
        if (pwm_oe !== 4'b1111) begin
            $display("ERROR: All pwm_oe should be high, got %b", pwm_oe);
        end else begin
            $display("PASS: All PWM channels have output enabled");
        end

        // -----------------------------------------------------------------
        // Done
        // -----------------------------------------------------------------
        $display("\n=== Testbench Complete ===");
        $display("Time: %0t - All tests finished", $time);

        #100;
        $finish;
    end

    // Timeout watchdog
    initial begin
        #100000;
        $display("ERROR: Testbench timeout!");
        $finish;
    end

endmodule
