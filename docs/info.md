## How it works

TMAC is a 4 × 5 array of ternary (1.58-bit) processing elements: the inner loop of a BitNet-style LLM layer
in silicon. Each weight is −1, 0 or +1, so a "multiply" is an add, a subtract or nothing, and the array has no
multipliers. It carries an FPGA accelerator (Zynq-7020, 512 PEs) onto SKY130, with the same weight format
and the same requantisation contract as the FPGA datapath.

- **Weights** are sent packed 5 per byte in base 3 (`byte = Σ (w_k+1)·3^k`, lowest index first; 1.6 bits per
  weight). One row of 5 weights is exactly one byte, and the whole array is 4 bytes. Bytes 243–255 are
  illegal: they load as zeros and set the sticky `ILLEGAL` flag.
- **Activations** are 5 signed int8 values shared by all four rows.
- **Compute** forms `dot_r = Σ_c w[r][c]·a[c]` for all rows (pipelined over two clocks) and adds it into a
  24-bit saturating accumulator (`CMP`), or overwrites it (`CMP_CLR`). Saturation clamps (never wraps) and sets
  a sticky per-row flag. 24 bits are exact for any reduction length K ≤ 65,535.
- **Readout** returns `sat16(acc >>> shift)` per row: an arithmetic right shift (floor division, so −1 >>> 1 =
  −1), then a clamp to int16, with `shift` = 0–31 set by command. This is the FPGA's requantisation. One shared
  shifter serves all rows. `READ_RAW` returns the exact 24-bit values.
- **BIST** runs 32 LFSR-generated rounds through the real datapath and compares a 16-bit signature with the
  value computed by the Python reference model. PASS/DONE appear on output pins.

### SPI protocol

Mode 0 (CPOL=0, CPHA=0), MSB first, one command per CS_n frame: an opcode byte, then data bytes. While the
opcode byte is clocked in, MISO returns the status byte. **f_SCK ≤ f_clk/16.** Keep CS_n low ≥ 8 clk
before the first SCK edge, and high ≥ 8 clk between frames.

| op | command | data |
|---|---|---|
| 0x00 | STATUS | out: per-row SAT flags (bit r = row r), then status |
| 0x10 | LOAD_W | in: 4 packed bytes, row 0 first (byte r = row r, columns 0–4) |
| 0x20 | LOAD_A | in: 5 int8 activations, a[0] first |
| 0x21 | LOAD_AC | in: activations; after every 5th byte, compute (accumulate). Stream any number of vectors |
| 0x30 | CMP | acc += W·a |
| 0x31 | CMP_CLR | acc = W·a |
| 0x40 | READ_ACC | out: 4 × int16 `sat16(acc >>> shift)`, row 0 first, MSB first |
| 0x41 | READ_RAW | out: 4 × 24-bit accumulators, MSB first |
| 0x50 | READ_W | out: 5 bytes of stored 2-bit codes (−1=11, 0=00, +1=01), 4 per byte, lowest index in LSBs |
| 0x60 | BIST | start the self-test (busy for 384 clk) |
| 0x61 | READ_SIG | out: 16-bit BIST signature, MSB first (expected 0xA97E) |
| 0x70 | CLEAR | zero accumulators, SAT, RSAT and ILLEGAL flags |
| 0x80 | SHIFT | in: one byte, readout shift = bits 4:0 |

Other opcodes do nothing and return status. Status byte: `bit7 = 1, bit6 BIST_BUSY, bit5 BIST_DONE,
bit4 BIST_PASS, bit3 ILLEGAL, bit2 ANY_SAT, bit1 RSAT (sticky: a READ_ACC returned a clamped value since the
last CLEAR), bit0 = 1`. After reset it reads 0x81. Reset takes effect 2 clocks after `rst_n` (synchroniser).

## How to test

1. Reset, then read STATUS: you should get 0x81.
2. Pulse `ui[3]` (BIST_START). After ~384 clocks `uo[2]` (DONE) and `uo[3]` (PASS) go high. This needs no SPI.
3. Over SPI, try a hand-checkable example. Weights: `LOAD_W F2 79 79 79` (0xF2 = 242 = all +1; 0x79 = 121 =
   all 0). Activations 1…5. Then `CMP_CLR` and `READ_RAW`: row 0 = 15, rows 1–3 = 0.
4. The repository's `test/tmac_model.py` is the bit-exact reference for anything else.

## External hardware

None needed. The devkit's RP2040 drives SPI and the BIST pin. LEDs on `uo[2]`/`uo[3]` show BIST at a glance.
