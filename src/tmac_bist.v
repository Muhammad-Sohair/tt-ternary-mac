/*
 * Copyright (c) 2026 Muhammad Sohair Khan
 * SPDX-License-Identifier: Apache-2.0
 *
 * Built-in self-test: drives the MAC core from a 16-bit LFSR for ITERS
 * rounds (load all weight bytes, load all activations, compute) and folds
 * the accumulators into a 16-bit MISR after every compute. At the end the
 * signature is compared with EXPECTED, which the Python reference model
 * computes (test/gen_bist.py writes src/bist_expected.vh).
 *
 * Every cycle in S_W / S_A consumes one LFSR state, starting from SEED, so
 * the byte sequence is simply consecutive LFSR states. Weight bytes > 242
 * are reduced by 243 so every BIST weight byte is legal. Rounds with (iter % 4 == 0) use compute-clear,
 * the others accumulate, so both compute modes are covered.
 */

`default_nettype none

module tmac_bist #(
    parameter ROWS     = 4,
    parameter COLS     = 5,
    parameter ACC_W    = 16,
    parameter ITERS    = 32,
    parameter [15:0] SEED     = 16'hACE1,
    parameter [15:0] EXPECTED = 16'h0000
) (
    input  wire                     clk,
    input  wire                     rst,
    input  wire                     go,           // one-cycle start pulse
    output wire                     busy,
    output reg                      done,         // sticky until next go / reset
    output reg                      pass,
    output reg  [15:0]              signature,

    output wire                     w_we,
    output reg  [$clog2(ROWS*COLS/5)-1:0] w_addr,
    output wire                     a_we,
    output reg  [$clog2(COLS)-1:0]  a_addr,
    output wire [7:0]               data,
    output wire                     compute,
    output wire                     clear,
    input  wire [ROWS*ACC_W-1:0]    acc_flat
);

  localparam NBYTES = ROWS * COLS / 5;
  localparam S_IDLE = 3'd0, S_W = 3'd1, S_A = 3'd2, S_CMP = 3'd3, S_WAIT = 3'd4, S_SIG = 3'd5;

  reg [2:0]  state;
  reg [15:0] lfsr;
  reg [$clog2(ITERS+1)-1:0] iter;

  // Galois LFSR, x^16 + x^14 + x^13 + x^11 + 1
  wire [15:0] lfsr_next = lfsr[0] ? ((lfsr >> 1) ^ 16'hB400) : (lfsr >> 1);
  wire [7:0]  raw = lfsr[7:0];

  assign busy    = (state != S_IDLE);
  assign w_we    = (state == S_W);
  assign a_we    = (state == S_A);
  assign compute = (state == S_CMP);
  assign clear   = (iter[1:0] == 2'd0);
  assign data    = (state == S_W && raw > 8'd242) ? raw - 8'd243 : raw;

  // XOR-fold of all accumulators: each row's ACC_W bits folded to 16
  // (low 16 XOR the rest), then rotated left by the row index
  reg [15:0] fold;
  reg [15:0] row16;
  integer r;
  always @* begin
    fold = 16'd0;
    for (r = 0; r < ROWS; r = r + 1) begin
      row16 = acc_flat[r*ACC_W +: 16] ^ (acc_flat[r*ACC_W +: ACC_W] >> 16);
      fold  = fold ^ ((row16 << (r % 16)) | (row16 >> ((16 - (r % 16)) % 16)));
    end
  end

  // MISR: shift with the same feedback taps, XOR in the fold
  wire [15:0] sig_next = {signature[14:0],
                          signature[15] ^ signature[13] ^ signature[12] ^ signature[10]} ^ fold;

  always @(posedge clk) begin
    if (rst) begin
      state     <= S_IDLE;
      done      <= 1'b0;
      pass      <= 1'b0;
      signature <= 16'd0;
      lfsr      <= SEED;
      iter      <= 0;
      w_addr    <= 0;
      a_addr    <= 0;
    end else begin
      case (state)
        S_IDLE: if (go) begin
          state     <= S_W;
          done      <= 1'b0;
          pass      <= 1'b0;
          signature <= 16'd0;
          lfsr      <= SEED;
          iter      <= 0;
          w_addr    <= 0;
          a_addr    <= 0;
        end
        S_W: begin
          lfsr   <= lfsr_next;
          w_addr <= w_addr + 1'b1;
          if (w_addr == NBYTES - 1) begin
            w_addr <= 0;
            state  <= S_A;
          end
        end
        S_A: begin
          lfsr   <= lfsr_next;
          a_addr <= a_addr + 1'b1;
          if (a_addr == COLS - 1) begin
            a_addr <= 0;
            state  <= S_CMP;
          end
        end
        S_CMP:  state <= S_WAIT;          // core registers the dot products
        S_WAIT: state <= S_SIG;           // core updates the accumulators
        S_SIG: begin
          signature <= sig_next;
          iter      <= iter + 1'b1;
          if (iter == ITERS - 1) begin
            state <= S_IDLE;
            done  <= 1'b1;
            pass  <= (sig_next == EXPECTED);
          end else begin
            state <= S_W;
          end
        end
        default: state <= S_IDLE;
      endcase
    end
  end

endmodule
