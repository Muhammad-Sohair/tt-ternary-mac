/*
 * Copyright (c) 2026 Muhammad Sohair Khan
 * SPDX-License-Identifier: Apache-2.0
 *
 * Packed byte -> five ternary weights, PACKING_FORMAT v1.0:
 *   byte = d0 + 3*d1 + 9*d2 + 27*d3 + 81*d4,  d = w + 1,  d0 = lowest-index weight.
 * Output code per trit (same as the FPGA PE): -1 = 2'b11, 0 = 2'b00, +1 = 2'b01.
 * Bytes 243..255 are illegal: all five weights decode to 0 and `illegal` is set.
 *
 * Digits are peeled off from the top with compare-and-subtract instead of
 * divide/modulo by 3, which would synthesise to a full divider.
 */

`default_nettype none

module trit_decoder (
    input  wire [7:0] byte_in,
    output wire [9:0] codes,     // codes[2k+1:2k] = weight k
    output wire       illegal
);

  assign illegal = (byte_in > 8'd242);

  function [1:0] digit_to_code(input [1:0] d);
    case (d)
      2'd0:    digit_to_code = 2'b11;  // -1
      2'd2:    digit_to_code = 2'b01;  // +1
      default: digit_to_code = 2'b00;  //  0
    endcase
  endfunction

  wire [7:0] r4 = byte_in;
  wire [1:0] d4 = (r4 >= 8'd162) ? 2'd2 : (r4 >= 8'd81) ? 2'd1 : 2'd0;
  wire [6:0] r3 = r4 - ((d4 == 2'd2) ? 8'd162 : (d4 == 2'd1) ? 8'd81 : 8'd0);
  wire [1:0] d3 = (r3 >= 7'd54) ? 2'd2 : (r3 >= 7'd27) ? 2'd1 : 2'd0;
  wire [4:0] r2 = r3 - ((d3 == 2'd2) ? 7'd54 : (d3 == 2'd1) ? 7'd27 : 7'd0);
  wire [1:0] d2 = (r2 >= 5'd18) ? 2'd2 : (r2 >= 5'd9) ? 2'd1 : 2'd0;
  wire [3:0] r1 = r2 - ((d2 == 2'd2) ? 5'd18 : (d2 == 2'd1) ? 5'd9 : 5'd0);
  wire [1:0] d1 = (r1 >= 4'd6) ? 2'd2 : (r1 >= 4'd3) ? 2'd1 : 2'd0;
  // r1 - 3*d1 is 0..2, so it can be computed modulo 4 (3*2 = 6 = 2 mod 4).
  wire [1:0] d0 = r1[1:0] - ((d1 == 2'd2) ? 2'd2 : (d1 == 2'd1) ? 2'd3 : 2'd0);

  assign codes = illegal ? 10'd0 :
                 {digit_to_code(d4), digit_to_code(d3), digit_to_code(d2),
                  digit_to_code(d1), digit_to_code(d0)};

endmodule
