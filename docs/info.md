## How it works

TMAC is a 4 × 10 array of ternary (1.58-bit) processing elements: the inner loop of a BitNet-style LLM layer
in silicon. Each weight is −1, 0 or +1, so a "multiply" is an add, a subtract or nothing, and the array has no
multipliers. It carries an FPGA accelerator (Zynq-7020, 512 PEs) onto SKY130.

- **Weights** are sent packed 5 per byte in base 3 (`byte = Σ (w_k+1)·3^k`, lowest index first; 1.6 bits per
  weight). A row of 10 weights is 2 bytes and the whole array is 8 bytes. Bytes 243–255 are illegal: they load
  as zeros and set the sticky `ILLEGAL` flag.
- **Activations** are 10 signed int8 values shared by all four rows.
- **Compute** forms `dot_r = Σ_c w[r][c]·a[c]` for all rows in one clock and adds it into a 24-bit
  saturating accumulator (`CMP`), or overwrites it (`CMP_CLR`). Saturation clamps and sets a sticky per-row
  flag. 24 bits are exact for any reduction length K ≤ 65,535.
- **Readout** returns `sat16(acc >>> shift)` per row: an arithmetic right shift (floor division), then a clamp
  to int16, with `shift` = 0–31 set by command. `READ_RAW` returns the exact 24-bit values.
- **BIST** runs 32 LFSR-generated rounds through the real datapath and compares a 16-bit signature with the
  value computed by the Python reference model. PASS/DONE appear on output pins.

### SPI protocol

Mode 0 (CPOL=0, CPHA=0), MSB first, one command per CS_n frame: an opcode byte, then data bytes. While the
opcode byte is clocked in, MISO returns the status byte. **f_SCK ≤ f_clk/16.** Keep CS_n low ≥ 8 clk
before the first SCK edge, and high ≥ 8 clk between frames.

| op | command | data |
|---|---|---|
| 0x00 | STATUS | out: per-row SAT flags (bit r = row r), then status |
| 0x10 | LOAD_W | in: 8 packed bytes, row 0 first (row r = bytes 2r, 2r+1; byte 2r holds columns 0–4) |
| 0x20 | LOAD_A | in: 10 int8 activations, a[0] first |
| 0x21 | LOAD_AC | in: activations; after every 10th byte, compute (accumulate). Stream any number of vectors |
| 0x30 | CMP | acc += W·a |
| 0x31 | CMP_CLR | acc = W·a |
| 0x40 | READ_ACC | out: 4 × int16 `sat16(acc >>> shift)`, row 0 first, MSB first |
| 0x41 | READ_RAW | out: 4 × 24-bit accumulators, MSB first |
| 0x50 | READ_W | out: 10 bytes of stored 2-bit codes (−1=11, 0=00, +1=01), 4 per byte, lowest index in LSBs |
| 0x60 | BIST | start the self-test (busy for 672 clk) |
| 0x61 | READ_SIG | out: 16-bit BIST signature, MSB first (expected 0xC8C3) |
| 0x70 | CLEAR | zero accumulators, SAT and ILLEGAL flags |
| 0x80 | SHIFT | in: one byte, readout shift = bits 4:0 |

Status byte: `bit7 = 1, bit6 BIST_BUSY, bit5 BIST_DONE, bit4 BIST_PASS, bit3 ILLEGAL, bit2 ANY_SAT,
bit1 RSAT (a row would clamp on READ_ACC at the current shift), bit0 = 1`. After reset it reads 0x81.

## How to test

1. Reset, then read STATUS: you should get 0x81.
2. Pulse `ui[3]` (BIST_START). After ~672 clocks `uo[2]` (DONE) and `uo[3]` (PASS) go high. This needs no SPI.
3. Over SPI, try a hand-checkable example. Weights row 0 = all +1: bytes `0xF2, 0xF2` (242 = all digits 2).
   Activations 1…10. Then `CMP_CLR` and `READ_ACC`: row 0 = 55, rows 1–3 = 0 (their weights are still 0 after
   reset).
4. The repository's `test/tmac_model.py` is the bit-exact reference for anything else.

## External hardware

None needed. The devkit's RP2040 drives SPI and the BIST pin. LEDs on `uo[2]`/`uo[3]` show BIST at a glance.
