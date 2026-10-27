/*
 * Copyright (c) 2026 Muhammad Sohair Khan
 * SPDX-License-Identifier: Apache-2.0
 *
 * SPI slave, mode 0 (CPOL=0, CPHA=0), MSB first, oversampled by clk.
 * SCK, CS_n and MOSI are asynchronous to clk: each passes through a
 * two-flop synchroniser and SCK edges are detected in the clk domain.
 * Requirement: f_SCK <= f_clk / 8 (each SCK phase >= 4 clk cycles).
 *
 *   rx_valid  one-cycle pulse when a full byte has arrived (rx_byte valid)
 *   tx_byte   sampled when a byte completes (and at CS_n fall) as the next
 *             byte to shift out; it must be valid in the same cycle.
 *   start     one-cycle pulse when CS_n falls (start of a transaction)
 *   active    high while CS_n is low
 */

`default_nettype none

module spi_slave (
    input  wire       clk,
    input  wire       rst,
    input  wire       sck_in,
    input  wire       csn_in,
    input  wire       mosi_in,
    output wire       miso,
    output reg  [7:0] rx_byte,
    output reg        rx_valid,
    input  wire [7:0] tx_byte,
    output wire       start,
    output wire       active
);

  reg [2:0] sck_s, csn_s;
  reg [1:0] mosi_s;
  always @(posedge clk) begin
    if (rst) begin
      sck_s  <= 3'b000;
      csn_s  <= 3'b111;
      mosi_s <= 2'b00;
    end else begin
      sck_s  <= {sck_s[1:0], sck_in};
      csn_s  <= {csn_s[1:0], csn_in};
      mosi_s <= {mosi_s[0], mosi_in};
    end
  end

  wire sck_rise = (sck_s[2:1] == 2'b01);
  wire sck_fall = (sck_s[2:1] == 2'b10);
  assign active = ~csn_s[1];
  assign start  = (csn_s[2:1] == 2'b10);

  reg [2:0] bit_cnt;
  reg [7:0] rx_shift;
  reg [7:0] tx_shift;
  reg       load_tx;     // a byte just completed: load tx_shift on next SCK fall

  always @(posedge clk) begin
    rx_valid <= 1'b0;
    if (rst || !active) begin
      bit_cnt  <= 3'd0;
      rx_shift <= 8'd0;
      load_tx  <= 1'b0;
      if (rst) begin
        rx_byte  <= 8'd0;
        tx_shift <= 8'd0;
      end
    end else begin
      if (start) begin
        tx_shift <= tx_byte;             // first MISO byte (status)
      end
      if (sck_rise) begin
        rx_shift <= {rx_shift[6:0], mosi_s[1]};
        bit_cnt  <= bit_cnt + 3'd1;
        if (bit_cnt == 3'd7) begin
          rx_byte  <= {rx_shift[6:0], mosi_s[1]};
          rx_valid <= 1'b1;
          load_tx  <= 1'b1;
        end
      end
      if (sck_fall) begin
        if (load_tx) begin
          tx_shift <= tx_byte;
          load_tx  <= 1'b0;
        end else begin
          tx_shift <= {tx_shift[6:0], 1'b0};
        end
      end
    end
  end

  assign miso = tx_shift[7];

endmodule
