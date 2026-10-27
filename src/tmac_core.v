/*
 * Copyright (c) 2026 Muhammad Sohair Khan
 * SPDX-License-Identifier: Apache-2.0
 *
 * Weight-stationary ternary MAC array, ROWS x COLS processing elements.
 *
 *   w[r][c] in {-1,0,+1}, stored as 2-bit codes, loaded as packed bytes
 *   a[c]    int8 activations, broadcast down each column
 *   compute: acc[r] <= sat(clear ? 0 : acc[r]) + sum_c w[r][c]*a[c])
 *
 * The products are multiplier-free (add / subtract / pass), as in the FPGA
 * PE. Each row's dot product is formed combinationally and accumulated in
 * one cycle; accumulators saturate to the signed ACC_W range and set a
 * sticky per-row flag instead of wrapping.
 *
 * Weight bytes are written in PACKING_FORMAT order: byte index
 * j = r*(COLS/5) + b holds columns 5b..5b+4 of row r.
 */

`default_nettype none

module tmac_core #(
    parameter ROWS  = 4,
    parameter COLS  = 5,            // must be a multiple of 5
    parameter ACC_W = 16
) (
    input  wire                     clk,
    input  wire                     rst,          // synchronous, active high

    input  wire                     w_we,
    input  wire [$clog2(ROWS*COLS/5)-1:0] w_addr,
    input  wire [7:0]               w_byte,

    input  wire                     a_we,
    input  wire [$clog2(COLS)-1:0]  a_addr,
    input  wire [7:0]               a_byte,

    input  wire                     compute,      // one-cycle strobe
    input  wire                     clear,        // with compute: acc = dot instead of acc + dot
    input  wire                     acc_rst,      // zero accumulators and all sticky flags

    output wire [ROWS*ACC_W-1:0]    acc_flat,
    output reg  [ROWS-1:0]          sat_flags,    // sticky
    output reg                      illegal_seen, // sticky: a byte > 242 was loaded
    output wire [ROWS*COLS*2-1:0]   w_flat
);

  localparam BPR    = COLS / 5;                   // packed bytes per row
  localparam NBYTES = ROWS * BPR;
  localparam DOT_W  = 8 + $clog2(COLS + 1);       // |dot| <= 128*COLS
  localparam signed [ACC_W:0] ACC_MAX = (1 <<< (ACC_W - 1)) - 1;
  localparam signed [ACC_W:0] ACC_MIN = -(1 <<< (ACC_W - 1));

  reg  [1:0]        w   [0:ROWS*COLS-1];
  reg  signed [7:0] a   [0:COLS-1];
  reg  signed [ACC_W-1:0] acc [0:ROWS-1];

  // ---- weight load through the shared decoder ----
  wire [9:0] dec_codes;
  wire       dec_illegal;
  trit_decoder u_dec (.byte_in(w_byte), .codes(dec_codes), .illegal(dec_illegal));

  // Each always block has its own loop variables: sharing one integer
  // between blocks simulates fine but is a multiple-driver error in synthesis.
  integer iw, k;
  always @(posedge clk) begin
    if (rst) begin
      for (iw = 0; iw < ROWS*COLS; iw = iw + 1) w[iw] <= 2'b00;
      illegal_seen <= 1'b0;
    end else if (acc_rst) begin
      illegal_seen <= 1'b0;
    end else if (w_we) begin
      for (k = 0; k < 5; k = k + 1) w[w_addr*5 + k] <= dec_codes[2*k +: 2];
      if (dec_illegal) illegal_seen <= 1'b1;
    end
  end

  integer ia;
  always @(posedge clk) begin
    if (rst) begin
      for (ia = 0; ia < COLS; ia = ia + 1) a[ia] <= 8'sd0;
    end else if (a_we) begin
      a[a_addr] <= a_byte;
    end
  end

  // ---- multiplier-free dot products ----
  // -a = ~a + 1, so each term is (a XOR neg) masked by nonzero, and the "+1"
  // carry-ins of all negated terms are added once as a count. This gives one
  // adder tree per row instead of a chain of add/subtract/pass muxes.
  //   w = +1 (01): term = a        w = -1 (11): term = ~a, +1 counted
  //   w =  0 (00): term = 0
  localparam CNT_W = $clog2(COLS + 1);
  reg signed [DOT_W-1:0] dot [0:ROWS-1];
  reg signed [7:0]       term;
  reg        [CNT_W-1:0] nneg;
  reg        [1:0]       wc;
  integer r, c;
  always @* begin
    for (r = 0; r < ROWS; r = r + 1) begin
      dot[r] = {DOT_W{1'b0}};
      nneg   = {CNT_W{1'b0}};
      for (c = 0; c < COLS; c = c + 1) begin
        wc     = w[r*COLS + c];
        term   = (a[c] ^ {8{wc[1]}}) & {8{wc[0]}};
        dot[r] = dot[r] + term;
        nneg   = nneg + (wc == 2'b11);
      end
      dot[r] = dot[r] + $signed({1'b0, nneg});
    end
  end

  // ---- saturating accumulate ----
  reg signed [ACC_W:0] sum;
  integer ra;
  always @(posedge clk) begin
    if (rst || acc_rst) begin
      for (ra = 0; ra < ROWS; ra = ra + 1) acc[ra] <= {ACC_W{1'b0}};
      sat_flags <= {ROWS{1'b0}};
    end else if (compute) begin
      for (ra = 0; ra < ROWS; ra = ra + 1) begin
        // Both operands are signed, so they sign-extend to ACC_W+1 bits:
        // the sum cannot wrap before the range check below.
        sum = clear ? dot[ra] : acc[ra] + dot[ra];
        if (sum > ACC_MAX) begin
          acc[ra] <= ACC_MAX[ACC_W-1:0];
          sat_flags[ra] <= 1'b1;
        end else if (sum < ACC_MIN) begin
          acc[ra] <= ACC_MIN[ACC_W-1:0];
          sat_flags[ra] <= 1'b1;
        end else begin
          acc[ra] <= sum[ACC_W-1:0];
        end
      end
    end
  end

  genvar g;
  generate
    for (g = 0; g < ROWS; g = g + 1) begin : g_acc
      assign acc_flat[g*ACC_W +: ACC_W] = acc[g];
    end
    for (g = 0; g < ROWS*COLS; g = g + 1) begin : g_w
      assign w_flat[2*g +: 2] = w[g];
    end
  endgenerate

endmodule
