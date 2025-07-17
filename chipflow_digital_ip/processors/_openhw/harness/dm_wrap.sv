// Wrapper to connect together dm_obi_top and db_jtag

import dm::*;

module dm_wrap (
    // Common
    input  logic clk_i,
    input  logic rst_ni,
    // CPU
    output logic ndmreset_o,
    output logic debug_req_o,

    // CPU -> DM
    input  logic dm_req_i,
    output logic dm_gnt_o,
    input  logic dm_we_i,
    input  logic [31:0] dm_addr_i,
    input  logic [3:0] dm_be_i,
    input  logic [31:0] dm_wdata_i,
    output logic [31:0] dm_rdata_o,
    output logic dm_rvalid_o,

    // DM -> system bus
    output logic sb_req_o,
    output logic [31:0] sb_addr_o,
    output logic sb_we_o,
    output logic [31:0] sb_wdata_o,
    output logic [3:0] sb_be_o,
    input  logic sb_gnt_i,
    input  logic sb_rvalid_i,
    input  logic [31:0] sb_rdata_i,

    // JTAG interface
    input  logic tck_i,
    input  logic tms_i,
    input  logic trst_ni,
    input  logic tdi_i,
    output logic tdo_o,
    output logic tdo_oe
);

    logic debug_req_ready;
    dmi_resp_t debug_resp;
    logic jtag_req_valid;
    dmi_req_t jtag_dmi_req;
    logic jtag_resp_ready;
    logic jtag_resp_valid;

    dm_obi_top #(
        .NrHarts(1),
        .BusWidth(32),
        .SelectableHarts(1)
    ) dm_top_i (
        .clk_i(clk_i),
        .rst_ni(rst_ni),
        .testmode_i(1'b0),
        .ndmreset_o(ndmreset_o),
        .debug_req_o(debug_req_o),
        .unavailable_i(1'b0),
        .hartinfo_i('0),
        .slave_req_i(dm_req_i),
        .slave_gnt_o(dm_gnt_o),
        .slave_we_i(dm_we_i),
        .slave_addr_i(dm_addr_i),
        .slave_be_i(dm_be_i),
        .slave_wdata_i(dm_wdata_i),
        .slave_rdata_o(dm_rdata_o),
        .slave_rvalid_o(dm_rvalid_o),

        .master_req_o(sb_req_o),
        .master_addr_o(sb_addr_o),
        .master_we_o(sb_we_o),
        .master_wdata_o(sb_wdata_o),
        .master_be_o(sb_be_o),
        .master_gnt_i(sb_gnt_i),
        .master_rvalid_i(sb_rvalid_i),
        .master_rdata_i(sb_rdata_i),
        .master_err_i(1'b0),
        .master_other_err_i(1'b0),

        .dmi_rst_ni(rst_ni),
        .dmi_req_valid_i(jtag_req_valid),
        .dmi_req_ready_o(debug_req_ready),
        .dmi_req_i(jtag_dmi_req),
        .dmi_resp_valid_o(jtag_resp_valid),
        .dmi_resp_ready_i(jtag_resp_ready),
        .dmi_resp_o(debug_resp)
    );

    dmi_jtag #(
        .IdcodeValue(32'h249511C3)
    ) dmi_jtag_i (
        .clk_i(clk_i),
        .rst_ni(rst_ni),
        .testmode_i(0),
        .dmi_req_o(jtag_dmi_req),
        .dmi_req_valid_o(jtag_req_valid),
        .dmi_req_ready_i(debug_req_ready),
        .dmi_resp_i(debug_resp),
        .dmi_resp_ready_o(jtag_resp_ready),
        .dmi_resp_valid_i(jtag_resp_valid),
        .tck_i(tck_i),
        .tms_i(tms_i),
        .trst_ni(trst_ni),
        .td_i(tdi_i),
        .td_o(tdo_o),
        .tdo_oe_o(tdo_oe)
    );

endmodule : dm_wrap
