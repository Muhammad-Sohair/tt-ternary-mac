/*
 * Copyright (c) 2026 Muhammad Sohair Khan
 * SPDX-License-Identifier: Apache-2.0
 *
 * Practice design: 8-bit loadable up-counter.
 *   ui_in[0] EN    count up by one per clock while high
 *   ui_in[1] LOAD  synchronous load of uio_in (has priority over EN)
 *   uo_out         current count
 * uio is input-only (the load value).
 */

`default_nettype none

module tt_um_msohair_counter (
    input  wire [7:0] ui_in,
    output wire [7:0] uo_out,
    input  wire [7:0] uio_in,
    output wire [7:0] uio_out,
    output wire [7:0] uio_oe,
    input  wire       ena,
    input  wire       clk,
    input  wire       rst_n
);

  reg [7:0] count;

  always @(posedge clk) begin
    if (!rst_n)        count <= 8'd0;
    else if (ui_in[1]) count <= uio_in;
    else if (ui_in[0]) count <= count + 8'd1;
  end

  assign uo_out  = count;
  assign uio_out = 8'd0;
  assign uio_oe  = 8'd0;

  wire _unused = &{ena, ui_in[7:2], 1'b0};

endmodule
