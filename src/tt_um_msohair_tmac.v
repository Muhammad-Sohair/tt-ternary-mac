/*
 * Copyright (c) 2026 Muhammad Sohair Khan
 * SPDX-License-Identifier: Apache-2.0
 *
 * TMAC: ternary (1.58-bit) weight-stationary MAC array behind an SPI slave.
 * See docs/info.md for the command set and pinout.
 */

`default_nettype none

module tt_um_msohair_tmac #(
    parameter ROWS  = 4,
    parameter COLS  = 10,
    parameter ACC_W = 24              // internal; exact for K <= 65,535 (|acc| <= 128*K)
) (
    input  wire [7:0] ui_in,
    output wire [7:0] uo_out,
    input  wire [7:0] uio_in,
    output wire [7:0] uio_out,
    output wire [7:0] uio_oe,
    input  wire       ena,
    input  wire       clk,
    input  wire       rst_n
);

  // BEGIN GENERATED BIST CONSTANTS (test/tmac_model.py --write-rtl; do not edit)
  localparam        BIST_ITERS    = 32;
  localparam [15:0] BIST_SEED     = 16'hACE1;
  localparam [15:0] BIST_EXPECTED = 16'hC8C3;
  // END GENERATED BIST CONSTANTS

  localparam NBYTES  = ROWS * COLS / 5;
  localparam RAW_B   = ACC_W / 8;            // bytes per accumulator on READ_RAW
  localparam NRAW_B  = ROWS * RAW_B;
  localparam NOUT_B  = ROWS * 2;             // READ_ACC: int16 per row
  localparam NTRIT   = ROWS * COLS;
  localparam NW_B    = (NTRIT + 3) / 4;      // READ_W: 4 codes per byte
  localparam WA_W    = $clog2(NBYTES);
  localparam AA_W    = $clog2(COLS);

  localparam [7:0] OP_STATUS  = 8'h00,
                   OP_LOAD_W  = 8'h10,
                   OP_LOAD_A  = 8'h20,
                   OP_LOAD_AC = 8'h21,   // load activations; after the last one, compute (accumulate)
                   OP_CMP     = 8'h30,   // acc += W.a
                   OP_CMP_CLR = 8'h31,   // acc  = W.a
                   OP_READ_A  = 8'h40,   // read sat16(acc >>> shift) per row, row 0 first, MSB first
                   OP_READ_R  = 8'h41,   // read raw ACC_W-bit accumulators, MSB first
                   OP_READ_W  = 8'h50,   // read stored weight codes, 4 per byte, LSB = lowest index
                   OP_BIST    = 8'h60,
                   OP_READ_S  = 8'h61,   // read BIST signature, MSB first
                   OP_CLEAR   = 8'h70,   // zero accumulators and sticky flags
                   OP_SHIFT   = 8'h80;   // one data byte: readout shift = byte[4:0]

  // Reset synchroniser. rst_n reaches us through the TT mux, asynchronous
  // to clk, and as a raw input it fanned out to ~430 flops: the input-to-flop
  // paths failed 50 MHz at ss/100C by 3.4 ns (4 ns of input delay plus the
  // buffer tree). Two flops give the reset tree a full cycle from a register.
  // Reset is asserted and released 2 clocks after rst_n.
  reg [1:0] rst_sync;
  always @(posedge clk) rst_sync <= {rst_sync[0], ~rst_n};
  wire rst = rst_sync[1];

  // ---------------- SPI ----------------
  wire       miso, rx_valid, spi_start, spi_active;
  wire [7:0] rx_byte;
  reg  [7:0] tx_byte;

  spi_slave u_spi (
      .clk(clk), .rst(rst),
      .sck_in(ui_in[0]), .csn_in(ui_in[1]), .mosi_in(ui_in[2]),
      .miso(miso), .rx_byte(rx_byte), .rx_valid(rx_valid),
      .tx_byte(tx_byte), .start(spi_start), .active(spi_active)
  );

  // ---------------- command decoder ----------------
  reg        have_op;
  reg  [7:0] op;
  reg  [7:0] idx;           // data-byte index within the current command

  reg             s_w_we, s_a_we, s_cmp, s_clr, s_acc_rst, bist_go, s_ac_cmp;
  reg  [WA_W-1:0] s_w_addr, w_ptr;
  reg  [AA_W-1:0] s_a_addr, a_ptr;
  reg  [7:0]      s_data;
  reg  [4:0]      shift;     // readout requantisation shift, as in the FPGA OPMODE

  wire bist_busy;

  always @(posedge clk) begin
    s_w_we <= 1'b0; s_a_we <= 1'b0; s_clr <= 1'b0; s_ac_cmp <= 1'b0;
    s_acc_rst <= 1'b0; bist_go <= 1'b0;
    // LOAD_AC: compute in the cycle after the last activation of a vector is
    // written. Registered alongside the write, so it does not depend on CS_n.
    s_cmp <= s_ac_cmp;
    if (rst || !spi_active) begin
      have_op <= 1'b0;
      op      <= OP_STATUS;
      idx     <= 8'd0;
      w_ptr   <= 0;
      a_ptr   <= 0;
      if (rst) begin
        s_w_addr <= 0; s_a_addr <= 0; s_data <= 8'd0; s_cmp <= 1'b0; shift <= 5'd0;
      end
    end else if (rx_valid && !have_op) begin
      have_op <= 1'b1;
      op      <= rx_byte;
      idx     <= 8'd0;
      w_ptr   <= 0;
      a_ptr   <= 0;
      case (rx_byte)
        OP_CMP:     s_cmp <= ~bist_busy;
        OP_CMP_CLR: begin s_cmp <= ~bist_busy; s_clr <= 1'b1; end
        OP_BIST:    bist_go <= ~bist_busy;
        OP_CLEAR:   s_acc_rst <= ~bist_busy;
        default: ;
      endcase
    end else if (rx_valid) begin
      if (idx != 8'hFF) idx <= idx + 8'd1;
      s_data <= rx_byte;
      case (op)
        OP_LOAD_W: begin
          s_w_we   <= ~bist_busy;
          s_w_addr <= w_ptr;
          w_ptr    <= (w_ptr == NBYTES - 1) ? 0 : w_ptr + 1'b1;
        end
        OP_SHIFT: if (idx == 8'd0) shift <= rx_byte[4:0];
        OP_LOAD_A, OP_LOAD_AC: begin
          s_a_we   <= ~bist_busy;
          s_a_addr <= a_ptr;
          a_ptr    <= (a_ptr == COLS - 1) ? 0 : a_ptr + 1'b1;
          s_ac_cmp <= ~bist_busy && (op == OP_LOAD_AC) && (a_ptr == COLS - 1);
        end
        default: ;
      endcase
    end
  end

  // ---------------- BIST + mux onto the core ----------------
  wire             b_w_we, b_a_we, b_cmp, b_clr, bist_done, bist_pass;
  wire [WA_W-1:0]  b_w_addr;
  wire [AA_W-1:0]  b_a_addr;
  wire [7:0]       b_data;
  wire [15:0]      bist_sig;
  wire [ROWS*ACC_W-1:0] acc_flat;
  wire [ROWS-1:0]  sat_flags;
  wire             illegal_seen;
  wire [2*NTRIT-1:0] w_flat;

  // ui_in[3]: BIST start pin (rising edge, synchronised)
  reg [2:0] bist_pin_s;
  always @(posedge clk) bist_pin_s <= rst ? 3'b000 : {bist_pin_s[1:0], ui_in[3]};
  wire bist_pin_go = (bist_pin_s[2:1] == 2'b01);

  tmac_bist #(
      .ROWS(ROWS), .COLS(COLS), .ACC_W(ACC_W),
      .ITERS(BIST_ITERS), .SEED(BIST_SEED), .EXPECTED(BIST_EXPECTED)
  ) u_bist (
      .clk(clk), .rst(rst), .go(bist_go | bist_pin_go),
      .busy(bist_busy), .done(bist_done), .pass(bist_pass), .signature(bist_sig),
      .w_we(b_w_we), .w_addr(b_w_addr), .a_we(b_a_we), .a_addr(b_a_addr),
      .data(b_data), .compute(b_cmp), .clear(b_clr), .acc_flat(acc_flat)
  );

  tmac_core #(.ROWS(ROWS), .COLS(COLS), .ACC_W(ACC_W)) u_core (
      .clk(clk), .rst(rst),
      .w_we   (bist_busy ? b_w_we   : s_w_we),
      .w_addr (bist_busy ? b_w_addr : s_w_addr),
      .w_byte (bist_busy ? b_data   : s_data),
      .a_we   (bist_busy ? b_a_we   : s_a_we),
      .a_addr (bist_busy ? b_a_addr : s_a_addr),
      .a_byte (bist_busy ? b_data   : s_data),
      .compute(bist_busy ? b_cmp    : s_cmp),
      .clear  (bist_busy ? b_clr    : s_clr),
      .acc_rst(s_acc_rst | bist_go | bist_pin_go),
      .acc_flat(acc_flat), .sat_flags(sat_flags),
      .illegal_seen(illegal_seen), .w_flat(w_flat)
  );

  // ---------------- requantised readout ----------------
  // One shared shifter on the readout path: the row selected by the byte
  // index is shifted and saturated, exactly as the FPGA's sat16_shift:
  // arithmetic shift (floor division for negatives), then clamp to int16.
  reg  [$clog2(ROWS)-1:0] rsel;
  reg  signed [ACC_W-1:0] racc;
  wire signed [ACC_W-1:0] rshift = racc >>> shift;
  wire rs_hi = (rshift >  $signed(32'sd32767));
  wire rs_lo = (rshift < -$signed(32'sd32768));
  wire [15:0] rsat16 = rs_hi ? 16'h7FFF : rs_lo ? 16'h8000 : rshift[15:0];

  // Sticky RSAT: set when a READ_ACC byte that came from a clamped value
  // has been sent; cleared by CLEAR and reset. (A live "would clamp" flag
  // needed a shifter per row: four 24-bit barrel shifters for one bit.)
  reg any_rsat;
  always @(posedge clk) begin
    if (rst || s_acc_rst || bist_go || bist_pin_go)
      any_rsat <= 1'b0;
    else if (spi_active && rx_valid && have_op && op == OP_READ_A && idx < NOUT_B && (rs_hi || rs_lo))
      any_rsat <= 1'b1;
  end

  // ---------------- MISO data ----------------
  wire [7:0] sat_byte = sat_flags;          // zero-extends (ROWS <= 8)
  wire [7:0] status = {1'b1, bist_busy, bist_done, bist_pass,
                       illegal_seen, |sat_flags, any_rsat, 1'b1};

  // Next byte to send. While the opcode is being received the host gets
  // STATUS; afterwards byte idx of the selected stream.
  reg [7:0] raw_byte, w_byte_out;
  integer j;
  always @* begin
    rsel = idx[$clog2(ROWS):1];
    racc = acc_flat[rsel*ACC_W +: ACC_W];
    raw_byte = 8'd0;
    for (j = 0; j < NRAW_B; j = j + 1)
      if (idx == j)
        raw_byte = acc_flat[(j / RAW_B) * ACC_W + (RAW_B - 1 - (j % RAW_B)) * 8 +: 8];
    w_byte_out = 8'd0;
    for (j = 0; j < NW_B; j = j + 1)
      if (idx == j)
        w_byte_out = {(4*j+3 < NTRIT) ? w_flat[2*(4*j+3) +: 2] : 2'b00,
                      (4*j+2 < NTRIT) ? w_flat[2*(4*j+2) +: 2] : 2'b00,
                      (4*j+1 < NTRIT) ? w_flat[2*(4*j+1) +: 2] : 2'b00,
                                        w_flat[2*(4*j)   +: 2]};
  end

  always @* begin
    if (!have_op) tx_byte = status;
    else case (op)
      OP_STATUS: tx_byte = (idx == 8'd0) ? sat_byte : status;
      OP_READ_A: tx_byte = (idx >= NOUT_B) ? 8'd0 : idx[0] ? rsat16[7:0] : rsat16[15:8];
      OP_READ_R: tx_byte = raw_byte;
      OP_READ_W: tx_byte = w_byte_out;
      OP_READ_S: tx_byte = (idx == 8'd0) ? bist_sig[15:8] : (idx == 8'd1) ? bist_sig[7:0] : 8'd0;
      default:   tx_byte = status;
    endcase
  end

  // ---------------- pins ----------------
  assign uo_out  = {spi_active, bist_busy, |sat_flags, illegal_seen,
                    bist_pass, bist_done, 1'b0, miso};
  assign uio_out = 8'd0;
  assign uio_oe  = 8'd0;

  wire _unused = &{ena, ui_in[7:4], uio_in, 1'b0};

endmodule
